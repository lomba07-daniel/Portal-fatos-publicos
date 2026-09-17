#!/usr/bin/env python3
"""Gera cargas compactas do catálogo eleitoral a partir do ZIP oficial do TSE.

O arquivo de origem contém dados pessoais que não são necessários ao portal.
Somente os campos explicitamente selecionados em ``normalizar`` são publicados.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


ANO = 2026
CARGOS = {
    "PRESIDENTE": ("Presidente", "profunda"),
    "GOVERNADOR": ("Governador", "profunda"),
    "SENADOR": ("Senador", "intermediaria"),
    "DEPUTADO FEDERAL": ("Deputado Federal", "intermediaria"),
    "DEPUTADO ESTADUAL": ("Deputado Estadual", "basica"),
    "DEPUTADO DISTRITAL": ("Deputado Distrital", "basica"),
}
ORDEM_CARGOS = [nome for nome, _ in CARGOS.values()]
ARQUIVOS_INICIAIS = {
    "executivos": "dados/candidatos_executivos_2026.b64",
    "senado": "dados/candidatos_senado_2026.b64",
}
PREFIXOS = {
    "Deputado Federal": "candidatos_deputado_federal_2026",
    "Deputado Estadual": "candidatos_deputado_estadual_2026",
    "Deputado Distrital": "candidatos_deputado_distrital_2026",
}


def texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def normalizar(linha: dict[str, str]) -> dict[str, str]:
    cargo, camada = CARGOS[texto(linha.get("DS_CARGO"))]
    uf = texto(linha.get("SG_UF"))
    if cargo == "Presidente":
        uf = "BR"
    return {
        "sq_candidato": texto(linha.get("SQ_CANDIDATO")),
        "nome": texto(linha.get("NM_CANDIDATO")),
        "nome_urna": texto(linha.get("NM_URNA_CANDIDATO")),
        "cargo": cargo,
        "cargo_codigo": texto(linha.get("CD_CARGO")),
        "uf": uf,
        "unidade_eleitoral": texto(linha.get("NM_UE")) or uf,
        "numero": texto(linha.get("NR_CANDIDATO")),
        "partido_sigla": texto(linha.get("SG_PARTIDO")),
        "partido_nome": texto(linha.get("NM_PARTIDO")),
        "situacao_candidatura": texto(linha.get("DS_SITUACAO_CANDIDATURA")),
        "situacao_totalizacao": texto(linha.get("DS_SIT_TOT_TURNO")),
        "camada": camada,
    }


def ler_csv_oficial(zip_path: Path) -> tuple[list[dict[str, str]], str, str]:
    with zipfile.ZipFile(zip_path) as zf:
        nomes = zf.namelist()
        preferido = f"consulta_cand_{ANO}_BRASIL.csv"
        csv_nome = preferido if preferido in nomes else next(
            (n for n in nomes if n.lower().endswith("_brasil.csv")), ""
        )
        if not csv_nome:
            raise SystemExit("CSV nacional do TSE não encontrado no ZIP.")
        with zf.open(csv_nome) as bruto:
            reader = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
            linhas = [r for r in reader if texto(r.get("DS_CARGO")) in CARGOS]

    if not linhas:
        raise SystemExit("Nenhuma candidatura dos cargos previstos foi encontrada.")
    primeira = linhas[0]
    gerado = " ".join(filter(None, [texto(primeira.get("DT_GERACAO")), texto(primeira.get("HH_GERACAO"))]))
    return linhas, csv_nome, gerado


def documento(
    candidatos: list[dict[str, str]],
    *,
    arquivo_origem: str,
    gerado_pelo_tse_em: str,
    cargo: str,
    uf: str,
) -> dict[str, object]:
    candidatos.sort(key=lambda x: (x["nome_urna"] or x["nome"], x["sq_candidato"]))
    return {
        "ano": ANO,
        "fonte": "Tribunal Superior Eleitoral — Dados Abertos",
        "fonte_url": f"https://dadosabertos.tse.jus.br/dataset/candidatos-{ANO}",
        "arquivo_origem": arquivo_origem,
        "gerado_pelo_tse_em": gerado_pelo_tse_em,
        "cargo": cargo,
        "uf": uf,
        "quantidade": len(candidatos),
        "minimizacao": "Campos pessoais não necessários ao catálogo foram omitidos.",
        "candidatos": candidatos,
    }


def gravar_b64(destino: Path, doc: dict[str, object]) -> None:
    bruto = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    comprimido = gzip.compress(bruto, compresslevel=9, mtime=0)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(base64.b64encode(comprimido).decode("ascii") + "\n", encoding="ascii")


def validar_documentos(saidas: list[Path], esperado: int) -> None:
    ids: set[str] = set()
    total = 0
    proibidos = {
        "NR_CPF_CANDIDATO",
        "DS_EMAIL",
        "DT_NASCIMENTO",
        "NR_TITULO_ELEITORAL_CANDIDATO",
    }
    for arquivo in saidas:
        texto_b64 = "".join(arquivo.read_text(encoding="ascii").split())
        doc = json.loads(gzip.decompress(base64.b64decode(texto_b64, validate=True)))
        candidatos = doc.get("candidatos", [])
        if doc.get("quantidade") != len(candidatos):
            raise SystemExit(f"Quantidade divergente em {arquivo}.")
        for candidato in candidatos:
            if proibidos.intersection(candidato):
                raise SystemExit(f"Campo pessoal proibido encontrado em {arquivo}.")
            sq = candidato["sq_candidato"]
            if sq in ids:
                raise SystemExit(f"Candidatura duplicada: {sq}.")
            ids.add(sq)
        total += len(candidatos)
    if total != esperado:
        raise SystemExit(f"Total publicado divergente: {total}; esperado: {esperado}.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path, help="ZIP oficial consulta_cand_2026")
    parser.add_argument("--saida", type=Path, default=Path("."), help="raiz do portal")
    parser.add_argument(
        "--escopo",
        choices=("federal", "completo"),
        default="federal",
        help="federal publica até a Câmara; completo inclui assembleias e Câmara Legislativa",
    )
    args = parser.parse_args()

    linhas, arquivo_origem, gerado = ler_csv_oficial(args.zip)
    normalizados = [normalizar(linha) for linha in linhas]
    por_cargo: dict[str, list[dict[str, str]]] = defaultdict(list)
    for candidato in normalizados:
        por_cargo[candidato["cargo"]].append(candidato)

    esperados = {
        "Presidente": 14,
        "Governador": 201,
        "Senador": 319,
        "Deputado Federal": 7801,
        "Deputado Estadual": 11292,
        "Deputado Distrital": 433,
    }
    for cargo, minimo in esperados.items():
        if len(por_cargo[cargo]) != minimo:
            raise SystemExit(f"Validação falhou para {cargo}: {len(por_cargo[cargo])}; esperado: {minimo}.")

    dados = args.saida / "dados"
    saidas: list[Path] = []
    cargas_iniciais: list[dict[str, object]] = []

    executivos = por_cargo["Presidente"] + por_cargo["Governador"]
    arq_exec = args.saida / ARQUIVOS_INICIAIS["executivos"]
    gravar_b64(
        arq_exec,
        documento(executivos, arquivo_origem=arquivo_origem, gerado_pelo_tse_em=gerado, cargo="Executivos", uf="BR"),
    )
    saidas.append(arq_exec)
    cargas_iniciais.append({"arquivo": ARQUIVOS_INICIAIS["executivos"], "quantidade": len(executivos)})

    arq_sen = args.saida / ARQUIVOS_INICIAIS["senado"]
    gravar_b64(
        arq_sen,
        documento(por_cargo["Senador"], arquivo_origem=arquivo_origem, gerado_pelo_tse_em=gerado, cargo="Senador", uf="BR"),
    )
    saidas.append(arq_sen)
    cargas_iniciais.append({"arquivo": ARQUIVOS_INICIAIS["senado"], "quantidade": len(por_cargo["Senador"])})

    cargos_particionados = ["Deputado Federal"]
    if args.escopo == "completo":
        cargos_particionados += ["Deputado Estadual", "Deputado Distrital"]

    cargas_por_cargo: dict[str, dict[str, dict[str, object]]] = {}
    for cargo in cargos_particionados:
        por_uf: dict[str, list[dict[str, str]]] = defaultdict(list)
        for candidato in por_cargo[cargo]:
            por_uf[candidato["uf"]].append(candidato)
        cargas_por_cargo[cargo] = {}
        for uf, candidatos in sorted(por_uf.items()):
            nome = f"{PREFIXOS[cargo]}_{uf.lower()}.b64"
            relativo = f"dados/{nome}"
            destino = dados / nome
            gravar_b64(
                destino,
                documento(candidatos, arquivo_origem=arquivo_origem, gerado_pelo_tse_em=gerado, cargo=cargo, uf=uf),
            )
            saidas.append(destino)
            cargas_por_cargo[cargo][uf] = {"arquivo": relativo, "quantidade": len(candidatos)}

    publicados = ["Presidente", "Governador", "Senador"] + cargos_particionados
    contagens = Counter(c["cargo"] for c in normalizados if c["cargo"] in publicados)
    manifesto = {
        "ano": ANO,
        "fonte": "Tribunal Superior Eleitoral — Dados Abertos",
        "fonte_url": f"https://dadosabertos.tse.jus.br/dataset/candidatos-{ANO}",
        "arquivo_origem": arquivo_origem,
        "gerado_pelo_tse_em": gerado,
        "quantidade_publicada": sum(contagens.values()),
        "por_cargo": {cargo: contagens[cargo] for cargo in ORDEM_CARGOS if cargo in contagens},
        "cargas_iniciais": cargas_iniciais,
        "cargas_por_cargo": cargas_por_cargo,
        "estrategia": "Cargas iniciais compactas e candidaturas legislativas carregadas sob demanda por cargo e UF.",
        "minimizacao": "CPF, e-mail, data de nascimento, título eleitoral e outros campos pessoais não necessários não são publicados.",
    }
    manifesto_path = dados / "candidatos_manifesto_2026.json"
    manifesto_path.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validar_documentos(saidas, manifesto["quantidade_publicada"])
    print(json.dumps({"quantidade_publicada": manifesto["quantidade_publicada"], "por_cargo": manifesto["por_cargo"], "arquivos_b64": len(saidas)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
