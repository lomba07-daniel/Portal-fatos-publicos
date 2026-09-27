#!/usr/bin/env python3
"""Enriquece candidatos de SC com mandato anterior, mas sem exercício atual na Câmara."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gerar_atuacao_camara_sc_2026 as camara


RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "dados/atuacao_camara_historica_2026_sc.b64"
MANIFESTO = RAIZ / "dados/atuacao_camara_historica_manifesto_2026.json"
ANOS_VOTOS = range(2001, camara.ANO_ATUAL + 1)
ANOS_CEAP = range(2008, camara.ANO_ATUAL + 1)


def main() -> None:
    candidatos = camara.ler_b64(RAIZ / "dados/candidatos_deputado_federal_2026_sc.b64")["candidatos"]
    atuais = camara.ler_b64(RAIZ / "dados/mandatos_federais_atuais_2026.b64").get("mandatos", {})
    historicos = camara.ler_b64(RAIZ / "dados/mandatos_federais_historicos_2026.b64").get("mandatos", {})
    anteriores = {}
    for candidato in candidatos:
        cid = str(candidato["sq_candidato"])
        atual = atuais.get(cid)
        if atual and atual.get("casa") == "Câmara dos Deputados":
            continue
        mandatos = [x for x in historicos.get(cid, []) if x.get("casa") == "Câmara dos Deputados"]
        if mandatos:
            anteriores[cid] = mandatos[0]
    oficiais = {str(m["id_oficial"]): cid for cid, m in anteriores.items()}
    print(f"Candidatos com passagem anterior e sem exercício atual: {len(anteriores)}")
    with tempfile.TemporaryDirectory(prefix="camara-historica-sc-") as pasta:
        tmp = Path(pasta)
        camara.ANOS = ANOS_VOTOS
        votos, votacoes, fontes_votos = camara.coletar_votacoes(tmp, set(oficiais))
        camara.ANOS = ANOS_CEAP
        ceap, fontes_ceap = camara.coletar_ceap(tmp, set(oficiais))
    atuacoes = {}
    for dep_id, cid in oficiais.items():
        mandato = anteriores[cid]
        linhas = votos.get(dep_id, [])
        atuacoes[cid] = {
            "deputado_id": dep_id,
            "nome_parlamentar": mandato.get("nome_parlamentar"),
            "url_perfil": mandato.get("url_perfil"),
            "legislaturas": mandato.get("legislaturas", []),
            "votacoes": linhas,
            "resumo_votos": dict(sorted(Counter(x["status_voto"] for x in linhas).items())),
            "ceap": ceap.get(dep_id, {"total_liquido_centavos": 0, "quantidade_documentos": 0, "por_ano": [], "principais_categorias": []}),
        }
    atualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documento = {
        "eleicao": 2026, "cargo": "Deputado Federal", "uf": "SC",
        "cobertura_votos": [2001, camara.ANO_ATUAL], "cobertura_ceap": [2008, camara.ANO_ATUAL],
        "criterio": "Candidatos com mandato anterior oficialmente vinculado e sem exercício atual na Câmara. Os registros são limitados aos anos disponíveis nas bases oficiais e não comprovam exercício contínuo.",
        "atualizado_em_utc": atualizado, "quantidade_com_mandato_anterior": len(atuacoes),
        "fontes": {"votacoes": fontes_votos, "ceap": fontes_ceap},
        "votacoes": votacoes, "atuacoes": atuacoes,
    }
    camara.gravar_b64(OUT, documento)
    manifesto = {
        "eleicao": 2026, "cargo": "Deputado Federal", "uf": "SC",
        "atualizado_em_utc": atualizado, "quantidade_com_mandato_anterior": len(atuacoes),
        "quantidade_com_votos": sum(bool(x["votacoes"]) for x in atuacoes.values()),
        "quantidade_votos": sum(len(x["votacoes"]) for x in atuacoes.values()),
        "quantidade_com_ceap": sum(bool(x["ceap"]["quantidade_documentos"]) for x in atuacoes.values()),
        "total_ceap_centavos": sum(x["ceap"]["total_liquido_centavos"] for x in atuacoes.values()),
        "cobertura_votos": "2001–2026", "cobertura_ceap": "2008–2026",
        "arquivo": "dados/atuacao_camara_historica_2026_sc.b64",
        "observacao": "Ausência de registro dentro ou fora da cobertura não é interpretada como ausência de atuação, presença, voto ou despesa.",
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
