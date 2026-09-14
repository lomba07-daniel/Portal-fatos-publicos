#!/usr/bin/env python3
"""Atualiza somente as votações nominais do ano corrente.

Fonte: Senado Federal — Dados Abertos / ListaVotacoesAAAA.json
Projeto: Portal Fatos Públicos

A rotina diária é deliberadamente leve: baixa apenas o arquivo do ano corrente.
O histórico anterior será carregado uma única vez em rotina separada de backfill.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENADOR_ID = "5894"
POLITICO_ID = "POL-000001"
ANO_ATUAL = datetime.now(timezone.utc).year
OUT = Path("dados/votacoes_senado.json")
URL = f"https://legis.senado.leg.br/dadosabertos/arquivos/ListaVotacoes{ANO_ATUAL}.json"
DOC = "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais/info/webservice-de-votacoes-de-um-senador"
HEADERS = {
    "User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial Senado)",
    "Accept": "application/json, */*;q=0.5",
}


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read()
        ctype = (r.headers.get("content-type") or "").lower()
    if "json" not in ctype and not raw.lstrip().startswith((b"{", b"[")):
        raise ValueError(f"Resposta não JSON: {ctype}")
    return json.loads(raw.decode("utf-8-sig"))


def as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def strip_accents_text(s: Any) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").casefold()


def normalize_vote(v: Any) -> tuple[str, str]:
    s = str(v or "").strip()
    n = re.sub(r"\s+", " ", strip_accents_text(s))
    compact = re.sub(r"[^a-z0-9]+", "", n)
    if n in {"sim", "s"}:
        return "Sim", "sim"
    if n in {"nao", "n"}:
        return "Não", "nao"
    if "absten" in n:
        return "Abstenção", "abstencao"
    if "obstru" in n:
        return "Obstrução", "obstrucao"
    mapping = {
        "pnrv": ("Presente sem registrar voto", "presente_sem_voto"),
        "ap": ("Atividade parlamentar", "atividade_parlamentar"),
        "ncom": ("Ausência", "ausencia"),
        "lp": ("Licença particular", "licenca"),
        "ls": ("Licença saúde", "licenca"),
        "ln": ("Licença", "licenca"),
        "mis": ("Missão", "missao"),
        "merc": ("Presente no Mercosul", "missao"),
        "votou": ("Votou (votação secreta)", "voto_secreto"),
    }
    if compact in mapping:
        return mapping[compact]
    if "presidente" in n:
        return s, "presidente"
    if not s:
        return "Voto não informado", "nao_informado"
    return s, "outro"


def norm_num(v: Any) -> str:
    s = str(v or "").strip()
    return s.lstrip("0") or ("0" if s else "")


def parse_current_year(payload: Any) -> list[dict[str, Any]]:
    root = payload.get("ListaVotacoes", {}) if isinstance(payload, dict) else {}
    votacoes = root.get("Votacoes", {}) if isinstance(root, dict) else {}
    items = votacoes.get("Votacao", []) if isinstance(votacoes, dict) else []
    rows: list[dict[str, Any]] = []

    for sessao in as_list(items):
        if not isinstance(sessao, dict):
            continue
        votos_obj = sessao.get("Votos", {})
        votos = votos_obj.get("VotoParlamentar", []) if isinstance(votos_obj, dict) else []
        alvo = next((vp for vp in as_list(votos)
                     if isinstance(vp, dict) and str(vp.get("CodigoParlamentar", "")).strip() == SENADOR_ID), None)
        if alvo is None:
            continue

        voto_raw = alvo.get("Voto")
        voto, status = normalize_vote(voto_raw)
        sigla = str(sessao.get("SiglaMateria") or sessao.get("SiglaSubtipoMateria") or "").strip()
        numero = norm_num(sessao.get("NumeroMateria"))
        ano_materia = str(sessao.get("AnoMateria") or "").strip()
        materia = " ".join(x for x in (sigla, numero) if x)
        if ano_materia:
            materia = f"{materia}/{ano_materia}" if materia else ano_materia
        if not materia:
            materia = str(sessao.get("DescricaoIdentificacaoMateria") or "Votação nominal").strip()

        rows.append({
            "data": str(sessao.get("DataSessao") or "").strip()[:10],
            "materia": materia,
            "voto": voto,
            "status_voto": status,
            "voto_original": str(voto_raw or "").strip(),
            "descricao_voto": str(alvo.get("DescricaoVoto") or "").strip(),
            "objeto": str(sessao.get("DescricaoVotacao") or sessao.get("DescricaoIdentificacaoMateria") or "").strip(),
            "contexto": "Registro obtido do arquivo anual oficial de votação nominal do Senado Federal.",
            "codigo_materia": str(sessao.get("CodigoMateria") or "").strip(),
            "codigo_sessao": str(sessao.get("CodigoSessao") or "").strip(),
            "codigo_sessao_votacao": str(sessao.get("CodigoSessaoVotacao") or "").strip(),
            "resultado": str(sessao.get("DescricaoResultado") or sessao.get("Resultado") or "").strip(),
            "ano_arquivo": ANO_ATUAL,
            "url": URL,
            "fonte": "Senado Federal — Dados Abertos",
        })

    uniq: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["data"], row["codigo_sessao_votacao"], row["materia"], row["objeto"])
        uniq[key] = row
    out = list(uniq.values())
    out.sort(key=lambda x: (x["data"], x["codigo_sessao_votacao"], x["materia"]), reverse=True)
    return out


def validate(votos: list[dict[str, Any]]) -> tuple[bool, str]:
    if len(votos) < 10:
        return False, f"quantidade inesperadamente baixa: {len(votos)}"
    counts = Counter(v["status_voto"] for v in votos)
    if counts.get("sim", 0) + counts.get("nao", 0) < 2:
        return False, "ano corrente sem quantidade plausível de votos Sim/Não"
    unknown = counts.get("outro", 0) + counts.get("nao_informado", 0)
    if unknown / len(votos) > 0.20:
        return False, f"muitos status não reconhecidos: {unknown}/{len(votos)}"
    if any(not v.get("data") for v in votos):
        return False, "há registros sem data"
    return True, ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def main() -> int:
    try:
        payload = fetch_json(URL)
    except Exception as e:
        print(f"Falha ao baixar {URL}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    votos = parse_current_year(payload)
    ok, validation_msg = validate(votos)
    if not ok:
        print("Validação de segurança falhou: " + validation_msg, file=sys.stderr)
        print("Arquivo anterior preservado.", file=sys.stderr)
        return 4

    doc = {
        "politico_id": POLITICO_ID,
        "senador_id": SENADOR_ID,
        "fonte": "Senado Federal — Dados Abertos",
        "fonte_documentacao": DOC,
        "escopo": "ano_corrente",
        "ano": ANO_ATUAL,
        "arquivo_anual": URL,
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quantidade": len(votos),
        "validacao": validation_msg,
        "votacoes": votos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(votos)} votações de {ANO_ATUAL} gravadas em {OUT}")
    print("Resumo: " + validation_msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
