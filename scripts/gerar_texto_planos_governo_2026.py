#!/usr/bin/env python3
"""Extrai texto e cria índice temático literal das propostas oficiais de governo."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
UFS_PRIORITARIAS = ("SC", "RS", "PR")
URL_MODELO = "https://cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_2026_{uf}.zip"
PADRAO = re.compile(r"^2026(?P<uf>[A-Z]{2})(?P<id>\d{12})_(?P<ordem>\d+)\.pdf$", re.I)
USER_AGENT = "PortalFatosPublicos/1.0 (dados públicos; contato pelo repositório)"
TEMAS = {
    "Saúde": ("saude", "sus", "hospital", "medico", "atencao basica", "saude mental", "farmacia", "cirurgia", "fila de espera"),
    "Educação": ("educacao", "escola", "professor", "ensino", "universidade", "creche", "alfabetiz", "estudante"),
    "Segurança pública": ("seguranca publica", "policia", "bombeiro", "criminal", "violencia", "feminicidio", "prisional", "defesa civil"),
    "Economia e emprego": ("emprego", "renda", "economia", "empreendedor", "industria", "comercio", "trabalho", "salario", "turismo"),
    "Infraestrutura e mobilidade": ("infraestrutura", "rodovia", "estrada", "mobilidade", "transporte", "ferrovia", "aeroporto", "porto", "saneamento"),
    "Meio ambiente": ("meio ambiente", "ambiental", "sustentabilidade", "clima", "descarbon", "enchente", "energia renovavel", "biodiversidade"),
    "Gestão pública": ("gestao publica", "servidor", "transparencia", "governanca", "eficiencia", "participacao social", "orcamento", "servico publico"),
    "Assistência e inclusão": ("assistencia social", "vulnerab", "pobreza", "inclusao", "pessoa com deficiencia", "idoso", "infancia", "direitos das mulheres"),
    "Agricultura e pesca": ("agricultura", "rural", "agronegocio", "agricultor", "pesca", "pecuaria", "agroecologia"),
    "Habitação": ("habitacao", "moradia", "casa propria", "regularizacao fundiaria"),
    "Ciência e tecnologia": ("ciencia", "tecnologia", "inovacao", "pesquisa", "digital", "inteligencia artificial"),
    "Cultura e esporte": ("cultura", "esporte", "lazer", "patrimonio cultural", "atleta"),
}


def ler_b64(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def obter(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/zip"})
    with urllib.request.urlopen(req, timeout=120) as resposta:
        return resposta.read()


def normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.casefold()).strip()


def numero_paginas(pdf: Path) -> int:
    saida = subprocess.check_output(["pdfinfo", str(pdf)], text=True, errors="replace")
    match = re.search(r"^Pages:\s+(\d+)", saida, re.M)
    if not match:
        raise RuntimeError(f"Não foi possível obter o número de páginas de {pdf.name}")
    return int(match.group(1))


def idiomas_tesseract() -> str:
    saida = subprocess.check_output(["tesseract", "--list-langs"], text=True, stderr=subprocess.STDOUT)
    disponiveis = set(saida.splitlines())
    return "por+eng" if {"por", "eng"} <= disponiveis else "por" if "por" in disponiveis else "eng"


def extrair_texto(pdf: Path, paginas: int) -> tuple[str, str, str | None]:
    texto = subprocess.check_output(
        ["pdftotext", "-layout", "-nopgbrk", "-enc", "UTF-8", str(pdf), "-"],
        text=True,
        errors="replace",
    )
    if len(normalizar(texto)) >= max(900, paginas * 35):
        return texto, "texto_embutido", None

    idioma = idiomas_tesseract()
    with tempfile.TemporaryDirectory(prefix="portal_ocr_") as pasta:
        prefixo = Path(pasta) / "pagina"
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", "165", str(pdf), str(prefixo)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        partes = []
        for imagem in sorted(Path(pasta).glob("pagina-*.jpg")):
            partes.append(subprocess.check_output(
                ["tesseract", str(imagem), "stdout", "-l", idioma, "--psm", "3"],
                text=True,
                errors="replace",
                stderr=subprocess.DEVNULL,
            ))
        texto = "\n\n".join(partes)
    if len(normalizar(texto)) < max(900, paginas * 35):
        raise RuntimeError(f"OCR insuficiente para {pdf.name}: {len(texto)} caracteres")
    return texto, "ocr", idioma


def quebrar_bloco(bloco: str, limite: int = 700) -> list[str]:
    bloco = re.sub(r"[ \t]+", " ", bloco).strip()
    if len(bloco) <= limite:
        return [bloco] if bloco else []
    frases = re.split(r"(?<=[.!?;:])\s+", bloco)
    partes, atual = [], ""
    for frase in frases:
        if len(atual) + len(frase) + 1 > limite and atual:
            partes.append(atual.strip())
            atual = ""
        atual = f"{atual} {frase}".strip()
    if atual:
        partes.append(atual)
    return partes


def paragrafos(texto: str) -> list[str]:
    texto = texto.replace("\r", "\n").replace("\f", "\n\n")
    blocos = re.split(r"\n\s*\n+", texto)
    resultado, vistos = [], set()
    for bloco in blocos:
        unido = " ".join(l.strip() for l in bloco.splitlines() if l.strip())
        for parte in quebrar_bloco(unido):
            chave = normalizar(parte)
            if len(chave) < 35 or chave in vistos:
                continue
            vistos.add(chave)
            resultado.append(parte)
    return resultado


def indexar_temas(itens: list[str], ordem_documento: int) -> dict[str, list[dict]]:
    indice: dict[str, list[dict]] = defaultdict(list)
    for texto in itens:
        base = normalizar(texto)
        for tema, termos in TEMAS.items():
            encontrados = sorted({termo for termo in termos if termo in base})
            if encontrados:
                indice[tema].append({
                    "documento": ordem_documento,
                    "termos": encontrados,
                    "texto": texto,
                })
    return dict(indice)


def processar_uf(uf: str, recriar_ocr: bool = False) -> tuple[dict, dict]:
    destino = RAIZ / f"dados/planos_governo_texto_2026_{uf.lower()}.b64"
    anterior = ler_b64(destino).get("propostas", {})
    cache = {}
    for proposta in anterior.values():
        for doc in proposta.get("documentos", []):
            cache[doc.get("sha256")] = doc

    bruto = obter(URL_MODELO.format(uf=uf))
    propostas: dict[str, dict] = {}
    contagens = Counter()
    datas = []
    with zipfile.ZipFile(io.BytesIO(bruto)) as pacote, tempfile.TemporaryDirectory(prefix=f"planos_{uf.lower()}_") as pasta:
        for info in pacote.infolist():
            nome = Path(info.filename).name
            match = PADRAO.match(nome)
            if not match or match.group("uf").upper() != uf:
                continue
            cid, ordem = match.group("id"), int(match.group("ordem"))
            pdf_bruto = pacote.read(info)
            sha = hashlib.sha256(pdf_bruto).hexdigest()
            reutilizado = cache.get(sha)
            if reutilizado and not (recriar_ocr and reutilizado.get("metodo_extracao") == "ocr"):
                doc = reutilizado
            else:
                pdf = Path(pasta) / nome
                pdf.write_bytes(pdf_bruto)
                paginas = numero_paginas(pdf)
                texto, metodo, idioma = extrair_texto(pdf, paginas)
                itens = paragrafos(texto)
                doc = {
                    "ordem": ordem,
                    "nome_arquivo_tse": nome,
                    "sha256": sha,
                    "paginas": paginas,
                    "metodo_extracao": metodo,
                    "idioma_ocr": idioma,
                    "quantidade_caracteres": sum(map(len, itens)),
                    "quantidade_palavras": sum(len(x.split()) for x in itens),
                    "paragrafos": itens,
                    "temas": indexar_temas(itens, ordem),
                }
            contagens[doc["metodo_extracao"]] += 1
            propostas.setdefault(cid, {"documentos": []})["documentos"].append(doc)
            datas.append("%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time)

    for proposta in propostas.values():
        proposta["documentos"].sort(key=lambda x: x["ordem"])
        agregados: dict[str, list[dict]] = defaultdict(list)
        for doc in proposta["documentos"]:
            for tema, trechos in doc["temas"].items():
                agregados[tema].extend(trechos)
        proposta["temas"] = {
            tema: {"ocorrencias": len(trechos), "trechos": trechos[:30]}
            for tema in TEMAS
            if (trechos := agregados.get(tema))
        }

    documento = {
        "eleicao": 2026,
        "uf": uf,
        "fonte": "Tribunal Superior Eleitoral — propostas de governo",
        "fonte_url": URL_MODELO.format(uf=uf),
        "data_pacote_tse": max(datas),
        "metodologia": "Texto nativo do PDF; OCR apenas quando o arquivo é composto por imagens. Temas associados por coincidência literal de termos, sem síntese ou interpretação.",
        "quantidade_candidatos": len(propostas),
        "quantidade_documentos": sum(len(x["documentos"]) for x in propostas.values()),
        "por_metodo_extracao": dict(sorted(contagens.items())),
        "propostas": dict(sorted(propostas.items())),
    }
    gravar_b64(destino, documento)
    ref = {
        "arquivo": f"dados/{destino.name}",
        "data_pacote_tse": documento["data_pacote_tse"],
        "quantidade_candidatos": documento["quantidade_candidatos"],
        "quantidade_documentos": documento["quantidade_documentos"],
        "por_metodo_extracao": documento["por_metodo_extracao"],
    }
    return documento, ref


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ufs", nargs="+", choices=UFS_PRIORITARIAS, default=["SC"])
    parser.add_argument("--recriar-ocr", action="store_true", help="Refaz apenas os documentos anteriormente extraídos por OCR.")
    args = parser.parse_args()
    ordem = [uf for uf in UFS_PRIORITARIAS if uf in args.ufs]
    refs, totais = {}, Counter()
    for uf in ordem:
        doc, refs[uf] = processar_uf(uf, recriar_ocr=args.recriar_ocr)
        totais["candidatos"] += doc["quantidade_candidatos"]
        totais["documentos"] += doc["quantidade_documentos"]
        totais.update(doc["por_metodo_extracao"])
    manifesto = {
        "eleicao": 2026,
        "escopo": "texto_pesquisavel_das_propostas",
        "ordem_prioridade": list(UFS_PRIORITARIAS),
        "estados_concluidos": ordem,
        "arquivos_por_uf": refs,
        "quantidade_candidatos": totais["candidatos"],
        "quantidade_documentos": totais["documentos"],
        "por_metodo_extracao": {k: totais[k] for k in ("texto_embutido", "ocr") if totais[k]},
        "metodologia": "Busca no texto oficial. Temas formados por palavras-chave; resultados não são resumo, promessa confirmada ou avaliação de viabilidade.",
    }
    (RAIZ / "dados/planos_governo_texto_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
