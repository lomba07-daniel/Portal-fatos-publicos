#!/usr/bin/env python3
"""Agrega bens declarados por candidato e eleição, sem publicar descrições pessoais."""

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--saida", type=Path, default=Path("."))
    args = parser.parse_args()

    manifesto_hist = json.loads(
        (args.saida / "dados/historico_candidaturas_manifesto_2026.json").read_text(encoding="utf-8")
    )
    alvos: dict[tuple[str, str, str], tuple[str, str]] = {}
    ambiguas_alvo: set[tuple[str, str, str]] = set()
    for uf_atual, referencia in manifesto_hist["arquivos_por_uf_atual"].items():
        doc = ler_b64(args.saida / referencia["arquivo"])
        for atual, historicos in doc["historicos"].items():
            for item in historicos:
                sq = item.get("sq_candidato_eleicao", "")
                if not sq:
                    continue
                uf_eleicao = "*" if item.get("cargo") == "Presidente" else item.get("uf", "")
                chave = (item["ano"], sq, uf_eleicao)
                destino = (uf_atual, atual)
                if chave in alvos and alvos[chave] != destino:
                    ambiguas_alvo.add(chave)
                else:
                    alvos[chave] = destino
    for chave in ambiguas_alvo:
        alvos.pop(chave, None)

    grupos: dict[tuple[str, str, str], dict] = {}
    geracoes: dict[str, str] = {}
    linhas_lidas = 0
    linhas_aproveitadas = 0
    anos: set[int] = set()
    for zip_path in args.zips:
        match = re.search(r"(20\d{2}|19\d{2})", zip_path.name)
        if not match:
            raise SystemExit(f"Ano não identificado: {zip_path}")
        ano = match.group(1)
        anos.add(int(ano))
        with zipfile.ZipFile(zip_path) as zf:
            membros = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            for membro in membros:
                with zf.open(membro) as bruto:
                    reader = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
                    for linha in reader:
                        linhas_lidas += 1
                        sq = (linha.get("SQ_CANDIDATO") or "").strip()
                        uf_eleicao = (linha.get("SG_UF") or "").strip()
                        chave_alvo = (ano, sq, uf_eleicao)
                        if chave_alvo not in alvos:
                            chave_alvo = (ano, sq, "*")
                        if chave_alvo not in alvos:
                            continue
                        if ano not in geracoes:
                            geracoes[ano] = " ".join(filter(None, [
                                (linha.get("DT_GERACAO") or "").strip(),
                                (linha.get("HH_GERACAO") or "").strip(),
                            ]))
                        uf_atual, atual = alvos[chave_alvo]
                        chave = (uf_atual, atual, ano)
                        grupo = grupos.setdefault(chave, {"total_centavos": 0, "quantidade_bens": 0, "tipos": defaultdict(int)})
                        valor = centavos(linha.get("VR_BEM_CANDIDATO"))
                        tipo = (linha.get("DS_TIPO_BEM_CANDIDATO") or "Não especificado").strip()
                        grupo["total_centavos"] += valor
                        grupo["quantidade_bens"] += 1
                        grupo["tipos"][tipo] += valor
                        linhas_aproveitadas += 1

    por_uf: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for (uf_atual, atual, ano), grupo in grupos.items():
        tipos = [
            {"tipo": tipo, "valor_centavos": valor}
            for tipo, valor in sorted(grupo["tipos"].items(), key=lambda x: (-x[1], x[0]))
        ]
        por_uf[uf_atual][atual].append({
            "ano": ano,
            "total_centavos": grupo["total_centavos"],
            "quantidade_bens": grupo["quantidade_bens"],
            "tipos": tipos,
        })

    dados = args.saida / "dados"
    arquivos = {}
    candidatos = set()
    declaracoes = 0
    total_centavos = 0
    for uf_atual in manifesto_hist["arquivos_por_uf_atual"]:
        registros = por_uf.get(uf_atual, {})
        for atual, itens in registros.items():
            itens.sort(key=lambda x: int(x["ano"]), reverse=True)
            candidatos.add(atual)
            declaracoes += len(itens)
            total_centavos += sum(x["total_centavos"] for x in itens)
        nome = f"patrimonio_historico_2026_{uf_atual.lower()}.b64"
        doc = {
            "uf_atual": uf_atual,
            "anos_carregados": sorted(anos),
            "fonte": "Tribunal Superior Eleitoral — Bens de candidatos",
            "fonte_url": "https://dadosabertos.tse.jus.br/",
            "patrimonios": registros,
        }
        gravar_b64(dados / nome, doc)
        arquivos[uf_atual] = {
            "arquivo": f"dados/{nome}",
            "quantidade_candidatos": len(registros),
            "quantidade_declaracoes": sum(map(len, registros.values())),
        }

    if len(candidatos) < 5_000 or declaracoes < 5_000 or len(arquivos) != 28:
        raise SystemExit(f"Cobertura patrimonial anormal: {len(candidatos)} candidatos, {declaracoes} declarações.")
    manifesto = {
        "anos_carregados": sorted(anos),
        "fonte": "Tribunal Superior Eleitoral — Bens de candidatos",
        "fonte_url": "https://dadosabertos.tse.jus.br/",
        "gerado_pelo_tse_em": geracoes,
        "quantidade_candidatos_com_bens": len(candidatos),
        "quantidade_declaracoes": declaracoes,
        "linhas_oficiais_processadas": linhas_lidas,
        "linhas_oficiais_aproveitadas": linhas_aproveitadas,
        "valor_total_centavos": total_centavos,
        "associacoes_historicas_ambiguas_excluidas": len(ambiguas_alvo),
        "arquivos_por_uf_atual": arquivos,
        "observacao": "Valores nominais declarados ao TSE. Variação entre eleições não representa, isoladamente, renda, ganho real ou irregularidade. Descrições livres dos bens não são publicadas para reduzir exposição de dados pessoais.",
    }
    (dados / "patrimonio_historico_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
