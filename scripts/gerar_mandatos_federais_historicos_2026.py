#!/usr/bin/env python3
"""Gera o histórico federal oficial dos candidatos prioritários de 2026.

Somente nomes civis exatamente iguais são candidatos ao vínculo. Câmara exige
UF confirmada no histórico funcional. Senado exige mandato com exercício.
"""

from __future__ import annotations

import base64
import concurrent.futures
import gzip
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
OUT = RAIZ / "dados/mandatos_federais_historicos_2026.b64"
MANIFESTO = RAIZ / "dados/mandatos_federais_historicos_manifesto_2026.json"
CAMARA_ARQUIVO = "https://dadosabertos.camara.leg.br/arquivos/deputados/json/deputados.json"
SENADO_LEGISLATURA = "https://legis.senado.leg.br/dadosabertos/senador/lista/legislatura/{legislatura}.json"
LEGISLATURAS = range(51, 58)
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter_json(url: str) -> dict:
    for tentativa in range(6):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resposta:
                return json.load(resposta)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as erro:
            codigo = getattr(erro, "code", None)
            if tentativa == 5 or codigo not in (None, 429, 500, 502, 503, 504):
                raise
            time.sleep(min(30, 2 ** tentativa))
    raise RuntimeError("Fonte oficial indisponível")


def normalizar(nome: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", nome or "") if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).strip()


def lista(valor):
    if not valor:
        return []
    return valor if isinstance(valor, list) else [valor]


def indice_candidatos(candidatos: list[dict]) -> tuple[dict, dict]:
    por_nome_uf, presidentes = defaultdict(list), defaultdict(list)
    for c in candidatos:
        chave = normalizar(c.get("nome", ""))
        if c.get("uf") == "BR":
            presidentes[chave].append(c)
        else:
            por_nome_uf[(chave, c.get("uf", ""))].append(c)
    return por_nome_uf, presidentes


def vincular(identidade: dict, por_nome_uf: dict, presidentes: dict) -> tuple[dict | None, bool]:
    nome, uf = normalizar(identidade.get("nome_civil", "")), identidade.get("uf", "")
    achados = por_nome_uf.get((nome, uf), []) + presidentes.get(nome, [])
    unicos = {x["sq_candidato"]: x for x in achados}
    if len(unicos) == 1:
        return next(iter(unicos.values())), False
    return None, len(unicos) > 1


def camara(por_nome_uf: dict, presidentes: dict) -> tuple[dict, list]:
    deputados = obter_json(CAMARA_ARQUIVO).get("dados", [])
    candidatos_por_nome = defaultdict(list)
    for (nome, _uf), itens in por_nome_uf.items():
        candidatos_por_nome[nome].extend(itens)
    for nome, itens in presidentes.items():
        candidatos_por_nome[nome].extend(itens)
    saida, ambiguos = defaultdict(list), []
    for deputado in deputados:
        nome = normalizar(deputado.get("nomeCivil", ""))
        unicos = {x["sq_candidato"]: x for x in candidatos_por_nome.get(nome, [])}
        if len(unicos) > 1:
            ambiguos.append({"nome_civil": deputado.get("nomeCivil", ""), "motivo": "nome civil duplicado no escopo prioritário"})
            continue
        if not unicos:
            continue
        candidato = next(iter(unicos.values()))
        inicial, final = int(deputado.get("idLegislaturaInicial") or 0), int(deputado.get("idLegislaturaFinal") or 0)
        if not inicial or not final:
            continue
        dep_id = deputado["uri"].rstrip("/").split("/")[-1]
        saida[candidato["sq_candidato"]].append({
            "casa": "Câmara dos Deputados",
            "cargo": "Deputado Federal",
            "id_oficial": str(dep_id),
            "nome_civil": deputado.get("nomeCivil", ""),
            "nome_parlamentar": deputado.get("nome", ""),
            "uf": candidato.get("uf", ""),
            "legislatura_inicial": inicial,
            "legislatura_final": final,
            "legislaturas": list(range(inicial, final + 1)),
            "url_perfil": f"https://www.camara.leg.br/deputados/{dep_id}",
            "url_api": deputado.get("uri"),
            "metodo_vinculo": "nome_civil_exato_normalizado+unicidade_no_escopo",
            "nota_periodo": "A fonte consolidada informa a primeira e a última legislatura; não implica exercício contínuo entre todos os dias do intervalo.",
        })
    return dict(saida), ambiguos


def senado(por_nome_uf: dict, presidentes: dict) -> tuple[dict, list]:
    pessoas, ambiguos = {}, []
    for legislatura in LEGISLATURAS:
        raiz = obter_json(SENADO_LEGISLATURA.format(legislatura=legislatura))["ListaParlamentarLegislatura"]
        for parlamentar in lista(raiz.get("Parlamentares", {}).get("Parlamentar")):
            ident = parlamentar.get("IdentificacaoParlamentar", {})
            codigo = str(ident.get("CodigoParlamentar", ""))
            pessoa = pessoas.setdefault(codigo, {"ident": ident, "mandatos": {}})
            for mandato in lista(parlamentar.get("Mandatos", {}).get("Mandato")):
                exercicios = lista(mandato.get("Exercicios", {}).get("Exercicio"))
                if exercicios:
                    pessoa["mandatos"][str(mandato.get("CodigoMandato", ""))] = mandato

    saida = defaultdict(list)
    for codigo, pessoa in pessoas.items():
        ident = pessoa["ident"]
        for mandato in pessoa["mandatos"].values():
            identidade = {"nome_civil": ident.get("NomeCompletoParlamentar", ""), "uf": mandato.get("UfParlamentar", "")}
            candidato, ambiguo = vincular(identidade, por_nome_uf, presidentes)
            if ambiguo:
                ambiguos.append(identidade)
            if not candidato:
                continue
            legislaturas = []
            for chave in ("PrimeiraLegislaturaDoMandato", "SegundaLegislaturaDoMandato"):
                if mandato.get(chave):
                    legislaturas.append(mandato[chave])
            exercicios = lista(mandato.get("Exercicios", {}).get("Exercicio"))
            saida[candidato["sq_candidato"]].append({
                "casa": "Senado Federal",
                "cargo": "Senador",
                "id_oficial": codigo,
                "codigo_mandato": str(mandato.get("CodigoMandato", "")),
                "nome_civil": ident.get("NomeCompletoParlamentar", ""),
                "nome_parlamentar": ident.get("NomeParlamentar", ""),
                "uf": mandato.get("UfParlamentar", ""),
                "partido_na_fonte": ident.get("SiglaPartidoParlamentar", ""),
                "participacao": mandato.get("DescricaoParticipacao", ""),
                "legislaturas": legislaturas,
                "exercicios": exercicios,
                "inicio_registrado": min((x.get("DataInicio") for x in exercicios if x.get("DataInicio")), default=None),
                "fim_registrado": max((x.get("DataFim") for x in exercicios if x.get("DataFim")), default=None),
                "url_perfil": (ident.get("UrlPaginaParlamentar") or f"https://www25.senado.leg.br/web/senadores/senador/-/perfil/{codigo}").replace("http://", "https://"),
                "url_api": SENADO_LEGISLATURA.format(legislatura=legislaturas[-1].get("NumeroLegislatura") if legislaturas else 57),
                "metodo_vinculo": "nome_civil_exato_normalizado+uf+exercicio_oficial",
            })
    return dict(saida), ambiguos


def main() -> None:
    escopo = ler_b64(RAIZ / "dados/escopo_prioritario_2026.b64")
    por_nome_uf, presidentes = indice_candidatos(escopo["candidatos"])
    camara_hist, amb_camara = camara(por_nome_uf, presidentes)
    senado_hist, amb_senado = senado(por_nome_uf, presidentes)
    historicos = defaultdict(list)
    for origem in (camara_hist, senado_hist):
        for cid, mandatos in origem.items():
            historicos[cid].extend(mandatos)
    historicos = dict(sorted(historicos.items()))
    por_casa = Counter(m["casa"] for itens in historicos.values() for m in itens)
    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    documento = {
        "eleicao": 2026,
        "escopo": "mandatos_federais_historicos",
        "atualizado_em_utc": agora,
        "legislaturas_consultadas": list(LEGISLATURAS),
        "criterio_vinculo": "Nome civil exatamente igual após normalização e único no escopo; Senado também exige UF e registro de exercício.",
        "fontes": {"camara": CAMARA_ARQUIVO, "senado": SENADO_LEGISLATURA.replace("{legislatura}", "<legislatura>")},
        "quantidade_candidatos_com_historico": len(historicos),
        "quantidade_registros_de_mandato": sum(len(x) for x in historicos.values()),
        "quantidade_ambiguos": len(amb_camara) + len(amb_senado),
        "por_casa": dict(sorted(por_casa.items())),
        "mandatos": historicos,
        "ambiguos": amb_camara + amb_senado,
    }
    gravar_b64(OUT, documento)
    manifesto = {k: documento[k] for k in ("eleicao", "escopo", "atualizado_em_utc", "legislaturas_consultadas", "criterio_vinculo", "fontes", "quantidade_candidatos_com_historico", "quantidade_registros_de_mandato", "quantidade_ambiguos", "por_casa")}
    manifesto.update({
        "arquivo": "dados/mandatos_federais_historicos_2026.b64",
        "observacao": "O histórico registra exercício parlamentar oficial; candidatura, eleição ou suplência sem exercício não bastam para criar vínculo.",
    })
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
