#!/usr/bin/env python3
"""Vincula parlamentares estaduais atuais de SC, PR e RS ao escopo prioritário."""

from __future__ import annotations

import base64
import gzip
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "dados/mandatos_estaduais_atuais_2026.b64"
MANIFESTO = RAIZ / "dados/mandatos_estaduais_atuais_manifesto_2026.json"
FONTES = {
    "SC": "https://www.alesc.sc.gov.br/deputados/",
    "PR": "https://www.assembleia.pr.leg.br/deputados/conheca",
    "RS": "https://ww4.al.rs.gov.br:5000/listarDestaqueDeputados",
}
CASAS = {
    "SC": "Assembleia Legislativa de Santa Catarina",
    "PR": "Assembleia Legislativa do Paraná",
    "RS": "Assembleia Legislativa do Rio Grande do Sul",
}
QUANTIDADES_ESPERADAS = {"SC": 40, "PR": 54, "RS": 55}
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter(url: str) -> bytes:
    for tentativa in range(5):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/html,application/json", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resposta:
                return resposta.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if tentativa == 4:
                raise
            time.sleep(2 ** tentativa)
    raise RuntimeError("Fonte oficial indisponível")


def normalizar(nome: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", nome or "") if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).strip()


def normalizar_partido(sigla: str) -> str:
    valor = normalizar(sigla)
    return {"PODEMOS": "PODE", "UNIAO BRASIL": "UNIAO"}.get(valor, valor)


def texto_html(valor: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", valor or "")).strip()


def coletar_sc() -> list[dict]:
    pagina = obter(FONTES["SC"]).decode("utf-8", "replace")
    padrao = re.compile(
        r'<article class="lab-card-team.*?<a href="(https://www\.alesc\.sc\.gov\.br/deputado/[^"]+/)"'
        r'.*?<h3 class="lab-title-news">(.*?)</h3>\s*<span[^>]*>(.*?)</span>', re.S
    )
    return [{"nome_parlamentar": texto_html(nome), "partido": texto_html(partido), "url_perfil": url}
            for url, nome, partido in padrao.findall(pagina)]


def coletar_pr() -> list[dict]:
    pagina = obter(FONTES["PR"]).decode("utf-8", "replace")
    padrao = re.compile(
        r'<a href="(https://www\.assembleia\.pr\.leg\.br/deputados/perfil/[^"]+)"'
        r'.*?<h3[^>]*>\s*(.*?)\s*</h3>\s*(?:<p[^>]*>\s*(.*?)\s*</p>)?', re.S
    )
    return [{"nome_parlamentar": texto_html(nome), "partido": texto_html(partido), "url_perfil": url}
            for url, nome, partido in padrao.findall(pagina)]


def coletar_rs() -> list[dict]:
    itens = json.loads(obter(FONTES["RS"]))["lista"]
    return [{
        "id_oficial": str(x.get("idDeputado", "")),
        "nome_parlamentar": (x.get("nomeDeputado") or "").strip(),
        "partido": x.get("siglaPartido") or "",
        "url_perfil": f"https://ww4.al.rs.gov.br/deputados/{x.get('idDeputado')}",
    } for x in itens]


def main() -> None:
    escopo = ler_b64(RAIZ / "dados/escopo_prioritario_2026.b64")
    indice = defaultdict(list)
    for candidato in escopo["candidatos"]:
        uf = candidato.get("uf", "")
        if uf not in FONTES:
            continue
        for nome in {normalizar(candidato.get("nome", "")), normalizar(candidato.get("nome_urna", ""))}:
            if nome:
                indice[(uf, nome)].append(candidato)

    por_uf = {"SC": coletar_sc(), "PR": coletar_pr(), "RS": coletar_rs()}
    for uf, esperado in QUANTIDADES_ESPERADAS.items():
        if len(por_uf[uf]) != esperado:
            raise SystemExit(f"Quantidade inesperada em {uf}: {len(por_uf[uf])}; esperado {esperado}.")

    mandatos, ambiguos = {}, []
    for uf, parlamentares in por_uf.items():
        for parlamentar in parlamentares:
            chave = (uf, normalizar(parlamentar["nome_parlamentar"]))
            unicos = {x["sq_candidato"]: x for x in indice.get(chave, [])}
            if len(unicos) > 1:
                pelo_partido = {cid: x for cid, x in unicos.items() if normalizar_partido(x.get("partido_sigla", "")) == normalizar_partido(parlamentar.get("partido", ""))}
                if len(pelo_partido) == 1:
                    unicos = pelo_partido
                else:
                    ambiguos.append({"uf": uf, "nome_parlamentar": parlamentar["nome_parlamentar"], "ids_candidatos": sorted(unicos)})
                    continue
            if not unicos:
                continue
            candidato = next(iter(unicos.values()))
            mandatos[candidato["sq_candidato"]] = {
                **parlamentar,
                "sq_candidato": candidato["sq_candidato"],
                "casa": CASAS[uf],
                "cargo": "Deputado Estadual",
                "uf": uf,
                "situacao": "Em exercício na lista oficial atual",
                "partido_candidatura_2026": candidato.get("partido_sigla", ""),
                "url_fonte": FONTES[uf],
                "metodo_vinculo": "nome_oficial_exato_normalizado+uf+unicidade" if len(indice.get(chave, [])) == 1 else "nome_oficial_exato_normalizado+uf+partido",
            }

    por_estado = Counter(x["uf"] for x in mandatos.values())
    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    documento = {
        "eleicao": 2026,
        "escopo": "mandatos_estaduais_atuais_sc_pr_rs",
        "atualizado_em_utc": agora,
        "criterio_vinculo": "Nome parlamentar oficial exatamente igual ao nome civil ou de urna normalizado, mesma UF e vínculo único.",
        "fontes": FONTES,
        "quantidade_parlamentares_nas_fontes": sum(map(len, por_uf.values())),
        "quantidade_vinculos": len(mandatos),
        "quantidade_ambiguos": len(ambiguos),
        "por_estado": dict(sorted(por_estado.items())),
        "mandatos": dict(sorted(mandatos.items())),
        "ambiguos": ambiguos,
    }
    gravar_b64(OUT, documento)
    manifesto = {k: documento[k] for k in (
        "eleicao", "escopo", "atualizado_em_utc", "criterio_vinculo", "fontes",
        "quantidade_parlamentares_nas_fontes", "quantidade_vinculos", "quantidade_ambiguos", "por_estado"
    )}
    manifesto.update({
        "arquivo": "dados/mandatos_estaduais_atuais_2026.b64",
        "observacao": "A carga cobre parlamentares estaduais em exercício nas listas oficiais atuais de SC, PR e RS.",
    })
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
