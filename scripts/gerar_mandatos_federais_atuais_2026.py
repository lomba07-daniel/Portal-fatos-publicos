#!/usr/bin/env python3
"""Cruza o escopo prioritário de 2026 com mandatos federais atuais oficiais.

O vínculo é deliberadamente conservador: nome civil normalizado exatamente igual e,
salvo Presidência (UF BR), a mesma UF. Nomes duplicados não são vinculados.
"""

from __future__ import annotations

import base64
import concurrent.futures
import gzip
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "dados/mandatos_federais_atuais_2026.b64"
MANIFESTO = RAIZ / "dados/mandatos_federais_atuais_manifesto_2026.json"
CAMARA_LISTA = "https://dadosabertos.camara.leg.br/api/v2/deputados?itens=100&ordem=ASC&ordenarPor=nome"
CAMARA_PERFIL = "https://dadosabertos.camara.leg.br/api/v2/deputados/{id}"
SENADO_LISTA = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json"
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter_json(url: str) -> dict:
    for tentativa in range(5):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=45) as resposta:
                return json.load(resposta)
        except urllib.error.HTTPError as erro:
            if erro.code != 429 or tentativa == 4:
                raise
            __import__("time").sleep(2 ** tentativa)
    raise RuntimeError("Fonte oficial indisponível")


def normalizar(nome: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", nome or "") if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).strip()


def deputados_atuais(nomes_prioritarios: set[tuple[str, str]]) -> list[dict]:
    resumo, url = [], CAMARA_LISTA
    while url:
        doc = obter_json(url)
        resumo.extend(doc.get("dados", []))
        url = next((x["href"] for x in doc.get("links", []) if x.get("rel") == "next"), None)

    # A lista já contém nome parlamentar e UF. Só abrimos perfis que podem
    # corresponder exatamente ao nome civil ou de urna de alguém prioritário.
    resumo = [x for x in resumo if (normalizar(x.get("nome", "")), x.get("siglaUf", "")) in nomes_prioritarios]

    def detalhe(item: dict) -> dict:
        d = obter_json(CAMARA_PERFIL.format(id=item["id"])).get("dados", {})
        status = d.get("ultimoStatus") or {}
        return {
            "casa": "Câmara dos Deputados",
            "cargo": "Deputado Federal",
            "id_oficial": str(item["id"]),
            "nome_civil": d.get("nomeCivil") or "",
            "nome_parlamentar": status.get("nome") or item.get("nome") or "",
            "uf": status.get("siglaUf") or item.get("siglaUf") or "",
            "partido": status.get("siglaPartido") or item.get("siglaPartido") or "",
            "situacao": status.get("situacao") or "Em exercício na lista atual",
            "legislatura": status.get("idLegislatura") or item.get("idLegislatura"),
            "inicio_status": status.get("data") or None,
            "url_perfil": f"https://www.camara.leg.br/deputados/{item['id']}",
            "url_api": CAMARA_PERFIL.format(id=item["id"]),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(detalhe, resumo))


def senadores_atuais() -> list[dict]:
    doc = obter_json(SENADO_LISTA)["ListaParlamentarEmExercicio"]
    itens = doc.get("Parlamentares", {}).get("Parlamentar", [])
    saida = []
    for item in itens:
        ident, mandato = item.get("IdentificacaoParlamentar", {}), item.get("Mandato", {})
        exercicios = mandato.get("Exercicios", {}).get("Exercicio", [])
        if isinstance(exercicios, dict):
            exercicios = [exercicios]
        legislaturas = []
        for chave in ("PrimeiraLegislaturaDoMandato", "SegundaLegislaturaDoMandato"):
            if mandato.get(chave):
                legislaturas.append(mandato[chave])
        saida.append({
            "casa": "Senado Federal",
            "cargo": "Senador",
            "id_oficial": str(ident.get("CodigoParlamentar", "")),
            "nome_civil": ident.get("NomeCompletoParlamentar") or "",
            "nome_parlamentar": ident.get("NomeParlamentar") or "",
            "uf": ident.get("UfParlamentar") or mandato.get("UfParlamentar") or "",
            "partido": ident.get("SiglaPartidoParlamentar") or "",
            "situacao": "Em exercício na lista atual",
            "participacao": mandato.get("DescricaoParticipacao") or "",
            "legislaturas": legislaturas,
            "exercicios": exercicios,
            "url_perfil": (ident.get("UrlPaginaParlamentar") or "").replace("http://", "https://"),
            "url_api": SENADO_LISTA,
        })
    return saida


def main() -> None:
    escopo = ler_b64(RAIZ / "dados/escopo_prioritario_2026.b64")
    candidatos = escopo["candidatos"]
    indice: dict[tuple[str, str], list[dict]] = defaultdict(list)
    nomes_prioritarios: set[tuple[str, str]] = set()
    presidentes: dict[str, list[dict]] = defaultdict(list)
    for c in candidatos:
        chave_nome = normalizar(c.get("nome", ""))
        if c.get("uf") == "BR":
            presidentes[chave_nome].append(c)
        else:
            indice[(chave_nome, c.get("uf", ""))].append(c)
            nomes_prioritarios.add((chave_nome, c.get("uf", "")))
            nomes_prioritarios.add((normalizar(c.get("nome_urna", "")), c.get("uf", "")))

    oficiais = deputados_atuais(nomes_prioritarios) + senadores_atuais()
    vinculos, ambiguos = {}, []
    for pessoa in oficiais:
        nome = normalizar(pessoa["nome_civil"])
        achados = indice.get((nome, pessoa["uf"]), []) + presidentes.get(nome, [])
        unicos = {x["sq_candidato"]: x for x in achados}
        if len(unicos) == 1:
            candidato = next(iter(unicos.values()))
            vinculos[candidato["sq_candidato"]] = {
                **pessoa,
                "sq_candidato": candidato["sq_candidato"],
                "partido_candidatura_2026": candidato.get("partido_sigla", ""),
                "metodo_vinculo": "nome_civil_exato_normalizado+uf" if candidato.get("uf") != "BR" else "nome_civil_exato_normalizado+unicidade",
            }
        elif len(unicos) > 1:
            ambiguos.append({"nome_civil": pessoa["nome_civil"], "uf": pessoa["uf"], "ids_candidatos": sorted(unicos)})

    contagem_casa = Counter(x["casa"] for x in vinculos.values())
    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    documento = {
        "eleicao": 2026,
        "escopo": "mandatos_federais_atuais",
        "atualizado_em_utc": agora,
        "criterio_vinculo": "Nome civil exatamente igual após normalização e mesma UF; Presidência exige nome único. Duplicidades ficam sem vínculo.",
        "fontes": {"camara": CAMARA_LISTA, "senado": SENADO_LISTA},
        "quantidade_registros_oficiais_avaliados": len(oficiais),
        "quantidade_vinculos": len(vinculos),
        "quantidade_ambiguos": len(ambiguos),
        "por_casa": dict(sorted(contagem_casa.items())),
        "mandatos": dict(sorted(vinculos.items())),
        "ambiguos": ambiguos,
    }
    gravar_b64(OUT, documento)
    manifesto = {k: documento[k] for k in ("eleicao", "escopo", "atualizado_em_utc", "criterio_vinculo", "fontes", "quantidade_registros_oficiais_avaliados", "quantidade_vinculos", "quantidade_ambiguos", "por_casa")}
    manifesto["arquivo"] = "dados/mandatos_federais_atuais_2026.b64"
    manifesto["observacao"] = "Esta carga cobre mandatos federais em exercício; mandatos anteriores e estaduais entram nas próximas cargas."
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
