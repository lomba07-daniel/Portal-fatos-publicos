#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
OUT = Path("dados/emendas_parlamentares.json")
AUTOR_ALVO = "FLAVIO BOLSONARO"
MAX_TENTATIVAS = 5


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", norm(s))


def br_number(v: str) -> float:
    s = (v or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def download() -> bytes:
    last = None
    for i in range(1, MAX_TENTATIVAS + 1):
        try:
            req = urllib.request.Request(
                URL,
                headers={
                    "User-Agent": "Mozilla/5.0 Portal-Fatos-Publicos/1.0",
                    "Accept": "application/zip,application/octet-stream,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) < 100_000:
                raise RuntimeError(f"arquivo muito pequeno ({len(data)} bytes)")
            if data[:2] != b"PK":
                raise RuntimeError("resposta não parece ser ZIP")
            return data
        except Exception as exc:
            last = exc
            print(f"tentativa {i}/{MAX_TENTATIVAS} falhou: {type(exc).__name__}: {exc}")
            if i < MAX_TENTATIVAS:
                time.sleep(i * 5)
    raise RuntimeError(f"falha no download após {MAX_TENTATIVAS} tentativas: {last}")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", errors="replace")


def choose_csv(z: zipfile.ZipFile) -> tuple[str, str]:
    candidates = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
    if not candidates:
        raise RuntimeError("ZIP sem CSV/TXT")
    for name in candidates:
        with z.open(name) as f:
            sample = decode(f.read(200_000))
        head = norm(sample.splitlines()[0] if sample.splitlines() else "")
        if "NOME DO AUTOR DA EMENDA" in head and "VALOR EMPENHADO" in head:
            return name, sample
    raise RuntimeError(f"não encontrei CSV principal entre: {candidates[:12]}")


def detect_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample[:50_000], delimiters=";,\t|")
    except csv.Error:
        class D(csv.excel):
            delimiter = ";"
        return D


def pick(row: dict, *names: str) -> str:
    idx = {key(k): v for k, v in row.items() if k is not None}
    for name in names:
        if key(name) in idx:
            return (idx[key(name)] or "").strip()
    return ""


def author_matches(name: str) -> bool:
    n = norm(name)
    return "FLAVIO" in n and "BOLSONARO" in n


def visual_url(codigo: str) -> str:
    q = urllib.parse.urlencode({
        "paginacaoSimples": "true",
        "direcaoOrdenacao": "asc",
        "palavraChave": codigo,
        "colunasSelecionadas": "codigoEmenda,ano,tipoEmenda,autor,numeroEmenda,localidadeDoGasto,funcao,subfuncao,valorEmpenhado,valorLiquidado,valorPago",
    })
    return "https://portaldatransparencia.gov.br/emendas/consulta?" + q


def add_agg(d: dict, label: str, emp: float, liq: float, pago: float, rap_pago: float):
    if not label:
        label = "Não informado"
    if label not in d:
        d[label] = {"qtd_registros": 0, "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "rap_pago": 0.0}
    x = d[label]
    x["qtd_registros"] += 1
    x["empenhado"] = round(x["empenhado"] + emp, 2)
    x["liquidado"] = round(x["liquidado"] + liq, 2)
    x["pago"] = round(x["pago"] + pago, 2)
    x["rap_pago"] = round(x["rap_pago"] + rap_pago, 2)


def main():
    data = download()
    print(f"download concluído: {len(data)/1024/1024:.1f} MiB")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name, sample = choose_csv(z)
        print(f"CSV principal: {name}")
        dialect = detect_dialect(sample)
        with z.open(name) as f:
            text = io.TextIOWrapper(f, encoding="cp1252", errors="replace", newline="")
            reader = csv.DictReader(text, dialect=dialect)
            records = []
            seen = set()
            autores_encontrados = set()
            for row in reader:
                autor = pick(row, "Nome do Autor da Emenda", "Nome Autor Emenda")
                if not author_matches(autor):
                    continue
                autores_encontrados.add(autor)
                codigo = pick(row, "Código da Emenda", "Codigo da Emenda")
                ano_s = pick(row, "Ano da Emenda", "Ano")
                try:
                    ano = int(re.sub(r"\D", "", ano_s)[:4])
                except Exception:
                    ano = int(codigo[:4]) if re.match(r"^\d{4}", codigo) else 0
                tipo = pick(row, "Tipo da Emenda", "Tipo de Emenda")
                numero = pick(row, "Número da Emenda", "Numero da Emenda")
                local = pick(row, "Localidade do Gasto")
                municipio = pick(row, "Município", "Municipio")
                uf = pick(row, "UF")
                regiao = pick(row, "Região", "Regiao")
                funcao = pick(row, "Nome Função", "Nome Funcao", "Função", "Funcao")
                subfuncao = pick(row, "Nome Subfunção", "Nome Subfuncao", "Subfunção", "Subfuncao")
                programa = pick(row, "Nome Programa")
                acao = pick(row, "Nome Ação", "Nome Acao")
                plano = pick(row, "Nome Plano Orçamentário", "Nome Plano Orcamentario")
                emp = br_number(pick(row, "Valor Empenhado"))
                liq = br_number(pick(row, "Valor Liquidado"))
                pago = br_number(pick(row, "Valor Pago"))
                rap_insc = br_number(pick(row, "Valor Restos A Pagar Inscritos"))
                rap_canc = br_number(pick(row, "Valor Restos A Pagar Cancelados"))
                rap_pago = br_number(pick(row, "Valor Restos A Pagar Pagos"))

                uniq = (codigo, local, municipio, uf, regiao, funcao, subfuncao, programa, acao, plano, emp, liq, pago, rap_insc, rap_canc, rap_pago)
                if uniq in seen:
                    continue
                seen.add(uniq)
                records.append({
                    "codigo_emenda": codigo,
                    "ano": ano,
                    "tipo_emenda": tipo,
                    "numero_emenda": numero,
                    "autor": autor,
                    "localidade": local or municipio or uf or regiao or "Não informado",
                    "municipio": municipio,
                    "uf": uf,
                    "regiao": regiao or "Não informado",
                    "funcao": funcao or "Não informado",
                    "subfuncao": subfuncao,
                    "programa": programa,
                    "acao": acao,
                    "plano_orcamentario": plano,
                    "empenhado": emp,
                    "liquidado": liq,
                    "pago": pago,
                    "rap_inscrito": rap_insc,
                    "rap_cancelado": rap_canc,
                    "rap_pago": rap_pago,
                    "url": visual_url(codigo),
                })

    if not records:
        raise SystemExit("Nenhum registro encontrado para Flávio Bolsonaro; arquivo anterior preservado.")

    years = sorted({r["ano"] for r in records if r["ano"]})
    if years and min(years) < 2019:
        raise SystemExit(f"Ano inesperado na seleção: {years}")

    by_area = {}
    by_region = {}
    by_year = {}
    codes = set()
    totals = {k: 0.0 for k in ("empenhado", "liquidado", "pago", "rap_inscrito", "rap_cancelado", "rap_pago")}
    for r in records:
        codes.add(r["codigo_emenda"])
        for k in totals:
            totals[k] = round(totals[k] + r[k], 2)
        add_agg(by_area, r["funcao"], r["empenhado"], r["liquidado"], r["pago"], r["rap_pago"])
        add_agg(by_region, r["regiao"], r["empenhado"], r["liquidado"], r["pago"], r["rap_pago"])
        add_agg(by_year, str(r["ano"]), r["empenhado"], r["liquidado"], r["pago"], r["rap_pago"])

    records.sort(key=lambda r: (r["ano"], r["codigo_emenda"], r["funcao"], r["localidade"]), reverse=True)
    doc = {
        "politico_id": "POL-000001",
        "autor_alvo": AUTOR_ALVO,
        "fonte": "Portal da Transparência / Controladoria-Geral da União",
        "fonte_download": "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares",
        "fonte_dicionario": "https://portaldatransparencia.gov.br/dicionario-de-dados/emendas-parlamentares",
        "escopo": "emendas_parlamentares_autor",
        "atualizado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anos": years,
        "ano_corrente_parcial": datetime.now(timezone.utc).year,
        "quantidade_registros": len(records),
        "quantidade_emendas_distintas": len(codes),
        "autores_encontrados": sorted(autores_encontrados),
        "totais": totals,
        "por_area": by_area,
        "por_regiao": by_region,
        "por_ano": by_year,
        "registros": records,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(records)} registros; {len(codes)} emendas distintas; anos={years}; totais={totals}")


if __name__ == "__main__":
    main()
