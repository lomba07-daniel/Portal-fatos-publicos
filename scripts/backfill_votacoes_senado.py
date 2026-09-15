#!/usr/bin/env python3
"""Backfill único das votações nominais de 2019 a 2025.

Reutiliza o mesmo parser/normalização já validado para 2026.
Não altera a rotina diária, que continua leve e limitada ao ano corrente.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import atualizar_votacoes_senado as atual

ANOS = range(2019, 2026)
OUT = Path("dados/votacoes_senado_historico.json")


def parse_year(payload, ano: int, url: str):
    antigo_ano, antiga_url = atual.ANO_ATUAL, atual.URL
    try:
        atual.ANO_ATUAL = ano
        atual.URL = url
        return atual.parse_current_year(payload)
    finally:
        atual.ANO_ATUAL = antigo_ano
        atual.URL = antiga_url


def validate_year(votos, ano: int):
    if not votos:
        return False, "nenhum registro"
    counts = Counter(v["status_voto"] for v in votos)
    unknown = counts.get("outro", 0) + counts.get("nao_informado", 0)
    if unknown / len(votos) > 0.20:
        return False, f"muitos status não reconhecidos: {unknown}/{len(votos)}"
    if any(not v.get("data") for v in votos):
        return False, "há registros sem data"
    return True, ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def main():
    todos = []
    resumos = {}
    arquivos = {}
    for ano in ANOS:
        url = f"https://legis.senado.leg.br/dadosabertos/arquivos/ListaVotacoes{ano}.json"
        print(f"Baixando {ano}...")
        payload = atual.fetch_json(url)
        votos = parse_year(payload, ano, url)
        ok, resumo = validate_year(votos, ano)
        if not ok:
            raise SystemExit(f"Validação falhou em {ano}: {resumo}. Arquivo anterior preservado.")
        print(f"{ano}: {len(votos)} registros — {resumo}")
        todos.extend(votos)
        resumos[str(ano)] = {"quantidade": len(votos), "status": resumo}
        arquivos[str(ano)] = url

    uniq = {}
    for row in todos:
        key = (row["data"], row["codigo_sessao_votacao"], row["materia"], row["objeto"])
        uniq[key] = row
    todos = list(uniq.values())
    todos.sort(key=lambda x: (x["data"], x["codigo_sessao_votacao"], x["materia"]), reverse=True)

    doc = {
        "politico_id": atual.POLITICO_ID,
        "senador_id": atual.SENADOR_ID,
        "fonte": "Senado Federal — Dados Abertos",
        "fonte_documentacao": atual.DOC,
        "escopo": "historico_fechado",
        "anos": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
        "arquivos_anuais": arquivos,
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quantidade": len(todos),
        "validacao_por_ano": resumos,
        "votacoes": todos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(todos)} registros históricos gravados em {OUT}")


if __name__ == "__main__":
    main()
