#!/usr/bin/env python3
"""Baixa e valida os ZIPs oficiais de bens de candidatos do TSE."""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

from curl_cffi import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ano", type=int)
    parser.add_argument("destino", type=Path)
    args = parser.parse_args()
    if args.ano < 2004 or args.ano > 2100 or args.ano % 2:
        raise SystemExit("Ano eleitoral inválido.")

    url = f"https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{args.ano}.zip"
    resposta = requests.get(url, impersonate="chrome", timeout=300)
    resposta.raise_for_status()
    if len(resposta.content) < 100_000:
        raise SystemExit(f"Download do TSE anormalmente pequeno: {len(resposta.content)} bytes.")

    args.destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.destino.parent, delete=False) as tmp:
        tmp.write(resposta.content)
        temporario = Path(tmp.name)
    try:
        with zipfile.ZipFile(temporario) as zf:
            membros = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not membros or not any(f"bem_candidato_{args.ano}_" in n for n in membros):
                raise SystemExit("ZIP oficial sem os CSVs de bens esperados.")
            corrompido = zf.testzip()
            if corrompido:
                raise SystemExit(f"Arquivo corrompido no ZIP: {corrompido}")
        temporario.replace(args.destino)
    finally:
        temporario.unlink(missing_ok=True)
    print(f"OK: {args.destino} ({args.destino.stat().st_size} bytes) — {url}")


if __name__ == "__main__":
    main()
