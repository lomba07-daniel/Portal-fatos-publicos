#!/usr/bin/env python3
"""Gera histórico eleitoral compacto dos candidatos de 2026 a partir do TSE."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path


def txt(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def gravar_b64(destino: Path, documento: dict[str, object]) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    destino.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def ids_do_catalogo(raiz: Path) -> set[str]:
    manifesto_path = raiz / "dados/candidatos_manifesto_2026.json"
    if not manifesto_path.exists():
        raise SystemExit("Manifesto do catálogo atual não encontrado; histórico não pode ser delimitado com segurança.")
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    referencias = list(manifesto.get("cargas_iniciais", []))
    for cargas_uf in manifesto.get("cargas_por_cargo", {}).values():
        referencias.extend(cargas_uf.values())
    ids: set[str] = set()
    for referencia in referencias:
        caminho = raiz / referencia["arquivo"]
        doc = json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))
        ids.update(txt(c.get("sq_candidato")) for c in doc.get("candidatos", []))
    ids.discard("")
    esperado = int(manifesto.get("quantidade_publicada", 0))
    if len(ids) != esperado:
        raise SystemExit(f"Catálogo atual divergente: {len(ids)} identificadores; manifesto informa {esperado}.")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--saida", type=Path, default=Path("."))
    args = parser.parse_args()

    ids_publicados = ids_do_catalogo(args.saida)

    with zipfile.ZipFile(args.zip) as zf:
        nome = "historico_candidatura_2026_BRASIL.csv"
        if nome not in zf.namelist():
            raise SystemExit(f"{nome} não encontrado no ZIP oficial.")
        with zf.open(nome) as bruto:
            reader = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
            linhas = list(reader)

    if len(linhas) < 40_000:
        raise SystemExit(f"Histórico anormalmente pequeno: {len(linhas)} linhas.")

    gerado = " ".join(filter(None, [txt(linhas[0].get("DT_GERACAO")), txt(linhas[0].get("HH_GERACAO"))]))
    por_uf: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    vistos: set[tuple[str, ...]] = set()

    for linha in linhas:
        atual = txt(linha.get("SQ_CANDIDATO_ATUAL"))
        uf_atual = txt(linha.get("SG_UF_ATUAL")) or "BR"
        if not atual or atual not in ids_publicados:
            continue
        item = {
            "sq_candidato_eleicao": txt(linha.get("SQ_CANDIDATO")),
            "ano": txt(linha.get("ANO_ELEICAO")),
            "eleicao": txt(linha.get("DS_ELEICAO")),
            "data_eleicao": txt(linha.get("DT_ELEICAO"))[:10],
            "turno": txt(linha.get("NR_TURNO")),
            "uf": txt(linha.get("SG_UF")),
            "unidade_eleitoral": txt(linha.get("NM_UE")),
            "cargo": txt(linha.get("DS_CARGO")),
            "numero": txt(linha.get("NR_CANDIDATO")),
            "partido_sigla": txt(linha.get("SG_PARTIDO")),
            "partido_nome": txt(linha.get("NM_PARTIDO")),
            "situacao_candidatura": txt(linha.get("DS_SITUACAO_CANDIDATURA")),
            "situacao_julgamento": txt(linha.get("DS_SITUACAO_JULGAMENTO")),
            "resultado": txt(linha.get("DS_SIT_TOT_TURNO")),
        }
        chave = (atual,) + tuple(item.values())
        if chave in vistos:
            continue
        vistos.add(chave)
        por_uf[uf_atual][atual].append(item)

    dados = args.saida / "dados"
    dados.mkdir(parents=True, exist_ok=True)
    arquivos: dict[str, dict[str, object]] = {}
    total_candidatos = 0
    total_registros = 0
    for uf, candidatos in sorted(por_uf.items()):
        for historico in candidatos.values():
            historico.sort(key=lambda x: (int(x["ano"] or 0), int(x["turno"] or 0)), reverse=True)
        nome_saida = f"historico_candidaturas_2026_{uf.lower()}.b64"
        doc = {
            "ano_referencia": 2026,
            "uf_atual": uf,
            "fonte": "Tribunal Superior Eleitoral — Histórico de candidaturas",
            "fonte_url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
            "gerado_pelo_tse_em": gerado,
            "quantidade_candidatos": len(candidatos),
            "quantidade_registros": sum(map(len, candidatos.values())),
            "historicos": candidatos,
        }
        gravar_b64(dados / nome_saida, doc)
        arquivos[uf] = {
            "arquivo": f"dados/{nome_saida}",
            "quantidade_candidatos": doc["quantidade_candidatos"],
            "quantidade_registros": doc["quantidade_registros"],
        }
        total_candidatos += doc["quantidade_candidatos"]
        total_registros += doc["quantidade_registros"]

    if total_candidatos < 15_000 or total_registros < 40_000 or len(arquivos) != 28:
        raise SystemExit(
            f"Validação falhou: {total_candidatos} candidatos, {total_registros} registros, {len(arquivos)} partições."
        )

    manifesto = {
        "ano_referencia": 2026,
        "fonte": "Tribunal Superior Eleitoral — Histórico de candidaturas",
        "fonte_url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
        "gerado_pelo_tse_em": gerado,
        "quantidade_candidatos_com_historico": total_candidatos,
        "quantidade_candidatos_sem_historico": len(ids_publicados) - total_candidatos,
        "quantidade_candidatos_no_catalogo": len(ids_publicados),
        "quantidade_registros": total_registros,
        "periodo": {"inicio": 2004, "fim": 2026},
        "arquivos_por_uf_atual": arquivos,
        "observacao": "Ausência de registro significa apenas que não foi localizada candidatura anterior no recurso histórico do TSE.",
    }
    (dados / "historico_candidaturas_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
