#!/usr/bin/env python3
"""Gera histórico estadual comprovado nas fontes legislativas disponíveis.

Nesta etapa, a ALEP oferece listas oficiais por legislatura desde 2003.
SC e RS permanecem explicitamente sem cobertura histórica estruturada.
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "dados/mandatos_estaduais_historicos_2026.b64"
MANIFESTO = RAIZ / "dados/mandatos_estaduais_historicos_manifesto_2026.json"
FONTE_PR = "https://www.assembleia.pr.leg.br/deputados/conheca"
CONSULTA_PR = "https://www.assembleia.pr.leg.br/deputados/legislatura?legislatura={slug}"
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter_texto(url: str) -> str:
    for tentativa in range(5):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resposta:
                return resposta.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if tentativa == 4:
                raise
            time.sleep(2 ** tentativa)
    raise RuntimeError("Fonte oficial indisponível")


def normalizar(nome: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", nome or "") if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).strip()


def limpar(valor: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", valor or "")).strip()


def periodos_disponiveis() -> list[dict]:
    pagina = obter_texto(FONTE_PR)
    opcoes = re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', pagina, re.S)
    saida = []
    for slug, rotulo_html in opcoes:
        rotulo = re.sub(r"\s+", " ", limpar(rotulo_html))
        leg = re.search(r"(\d+)ª?\s+Legislatura", rotulo, re.I)
        anos = re.search(r"\((\d{4})\s*[-–]\s*(\d{4})\)", rotulo)
        if not leg or not anos:
            continue
        legislatura, inicio, fim = int(leg.group(1)), int(anos.group(1)), int(anos.group(2))
        if legislatura < 15 or legislatura >= 20:
            continue
        saida.append({"slug": slug, "rotulo": rotulo, "legislatura": legislatura, "inicio": inicio, "fim": fim})
    if len(saida) != 8:
        raise SystemExit(f"Períodos históricos inesperados na ALEP: {len(saida)}; esperado 8.")
    return saida


def parlamentares_periodo(periodo: dict) -> list[dict]:
    url = CONSULTA_PR.format(slug=urllib.parse.quote(periodo["slug"]))
    pagina = obter_texto(url)
    padrao = re.compile(
        r'<a\s+href="(https://www\.assembleia\.pr\.leg\.br/deputados/perfil/[^"]+)"'
        r'.*?<h3[^>]*>\s*(.*?)\s*</h3>', re.S
    )
    unicos = {}
    for perfil, nome_html in padrao.findall(pagina):
        nome = re.sub(r"\s+", " ", limpar(nome_html))
        if nome:
            unicos[(perfil, normalizar(nome))] = {"nome_parlamentar": nome, "url_perfil": perfil}
    if len(unicos) < 45:
        raise SystemExit(f"Lista histórica curta na ALEP ({periodo['rotulo']}): {len(unicos)} nomes.")
    return list(unicos.values())


def main() -> None:
    escopo = ler_b64(RAIZ / "dados/escopo_prioritario_2026.b64")
    indice = defaultdict(list)
    for candidato in escopo["candidatos"]:
        if candidato.get("uf") != "PR":
            continue
        for nome in {normalizar(candidato.get("nome", "")), normalizar(candidato.get("nome_urna", ""))}:
            if nome:
                indice[nome].append(candidato)

    encontrados, ambiguos, fontes_periodos = defaultdict(list), [], []
    for periodo in periodos_disponiveis():
        url = CONSULTA_PR.format(slug=urllib.parse.quote(periodo["slug"]))
        parlamentares = parlamentares_periodo(periodo)
        fontes_periodos.append({**periodo, "url": url, "quantidade_nomes": len(parlamentares)})
        for parlamentar in parlamentares:
            unicos = {x["sq_candidato"]: x for x in indice.get(normalizar(parlamentar["nome_parlamentar"]), [])}
            if len(unicos) > 1:
                ambiguos.append({"nome_parlamentar": parlamentar["nome_parlamentar"], "periodo": periodo["rotulo"], "ids_candidatos": sorted(unicos)})
                continue
            if not unicos:
                continue
            candidato = next(iter(unicos.values()))
            encontrados[candidato["sq_candidato"]].append({
                **parlamentar,
                "casa": "Assembleia Legislativa do Paraná",
                "cargo": "Deputado Estadual",
                "uf": "PR",
                "legislatura": periodo["legislatura"],
                "periodo_inicio": periodo["inicio"],
                "periodo_fim": periodo["fim"],
                "rotulo_fonte": periodo["rotulo"],
                "url_fonte": url,
                "metodo_vinculo": "nome_oficial_exato_normalizado+uf+unicidade",
            })

    mandatos = {}
    for cid, registros in encontrados.items():
        grupos = defaultdict(list)
        for registro in registros:
            grupos[registro["legislatura"]].append(registro)
        mandatos[cid] = []
        for legislatura, itens in sorted(grupos.items()):
            mandatos[cid].append({
                "casa": itens[0]["casa"], "cargo": itens[0]["cargo"], "uf": "PR",
                "nome_parlamentar": itens[0]["nome_parlamentar"], "url_perfil": itens[-1]["url_perfil"],
                "legislatura": legislatura, "periodo_inicio": min(x["periodo_inicio"] for x in itens),
                "periodo_fim": max(x["periodo_fim"] for x in itens),
                "periodos_oficiais": [x["rotulo_fonte"] for x in itens],
                "fontes": [x["url_fonte"] for x in itens],
                "metodo_vinculo": itens[0]["metodo_vinculo"],
            })

    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    por_legislatura = Counter(str(x["legislatura"]) for itens in mandatos.values() for x in itens)
    documento = {
        "eleicao": 2026,
        "escopo": "mandatos_estaduais_historicos",
        "atualizado_em_utc": agora,
        "periodo_coberto": "2003–2022",
        "estados_com_cobertura": ["PR"],
        "estados_sem_fonte_historica_estruturada": ["SC", "RS"],
        "criterio_vinculo": "Nome oficial exatamente igual ao nome civil ou de urna normalizado, mesma UF e vínculo único.",
        "fonte_pr": FONTE_PR,
        "fontes_periodos": fontes_periodos,
        "quantidade_candidatos_com_historico": len(mandatos),
        "quantidade_registros_de_mandato": sum(len(x) for x in mandatos.values()),
        "quantidade_ambiguos": len(ambiguos),
        "por_legislatura": dict(sorted(por_legislatura.items())),
        "mandatos": dict(sorted(mandatos.items())),
        "ambiguos": ambiguos,
    }
    gravar_b64(OUT, documento)
    manifesto = {k: documento[k] for k in (
        "eleicao", "escopo", "atualizado_em_utc", "periodo_coberto", "estados_com_cobertura",
        "estados_sem_fonte_historica_estruturada", "criterio_vinculo", "fonte_pr",
        "quantidade_candidatos_com_historico", "quantidade_registros_de_mandato", "quantidade_ambiguos", "por_legislatura"
    )}
    manifesto.update({
        "arquivo": "dados/mandatos_estaduais_historicos_2026.b64",
        "observacao": "A cobertura histórica estadual é parcial: Paraná concluído com listas oficiais; SC e RS aguardam fonte pública estruturada que comprove exercício.",
    })
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
