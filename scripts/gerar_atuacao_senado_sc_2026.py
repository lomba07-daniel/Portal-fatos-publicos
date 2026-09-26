#!/usr/bin/env python3
"""Publica votações nominais e gastos de mandato dos candidatos ao Senado por SC.

Somente candidatos vinculados a um mandato efetivamente exercido no Senado entram
na carga. Candidatura, eleição ou suplência sem exercício não geram atuação.
"""
from __future__ import annotations

import base64
import gzip
import json
import math
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import atualizar_votacoes_senado as votos_senado


RAIZ = Path(__file__).resolve().parent.parent
ANO_ATUAL = datetime.now(timezone.utc).year
API_GASTOS = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/{senador}/recursos-utilizados?ano={ano}&formato=json"
PAGINA_GASTOS = "https://www6g.senado.leg.br/transparencia/sen/{senador}/?ano={ano}"
DOC_VOTOS = "https://www12.senado.leg.br/dados-abertos/legislativo/plenario/votacoes-nominais/info/webservice-de-votacoes-de-um-senador"
OUT = RAIZ / "dados/atuacao_senado_2026_sc.b64"
MANIFESTO = RAIZ / "dados/atuacao_senado_manifesto_2026.json"


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def fetch_json(url: str, tentativas: int = 4) -> Any:
    erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers=votos_senado.HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resposta:
                return json.loads(resposta.read().decode("utf-8-sig"))
        except Exception as exc:
            erro = exc
            if tentativa < tentativas:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {erro}") from erro


def numero(v: Any) -> float:
    n = float(v or 0)
    if not math.isfinite(n) or n < 0:
        raise ValueError(f"Valor inválido: {v!r}")
    return round(n, 2)


def coletar_votos(senador_id: str, inicio: int) -> tuple[list[dict], dict]:
    todos: list[dict] = []
    por_ano = {}
    for ano in range(inicio, ANO_ATUAL + 1):
        url = f"https://legis.senado.leg.br/dadosabertos/arquivos/ListaVotacoes{ano}.json"
        payload = fetch_json(url)
        id_antigo, ano_antigo, url_antiga = votos_senado.SENADOR_ID, votos_senado.ANO_ATUAL, votos_senado.URL
        try:
            votos_senado.SENADOR_ID = senador_id
            votos_senado.ANO_ATUAL = ano
            votos_senado.URL = url
            linhas = votos_senado.parse_current_year(payload)
        finally:
            votos_senado.SENADOR_ID, votos_senado.ANO_ATUAL, votos_senado.URL = id_antigo, ano_antigo, url_antiga
        desconhecidos = sum(x["status_voto"] in {"outro", "nao_informado"} for x in linhas)
        if linhas and desconhecidos / len(linhas) > 0.20:
            raise ValueError(f"{ano}: proporção excessiva de votos não reconhecidos")
        por_ano[str(ano)] = {"quantidade": len(linhas), "arquivo": url}
        todos.extend(linhas)
    unicos = {(x["data"], x["codigo_sessao_votacao"], x["materia"], x["objeto"]): x for x in todos}
    saida = sorted(unicos.values(), key=lambda x: (x["data"], x["codigo_sessao_votacao"]), reverse=True)
    return saida, por_ano


def coletar_gastos(senador_id: str, nome: str, inicio: int) -> dict:
    anos = []
    categorias_ceaps: dict[str, float] = defaultdict(float)
    categorias_fora: dict[str, float] = defaultdict(float)
    for ano in range(inicio, ANO_ATUAL + 1):
        url = API_GASTOS.format(senador=senador_id, ano=ano)
        payload = fetch_json(url)
        dados = payload.get("data")
        if payload.get("statusCode") != 200 or not isinstance(dados, list) or len(dados) != 1:
            raise ValueError(f"{ano}: estrutura inesperada na API de gastos")
        linha = dados[0]
        nome_api = str((linha.get("parlamentar") or {}).get("nome") or "")
        if nome.split()[0].casefold() not in nome_api.casefold():
            raise ValueError(f"{ano}: parlamentar divergente na API: {nome_api}")
        cotas, fora = linha.get("cotas") or {}, linha.get("gastosNaoInclusos") or {}
        ceaps = [{"categoria": str(x.get("recurso") or "").strip(), "valor": numero(x.get("valor"))} for x in cotas.get("despesas") or []]
        extras = [{"categoria": str(x.get("recurso") or "").strip(), "valor": numero(x.get("valor"))} for x in fora.get("despesas") or []]
        total_ceaps, total_fora = numero(cotas.get("totalValor")), numero(fora.get("totalValor"))
        if abs(sum(x["valor"] for x in ceaps) - total_ceaps) > 0.10 or abs(sum(x["valor"] for x in extras) - total_fora) > 0.10:
            raise ValueError(f"{ano}: totais de gastos inconsistentes")
        for item in ceaps:
            categorias_ceaps[item["categoria"]] += item["valor"]
        for item in extras:
            categorias_fora[item["categoria"]] += item["valor"]
        anos.append({
            "ano": ano, "parcial": ano == ANO_ATUAL,
            "total_ceaps": total_ceaps, "total_fora_ceaps": total_fora,
            "total_mostrado": round(total_ceaps + total_fora, 2),
            "fonte_api": url, "fonte_visual": PAGINA_GASTOS.format(senador=senador_id, ano=ano),
        })
    return {
        "por_ano": anos,
        "total_ceaps_periodo": round(sum(x["total_ceaps"] for x in anos), 2),
        "total_fora_ceaps_periodo": round(sum(x["total_fora_ceaps"] for x in anos), 2),
        "total_mostrado_periodo": round(sum(x["total_mostrado"] for x in anos), 2),
        "principais_categorias_ceaps": [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(categorias_ceaps.items(), key=lambda x: -x[1])[:8]],
        "principais_categorias_fora_ceaps": [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(categorias_fora.items(), key=lambda x: -x[1])[:8]],
    }


def main() -> None:
    candidatos = [x for x in ler_b64(RAIZ / "dados/candidatos_senado_2026.b64")["candidatos"] if x.get("uf") == "SC"]
    mandatos = ler_b64(RAIZ / "dados/mandatos_federais_atuais_2026.b64").get("mandatos", {})
    atuacoes = {}
    for candidato in candidatos:
        cid = str(candidato["sq_candidato"])
        mandato = mandatos.get(cid)
        if not mandato or mandato.get("casa") != "Senado Federal" or not mandato.get("exercicios"):
            continue
        senador_id = str(mandato["id_oficial"])
        datas_inicio = [str(x.get("DataInicio"))[:10] for x in mandato["exercicios"] if x.get("DataInicio")]
        inicio_data = min(datas_inicio)
        inicio = int(inicio_data[:4])
        print(f"Coletando {candidato['nome_urna']} ({senador_id}), {inicio}–{ANO_ATUAL}...")
        votos, votos_por_ano = coletar_votos(senador_id, inicio)
        gastos = coletar_gastos(senador_id, mandato.get("nome_parlamentar") or candidato["nome_urna"], inicio)
        atuacoes[cid] = {
            "senador_id": senador_id,
            "nome_parlamentar": mandato.get("nome_parlamentar"),
            "periodo_exercicio": {"inicio": inicio_data, "fim": None},
            "votacoes": votos,
            "resumo_votos": dict(sorted(Counter(x["status_voto"] for x in votos).items())),
            "votos_por_ano": votos_por_ano,
            "gastos": gastos,
            "url_perfil": mandato.get("url_perfil"),
        }
    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Senador", "uf": "SC",
        "criterio": "Somente exercício no Senado confirmado em fonte oficial; candidatura, eleição e suplência sem exercício não geram atuação.",
        "fontes": {"votacoes": DOC_VOTOS, "gastos": "https://www6g.senado.leg.br/transparencia/"},
        "atualizado_em_utc": atualizado, "quantidade_candidatos": len(candidatos),
        "quantidade_com_exercicio_senado": len(atuacoes), "atuacoes": atuacoes,
    }
    gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Senador", "uf": "SC", "atualizado_em_utc": atualizado,
        "quantidade_candidatos": len(candidatos), "quantidade_com_exercicio_senado": len(atuacoes),
        "quantidade_votacoes": sum(len(x["votacoes"]) for x in atuacoes.values()),
        "arquivo": "dados/atuacao_senado_2026_sc.b64", "fontes": documento["fontes"],
        "observacao": "Ausência nesta carga não significa ausência de atuação pública; significa que não houve exercício no Senado vinculado pelas bases oficiais usadas.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
