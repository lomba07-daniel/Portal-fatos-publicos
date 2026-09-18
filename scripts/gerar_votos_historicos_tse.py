#!/usr/bin/env python3
"""Agrega votos oficiais por candidatura histórica já publicada no portal."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path


def inteiro(valor: object) -> int:
    try:
        return int(str(valor or "0").strip())
    except ValueError:
        return 0


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--saida", type=Path, default=Path("."))
    args = parser.parse_args()

    manifesto_hist = json.loads(
        (args.saida / "dados/historico_candidaturas_manifesto_2026.json").read_text(encoding="utf-8")
    )
    alvos: dict[tuple[str, str, str], tuple[str, str]] = {}
    for uf, referencia in manifesto_hist["arquivos_por_uf_atual"].items():
        doc = ler_b64(args.saida / referencia["arquivo"])
        for atual, historicos in doc["historicos"].items():
            for item in historicos:
                sq = item.get("sq_candidato_eleicao", "")
                if sq:
                    alvos[(item["ano"], sq, item.get("turno", "1"))] = (uf, atual)

    if len(alvos) < 40_000:
        raise SystemExit(f"Apenas {len(alvos)} candidaturas históricas identificáveis; base incompleta.")

    totais: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    anos: list[int] = []
    linhas_lidas = 0
    linhas_aproveitadas = 0
    geracoes: dict[str, str] = {}

    for zip_path in args.zips:
        match = re.search(r"(20\d{2}|19\d{2})", zip_path.name)
        if not match:
            raise SystemExit(f"Ano não identificado no nome: {zip_path}")
        ano = match.group(1)
        anos.append(int(ano))
        with zipfile.ZipFile(zip_path) as zf:
            membros = [
                n for n in zf.namelist()
                if n.lower().endswith(".csv") and not n.upper().endswith("_BRASIL.CSV")
            ]
            if not membros:
                raise SystemExit(f"Nenhum CSV estadual encontrado em {zip_path}.")
            for membro in membros:
                with zf.open(membro) as bruto:
                    reader = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
                    for linha in reader:
                        linhas_lidas += 1
                        if ano not in geracoes:
                            geracoes[ano] = " ".join(
                                filter(None, [linha.get("DT_GERACAO", "").strip(), linha.get("HH_GERACAO", "").strip()])
                            )
                        chave = (ano, linha.get("SQ_CANDIDATO", "").strip(), linha.get("NR_TURNO", "").strip())
                        if chave not in alvos:
                            continue
                        totais[chave][0] += inteiro(linha.get("QT_VOTOS_NOMINAIS"))
                        totais[chave][1] += inteiro(linha.get("QT_VOTOS_NOMINAIS_VALIDOS"))
                        linhas_aproveitadas += 1

    por_uf: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    for chave, (votos, validos) in totais.items():
        ano, sq, turno = chave
        uf, atual = alvos[chave]
        por_uf[uf][atual].append({
            "ano": ano,
            "sq_candidato_eleicao": sq,
            "turno": turno,
            "votos_nominais": votos,
            "votos_nominais_validos": validos,
        })

    dados = args.saida / "dados"
    arquivos = {}
    candidaturas_com_votos = 0
    for uf in manifesto_hist["arquivos_por_uf_atual"]:
        candidatos = por_uf.get(uf, {})
        for itens in candidatos.values():
            itens.sort(key=lambda x: (int(x["ano"]), int(x["turno"])), reverse=True)
            candidaturas_com_votos += len(itens)
        nome = f"votos_historicos_2026_{uf.lower()}.b64"
        doc = {
            "uf_atual": uf,
            "anos_carregados": sorted(set(anos)),
            "fonte": "Tribunal Superior Eleitoral — Votação nominal por município e zona",
            "fonte_url": "https://dadosabertos.tse.jus.br/",
            "gerado_pelo_tse_em": geracoes,
            "quantidade_candidatos": len(candidatos),
            "quantidade_candidaturas_com_votos": sum(map(len, candidatos.values())),
            "votos": candidatos,
        }
        gravar_b64(dados / nome, doc)
        arquivos[uf] = {
            "arquivo": f"dados/{nome}",
            "quantidade_candidatos": doc["quantidade_candidatos"],
            "quantidade_candidaturas_com_votos": doc["quantidade_candidaturas_com_votos"],
        }

    if candidaturas_com_votos < 1_000:
        raise SystemExit(f"Cobertura de votos anormalmente baixa: {candidaturas_com_votos} candidaturas.")
    manifesto = {
        "anos_carregados": sorted(set(anos)),
        "fonte": "Tribunal Superior Eleitoral — Votação nominal por município e zona",
        "fonte_url": "https://dadosabertos.tse.jus.br/",
        "gerado_pelo_tse_em": geracoes,
        "quantidade_candidaturas_com_votos": candidaturas_com_votos,
        "linhas_oficiais_processadas": linhas_lidas,
        "linhas_oficiais_aproveitadas": linhas_aproveitadas,
        "arquivos_por_uf_atual": arquivos,
        "observacao": "Totais agregados por candidatura e turno; arquivos brutos por município e zona não são publicados.",
    }
    (dados / "votos_historicos_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
