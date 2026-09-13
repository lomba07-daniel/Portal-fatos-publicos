#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portal de Transparência Política — Atualizador de votações v0.7

Consulta somente serviços oficiais do Senado Federal e atualiza:
  dados/dados_v07.json
  site/index.html

Não requer bibliotecas externas.
"""
from pathlib import Path
import urllib.request, urllib.error, json, re, unicodedata
from datetime import datetime

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA_PATH = ROOT / "dados" / "dados.json"
HTML_PATH = ROOT / "index.html"
CODIGO = "5894"
NOME_ALVO = "FLAVIO BOLSONARO"
NOME_COMPLETO = "FLAVIO NANTES BOLSONARO"
API_ANTIGA = f"https://legis.senado.leg.br/dadosabertos/senador/{CODIGO}/votacoes.json"
API_NOVA = "https://legis.senado.leg.br/dadosabertos/votacao"
PAGINA_OFICIAL = "https://www25.senado.leg.br/web/atividade/votacoes-nominais/-/v/parlamentar/Fl%C3%A1vio%20Nantes%20Bolsonaro"

def norm(s):
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode()
    return re.sub(r"\s+"," ",s.strip().upper())

def get_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":"PortalTransparenciaPolitica/0.7 (projeto pessoal; dados publicos)",
            "Accept":"application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8-sig"))

def scalar(d, *keys):
    if not isinstance(d, dict):
        return None
    nk={norm(k):k for k in d.keys()}
    for k in keys:
        hit=nk.get(norm(k))
        if hit is not None and not isinstance(d[hit], (dict,list)):
            return d[hit]
    return None

def status_vote(desc, sigla=""):
    t=norm(desc); s=norm(sigla)
    if t=="SIM" or s in {"SIM","S"}: return "sim"
    if t in {"NAO","NÃO"} or s in {"NAO","NÃO","N"}: return "nao"
    if "ABSTEN" in t or "ABSTEN" in s: return "abstencao"
    if "OBSTRU" in t or "OBSTRU" in s: return "obstrucao"
    if "PRESENTE" in t and ("NAO REGISTROU" in t or "SEM VOTO" in t): return "presente_sem_voto"
    if "LICEN" in t: return "licenca"
    if "NAO COMPARECEU" in t or "AUSENTE" in t: return "ausente"
    if t=="VOTOU" or "SECRETA" in t: return "secreto"
    return "outro"

def vote_type(desc):
    t=norm(desc)
    if "DESTAQUE" in t: return "Destaque"
    if "REQUERIMENTO" in t: return "Requerimento"
    if "EMENDA" in t: return "Emenda"
    if "SUBSTITUTIVO" in t: return "Substitutivo"
    if "VETO" in t: return "Veto"
    return "Votação nominal"

def placar(v):
    sim=scalar(v,"TotalVotosSim","TotalSim")
    nao=scalar(v,"TotalVotosNao","TotalVotosNão","TotalNao")
    abs_=scalar(v,"TotalVotosAbstencao","TotalVotosAbstenção","TotalAbstencao")
    out=[]
    if sim is not None: out.append(f"{sim} Sim")
    if nao is not None: out.append(f"{nao} Não")
    if abs_ is not None: out.append(f"{abs_} Abstenção")
    return " · ".join(out)

def normalize_old(payload):
    root=payload.get("VotacaoParlamentar", payload)
    parl=root.get("Parlamentar", {})
    votes=(parl.get("Votacoes") or {}).get("Votacao") or []
    if isinstance(votes, dict): votes=[votes]
    out=[]
    for v in votes:
        mat=v.get("Materia") or {}
        ses=v.get("SessaoPlenaria") or {}
        desc=scalar(v,"DescricaoVotacao") or ""
        voto=scalar(v,"DescricaoVoto") or scalar(v,"SiglaDescricaoVoto") or "Não informado"
        sigla=scalar(v,"SiglaDescricaoVoto") or ""
        data=scalar(ses,"DataSessao") or scalar(v,"DataSessao") or ""
        code=scalar(mat,"Codigo") or scalar(v,"CodigoMateria")
        ident=scalar(mat,"DescricaoIdentificacao")
        if not ident:
            sg=scalar(mat,"Sigla") or ""
            nr=scalar(mat,"Numero") or ""
            an=scalar(mat,"Ano") or ""
            ident=" ".join(x for x in [sg, f"{nr}/{an}" if nr and an else nr] if x).strip() or "Matéria não identificada"
        ementa=scalar(mat,"Ementa") or ""
        url=(f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{code}/votacoes"
             if code else PAGINA_OFICIAL)
        out.append({
            "data":data,
            "materia":ident,
            "tipo_votacao":vote_type(desc),
            "objeto":desc or "Votação nominal registrada pelo Senado.",
            "voto":voto,
            "status_voto":status_vote(voto,sigla),
            "resultado":scalar(v,"DescricaoResultado") or "",
            "placar":placar(v),
            "tema":"Não classificado",
            "ementa":ementa,
            "contexto":"Registro importado diretamente do serviço oficial de votações do Senado.",
            "fonte":"Senado Federal — Dados Abertos",
            "url":url,
            "codigo_sessao_votacao":scalar(v,"CodigoSessaoVotacao"),
            "sequencial":scalar(v,"Sequencial"),
            "origem":"API oficial do Senado"
        })
    return out

def has_target(node):
    try:
        txt=norm(json.dumps(node,ensure_ascii=False))
    except Exception:
        return False
    return CODIGO in txt or NOME_ALVO in txt or NOME_COMPLETO in txt

def find_target_vote(node):
    """Procura a descrição individual do voto em uma árvore JSON."""
    if isinstance(node, dict):
        txt=norm(json.dumps(node,ensure_ascii=False))
        if (CODIGO in txt or NOME_ALVO in txt or NOME_COMPLETO in txt):
            for k in ("DescricaoVoto","Voto","TipoVoto","SiglaDescricaoVoto"):
                val=scalar(node,k)
                if val not in (None,""):
                    return str(val), str(scalar(node,"SiglaDescricaoVoto") or "")
        for v in node.values():
            hit=find_target_vote(v)
            if hit: return hit
    elif isinstance(node,list):
        for v in node:
            hit=find_target_vote(v)
            if hit: return hit
    return None

def pick_recursive(node, names):
    if isinstance(node,dict):
        v=scalar(node,*names)
        if v not in (None,""): return v
        for child in node.values():
            hit=pick_recursive(child,names)
            if hit not in (None,""): return hit
    elif isinstance(node,list):
        for child in node:
            hit=pick_recursive(child,names)
            if hit not in (None,""): return hit
    return None

def scan_new(node, out):
    """Fallback tolerante a mudanças de schema do endpoint /votacao."""
    if isinstance(node,dict):
        keys={norm(k) for k in node}
        looks_vote=("CODIGOSESSAOVOTACAO" in keys or "DESCRICAOVOTACAO" in keys or
                    "DESCRICAO VOTACAO" in keys)
        if looks_vote and has_target(node):
            indiv=find_target_vote(node)
            if indiv:
                voto,sigla=indiv
                desc=pick_recursive(node,["DescricaoVotacao"]) or "Votação nominal registrada pelo Senado."
                data=pick_recursive(node,["DataSessao","Data"])
                code=pick_recursive(node,["CodigoMateria","Codigo"])
                ident=pick_recursive(node,["DescricaoIdentificacao"])
                sg=pick_recursive(node,["Sigla","SiglaSubtipoMateria"])
                nr=pick_recursive(node,["Numero","NumeroMateria"])
                an=pick_recursive(node,["Ano","AnoMateria"])
                if not ident:
                    ident=f"{sg or ''} {nr or ''}/{an or ''}".strip(" /") or "Matéria não identificada"
                ementa=pick_recursive(node,["Ementa"]) or ""
                url=(f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{code}/votacoes"
                     if code else PAGINA_OFICIAL)
                rec={
                    "data":str(data or ""),
                    "materia":str(ident),
                    "tipo_votacao":vote_type(str(desc)),
                    "objeto":str(desc),
                    "voto":voto,
                    "status_voto":status_vote(voto,sigla),
                    "resultado":str(pick_recursive(node,["DescricaoResultado"]) or ""),
                    "placar":"",
                    "tema":"Não classificado",
                    "ementa":str(ementa),
                    "contexto":"Registro importado diretamente do serviço oficial de votações do Senado.",
                    "fonte":"Senado Federal — Dados Abertos",
                    "url":url,
                    "codigo_sessao_votacao":str(pick_recursive(node,["CodigoSessaoVotacao"]) or ""),
                    "origem":"API oficial do Senado"
                }
                out.append(rec)
        for v in node.values():
            scan_new(v,out)
    elif isinstance(node,list):
        for v in node: scan_new(v,out)

def normalize_new(payload):
    out=[]
    scan_new(payload,out)
    return out

def key(r):
    return (
        str(r.get("codigo_sessao_votacao") or ""),
        str(r.get("data") or ""),
        norm(r.get("materia")),
        norm(r.get("objeto")),
        norm(r.get("voto"))
    )

def dedupe(rows):
    seen=set(); out=[]
    for r in rows:
        k=key(r)
        if k in seen: continue
        seen.add(k); out.append(r)
    return out

def fetch_history():
    errors=[]
    # O endpoint por senador, embora legado, é o mais conveniente para reconstruir o mandato.
    try:
        p=get_json(API_ANTIGA)
        rows=normalize_old(p)
        if rows:
            return dedupe(rows), "api_senador"
    except Exception as e:
        errors.append(f"API por senador: {e}")

    # Fallback para o endpoint novo. Tenta anos de todo o mandato; o serviço pode limitar anos antigos.
    allrows=[]
    for ano in range(2019, 2027):
        try:
            p=get_json(f"{API_NOVA}?ano={ano}")
            allrows.extend(normalize_new(p))
        except Exception as e:
            errors.append(f"API nova {ano}: {e}")
    allrows=dedupe(allrows)
    if allrows:
        return allrows, "api_votacao"
    raise RuntimeError("Nenhum voto foi recuperado. " + " | ".join(errors))

def enrich_with_seed(rows, seed):
    for r in rows:
        candidates=[s for s in seed
                    if s.get("data")==r.get("data")
                    and norm(s.get("materia")).split(" — ")[0] in norm(r.get("materia"))
                    and s.get("status_voto")==r.get("status_voto")]
        if candidates:
            s=candidates[0]
            if len(str(s.get("contexto",""))) > len(str(r.get("contexto",""))):
                r["contexto"]=s["contexto"]
            if s.get("tema") and s.get("tema")!="Não classificado":
                r["tema"]=s["tema"]
            if s.get("tipo_votacao"):
                r["tipo_votacao"]=s["tipo_votacao"]
    return rows

def update_html(data):
    html=HTML_PATH.read_text(encoding="utf-8")
    payload=json.dumps(data,ensure_ascii=False,separators=(",",":")).replace("</","<\\/")
    new,n=re.subn(r"const DATA=.*?;\nconst money",
                  "const DATA="+payload+";\nconst money",
                  html,count=1,flags=re.S)
    if n!=1:
        raise RuntimeError("Não foi possível localizar const DATA no HTML.")
    HTML_PATH.write_text(new,encoding="utf-8")

def main():
    data=json.loads(DATA_PATH.read_text(encoding="utf-8"))
    seed=data.get("votacoes_nominais",[])
    print("Consultando histórico oficial de votações do Senado...")
    rows,mode=fetch_history()
    rows=enrich_with_seed(rows,seed)
    rows=sorted(rows,key=lambda x:(x.get("data") or "",x.get("materia") or ""),reverse=True)
    data["votacoes_nominais"]=rows
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta=data.setdefault("historico_votacoes",{})
    meta.update({
        "modo":"api_completa",
        "origem_coleta":mode,
        "atualizado_em":now,
        "quantidade":len(rows),
        "periodo":"2019–2026",
        "nota":"Histórico reconstruído a partir dos serviços oficiais de votações nominais do Senado Federal."
    })
    DATA_PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    update_html(data)
    print(f"OK: {len(rows)} registros nominais gravados.")
    print("Abra site/index.html")

if __name__=="__main__":
    main()
