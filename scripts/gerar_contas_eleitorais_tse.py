#!/usr/bin/env python3
"""Agrega receitas e despesas de 2026 sem publicar doadores, fornecedores ou documentos."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def centavos(valor: object) -> int:
    texto = str(valor or "0").strip().replace(".", "").replace(",", ".")
    try:
        return int((Decimal(texto) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return 0


def catalogo(raiz: Path) -> tuple[dict[str, str], int]:
    manifesto = json.loads((raiz / "dados/candidatos_manifesto_2026.json").read_text(encoding="utf-8"))
    referencias = list(manifesto["cargas_iniciais"])
    for cargas in manifesto["cargas_por_cargo"].values():
        referencias.extend(cargas.values())
    uf_por_id: dict[str, str] = {}
    for ref in referencias:
        doc = ler_b64(raiz / ref["arquivo"])
        for candidato in doc.get("candidatos", []):
            cid = str(candidato.get("sq_candidato", ""))
            if cid:
                uf_por_id[cid] = candidato.get("uf") or "BR"
    esperado = int(manifesto["quantidade_publicada"])
    if len(uf_por_id) != esperado:
        raise SystemExit(f"Catálogo divergente: {len(uf_por_id)} IDs; manifesto informa {esperado}")
    return uf_por_id, esperado


def linhas(zf: zipfile.ZipFile, nome: str):
    with zf.open(nome) as bruto:
        yield from csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--saida", type=Path, default=Path("."))
    args = parser.parse_args()
    uf_por_id, total_catalogo = catalogo(args.saida)
    dados_candidato: dict[str, dict] = {}
    prestador_para_candidato: dict[str, str] = {}
    gerado = ""
    lidas = defaultdict(int)

    def registro(cid: str) -> dict:
        return dados_candidato.setdefault(cid, {
            "receitas_centavos": 0,
            "despesas_contratadas_centavos": 0,
            "despesas_pagas_centavos": 0,
            "quantidade_receitas": 0,
            "quantidade_despesas_contratadas": 0,
            "quantidade_pagamentos": 0,
            "origens_receitas": defaultdict(int),
            "origens_despesas": defaultdict(int),
        })

    with zipfile.ZipFile(args.zip) as zf:
        for tipo, nome, campo_valor, campo_origem in (
            ("receitas", "receitas_candidatos_2026_BRASIL.csv", "VR_RECEITA", "DS_ORIGEM_RECEITA"),
            ("contratadas", "despesas_contratadas_candidatos_2026_BRASIL.csv", "VR_DESPESA_CONTRATADA", "DS_ORIGEM_DESPESA"),
        ):
            for linha in linhas(zf, nome):
                lidas[tipo] += 1
                if not gerado:
                    gerado = " ".join(filter(None, [linha.get("DT_GERACAO", "").strip(), linha.get("HH_GERACAO", "").strip()]))
                cid = linha.get("SQ_CANDIDATO", "").strip()
                if cid not in uf_por_id:
                    continue
                prestador = linha.get("SQ_PRESTADOR_CONTAS", "").strip()
                if prestador:
                    prestador_para_candidato[prestador] = cid
                item = registro(cid)
                valor = centavos(linha.get(campo_valor))
                origem = (linha.get(campo_origem) or "Não especificada").strip()
                if tipo == "receitas":
                    item["receitas_centavos"] += valor
                    item["quantidade_receitas"] += 1
                    item["origens_receitas"][origem] += valor
                else:
                    item["despesas_contratadas_centavos"] += valor
                    item["quantidade_despesas_contratadas"] += 1
                    item["origens_despesas"][origem] += valor

        pagamentos_sem_vinculo = 0
        for linha in linhas(zf, "despesas_pagas_candidatos_2026_BRASIL.csv"):
            lidas["pagas"] += 1
            cid = prestador_para_candidato.get(linha.get("SQ_PRESTADOR_CONTAS", "").strip())
            if not cid:
                pagamentos_sem_vinculo += 1
                continue
            item = registro(cid)
            item["despesas_pagas_centavos"] += centavos(linha.get("VR_PAGTO_DESPESA"))
            item["quantidade_pagamentos"] += 1

    por_uf: dict[str, dict[str, dict]] = defaultdict(dict)
    for cid, item in dados_candidato.items():
        item["origens_receitas"] = [
            {"origem": k, "valor_centavos": v}
            for k, v in sorted(item["origens_receitas"].items(), key=lambda x: (-x[1], x[0]))
        ]
        item["origens_despesas"] = [
            {"origem": k, "valor_centavos": v}
            for k, v in sorted(item["origens_despesas"].items(), key=lambda x: (-x[1], x[0]))
        ]
        por_uf[uf_por_id[cid]][cid] = item

    if len(dados_candidato) < 1_000:
        raise SystemExit(f"Cobertura financeira anormalmente baixa: {len(dados_candidato)} candidatos")
    dados = args.saida / "dados"
    arquivos = {}
    totais = defaultdict(int)
    for uf in sorted(set(uf_por_id.values())):
        registros = por_uf.get(uf, {})
        nome = f"contas_eleitorais_2026_{uf.lower()}.b64"
        doc = {
            "ano": 2026,
            "uf_atual": uf,
            "fonte": "Tribunal Superior Eleitoral — Prestação de contas eleitorais de candidatos",
            "fonte_url": "https://dadosabertos.tse.jus.br/",
            "gerado_pelo_tse_em": gerado,
            "contas": registros,
        }
        gravar_b64(dados / nome, doc)
        arquivos[uf] = {"arquivo": f"dados/{nome}", "quantidade_candidatos": len(registros)}
        for item in registros.values():
            for campo in ("receitas_centavos", "despesas_contratadas_centavos", "despesas_pagas_centavos"):
                totais[campo] += item[campo]

    manifesto = {
        "ano": 2026,
        "fonte": "Tribunal Superior Eleitoral — Prestação de contas eleitorais de candidatos",
        "fonte_url": "https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026",
        "gerado_pelo_tse_em": gerado,
        "quantidade_candidatos_no_catalogo": total_catalogo,
        "quantidade_candidatos_com_movimentacao": len(dados_candidato),
        "linhas_oficiais_processadas": dict(lidas),
        "pagamentos_sem_vinculo_excluidos": pagamentos_sem_vinculo,
        "totais_centavos": dict(totais),
        "arquivos_por_uf_atual": arquivos,
        "observacao": "Valores declarados ao TSE e sujeitos a atualização. A ausência de movimentação não significa irregularidade. Nomes, documentos, descrições livres, doadores e fornecedores não são publicados nesta carga agregada.",
    }
    (dados / "contas_eleitorais_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
