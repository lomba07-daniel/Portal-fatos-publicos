#!/usr/bin/env python3
"""Baixa o ZIP oficial de candidaturas contornando bloqueios indevidos do CDN.

O CDN do TSE responde 403 a clientes HTTP automatizados comuns. ``curl_cffi``
faz a mesma negociação TLS de um navegador moderno, sem usar proxy ou fonte
intermediária: o arquivo continua vindo diretamente de ``cdn.tse.jus.br``.
"""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

from curl_cffi import requests


RECURSOS = {
    "catalogo": (
        "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip",
        "consulta_cand_2026_BRASIL.csv",
    ),
    "historico": (
        "https://cdn.tse.jus.br/estatistica/sead/odsele/historico_candidatura/historico_candidatura_2026.zip",
        "historico_candidatura_2026_BRASIL.csv",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destino", type=Path)
    parser.add_argument("--recurso", choices=tuple(RECURSOS), default="catalogo")
    args = parser.parse_args()
    url, arquivo_esperado = RECURSOS[args.recurso]

    resposta = requests.get(url, impersonate="chrome", timeout=180)
    resposta.raise_for_status()
    if len(resposta.content) < 500_000:
        raise SystemExit(f"Download do TSE anormalmente pequeno: {len(resposta.content)} bytes.")

    args.destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.destino.parent, delete=False) as tmp:
        tmp.write(resposta.content)
        temporario = Path(tmp.name)

    try:
        with zipfile.ZipFile(temporario) as zf:
            if arquivo_esperado not in zf.namelist():
                raise SystemExit(f"{arquivo_esperado} não encontrado no ZIP oficial.")
            corrompido = zf.testzip()
            if corrompido:
                raise SystemExit(f"Arquivo corrompido dentro do ZIP oficial: {corrompido}")
        temporario.replace(args.destino)
    finally:
        temporario.unlink(missing_ok=True)

    print(f"OK: {args.destino} ({args.destino.stat().st_size} bytes) baixado diretamente de {url}")


if __name__ == "__main__":
    main()
