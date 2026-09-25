#!/usr/bin/env python3
"""Materializa o escopo prioritário até 04/10 e mede a cobertura de cada perfil."""

from __future__ import annotations

import base64
import gzip
import json
from collections import Counter
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
UFS_LEGISLATIVAS = {"SC", "PR", "RS"}
CARGOS_EXECUTIVOS = {"Presidente", "Governador"}
CARGOS_LEGISLATIVOS = {"Senador", "Deputado Federal", "Deputado Estadual"}


def ler_b64(caminho: Path) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(caminho.read_text(encoding="ascii"))))


def gravar_b64(caminho: Path, documento: dict) -> None:
    bruto = json.dumps(documento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    caminho.write_text(base64.b64encode(gzip.compress(bruto, compresslevel=9, mtime=0)).decode("ascii") + "\n")


def carregar_catalogo() -> tuple[dict, dict[str, dict]]:
    manifesto = json.loads((RAIZ / "dados/candidatos_manifesto_2026.json").read_text(encoding="utf-8"))
    referencias = list(manifesto["cargas_iniciais"])
    for cargas in manifesto["cargas_por_cargo"].values():
        referencias.extend(cargas.values())
    candidatos = {}
    for ref in referencias:
        for candidato in ler_b64(RAIZ / ref["arquivo"]).get("candidatos", []):
            cid = str(candidato.get("sq_candidato", ""))
            if cid:
                candidatos[cid] = candidato
    if len(candidatos) != int(manifesto["quantidade_publicada"]):
        raise SystemExit("Catálogo divergente do manifesto.")
    return manifesto, candidatos


def ids_e_contagens(manifesto_nome: str, chave_raiz: str) -> tuple[set[str], dict[str, int]]:
    manifesto = json.loads((RAIZ / f"dados/{manifesto_nome}").read_text(encoding="utf-8"))
    ids: set[str] = set()
    contagens: dict[str, int] = Counter()
    for ref in manifesto["arquivos_por_uf_atual"].values():
        doc = ler_b64(RAIZ / ref["arquivo"])
        for cid, itens in doc.get(chave_raiz, {}).items():
            ids.add(cid)
            contagens[cid] += len(itens) if isinstance(itens, list) else 1
    return ids, dict(contagens)


def main() -> None:
    catalogo_meta, catalogo = carregar_catalogo()
    hist_ids, hist_n = ids_e_contagens("historico_candidaturas_manifesto_2026.json", "historicos")
    votos_ids, votos_n = ids_e_contagens("votos_historicos_manifesto_2026.json", "votos")
    patrimonio_ids, patrimonio_n = ids_e_contagens("patrimonio_historico_manifesto_2026.json", "patrimonios")
    contas_ids, _ = ids_e_contagens("contas_eleitorais_manifesto_2026.json", "contas")
    mandatos_path = RAIZ / "dados/mandatos_federais_atuais_2026.b64"
    mandatos_ids = set(ler_b64(mandatos_path).get("mandatos", {})) if mandatos_path.exists() else set()

    selecionados = []
    for cid, c in catalogo.items():
        cargo = c.get("cargo", "")
        uf = c.get("uf") or "BR"
        executivo = cargo in CARGOS_EXECUTIVOS
        legislativo_foco = cargo in CARGOS_LEGISLATIVOS and uf in UFS_LEGISLATIVAS
        if not executivo and not legislativo_foco:
            continue
        selecionados.append({
            "sq_candidato": cid,
            "nome": c.get("nome", ""),
            "nome_urna": c.get("nome_urna", ""),
            "cargo": cargo,
            "uf": uf,
            "partido_sigla": c.get("partido_sigla", ""),
            "numero": c.get("numero", ""),
            "prioridade": "perfil_completo" if executivo else "perfil_regional",
            "cobertura": {
                "historico_eleitoral": cid in hist_ids,
                "quantidade_candidaturas": hist_n.get(cid, 0),
                "votos_historicos": cid in votos_ids,
                "quantidade_resultados": votos_n.get(cid, 0),
                "patrimonio": cid in patrimonio_ids,
                "quantidade_declaracoes_patrimoniais": patrimonio_n.get(cid, 0),
                "contas_eleitorais_2026": cid in contas_ids,
                "mandatos": cid in mandatos_ids,
                "atuacao_publica": False,
                "plano_governo": False,
            },
        })
    selecionados.sort(key=lambda x: (x["prioridade"] != "perfil_completo", x["uf"], x["cargo"], x["nome_urna"]))

    por_cargo = Counter(x["cargo"] for x in selecionados)
    por_uf_legislativa = Counter(x["uf"] for x in selecionados if x["prioridade"] == "perfil_regional")
    cobertura = {}
    campos = ("historico_eleitoral", "votos_historicos", "patrimonio", "contas_eleitorais_2026", "mandatos", "atuacao_publica", "plano_governo")
    for campo in campos:
        quantidade = sum(bool(x["cobertura"][campo]) for x in selecionados)
        cobertura[campo] = {
            "quantidade": quantidade,
            "percentual": round(quantidade * 100 / len(selecionados), 2),
        }

    if len(selecionados) != 2940 or por_cargo != Counter({
        "Deputado Estadual": 1573,
        "Deputado Federal": 1117,
        "Governador": 201,
        "Senador": 35,
        "Presidente": 14,
    }):
        raise SystemExit(f"Escopo inesperado: {len(selecionados)} candidatos; {dict(por_cargo)}")

    documento = {
        "eleicao": 2026,
        "data_alvo": "04/10/2026",
        "criterio": {
            "perfil_completo": "Todos os candidatos a Presidente e Governador no Brasil.",
            "perfil_regional": "Senador, Deputado Federal e Deputado Estadual em SC, PR e RS.",
            "fora_do_aprofundamento": "Demais candidatos permanecem pesquisáveis no catálogo nacional, sem prioridade de enriquecimento antes da eleição.",
        },
        "ufs_legislativas": sorted(UFS_LEGISLATIVAS),
        "quantidade_prioritaria": len(selecionados),
        "quantidade_catalogo_nacional": len(catalogo),
        "candidatos": selecionados,
    }
    gravar_b64(RAIZ / "dados/escopo_prioritario_2026.b64", documento)
    manifesto = {
        "eleicao": 2026,
        "data_alvo": "04/10/2026",
        "gerado_a_partir_do_catalogo_tse_em": catalogo_meta.get("gerado_pelo_tse_em"),
        "quantidade_prioritaria": len(selecionados),
        "quantidade_perfil_completo": sum(x["prioridade"] == "perfil_completo" for x in selecionados),
        "quantidade_perfil_regional": sum(x["prioridade"] == "perfil_regional" for x in selecionados),
        "quantidade_catalogo_nacional": len(catalogo),
        "por_cargo": dict(sorted(por_cargo.items())),
        "por_uf_legislativa": dict(sorted(por_uf_legislativa.items())),
        "cobertura": cobertura,
        "arquivo": "dados/escopo_prioritario_2026.b64",
        "observacao": "O escopo orienta prioridade de enriquecimento; não remove candidaturas do catálogo nacional.",
    }
    (RAIZ / "dados/escopo_prioritario_manifesto_2026.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifesto, ensure_ascii=False))


if __name__ == "__main__":
    main()
