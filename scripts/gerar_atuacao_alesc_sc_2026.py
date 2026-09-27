#!/usr/bin/env python3
"""Agrega despesas oficiais dos gabinetes dos candidatos em exercício na ALESC."""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from gerar_atuacao_camara_sc_2026 import gravar_b64, ler_b64


RAIZ = Path(__file__).resolve().parent.parent
ANO_ATUAL = datetime.now(timezone.utc).year
ANOS = range(2023, ANO_ATUAL + 1)
URL = "https://transparencia.alesc.sc.gov.br/gabinetes-parlamentares/csv/{ano}"
OUT = RAIZ / "dados/atuacao_alesc_2026_sc.b64"
MANIFESTO = RAIZ / "dados/atuacao_alesc_manifesto_2026.json"
HEADERS = {"User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial ALESC)"}


def normalizar(valor: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFD", valor or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texto.casefold()).strip()


def em_centavos(valor: str) -> int:
    limpo = (valor or "0").replace(".", "").replace(",", ".")
    return int((Decimal(limpo) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def baixar_csv(ano: int) -> list[dict]:
    req = urllib.request.Request(URL.format(ano=ano), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resposta:
        texto = resposta.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def vincular_conta(nome: str, contas: set[str]) -> str:
    alvo = set(normalizar(nome).split())
    candidatos = [conta for conta in contas if alvo and alvo.issubset(set(normalizar(conta).split()))]
    if len(candidatos) != 1:
        raise ValueError(f"Conta de gabinete ambígua/ausente para {nome}: {candidatos}")
    return candidatos[0]


def main() -> None:
    candidatos = ler_b64(RAIZ / "dados/candidatos_deputado_estadual_2026_sc.b64")["candidatos"]
    mandatos = ler_b64(RAIZ / "dados/mandatos_estaduais_atuais_2026.b64").get("mandatos", {})
    atuais = {str(c["sq_candidato"]): mandatos[str(c["sq_candidato"])] for c in candidatos if str(c["sq_candidato"]) in mandatos}
    linhas_por_ano = {ano: baixar_csv(ano) for ano in ANOS}
    contas = {str(x.get("Conta") or "").strip() for linhas in linhas_por_ano.values() for x in linhas if x.get("Conta")}
    conta_por_cid = {cid: vincular_conta(m["nome_parlamentar"], contas) for cid, m in atuais.items()}
    cid_por_conta = {conta: cid for cid, conta in conta_por_cid.items()}
    agregado = defaultdict(lambda: {
        "total_centavos": 0, "quantidade_registros": 0,
        "por_ano": defaultdict(lambda: {"total_centavos": 0, "quantidade_registros": 0}),
        "categorias": defaultdict(int),
    })
    for ano, linhas in linhas_por_ano.items():
        for row in linhas:
            cid = cid_por_conta.get(str(row.get("Conta") or "").strip())
            if not cid:
                continue
            valor = em_centavos(row.get("Valor", "0"))
            categoria = " — ".join(x for x in ((row.get("Verba") or "").strip(), (row.get("Descrição") or "").strip()) if x) or "Categoria não informada"
            item = agregado[cid]
            item["total_centavos"] += valor
            item["quantidade_registros"] += 1
            item["por_ano"][str(ano)]["total_centavos"] += valor
            item["por_ano"][str(ano)]["quantidade_registros"] += 1
            item["categorias"][categoria] += valor
    atuacoes = {}
    for cid, mandato in atuais.items():
        item = agregado[cid]
        atuacoes[cid] = {
            "nome_parlamentar": mandato.get("nome_parlamentar"),
            "conta_fonte": conta_por_cid[cid],
            "url_perfil": mandato.get("url_perfil"),
            "despesas_gabinete": {
                "total_centavos": item["total_centavos"],
                "quantidade_registros": item["quantidade_registros"],
                "por_ano": [{"ano": int(ano), "parcial": int(ano) == ANO_ATUAL, **dados} for ano, dados in sorted(item["por_ano"].items())],
                "principais_categorias": [{"categoria": k, "valor_centavos": v} for k, v in sorted(item["categorias"].items(), key=lambda x: (-x[1], x[0]))[:10]],
            },
        }
    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC", "periodo": [2023, ANO_ATUAL],
        "criterio": "Somente candidaturas vinculadas à lista atual de deputados da ALESC; valores agregados por conta oficial do gabinete, sem favorecidos.",
        "fonte": "ALESC — Portal da Transparência", "fonte_url": "https://transparencia.alesc.sc.gov.br/gabinetes-parlamentares/dados-abertos",
        "fontes_anuais": {str(ano): URL.format(ano=ano) for ano in ANOS},
        "atualizado_em_utc": atualizado, "quantidade_candidatos": len(candidatos),
        "quantidade_com_exercicio_atual": len(atuacoes), "atuacoes": atuacoes,
    }
    gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC", "atualizado_em_utc": atualizado,
        "quantidade_candidatos": len(candidatos), "quantidade_com_exercicio_atual": len(atuacoes),
        "quantidade_registros": sum(x["despesas_gabinete"]["quantidade_registros"] for x in atuacoes.values()),
        "total_despesas_gabinetes_centavos": sum(x["despesas_gabinete"]["total_centavos"] for x in atuacoes.values()),
        "arquivo": "dados/atuacao_alesc_2026_sc.b64", "fonte": documento["fonte_url"],
        "observacao": "O total agrega as rubricas publicadas por conta de gabinete e não representa o custo total do mandato. O ano de 2026 é parcial.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
