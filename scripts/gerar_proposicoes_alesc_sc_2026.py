#!/usr/bin/env python3
"""Publica proposições do processo legislativo vinculadas aos deputados atuais da ALESC."""
from __future__ import annotations

import html
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from gerar_atuacao_alesc_sc_2026 import normalizar
from gerar_atuacao_camara_sc_2026 import gravar_b64, ler_b64


RAIZ = Path(__file__).resolve().parent.parent
BASE = "https://portalelegis.alesc.sc.gov.br"
ROTA = "/proposicoes/processo-legislativo"
INICIO = "2023-02-01"
FIM = datetime.now(timezone.utc).date().isoformat()
OUT = RAIZ / "dados/proposicoes_alesc_2026_sc.b64"
MANIFESTO = RAIZ / "dados/proposicoes_alesc_manifesto_2026.json"
HEADERS = {"User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial ALESC)"}


def obter(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resposta:
        return resposta.read().decode("utf-8", "replace")


def texto(fragmento: str) -> str:
    sem_tags = re.sub(r"<[^>]+>", " ", fragmento)
    return re.sub(r"\s+", " ", html.unescape(sem_tags)).strip()


def iniciativas_disponiveis(pagina: str) -> dict[str, str]:
    bloco = re.search(r'<select name="iniciativa".*?</select>', pagina, re.S)
    if not bloco:
        raise ValueError("Lista de iniciativas não encontrada no e-Legis")
    return {valor: texto(rotulo) for valor, rotulo in re.findall(r'<option value="([^"]+)">(.*?)</option>', bloco.group(0), re.S) if valor}


def vincular_iniciativa(nome: str, opcoes: dict[str, str]) -> str:
    alvo = set(normalizar(nome).split())
    candidatos = []
    for slug, rotulo in opcoes.items():
        tokens = set(normalizar(re.sub(r"^dep(?:utado|utada)?\s+", "", rotulo, flags=re.I)).split())
        if alvo and alvo.issubset(tokens):
            candidatos.append(slug)
    if len(candidatos) != 1:
        raise ValueError(f"Iniciativa ambígua/ausente para {nome}: {candidatos}")
    return candidatos[0]


def url_consulta(slug: str, pagina: int = 1) -> str:
    qs = {"iniciativa": slug, "inicio": INICIO, "fim": FIM, "arquivados": "1"}
    if pagina > 1:
        qs["page"] = str(pagina)
    return BASE + ROTA + "?" + urllib.parse.urlencode(qs)


def quantidade(pagina: str) -> int:
    m = re.search(r"Exibindo\s+\d+\s+-\s+\d+\s+de\s+([\d.]+)", pagina)
    return int(m.group(1).replace(".", "")) if m else 0


def analisar(pagina: str) -> list[dict]:
    itens = []
    for bloco in pagina.split('<div class="card card-alesc mb-3">')[1:]:
        cab = re.search(r'<h4 class="card-title">\s*<a href="(/proposicoes/[^"/]+)">(.*?)</a>', bloco, re.S)
        if not cab:
            continue
        ementa = re.search(r'<p class="mb-1 fst-italic"[^>]*>(.*?)</p>', bloco, re.S)
        def campo(nome: str) -> str:
            m = re.search(rf'>{re.escape(nome)}</div>\s*<div class="col-lg-10">(.*?)</div>', bloco, re.S)
            return texto(m.group(1)) if m else ""
        autores_html = re.search(r'>Autoria</div>\s*<div class="col-lg-10">(.*?)</div>', bloco, re.S)
        autores = [texto(x) for x in re.findall(r'<li>(.*?)</li>', autores_html.group(1), re.S)] if autores_html else []
        numero = texto(cab.group(2))
        itens.append({
            "id": cab.group(1).rsplit("/", 1)[-1], "numero": numero,
            "tipo": numero.split("/", 1)[0].rstrip("."),
            "entrada": campo("Entrada"), "ementa": texto(ementa.group(1)) if ementa else "",
            "autores": autores, "setor_atual": campo("Setor atual"),
            "situacao_atual": campo("Situação atual"), "url": BASE + cab.group(1),
        })
    return itens


def main() -> None:
    candidatos = ler_b64(RAIZ / "dados/candidatos_deputado_estadual_2026_sc.b64")["candidatos"]
    mandatos = ler_b64(RAIZ / "dados/mandatos_estaduais_atuais_2026.b64").get("mandatos", {})
    atuais = {str(c["sq_candidato"]): mandatos[str(c["sq_candidato"])] for c in candidatos if str(c["sq_candidato"]) in mandatos}
    inicial = obter(BASE + ROTA)
    opcoes = iniciativas_disponiveis(inicial)
    slugs = {cid: vincular_iniciativa(m["nome_parlamentar"], opcoes) for cid, m in atuais.items()}

    primeiras = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futuros = {pool.submit(obter, url_consulta(slug)): cid for cid, slug in slugs.items()}
        for futuro in as_completed(futuros):
            primeiras[futuros[futuro]] = futuro.result()
    tarefas = []
    for cid, pagina in primeiras.items():
        total = quantidade(pagina)
        for num in range(2, math.ceil(total / 10) + 1):
            tarefas.append((cid, num, url_consulta(slugs[cid], num)))
    adicionais: dict[str, list[str]] = {cid: [] for cid in atuais}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futuros = {pool.submit(obter, url): cid for cid, _, url in tarefas}
        for futuro in as_completed(futuros):
            adicionais[futuros[futuro]].append(futuro.result())

    proposicoes = {}
    for cid, mandato in atuais.items():
        paginas = [primeiras[cid], *adicionais[cid]]
        itens = [item for pagina in paginas for item in analisar(pagina)]
        unicos = {x["id"]: x for x in itens}
        itens = sorted(unicos.values(), key=lambda x: (x["entrada"].split("/")[::-1], x["numero"]), reverse=True)
        proposicoes[cid] = {
            "nome_parlamentar": mandato.get("nome_parlamentar"), "iniciativa_slug": slugs[cid],
            "quantidade": len(itens), "por_tipo": dict(sorted(Counter(x["tipo"] for x in itens).items())),
            "itens": itens,
        }
    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC", "periodo": [INICIO, FIM],
        "criterio": "Proposições retornadas pelo filtro oficial de iniciativa do parlamentar. A lista de autores é preservada para distinguir autoria individual e coletiva.",
        "fonte": "ALESC — e-Legis", "fonte_url": BASE + ROTA,
        "atualizado_em_utc": atualizado, "quantidade_parlamentares": len(proposicoes), "proposicoes": proposicoes,
    }
    gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC", "atualizado_em_utc": atualizado,
        "periodo": f"{INICIO}–{FIM}", "quantidade_parlamentares": len(proposicoes),
        "quantidade_proposicoes": sum(x["quantidade"] for x in proposicoes.values()),
        "arquivo": "dados/proposicoes_alesc_2026_sc.b64", "fonte": documento["fonte_url"],
        "observacao": "A iniciativa de uma proposição não equivale a aprovação, vigência, autoria exclusiva ou posição geral sobre o tema.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
