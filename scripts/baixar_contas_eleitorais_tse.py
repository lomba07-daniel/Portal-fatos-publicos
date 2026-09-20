#!/usr/bin/env python3
"""Baixa e valida o pacote oficial de prestação de contas de candidatos de 2026."""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

from curl_cffi import requests


URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip"
ESPERADOS = {
    "receitas_candidatos_2026_BRASIL.csv",
    "despesas_contratadas_candidatos_2026_BRASIL.csv",
    "despesas_pagas_candidatos_2026_BRASIL.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destino", type=Path)
    args = parser.parse_args()
    resposta = requests.get(URL, impersonate="chrome", timeout=600)
    resposta.raise_for_status()
    if len(resposta.content) < 1_000_000:
        raise SystemExit(f"Download do TSE anormalmente pequeno: {len(resposta.content)} bytes")
    args.destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.destino.parent, delete=False) as tmp:
        tmp.write(resposta.content)
        temporario = Path(tmp.name)
    try:
        with zipfile.ZipFile(temporario) as zf:
            faltantes = ESPERADOS - set(zf.namelist())
            if faltantes:
                raise SystemExit(f"Arquivos ausentes no pacote oficial: {sorted(faltantes)}")
            corrompido = zf.testzip()
            if corrompido:
                raise SystemExit(f"Arquivo corrompido no ZIP: {corrompido}")
        temporario.replace(args.destino)
    finally:
        temporario.unlink(missing_ok=True)
    print(f"OK: {args.destino} ({args.destino.stat().st_size} bytes) — {URL}")


if __name__ == "__main__":
    main()
