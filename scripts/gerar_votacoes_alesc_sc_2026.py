#!/usr/bin/env python3
"""Publica votos nominais dos deputados atuais a partir das sessões da ALESC."""
from __future__ import annotations

import concurrent.futures
import html
import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

from gerar_atuacao_alesc_sc_2026 import normalizar
from gerar_atuacao_camara_sc_2026 import gravar_b64, ler_b64


RAIZ = Path(__file__).resolve().parent.parent
BASE = "https://portalelegis.alesc.sc.gov.br"
OUT = RAIZ / "dados/votacoes_alesc_2026_sc.b64"
MANIFESTO = RAIZ / "dados/votacoes_alesc_manifesto_2026.json"
HEADERS = {"User-Agent": "Portal-Fatos-Publicos/1.0 (+GitHub Pages; fonte oficial ALESC)"}


def texto(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def obter(path: str, opener=None, referer: str | None = None) -> str:
    cabecalhos = dict(HEADERS)
    if referer:
        cabecalhos.update({"X-Requested-With": "XMLHttpRequest", "Referer": BASE + referer})
    erro = None
    for tentativa in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers=cabecalhos)
            abertura = opener.open if opener else urllib.request.urlopen
            with abertura(req, timeout=90) as resposta:
                return resposta.read().decode("utf-8", "replace")
        except Exception as exc:
            erro = exc
            time.sleep(1.5 * (tentativa + 1))
    raise RuntimeError(f"Falha em {path}: {erro}")


def paginas_sessoes() -> list[str]:
    primeira = obter("/sessoes-plenarias")
    paginas = [int(x) for x in re.findall(r"/sessoes-plenarias\?page=(\d+)", primeira)]
    ultima = max(paginas, default=1)
    conteudos = [primeira]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        conteudos.extend(pool.map(lambda n: obter(f"/sessoes-plenarias?page={n}"), range(2, ultima + 1)))
    links = {
        x for pagina in conteudos
        for x in re.findall(r'href="(/sessoes-plenarias/[^"/]+/ordem-do-dia)"', pagina)
    }
    return sorted(links)


def blocos_nominais(pagina: str) -> list[dict]:
    itens = []
    for bloco in pagina.split('<div class="border-bottom mb-3">')[1:]:
        bloco = bloco.split('<div class="border-bottom mb-3">', 1)[0]
        extrato = re.search(r'hx-get="(/extrato-votacao/[^"/]+)"', bloco)
        materia = re.search(r'<a href="(/proposicoes/[^"/]+)">(.*?)</a>', bloco, re.S)
        if not extrato or not materia:
            continue
        badges = [texto(x) for x in re.findall(r'<span class="badge [^"]*">(.*?)</span>', bloco, re.S)]
        ementa = re.search(r'<p class="fst-italic[^>]*>(.*?)</p>', bloco, re.S)
        itens.append({
            "extrato": extrato.group(1),
            "materia": texto(materia.group(2)),
            "url_materia": BASE + materia.group(1),
            "resultado": badges[0] if badges else "",
            "ementa": texto(ementa.group(1)) if ementa else "",
        })
    return itens


def analisar_extrato(pagina: str) -> tuple[str, list[tuple[str, str]]]:
    fase = re.findall(r'<h5 class="row text-center">(.*?)</h5>', pagina, re.S)
    votos = []
    padrao = re.compile(
        r'<div class="d-flex justify-content-between align-items-center w-100">\s*'
        r'<div>(.*?)</div>\s*<div><span class="badge [^"]*">(.*?)</span>', re.S
    )
    for nome, voto in padrao.findall(pagina):
        votos.append((texto(nome), texto(voto)))
    return (texto(fase[0]) if fase else "", votos)


def analisar_sessao(path: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    pagina = obter(path, opener=opener)
    titulo = re.search(r'<h4 class="card-title[^>]*>(.*?)</h4>', pagina, re.S)
    inicio = re.search(r'<th>Início</th>\s*<td>(.*?)</td>', pagina, re.S)
    itens = []
    for item in blocos_nominais(pagina):
        extrato = obter(item["extrato"], opener=opener, referer=path)
        fase, votos = analisar_extrato(extrato)
        item.update({
            "id_votacao": item["extrato"].rsplit("/", 1)[-1],
            "fase": fase,
            "url_extrato": BASE + item["extrato"],
            "votos": votos,
        })
        itens.append(item)
    return {
        "url_sessao": BASE + path,
        "sessao": texto(titulo.group(1)) if titulo else "",
        "inicio": texto(inicio.group(1)) if inicio else "",
        "itens": itens,
    }


def main() -> None:
    candidatos = ler_b64(RAIZ / "dados/candidatos_deputado_estadual_2026_sc.b64")["candidatos"]
    mandatos = ler_b64(RAIZ / "dados/mandatos_estaduais_atuais_2026.b64").get("mandatos", {})
    atuais = {str(c["sq_candidato"]): mandatos[str(c["sq_candidato"])] for c in candidatos if str(c["sq_candidato"]) in mandatos}
    por_nome = {normalizar(m["nome_parlamentar"]): cid for cid, m in atuais.items()}

    links = paginas_sessoes()
    sessoes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as pool:
        futuros = {pool.submit(analisar_sessao, path): path for path in links}
        for i, futuro in enumerate(concurrent.futures.as_completed(futuros), 1):
            sessoes.append(futuro.result())
            if i % 100 == 0:
                print(f"Sessões processadas: {i}/{len(links)}", flush=True)

    votacoes = {}
    votos_por_candidato = {cid: [] for cid in atuais}
    votos_individuais = 0
    for sessao in sessoes:
        for item in sessao["itens"]:
            vid = item["id_votacao"]
            votacoes[vid] = {k: v for k, v in item.items() if k not in ("extrato", "votos")}
            votacoes[vid].update({"sessao": sessao["sessao"], "inicio": sessao["inicio"], "url_sessao": sessao["url_sessao"]})
            for nome, voto in item["votos"]:
                cid = por_nome.get(normalizar(nome))
                if not cid:
                    continue
                votos_por_candidato[cid].append({"id_votacao": vid, "voto": voto})
                votos_individuais += 1

    parlamentares = {}
    for cid, mandato in atuais.items():
        votos = sorted(
            votos_por_candidato[cid],
            key=lambda x: votacoes[x["id_votacao"]]["inicio"].split(" às ")[0].split("/")[::-1],
            reverse=True,
        )
        parlamentares[cid] = {
            "nome_parlamentar": mandato["nome_parlamentar"],
            "quantidade": len(votos),
            "por_voto": dict(sorted(Counter(x["voto"] for x in votos).items())),
            "votos": votos,
        }

    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    datas = [s["inicio"].split(" às ")[0] for s in sessoes if s["inicio"]]
    documento = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC",
        "criterio": "Somente extratos nominais publicados pelo e-Legis. Deliberações simbólicas e ausência de nome no extrato não são convertidas em voto ou posição.",
        "fonte": "ALESC — e-Legis — Sessões Plenárias", "fonte_url": BASE + "/sessoes-plenarias",
        "atualizado_em_utc": atualizado, "quantidade_sessoes_avaliadas": len(sessoes),
        "quantidade_votacoes_nominais": len(votacoes), "quantidade_votos_vinculados": votos_individuais,
        "periodo": [min(datas, key=lambda x: x.split("/")[::-1]), max(datas, key=lambda x: x.split("/")[::-1])],
        "votacoes": votacoes, "parlamentares": parlamentares,
    }
    gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Deputado Estadual", "uf": "SC", "atualizado_em_utc": atualizado,
        "periodo": "–".join(documento["periodo"]), "quantidade_parlamentares": len(parlamentares),
        "quantidade_sessoes_avaliadas": len(sessoes), "quantidade_votacoes_nominais": len(votacoes),
        "quantidade_votos_vinculados": votos_individuais, "arquivo": "dados/votacoes_alesc_2026_sc.b64",
        "fonte": documento["fonte_url"],
        "observacao": "A base inclui apenas votos individualizados nos extratos nominais; votação simbólica, ausência e presença sem voto não são posições inferidas.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
