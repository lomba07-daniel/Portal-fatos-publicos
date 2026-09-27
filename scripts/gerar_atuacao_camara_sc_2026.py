#!/usr/bin/env python3
"""Publica votações e CEAP dos candidatos a deputado federal em exercício por SC."""
from __future__ import annotations

import base64
import csv
import gzip
import io
import json
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
ANO_ATUAL = datetime.now(timezone.utc).year
ANOS = range(2023, ANO_ATUAL + 1)
OUT = RAIZ / "dados/atuacao_camara_2026_sc.b64"
MANIFESTO = RAIZ / "dados/atuacao_camara_manifesto_2026.json"
URL_VOTOS = "https://dadosabertos.camara.leg.br/arquivos/votacoesVotos/csv/votacoesVotos-{ano}.csv"
URL_VOTACOES = "https://dadosabertos.camara.leg.br/arquivos/votacoes/csv/votacoes-{ano}.csv"
URL_CEAP = "https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
HEADERS = {"User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fontes oficiais)"}


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def baixar(url: str, destino: Path) -> None:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resposta, destino.open("wb") as saida:
        while bloco := resposta.read(1024 * 1024):
            saida.write(bloco)


def centavos(valor: str) -> int:
    return int((Decimal((valor or "0").replace(",", ".")) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalizar_voto(valor: str) -> str:
    texto = (valor or "").strip()
    chave = texto.casefold()
    if chave == "sim":
        return "sim"
    if chave in {"não", "nao"}:
        return "nao"
    if "absten" in chave:
        return "abstencao"
    if "obstru" in chave:
        return "obstrucao"
    if not texto:
        return "nao_informado"
    return "outro"


def coletar_votacoes(tmp: Path, ids: set[str]) -> tuple[dict[str, list], dict[str, dict], dict]:
    por_deputado: dict[str, list] = defaultdict(list)
    votacoes_usadas: dict[str, dict] = {}
    fontes = {}
    for ano in ANOS:
        arq_votacoes, arq_votos = tmp / f"votacoes-{ano}.csv", tmp / f"votos-{ano}.csv"
        baixar(URL_VOTACOES.format(ano=ano), arq_votacoes)
        baixar(URL_VOTOS.format(ano=ano), arq_votos)
        metadados = {}
        with arq_votacoes.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                metadados[row["id"]] = row
        with arq_votos.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                dep_id = row.get("deputado_id", "")
                if dep_id not in ids:
                    continue
                meta = metadados.get(row.get("idVotacao", ""), {})
                voto_original = (row.get("voto") or "").strip()
                votacao_id = row.get("idVotacao", "")
                votacoes_usadas[votacao_id] = {
                    "descricao": (meta.get("descricao") or "").strip(),
                    "orgao": (meta.get("siglaOrgao") or "").strip(),
                    "aprovacao": (meta.get("aprovacao") or "").strip(),
                    "proposicao": (meta.get("ultimaApresentacaoProposicao_descricao") or "").strip(),
                    "url": row.get("uriVotacao", ""),
                }
                por_deputado[dep_id].append({
                    "id_votacao": votacao_id,
                    "data_hora": row.get("dataHoraVoto", ""),
                    "voto": voto_original or "Não informado",
                    "status_voto": normalizar_voto(voto_original),
                })
        fontes[str(ano)] = {"votacoes": URL_VOTACOES.format(ano=ano), "votos": URL_VOTOS.format(ano=ano)}
    for linhas in por_deputado.values():
        unicas = {(x["id_votacao"], x["data_hora"]): x for x in linhas}
        linhas[:] = sorted(unicas.values(), key=lambda x: x["data_hora"], reverse=True)
    return por_deputado, votacoes_usadas, fontes


def coletar_ceap(tmp: Path, ids: set[str]) -> tuple[dict[str, dict], dict]:
    totais: dict[str, dict] = defaultdict(lambda: {
        "total_liquido_centavos": 0, "quantidade_documentos": 0,
        "por_ano": defaultdict(lambda: {"total_liquido_centavos": 0, "quantidade_documentos": 0}),
        "categorias": defaultdict(int),
    })
    fontes = {}
    for ano in ANOS:
        arquivo = tmp / f"ceap-{ano}.zip"
        url = URL_CEAP.format(ano=ano)
        baixar(url, arquivo)
        with zipfile.ZipFile(arquivo) as zf:
            nome = zf.namelist()[0]
            with zf.open(nome) as bruto, io.TextIOWrapper(bruto, encoding="utf-8-sig", newline="") as texto:
                for row in csv.DictReader(texto, delimiter=";"):
                    dep_id = (row.get("ideCadastro") or "").strip()
                    if dep_id not in ids:
                        continue
                    valor = centavos(row.get("vlrLiquido", "0"))
                    categoria = (row.get("txtDescricao") or "Categoria não informada").strip()
                    item = totais[dep_id]
                    item["total_liquido_centavos"] += valor
                    item["quantidade_documentos"] += 1
                    item["por_ano"][str(ano)]["total_liquido_centavos"] += valor
                    item["por_ano"][str(ano)]["quantidade_documentos"] += 1
                    item["categorias"][categoria] += valor
        fontes[str(ano)] = url
    saida = {}
    for dep_id, item in totais.items():
        saida[dep_id] = {
            "total_liquido_centavos": item["total_liquido_centavos"],
            "quantidade_documentos": item["quantidade_documentos"],
            "por_ano": [{"ano": int(ano), "parcial": int(ano) == ANO_ATUAL, **dados} for ano, dados in sorted(item["por_ano"].items())],
            "principais_categorias": [{"categoria": k, "valor_centavos": v} for k, v in sorted(item["categorias"].items(), key=lambda x: (-x[1], x[0]))[:10]],
        }
    return saida, fontes


def main() -> None:
    candidatos = ler_b64(RAIZ / "dados/candidatos_deputado_federal_2026_sc.b64")["candidatos"]
    mandatos = ler_b64(RAIZ / "dados/mandatos_federais_atuais_2026.b64").get("mandatos", {})
    atuais = {
        str(c["sq_candidato"]): mandatos[str(c["sq_candidato"])]
        for c in candidatos
        if str(c["sq_candidato"]) in mandatos and mandatos[str(c["sq_candidato"])].get("casa") == "Câmara dos Deputados"
    }
    oficiais = {str(m["id_oficial"]): cid for cid, m in atuais.items()}
    print(f"Candidatos em SC: {len(candidatos)}; deputados em exercício vinculados: {len(atuais)}")
    with tempfile.TemporaryDirectory(prefix="camara-sc-") as pasta:
        tmp = Path(pasta)
        votos, votacoes, fontes_votos = coletar_votacoes(tmp, set(oficiais))
        ceap, fontes_ceap = coletar_ceap(tmp, set(oficiais))
    atuacoes = {}
    for dep_id, cid in oficiais.items():
        linhas = votos.get(dep_id, [])
        atuacoes[cid] = {
            "deputado_id": dep_id,
            "nome_parlamentar": atuais[cid].get("nome_parlamentar"),
            "url_perfil": atuais[cid].get("url_perfil"),
            "legislatura": 57,
            "votacoes": linhas,
            "resumo_votos": dict(sorted(Counter(x["status_voto"] for x in linhas).items())),
            "ceap": ceap.get(dep_id, {"total_liquido_centavos": 0, "quantidade_documentos": 0, "por_ano": [], "principais_categorias": []}),
        }
    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Deputado Federal", "uf": "SC", "legislatura": 57,
        "periodo": [2023, ANO_ATUAL],
        "criterio": "Somente candidatos vinculados a exercício atual na Câmara; candidatura, eleição ou suplência sem exercício não geram atuação.",
        "atualizado_em_utc": atualizado, "quantidade_candidatos": len(candidatos),
        "quantidade_com_exercicio_atual": len(atuacoes),
        "fontes": {"votacoes": fontes_votos, "ceap": fontes_ceap},
        "votacoes": votacoes, "atuacoes": atuacoes,
    }
    gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Deputado Federal", "uf": "SC", "legislatura": 57,
        "atualizado_em_utc": atualizado, "quantidade_candidatos": len(candidatos),
        "quantidade_com_exercicio_atual": len(atuacoes),
        "quantidade_votos": sum(len(x["votacoes"]) for x in atuacoes.values()),
        "total_ceap_centavos": sum(x["ceap"]["total_liquido_centavos"] for x in atuacoes.values()),
        "arquivo": "dados/atuacao_camara_2026_sc.b64",
        "observacao": "A ausência nesta carga não significa ausência de atuação pública; o primeiro bloco cobre apenas exercício atual na Câmara, de 2023 a 2026.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
