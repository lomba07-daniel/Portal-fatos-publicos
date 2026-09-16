#!/usr/bin/env python3
"""Atualiza gastos do mandato no Senado a partir da API oficial de transparência.

Coleta, por ano, as categorias da CEAPS e os gastos não inclusos na CEAPS.
Preserva as categorias oficiais e valida os totais antes de substituir a base.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENADOR_ID = "5894"
POLITICO_ID = "POL-000001"
ANO_INICIAL = 2019
ANO_ATUAL = datetime.now(timezone.utc).year
OUT = Path("dados/gastos_mandato_senado.json")
API = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/{senador}/recursos-utilizados?ano={ano}&formato=json"
PAGINA = "https://www6g.senado.leg.br/transparencia/sen/{senador}/?ano={ano}"
HEADERS = {
    "User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial Senado)",
    "Accept": "application/json, */*;q=0.5",
}


def fetch_json(url: str, tentativas: int = 4) -> Any:
    erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            erro = exc
            if tentativa < tentativas:
                espera = tentativa * 3
                print(f"  tentativa {tentativa}/{tentativas} falhou: {type(exc).__name__}: {exc}; nova em {espera}s")
                time.sleep(espera)
    raise RuntimeError(f"Falha ao baixar {url}: {erro}") from erro


def num(v: Any) -> float:
    x = float(v or 0)
    if not math.isfinite(x):
        raise ValueError(f"valor não finito: {v!r}")
    return round(x, 2)


def validar_grupo(nome: str, despesas: list[dict[str, Any]], total: float, ano: int) -> None:
    if not isinstance(despesas, list) or not despesas:
        raise ValueError(f"{ano}: grupo {nome} sem despesas")
    if any(not str(d.get("recurso") or "").strip() for d in despesas):
        raise ValueError(f"{ano}: categoria vazia em {nome}")
    if any(num(d.get("valor")) < 0 for d in despesas):
        raise ValueError(f"{ano}: valor negativo em {nome}")
    soma = round(sum(num(d.get("valor")) for d in despesas), 2)
    if abs(soma - total) > 0.10:
        raise ValueError(f"{ano}: total inconsistente em {nome}: soma={soma:.2f}, informado={total:.2f}")


def main() -> int:
    anos = []
    agregado_ceaps: dict[str, float] = defaultdict(float)
    agregado_fora: dict[str, float] = defaultdict(float)

    for ano in range(ANO_INICIAL, ANO_ATUAL + 1):
        url = API.format(senador=SENADOR_ID, ano=ano)
        print(f"Coletando {ano}...")
        payload = fetch_json(url)
        if payload.get("statusCode") != 200:
            raise SystemExit(f"{ano}: API retornou status inesperado: {payload.get('statusCode')}")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise SystemExit(f"{ano}: estrutura inesperada em data")
        row = data[0]
        if int(row.get("ano") or 0) != ano:
            raise SystemExit(f"{ano}: ano retornado difere do solicitado")
        parlamentar = row.get("parlamentar") or {}
        if "flávio" not in str(parlamentar.get("nome") or "").casefold() and "flavio" not in str(parlamentar.get("nome") or "").casefold():
            raise SystemExit(f"{ano}: parlamentar inesperado: {parlamentar.get('nome')}")

        cotas = row.get("cotas") or {}
        fora = row.get("gastosNaoInclusos") or {}
        ceaps = [{"categoria": str(x.get("recurso") or "").strip(), "valor": num(x.get("valor"))} for x in (cotas.get("despesas") or [])]
        extras = [{"categoria": str(x.get("recurso") or "").strip(), "valor": num(x.get("valor"))} for x in (fora.get("despesas") or [])]
        total_ceaps = num(cotas.get("totalValor"))
        total_fora = num(fora.get("totalValor"))
        validar_grupo("CEAPS", [{"recurso": x["categoria"], "valor": x["valor"]} for x in ceaps], total_ceaps, ano)
        validar_grupo("fora da CEAPS", [{"recurso": x["categoria"], "valor": x["valor"]} for x in extras], total_fora, ano)

        for x in ceaps:
            agregado_ceaps[x["categoria"]] += x["valor"]
        for x in extras:
            agregado_fora[x["categoria"]] += x["valor"]

        anos.append({
            "ano": ano,
            "parcial": ano == ANO_ATUAL,
            "ceaps": ceaps,
            "total_ceaps": total_ceaps,
            "fora_ceaps": extras,
            "total_fora_ceaps": total_fora,
            "total_mostrado": round(total_ceaps + total_fora, 2),
            "fonte_api": url,
            "fonte_visual": PAGINA.format(senador=SENADOR_ID, ano=ano),
        })
        print(f"  OK: CEAPS={total_ceaps:.2f}; fora={total_fora:.2f}; total mostrado={total_ceaps + total_fora:.2f}")

    doc = {
        "politico_id": POLITICO_ID,
        "senador_id": SENADOR_ID,
        "fonte": "Senado Federal — Transparência e Dados Abertos",
        "escopo": "gastos_mandato_senado",
        "anos": list(range(ANO_INICIAL, ANO_ATUAL + 1)),
        "ano_corrente_parcial": ANO_ATUAL,
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_ceaps_periodo": round(sum(x["total_ceaps"] for x in anos), 2),
        "total_fora_ceaps_periodo": round(sum(x["total_fora_ceaps"] for x in anos), 2),
        "total_mostrado_periodo": round(sum(x["total_mostrado"] for x in anos), 2),
        "agregado_ceaps": [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(agregado_ceaps.items(), key=lambda kv: (-kv[1], kv[0]))],
        "agregado_fora_ceaps": [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(agregado_fora.items(), key=lambda kv: (-kv[1], kv[0]))],
        "por_ano": anos,
        "observacao": "Valores oficiais agregados pelo Senado. O ano corrente é parcial e pode sofrer alterações, estornos ou ajustes posteriores.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(anos)} anos gravados em {OUT}; total mostrado={doc['total_mostrado_periodo']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
