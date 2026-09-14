#!/usr/bin/env python3
"""Atualiza dados/votacoes_senado.json a partir de fonte oficial do Senado.

Projeto: Portal Fatos Públicos
Princípios:
- usa somente fonte pública oficial;
- não requer credenciais externas;
- não transforma ausência/licença/presença em voto Sim ou Não;
- mantém o conteúdo factual e rastreável;
- falha com segurança se o schema deixar de ser reconhecido.
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
OUT = Path("dados/votacoes_senado.json")
URLS = [
    f"https://legis.senado.leg.br/dadosabertos/senador/{SENADOR_ID}/votacoes.json",
    f"https://legis.senado.leg.br/dadosabertos/senador/{SENADOR_ID}/votacoes",
]
HEADERS = {
    "User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial Senado)",
    "Accept": "application/json, application/xml;q=0.8, */*;q=0.5",
}


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        ctype = (r.headers.get("content-type") or "").lower()
    if "json" not in ctype and not raw.lstrip().startswith((b"{", b"[")):
        raise ValueError(f"Resposta não JSON em {url}: {ctype}")
    return json.loads(raw.decode("utf-8-sig"))


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


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

    # Códigos canônicos usados pelo Senado.
    if compact in {"pnrv"}:
        return "Presente sem registrar voto", "presente_sem_voto"
    if compact in {"ap"}:
        return "Atividade parlamentar", "atividade_parlamentar"
    if compact in {"ncom"}:
        return "Ausência", "ausencia"
    if compact in {"lp"}:
        return "Licença particular", "licenca"
    if compact in {"ls"}:
        return "Licença saúde", "licenca"
    if compact in {"ln"}:
        return "Licença", "licenca"
    if compact in {"mis"}:
        return "Missão", "missao"
    if compact in {"merc"}:
        return "Presente no Mercosul", "missao"
    if compact in {"votou"}:
        return "Votou (votação secreta)", "voto_secreto"

    if "licen" in n:
        return s or "Licença", "licenca"
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


def scalar_from(obj: Any, *names: str):
    wanted = [norm_key(n) for n in names]
    if isinstance(obj, dict):
        # Respeita a ordem de prioridade informada em names.
        by_norm = {norm_key(k): v for k, v in obj.items()}
        for wanted_key in wanted:
            v = by_norm.get(wanted_key)
            if not isinstance(v, (dict, list)) and v not in (None, ""):
                return v
        for v in obj.values():
            found = scalar_from(v, *names)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = scalar_from(v, *names)
            if found not in (None, ""):
                return found
    return None


def looks_like_vote_container(d: dict) -> bool:
    keys = {norm_key(k) for k in d.keys()}
    markers = {
        "descricaovoto", "voto", "descricaoresultado", "descricaovotacao",
        "codigomateria", "numeromateria", "datasessao", "datavotacao"
    }
    return len(keys & markers) >= 2


def infer_sigla(desc: Any) -> str:
    t = strip_accents_text(desc)
    patterns = [
        ("projeto de lei complementar", "PLP"),
        ("proposta de emenda a constituicao", "PEC"),
        ("projeto de decreto legislativo", "PDL"),
        ("projeto de resolucao", "PRS"),
        ("projeto de lei", "PL"),
        ("medida provisoria", "MPV"),
        ("mensagem", "MSF"),
        ("requerimento", "RQS"),
    ]
    for phrase, sigla in patterns:
        if phrase in t:
            return sigla
    return ""


def schema_paths(obj: Any, prefix: str = "", depth: int = 0, max_depth: int = 6, out=None):
    if out is None:
        out = set()
    if depth > max_depth or len(out) >= 120:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            typ = "dict" if isinstance(v, dict) else "list" if isinstance(v, list) else type(v).__name__
            out.add(f"{p} [{typ}]")
            if isinstance(v, (dict, list)):
                schema_paths(v, p, depth + 1, max_depth, out)
    elif isinstance(obj, list) and obj:
        schema_paths(obj[0], prefix + "[]", depth + 1, max_depth, out)
    return out


def parse(payload: Any) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for d in walk(payload):
        if not isinstance(d, dict) or not looks_like_vote_container(d):
            continue

        # Campo canônico primeiro. DescricaoVoto é apenas fallback.
        voto_raw = scalar_from(d, "Voto", "DescricaoVoto", "DescricaoVotacaoParlamentar")
        data = scalar_from(d, "DataSessao", "DataVotacao", "Data")
        numero = scalar_from(d, "NumeroMateria", "Numero")
        ano = scalar_from(d, "AnoMateria", "Ano")
        desc_votacao = scalar_from(d, "DescricaoVotacao", "TextoVotacao")
        sigla = scalar_from(d, "SiglaSubtipoMateria", "SiglaMateria", "SiglaTipoMateria") or infer_sigla(desc_votacao)
        if voto_raw is None or data is None:
            continue

        voto, status = normalize_vote(voto_raw)
        materia = " ".join(str(x).strip() for x in (sigla, numero) if x not in (None, ""))
        if ano not in (None, ""):
            materia = (materia + "/" + str(ano)).strip("/")
        if not materia:
            materia = str(desc_votacao or "Votação nominal")[:160]

        cod = scalar_from(d, "CodigoMateria", "CodigoVotacao", "CodigoSessao")
        key = (str(data), materia, voto, str(cod or ""), str(desc_votacao or ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "data": str(data)[:10],
            "materia": materia,
            "voto": voto,
            "status_voto": status,
            "objeto": str(desc_votacao or "").strip(),
            "contexto": "Registro obtido dos Dados Abertos do Senado Federal.",
            "codigo_materia": str(scalar_from(d, "CodigoMateria") or ""),
            "codigo_sessao": str(scalar_from(d, "CodigoSessao") or ""),
            "resultado": str(scalar_from(d, "DescricaoResultado", "Resultado") or ""),
            "url": "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais",
            "fonte": "Senado Federal — Dados Abertos",
        })
    rows.sort(key=lambda x: (x.get("data", ""), x.get("materia", ""), x.get("objeto", "")), reverse=True)
    return rows


def validate(votos: list[dict[str, Any]]) -> tuple[bool, str]:
    if not votos:
        return False, "nenhuma votação reconhecida"
    if len(votos) < 20:
        return False, f"quantidade inesperadamente baixa: {len(votos)}"
    counts = Counter(v["status_voto"] for v in votos)
    unknown = counts.get("outro", 0) + counts.get("nao_informado", 0)
    if unknown / len(votos) > 0.25:
        return False, f"muitos status não reconhecidos: {unknown}/{len(votos)}"
    # Um histórico desta dimensão sem qualquer Sim/Não indica leitura do campo errado.
    if counts.get("sim", 0) + counts.get("nao", 0) < 5:
        return False, "histórico sem quantidade plausível de votos Sim/Não"
    missing_date = sum(not v.get("data") for v in votos)
    if missing_date:
        return False, f"{missing_date} registros sem data"
    return True, ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def main() -> int:
    payload = None
    errors = []
    source_url = None
    for url in URLS:
        try:
            payload = fetch_json(url)
            source_url = url
            break
        except Exception as e:
            errors.append(f"{url}: {e}")
    if payload is None:
        print("Falha ao obter dados do Senado:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 2

    votos = parse(payload)
    if not votos:
        print(f"A fonte respondeu em {source_url}, mas nenhum voto reconhecível foi encontrado.", file=sys.stderr)
        print("Schema observado (somente nomes de campos e tipos; sem valores):", file=sys.stderr)
        for p in sorted(schema_paths(payload)):
            print("- " + p, file=sys.stderr)
        print("Arquivo anterior preservado.", file=sys.stderr)
        return 3

    ok, validation_msg = validate(votos)
    if not ok:
        print("Validação de segurança falhou: " + validation_msg, file=sys.stderr)
        print("Arquivo anterior preservado.", file=sys.stderr)
        return 4

    doc = {
        "politico_id": "POL-000001",
        "senador_id": SENADOR_ID,
        "fonte": "Senado Federal — Dados Abertos",
        "fonte_url_consulta": source_url,
        "fonte_documentacao": "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais/info/webservice-de-votacoes-de-um-senador",
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
    print("Resumo da validação: " + validation_msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
