#!/usr/bin/env python3
"""Atualiza dados/votacoes_senado.json a partir de fonte oficial do Senado.

Projeto: Portal Fatos Públicos
Princípios:
- usa somente fonte pública oficial;
- não requer credenciais externas;
- não transforma ausência/licença/presença em voto Sim ou Não;
- mantém o conteúdo factual e rastreável;
- em falha de schema, preserva o arquivo anterior e imprime apenas nomes de campos.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
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


def get_any(d: dict, *names: str):
    norm = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in d.items()}
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in norm and norm[key] not in (None, ""):
            return norm[key]
    return None


def normalize_vote(v: Any) -> tuple[str, str]:
    s = str(v or "").strip()
    n = re.sub(r"\s+", " ", s.casefold())
    if n in {"sim", "s"}:
        return "Sim", "sim"
    if n in {"não", "nao", "n"}:
        return "Não", "nao"
    if "absten" in n:
        return "Abstenção", "abstencao"
    if "obstru" in n:
        return "Obstrução", "obstrucao"
    if "licen" in n:
        return "Licença", "licenca"
    if "ausen" in n or "não compareceu" in n or "nao compareceu" in n:
        return "Ausência", "ausencia"
    if "presen" in n and ("sem" in n or "não vot" in n or "nao vot" in n):
        return "Presente sem registrar voto", "presente_sem_voto"
    if not s:
        return "Voto não informado", "nao_informado"
    return s, "outro"


def scalar_from(obj: Any, *names: str):
    """Busca recursivamente o primeiro valor escalar por nome de campo."""
    wanted = {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names}
    if isinstance(obj, dict):
        for k, v in obj.items():
            nk = re.sub(r"[^a-z0-9]", "", str(k).lower())
            if nk in wanted and not isinstance(v, (dict, list)) and v not in (None, ""):
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
    keys = {re.sub(r"[^a-z0-9]", "", str(k).lower()) for k in d.keys()}
    markers = {
        "descricaovoto", "voto", "descricaoresultado", "descricaovotacao",
        "codigomateria", "numeromateria", "datasessao", "datavotacao"
    }
    return len(keys & markers) >= 2


def parse(payload: Any) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for d in walk(payload):
        if not isinstance(d, dict) or not looks_like_vote_container(d):
            continue

        voto_raw = scalar_from(d, "DescricaoVoto", "Voto", "DescricaoVotacaoParlamentar")
        data = scalar_from(d, "DataSessao", "DataVotacao", "Data")
        numero = scalar_from(d, "NumeroMateria", "Numero")
        ano = scalar_from(d, "AnoMateria", "Ano")
        sigla = scalar_from(d, "SiglaSubtipoMateria", "SiglaMateria", "SiglaTipoMateria")
        desc_votacao = scalar_from(d, "DescricaoVotacao", "TextoVotacao")
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

    rows.sort(key=lambda x: (x.get("data", ""), x.get("materia", "")), reverse=True)
    return rows


def schema_paths(obj: Any, prefix: str = "", depth: int = 0, max_depth: int = 6, out=None):
    """Retorna somente caminhos de chaves/tipos; nunca valores."""
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

    doc = {
        "politico_id": "POL-000001",
        "senador_id": SENADOR_ID,
        "fonte": "Senado Federal — Dados Abertos",
        "fonte_url_consulta": source_url,
        "fonte_documentacao": "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais/info/webservice-de-votacoes-de-um-senador",
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quantidade": len(votos),
        "votacoes": votos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(votos)} votações gravadas em {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
