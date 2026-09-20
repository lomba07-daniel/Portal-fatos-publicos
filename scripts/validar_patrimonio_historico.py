#!/usr/bin/env python3
"""Valida integralmente as cargas patrimoniais publicadas e gera relatório auditável."""

from __future__ import annotations

import base64
import gzip
import json
from collections import Counter
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def main() -> None:
    manifesto = json.loads((RAIZ / "dados/patrimonio_historico_manifesto_2026.json").read_text(encoding="utf-8"))
    erros: list[str] = []
    anos = Counter()
    candidatos: set[str] = set()
    declaracoes = 0
    for uf, referencia in manifesto["arquivos_por_uf_atual"].items():
        doc = ler_b64(RAIZ / referencia["arquivo"])
        if doc.get("uf_atual") != uf:
            erros.append(f"Partição {uf} identifica {doc.get('uf_atual')}")
        if doc.get("anos_carregados") != manifesto["anos_carregados"]:
            erros.append(f"Anos divergentes na partição {uf}")
        for candidato, itens in doc.get("patrimonios", {}).items():
            candidatos.add(candidato)
            vistos: set[str] = set()
            for item in itens:
                ano = str(item["ano"])
                if ano in vistos:
                    erros.append(f"Ano duplicado: {uf}/{candidato}/{ano}")
                vistos.add(ano)
                soma = sum(int(tipo["valor_centavos"]) for tipo in item["tipos"])
                if soma != int(item["total_centavos"]):
                    erros.append(f"Soma divergente: {uf}/{candidato}/{ano}")
                if int(item["quantidade_bens"]) < len(item["tipos"]):
                    erros.append(f"Quantidade de bens inválida: {uf}/{candidato}/{ano}")
                anos[ano] += 1
                declaracoes += 1
    if len(candidatos) != manifesto["quantidade_candidatos_com_bens"]:
        erros.append("Quantidade de candidatos diverge do manifesto")
    if declaracoes != manifesto["quantidade_declaracoes"]:
        erros.append("Quantidade de declarações diverge do manifesto")
    relatorio = {
        "status": "aprovado" if not erros else "reprovado",
        "escopo": "Patrimônio eleitoral agregado de 2006 a 2026",
        "quantidade_particoes": len(manifesto["arquivos_por_uf_atual"]),
        "quantidade_candidatos": len(candidatos),
        "quantidade_declaracoes": declaracoes,
        "declaracoes_por_ano": dict(sorted(anos.items())),
        "testes": {
            "particao_corresponde_uf": not any("Partição" in e for e in erros),
            "anos_consistentes": not any("Anos divergentes" in e for e in erros),
            "sem_ano_duplicado_por_candidato": not any("Ano duplicado" in e for e in erros),
            "total_igual_soma_categorias": not any("Soma divergente" in e for e in erros),
            "contagens_iguais_manifesto": not any("Quantidade" in e and "inválida" not in e for e in erros),
        },
        "erros": erros,
        "observacao": "A validação comprova consistência interna e de vínculo; não certifica a veracidade econômica dos valores declarados pelos candidatos.",
    }
    destino = RAIZ / "dados/validacao_patrimonio_historico_2026.json"
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False))
    if erros:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
