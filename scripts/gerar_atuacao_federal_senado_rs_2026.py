#!/usr/bin/env python3
"""Enriquece os candidatos ao Senado pelo RS com atuação federal comprovada."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gerar_atuacao_camara_sc_2026 as camara


RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "dados/atuacao_federal_senado_2026_rs.b64"
MANIFESTO = RAIZ / "dados/atuacao_federal_senado_manifesto_2026_rs.json"
ANOS_VOTOS = range(2001, camara.ANO_ATUAL + 1)
ANOS_CEAP = range(2008, camara.ANO_ATUAL + 1)


def main() -> None:
    candidatos = [x for x in camara.ler_b64(RAIZ / "dados/candidatos_senado_2026.b64")["candidatos"] if x.get("uf") == "RS"]
    atuais = camara.ler_b64(RAIZ / "dados/mandatos_federais_atuais_2026.b64").get("mandatos", {})
    historicos = camara.ler_b64(RAIZ / "dados/mandatos_federais_historicos_2026.b64").get("mandatos", {})
    perfis = {}
    deputados = {}
    exercicios_senado = 0
    for candidato in candidatos:
        cid = str(candidato["sq_candidato"])
        mandatos = historicos.get(cid, [])
        senado = [x for x in mandatos if x.get("casa") == "Senado Federal" and x.get("exercicios")]
        camara_hist = [x for x in mandatos if x.get("casa") == "Câmara dos Deputados"]
        atual = atuais.get(cid)
        camara_atual = bool(atual and atual.get("casa") == "Câmara dos Deputados")
        exercicios_senado += bool(senado)
        perfis[cid] = {
            "nome_urna": candidato["nome_urna"],
            "exercicio_senado_confirmado": bool(senado),
            "quantidade_mandatos_camara": len(camara_hist),
            "exercicio_atual_camara": camara_atual,
        }
        if camara_hist:
            mandato = camara_hist[0]
            dep_id = str(mandato["id_oficial"])
            deputados[dep_id] = (cid, mandato, camara_atual)

    print(f"Candidatos: {len(candidatos)}; Senado: {exercicios_senado}; Câmara: {len(deputados)}")
    with tempfile.TemporaryDirectory(prefix="senado-rs-camara-") as pasta:
        tmp = Path(pasta)
        camara.ANOS = ANOS_VOTOS
        votos, votacoes, fontes_votos = camara.coletar_votacoes(tmp, set(deputados))
        camara.ANOS = ANOS_CEAP
        ceap, fontes_ceap = camara.coletar_ceap(tmp, set(deputados))

    atuacoes = {}
    for dep_id, (cid, mandato, camara_atual) in deputados.items():
        linhas = votos.get(dep_id, [])
        atuacoes[cid] = {
            "deputado_id": dep_id,
            "nome_parlamentar": mandato.get("nome_parlamentar"),
            "url_perfil": mandato.get("url_perfil"),
            "legislaturas": mandato.get("legislaturas", []),
            "exercicio_atual": camara_atual,
            "votacoes": linhas,
            "resumo_votos": dict(sorted(Counter(x["status_voto"] for x in linhas).items())),
            "ceap": ceap.get(dep_id, {"total_liquido_centavos": 0, "quantidade_documentos": 0, "por_ano": [], "principais_categorias": []}),
        }

    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Senador", "uf": "RS",
        "cobertura_votos": [2001, camara.ANO_ATUAL], "cobertura_ceap": [2008, camara.ANO_ATUAL],
        "criterio": "Exercício parlamentar federal vinculado por nome civil oficial e unicidade. Candidatura, eleição ou suplência sem exercício não geram mandato.",
        "atualizado_em_utc": atualizado, "quantidade_candidatos": len(candidatos),
        "quantidade_com_exercicio_senado": exercicios_senado,
        "quantidade_com_exercicio_camara": len(atuacoes),
        "fontes": {"votacoes": fontes_votos, "ceap": fontes_ceap},
        "perfis": perfis, "votacoes": votacoes, "atuacoes_camara": atuacoes,
    }
    camara.gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Senador", "uf": "RS", "atualizado_em_utc": atualizado,
        "quantidade_candidatos": len(candidatos), "quantidade_com_exercicio_senado": exercicios_senado,
        "quantidade_com_exercicio_camara": len(atuacoes),
        "quantidade_com_exercicio_atual_camara": sum(x["exercicio_atual"] for x in atuacoes.values()),
        "quantidade_votos_camara": sum(len(x["votacoes"]) for x in atuacoes.values()),
        "total_ceap_centavos": sum(x["ceap"]["total_liquido_centavos"] for x in atuacoes.values()),
        "cobertura_votos": "2001–2026", "cobertura_ceap": "2008–2026",
        "arquivo": "dados/atuacao_federal_senado_2026_rs.b64",
        "observacao": "Nenhum candidato foi vinculado a exercício no Senado. Registros da Câmara respeitam os limites temporais das fontes; ausência de registro não comprova ausência de atuação.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
