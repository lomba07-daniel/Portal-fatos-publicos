#!/usr/bin/env python3
"""Coleta o histórico de votações nominais de um senador em arquivos anuais oficiais.

Fonte: Senado Federal — Dados Abertos / ListaVotacoesAAAA.json
Projeto: Portal Fatos Públicos

Regras de segurança metodológica:
- usa o campo canônico `Voto` do registro do parlamentar;
- não converte ausência/licença/presença em Sim ou Não;
- preserva o arquivo anterior se a fonte ou a validação falhar;
- não usa credenciais externas.
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
ANO_INICIAL = 2019
ANO_ATUAL = datetime.now(timezone.utc).year
OUT = Path("dados/votacoes_senado.json")
BASE = "https://legis.senado.leg.br/dadosabertos/arquivos/ListaVotacoes{ano}.json"
DOC = "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais/info/webservice-de-votacoes-de-um-senador"
HEADERS = {
    "User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial Senado)",
    "Accept": "application/json, */*;q=0.5",
}


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
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
    if compact == "pnrv":
        return "Presente sem registrar voto", "presente_sem_voto"
    if compact == "ap":
        return "Atividade parlamentar", "atividade_parlamentar"
    if compact == "ncom":
        return "Ausência", "ausencia"
    if compact == "lp":
        return "Licença particular", "licenca"
    if compact == "ls":
        return "Licença saúde", "licenca"
    if compact == "ln":
        return "Licença", "licenca"
    if compact == "mis":
        return "Missão", "missao"
    if compact == "merc":
        return "Presente no Mercosul", "missao"
    if compact == "votou":
        return "Votou (votação secreta)", "voto_secreto"
    if "presidente" in n:
        return s, "presidente"
    if "licen" in n:
        return s, "licenca"
    if "ausen" in n or "nao compareceu" in n:
        return "Ausência", "ausencia"
    if "presen" in n and ("nao registr" in n or "sem registr" in n or "sem voto" in n or "nao vot" in n):
        return "Presente sem registrar voto", "presente_sem_voto"
    if "atividade parlamentar" in n:
        return "Atividade parlamentar", "atividade_parlamentar"
    if "missao" in n:
        return s, "missao"
    if not s:
        return "Voto não informado", "nao_informado"
    return s, "outro"


def norm_num(v: Any) -> str:
    s = str(v or "").strip()
    return s.lstrip("0") or ("0" if s else "")


def parse_year(payload: Any, ano_arquivo: int, source_url: str) -> list[dict[str, Any]]:
    root = payload.get("ListaVotacoes", {}) if isinstance(payload, dict) else {}
    votacoes = root.get("Votacoes", {}) if isinstance(root, dict) else {}
    items = votacoes.get("Votacao", []) if isinstance(votacoes, dict) else []

    rows: list[dict[str, Any]] = []
    for sessao in as_list(items):
        if not isinstance(sessao, dict):
            continue
        votos_obj = sessao.get("Votos", {})
        votos = votos_obj.get("VotoParlamentar", []) if isinstance(votos_obj, dict) else []
        alvo = None
        for vp in as_list(votos):
            if isinstance(vp, dict) and str(vp.get("CodigoParlamentar", "")).strip() == SENADOR_ID:
                alvo = vp
                break
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

        data = str(sessao.get("DataSessao") or "").strip()[:10]
        objeto = str(sessao.get("DescricaoVotacao") or sessao.get("DescricaoIdentificacaoMateria") or "").strip()
        resultado = str(sessao.get("DescricaoResultado") or sessao.get("Resultado") or "").strip()

        rows.append({
            "data": data,
            "materia": materia,
            "voto": voto,
            "status_voto": status,
            "voto_original": str(voto_raw or "").strip(),
            "descricao_voto": str(alvo.get("DescricaoVoto") or "").strip(),
            "objeto": objeto,
            "contexto": "Registro obtido do arquivo anual oficial de votação nominal do Senado Federal.",
            "codigo_materia": str(sessao.get("CodigoMateria") or "").strip(),
            "codigo_sessao": str(sessao.get("CodigoSessao") or "").strip(),
            "codigo_sessao_votacao": str(sessao.get("CodigoSessaoVotacao") or "").strip(),
            "resultado": resultado,
            "ano_arquivo": ano_arquivo,
            "url": source_url,
            "fonte": "Senado Federal — Dados Abertos",
        })
    return rows


def validate(votos: list[dict[str, Any]], anos_ok: list[int]) -> tuple[bool, str]:
    if ANO_ATUAL not in anos_ok:
        return False, f"arquivo do ano corrente ({ANO_ATUAL}) não foi carregado"
    if len(anos_ok) < max(1, ANO_ATUAL - ANO_INICIAL):
        return False, f"poucos anos carregados: {anos_ok}"
    if len(votos) < 100:
        return False, f"quantidade inesperadamente baixa de registros: {len(votos)}"

    counts = Counter(v["status_voto"] for v in votos)
    valid_yes_no = counts.get("sim", 0) + counts.get("nao", 0)
    if valid_yes_no < 20:
        return False, f"poucos votos Sim/Não reconhecidos: {valid_yes_no}"
    unknown = counts.get("outro", 0) + counts.get("nao_informado", 0)
    if unknown / len(votos) > 0.15:
        return False, f"muitos status não reconhecidos: {unknown}/{len(votos)}"
    if any(not v.get("data") for v in votos):
        return False, "há registros sem data"

    return True, ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def main() -> int:
    all_rows: list[dict[str, Any]] = []
    anos_ok: list[int] = []
    erros: list[str] = []

    for ano in range(ANO_INICIAL, ANO_ATUAL + 1):
        url = BASE.format(ano=ano)
        try:
            payload = fetch_json(url)
            rows = parse_year(payload, ano, url)
            all_rows.extend(rows)
            anos_ok.append(ano)
            print(f"{ano}: {len(rows)} registros do parlamentar")
        except Exception as e:
            erros.append(f"{ano}: {type(e).__name__}: {e}")
            print(f"Falha em {ano}: {e}", file=sys.stderr)

    # remove duplicidades por votação/sessão/parlamentar, preservando o registro mais informativo
    uniq: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in all_rows:
        key = (
            row.get("data", ""),
            row.get("codigo_sessao_votacao", ""),
            row.get("materia", ""),
            row.get("objeto", ""),
        )
        uniq[key] = row
    votos = list(uniq.values())
    votos.sort(key=lambda x: (x.get("data", ""), x.get("codigo_sessao_votacao", ""), x.get("materia", "")), reverse=True)

    ok, validation_msg = validate(votos, anos_ok)
    if not ok:
        print("Validação de segurança falhou: " + validation_msg, file=sys.stderr)
        if erros:
            print("Erros de coleta: " + " | ".join(erros), file=sys.stderr)
        print("Arquivo anterior preservado.", file=sys.stderr)
        return 4

    doc = {
        "politico_id": POLITICO_ID,
        "senador_id": SENADOR_ID,
        "fonte": "Senado Federal — Dados Abertos",
        "fonte_documentacao": DOC,
        "arquivos_anuais": [BASE.format(ano=a) for a in anos_ok],
        "anos_carregados": anos_ok,
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quantidade": len(votos),
        "validacao": validation_msg,
        "votacoes": votos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(votos)} votações gravadas em {OUT}")
    print("Anos: " + ", ".join(map(str, anos_ok)))
    print("Resumo: " + validation_msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
