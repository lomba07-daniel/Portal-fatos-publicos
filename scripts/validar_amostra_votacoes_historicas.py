#!/usr/bin/env python3
"""Validação semântica independente de uma amostra do histórico 2019-2025.

Compara 2 registros por ano do arquivo publicado pelo portal contra os arquivos
anuais oficiais ListaVotacoesAAAA.json do Senado Federal, sem reutilizar o parser
de produção para interpretar os registros oficiais.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENADOR_ID = "5894"
HIST = Path("dados/votacoes_senado_historico.json")
OUT = Path("dados/validacao_amostra_votacoes_2019_2025.json")
MAX_TENTATIVAS = 5
HEADERS = {
    "User-Agent": "Portal-Fatos-Publicos/1.0 (validacao independente; fonte oficial Senado)",
    "Accept": "application/json, */*;q=0.5",
}

# Dois perfis por ano, com variedade entre voto de mérito e situações especiais.
DESEJADOS = {
    2019: ["sim", "nao"],
    2020: ["sim", "presente_sem_voto"],
    2021: ["nao", "voto_secreto"],
    2022: ["sim", "presente_sem_voto"],
    2023: ["nao", "voto_secreto"],
    2024: ["sim", "nao"],
    2025: ["licenca", "abstencao"],
}


def as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def fetch_json(url: str) -> Any:
    last = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            if tentativa > 1:
                time.sleep(3 * (tentativa - 1))
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            last = exc
            print(f"Tentativa {tentativa}/{MAX_TENTATIVAS} falhou para {url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(f"Falha ao baixar {url}: {last}") from last


def norm_num(v: Any) -> str:
    s = str(v or "").strip()
    return s.lstrip("0") or ("0" if s else "")


def materia_raw(sessao: dict[str, Any]) -> str:
    sigla = str(sessao.get("SiglaMateria") or sessao.get("SiglaSubtipoMateria") or "").strip()
    numero = norm_num(sessao.get("NumeroMateria"))
    ano = str(sessao.get("AnoMateria") or "").strip()
    materia = " ".join(x for x in (sigla, numero) if x)
    if ano:
        materia = f"{materia}/{ano}" if materia else ano
    if not materia:
        materia = str(sessao.get("DescricaoIdentificacaoMateria") or "Votação nominal").strip()
    return materia


def expected_status(voto_raw: str) -> str:
    s = str(voto_raw or "").strip()
    compact = "".join(ch for ch in s.casefold() if ch.isalnum())
    if compact in {"sim", "s"}: return "sim"
    if compact in {"não", "nao", "n"}: return "nao"
    if "absten" in compact: return "abstencao"
    if "obstru" in compact: return "obstrucao"
    mapping = {
        "pnrv": "presente_sem_voto",
        "ap": "atividade_parlamentar",
        "ncom": "ausencia",
        "lp": "licenca",
        "ls": "licenca",
        "ln": "licenca",
        "mis": "missao",
        "merc": "missao",
        "votou": "voto_secreto",
    }
    if compact in mapping: return mapping[compact]
    if "presidente" in compact: return "presidente"
    return "nao_informado" if not s else "outro"


def localizar_sessao(payload: Any, codigo_votacao: str) -> dict[str, Any]:
    root = payload.get("ListaVotacoes", {}) if isinstance(payload, dict) else {}
    votos = root.get("Votacoes", {}) if isinstance(root, dict) else {}
    itens = votos.get("Votacao", []) if isinstance(votos, dict) else []
    achados = [s for s in as_list(itens) if isinstance(s, dict) and str(s.get("CodigoSessaoVotacao") or "").strip() == codigo_votacao]
    if len(achados) != 1:
        raise AssertionError(f"CodigoSessaoVotacao {codigo_votacao}: esperada 1 ocorrência, encontradas {len(achados)}")
    return achados[0]


def validar_registro(row: dict[str, Any], payload: Any) -> dict[str, Any]:
    sessao = localizar_sessao(payload, str(row["codigo_sessao_votacao"]))
    vp_obj = sessao.get("Votos", {})
    parlamentares = vp_obj.get("VotoParlamentar", []) if isinstance(vp_obj, dict) else []
    alvo = [v for v in as_list(parlamentares) if isinstance(v, dict) and str(v.get("CodigoParlamentar") or "").strip() == SENADOR_ID]
    if len(alvo) != 1:
        raise AssertionError(f"Senador {SENADOR_ID}: esperada 1 ocorrência, encontradas {len(alvo)}")
    alvo = alvo[0]

    bruto_voto = str(alvo.get("Voto") or "").strip()
    objeto_raw = str(sessao.get("DescricaoVotacao") or sessao.get("DescricaoIdentificacaoMateria") or "").strip()
    checks = {
        "data": row["data"] == str(sessao.get("DataSessao") or "").strip()[:10],
        "materia": row["materia"] == materia_raw(sessao),
        "objeto": row["objeto"] == objeto_raw,
        "voto_original": row["voto_original"] == bruto_voto,
        "status_voto": row["status_voto"] == expected_status(bruto_voto),
        "codigo_materia": str(row["codigo_materia"]) == str(sessao.get("CodigoMateria") or "").strip(),
        "codigo_sessao": str(row["codigo_sessao"]) == str(sessao.get("CodigoSessao") or "").strip(),
        "codigo_sessao_votacao": str(row["codigo_sessao_votacao"]) == str(sessao.get("CodigoSessaoVotacao") or "").strip(),
    }
    if not all(checks.values()):
        falhas = [k for k, ok in checks.items() if not ok]
        raise AssertionError(f"Divergência em {row['data']} {row['materia']} ({row['codigo_sessao_votacao']}): {', '.join(falhas)}")

    return {
        "ano": row["ano_arquivo"],
        "data": row["data"],
        "materia": row["materia"],
        "objeto": row["objeto"],
        "codigo_sessao_votacao": row["codigo_sessao_votacao"],
        "voto_portal": row["voto"],
        "voto_original_senado": bruto_voto,
        "status_portal": row["status_voto"],
        "checks": checks,
        "resultado": "aprovado",
    }


def escolher(rows: list[dict[str, Any]], ano: int) -> list[dict[str, Any]]:
    ano_rows = [r for r in rows if int(r.get("ano_arquivo") or 0) == ano]
    saida = []
    usados = set()
    for status in DESEJADOS[ano]:
        candidato = next((r for r in ano_rows if r.get("status_voto") == status and r.get("codigo_sessao_votacao") not in usados), None)
        if candidato is None:
            raise AssertionError(f"{ano}: não foi encontrado registro para status amostral {status}")
        saida.append(candidato)
        usados.add(candidato["codigo_sessao_votacao"])
    return saida


def main() -> int:
    hist = json.loads(HIST.read_text(encoding="utf-8"))
    rows = hist["votacoes"]
    resultados = []

    for ano in range(2019, 2026):
        url = f"https://legis.senado.leg.br/dadosabertos/arquivos/ListaVotacoes{ano}.json"
        print(f"Validando {ano} contra {url}")
        payload = fetch_json(url)
        for row in escolher(rows, ano):
            res = validar_registro(row, payload)
            resultados.append(res)
            print(f"  OK {res['data']} {res['materia']} — {res['voto_portal']} ({res['status_portal']})")

    doc = {
        "fonte": "Senado Federal — arquivos anuais oficiais ListaVotacoesAAAA.json",
        "senador_id": SENADOR_ID,
        "criterio": "2 registros por ano; comparação independente de data, matéria, objeto, voto bruto, status e códigos oficiais",
        "executado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anos": list(range(2019, 2026)),
        "quantidade_amostrada": len(resultados),
        "quantidade_aprovada": sum(r["resultado"] == "aprovado" for r in resultados),
        "resultado_geral": "aprovado" if all(r["resultado"] == "aprovado" for r in resultados) else "reprovado",
        "amostra": resultados,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RESULTADO: {doc['resultado_geral']} — {doc['quantidade_aprovada']}/{doc['quantidade_amostrada']} registros")
    return 0 if doc["resultado_geral"] == "aprovado" else 1


if __name__ == "__main__":
    raise SystemExit(main())
