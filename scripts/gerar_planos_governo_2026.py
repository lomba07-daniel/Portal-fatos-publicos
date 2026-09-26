#!/usr/bin/env python3
"""Vincula propostas oficiais do TSE, com prioridade SC → RS → PR."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
UFS_PRIORITARIAS = ("SC", "RS", "PR")
ID_ELEICAO = "20322002026"
URL_PACOTE = "https://cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_2026_{uf}.zip"
URL_CANDIDATO = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/buscar/2026/{uf}/" + ID_ELEICAO + "/candidato/{cid}"
URL_DOCUMENTO = "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/doc/{id_arquivo}"
PADRAO_ARQUIVO = re.compile(r"^2026(?P<uf>[A-Z]{2})(?P<id>\d{12})_(?P<ordem>\d+)\.pdf$", re.I)
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter(url: str, *, metodo: str = "GET") -> bytes | urllib.response.addinfourl:
    ultimo_erro = None
    for tentativa in range(4):
        try:
            req = urllib.request.Request(url, method=metodo, headers={"User-Agent": USER_AGENT})
            resposta = urllib.request.urlopen(req, timeout=120)
            return resposta if metodo == "HEAD" else resposta.read()
        except Exception as erro:  # a mensagem final preserva a URL e a causa da falha oficial
            ultimo_erro = erro
            if tentativa < 3:
                time.sleep(2 ** tentativa)
    raise RuntimeError(f"Fonte oficial indisponível: {url}: {ultimo_erro}")


def candidatos_governador() -> dict[str, dict]:
    doc = ler_b64(RAIZ / "dados/candidatos_executivos_2026.b64")
    return {
        str(c["sq_candidato"]): c
        for c in doc.get("candidatos", [])
        if c.get("cargo") == "Governador" and c.get("uf") in UFS_PRIORITARIAS
    }


def documentos_do_pacote(uf: str) -> tuple[dict[str, list[dict]], str]:
    bruto = obter(URL_PACOTE.format(uf=uf))
    documentos: dict[str, list[dict]] = defaultdict(list)
    datas: list[str] = []
    with zipfile.ZipFile(io.BytesIO(bruto)) as pacote:
        for info in pacote.infolist():
            nome = Path(info.filename).name
            match = PADRAO_ARQUIVO.match(nome)
            if not match or match.group("uf").upper() != uf:
                continue
            pdf = pacote.read(info)
            if not pdf.startswith(b"%PDF-"):
                raise SystemExit(f"Documento inválido no pacote do TSE: {nome}")
            cid = match.group("id")
            documentos[cid].append({
                "ordem": int(match.group("ordem")),
                "nome_arquivo_tse": nome,
                "tamanho_bytes": len(pdf),
                "sha256": hashlib.sha256(pdf).hexdigest(),
            })
            datas.append("%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time)
    for itens in documentos.values():
        itens.sort(key=lambda x: x["ordem"])
    return dict(documentos), max(datas)


def arquivos_atuais_api(uf: str, cid: str, esperados: list[dict]) -> list[dict]:
    detalhe = json.loads(obter(URL_CANDIDATO.format(uf=uf, cid=cid)))
    opcoes = [x for x in detalhe.get("arquivos") or [] if str(x.get("codTipo")) == "5"]
    por_tamanho: dict[int, list[dict]] = defaultdict(list)
    for item in opcoes:
        url = URL_DOCUMENTO.format(id_arquivo=item["idArquivo"])
        with obter(url, metodo="HEAD") as resposta:
            tipo = resposta.headers.get_content_type()
            tamanho = int(resposta.headers.get("Content-Length") or 0)
        if tipo != "application/pdf" or tamanho <= 0:
            continue
        por_tamanho[tamanho].append({
            "id_arquivo_tse": str(item["idArquivo"]),
            "nome_original": item.get("nome") or "Proposta de governo",
            "url": url,
            "tamanho_bytes": tamanho,
        })

    vinculados = []
    for esperado in esperados:
        candidatos = por_tamanho.get(esperado["tamanho_bytes"], [])
        if len(candidatos) != 1:
            candidatos = []
            for item in opcoes:
                url = URL_DOCUMENTO.format(id_arquivo=item["idArquivo"])
                pdf = obter(url)
                if hashlib.sha256(pdf).hexdigest() == esperado["sha256"]:
                    candidatos.append({
                        "id_arquivo_tse": str(item["idArquivo"]),
                        "nome_original": item.get("nome") or "Proposta de governo",
                        "url": url,
                        "tamanho_bytes": len(pdf),
                    })
        if len(candidatos) != 1:
            raise SystemExit(f"Não foi possível identificar unicamente o documento atual de {cid}/{uf}.")
        vinculados.append({**esperado, **candidatos[0]})
    return vinculados


def processar_uf(uf: str, candidatos: dict[str, dict]) -> tuple[dict, dict]:
    pacote, data_pacote = documentos_do_pacote(uf)
    esperados = {cid for cid, c in candidatos.items() if c.get("uf") == uf}
    if set(pacote) != esperados:
        faltam = sorted(esperados - set(pacote))
        sobram = sorted(set(pacote) - esperados)
        raise SystemExit(f"Divergência entre catálogo e propostas de {uf}; faltam={faltam}; sobram={sobram}")

    propostas = {}
    for cid in sorted(esperados):
        propostas[cid] = arquivos_atuais_api(uf, cid, pacote[cid])
        time.sleep(0.15)

    documento = {
        "eleicao": 2026,
        "uf": uf,
        "cargo": "Governador",
        "fonte": "Tribunal Superior Eleitoral — Dados Abertos e DivulgaCandContas",
        "fonte_url": URL_PACOTE.format(uf=uf),
        "data_pacote_tse": data_pacote,
        "quantidade_candidatos": len(propostas),
        "quantidade_documentos": sum(map(len, propostas.values())),
        "propostas": dict(sorted(propostas.items())),
    }
    arquivo_b64 = RAIZ / f"dados/planos_governo_2026_{uf.lower()}.b64"
    gravar_b64(arquivo_b64, documento)
    referencia = {
        "arquivo": f"dados/{arquivo_b64.name}",
        "fonte_url": documento["fonte_url"],
        "data_pacote_tse": data_pacote,
        "quantidade_candidatos": documento["quantidade_candidatos"],
        "quantidade_documentos": documento["quantidade_documentos"],
    }
    return documento, referencia


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ufs", nargs="+", choices=UFS_PRIORITARIAS, default=list(UFS_PRIORITARIAS))
    args = parser.parse_args()
    ordem = [uf for uf in UFS_PRIORITARIAS if uf in args.ufs]
    candidatos = candidatos_governador()
    referencias, totais = {}, Counter()
    for uf in ordem:
        documento, referencias[uf] = processar_uf(uf, candidatos)
        totais["candidatos"] += documento["quantidade_candidatos"]
        totais["documentos"] += documento["quantidade_documentos"]

    manifesto = {
        "eleicao": 2026,
        "escopo": "propostas_de_governo_prioridade_sul",
        "ordem_prioridade": list(UFS_PRIORITARIAS),
        "fonte": "Tribunal Superior Eleitoral — Dados Abertos e DivulgaCandContas",
        "pagina_fonte": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
        "arquivos_por_uf": referencias,
        "quantidade_candidatos": totais["candidatos"],
        "quantidade_documentos": totais["documentos"],
        "observacao": "Os links abrem os documentos atuais no domínio oficial do TSE; publicação não significa validação das propostas pelo Tribunal ou pelo portal.",
    }
    (RAIZ / "dados/planos_governo_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
