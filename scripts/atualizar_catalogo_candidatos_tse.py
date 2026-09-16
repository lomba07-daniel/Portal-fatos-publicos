#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE='https://divulgacandcontas.tse.jus.br/divulga/rest/v1'
ELEICAO='20322002026'
ANO=2026
OUT=Path('dados/candidatos_2026.json')
MAX_TENTATIVAS=4
UFS=['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO']
CARGOS={1:'Presidente',3:'Governador',5:'Senador',6:'Deputado Federal',7:'Deputado Estadual',8:'Deputado Distrital'}
HEADERS={
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36',
    'Referer':'https://divulgacandcontas.tse.jus.br/divulga/',
    'Origin':'https://divulgacandcontas.tse.jus.br',
    'Accept':'application/json, text/plain, */*',
    'Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8',
}


def get_json(url:str):
    ultimo=None
    for i in range(1,MAX_TENTATIVAS+1):
        try:
            req=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(req,timeout=90) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as exc:
            ultimo=exc
            print(f'Tentativa {i}/{MAX_TENTATIVAS}: {url} -> {type(exc).__name__}: {exc}')
            if i<MAX_TENTATIVAS:
                time.sleep(2*i)
    raise RuntimeError(f'Falha na API do TSE: {url}: {ultimo}') from ultimo


def camada(cargo:str)->str:
    if cargo in {'Presidente','Governador'}:
        return 'profunda'
    if cargo in {'Senador','Deputado Federal'}:
        return 'intermediaria'
    return 'basica'


def clean(v):
    if v is None:
        return ''
    return str(v).strip()


def parse_candidate(c:dict,cargo_nome:str,localidade:str)->dict:
    partido=c.get('partido') or {}
    cargo=c.get('cargo') or {}
    return {
        'sq_candidato':clean(c.get('id')),
        'nome':clean(c.get('nomeCompleto')),
        'nome_urna':clean(c.get('nomeUrna')),
        'cargo':clean(cargo.get('nome')) or cargo_nome,
        'cargo_codigo':clean(cargo.get('codigo')),
        'uf':clean(c.get('ufCandidatura')) or ('' if localidade=='BR' else localidade),
        'unidade_eleitoral':clean(c.get('localCandidatura')) or localidade,
        'numero':clean(c.get('numero')),
        'partido_sigla':clean(partido.get('sigla')),
        'partido_nome':clean(partido.get('nome')),
        'situacao_candidatura':clean(c.get('descricaoSituacao')),
        'situacao_totalizacao':clean(c.get('descricaoTotalizacao')),
        'coligacao_nome':clean(c.get('nomeColigacao')),
        'coligacao_composicao':clean(c.get('composicaoColigacao')),
        'ocupacao':clean(c.get('ocupacao')),
        'grau_instrucao':clean(c.get('grauInstrucao')),
        'camada':camada(cargo_nome),
        'atualizado_tse':clean(c.get('dataUltimaAtualizacao')),
    }


def carregar_lista(localidade:str,cargo:int):
    url=f'{BASE}/candidatura/listar/{ANO}/{localidade}/{ELEICAO}/{cargo}/candidatos'
    data=get_json(url)
    rows=data.get('candidatos',[]) if isinstance(data,dict) else []
    if not isinstance(rows,list):
        raise RuntimeError(f'Resposta inesperada: {url}')
    return rows,url


def main():
    candidatos={}
    fontes=[]

    # Presidência: abrangência nacional.
    rows,url=carregar_lista('BR',1)
    fontes.append(url)
    for c in rows:
        item=parse_candidate(c,'Presidente','BR')
        if item['sq_candidato']:
            candidatos[item['sq_candidato']]=item
    print('Presidente:',len(rows))

    # Demais cargos: uma consulta por UF e cargo principal.
    for uf in UFS:
        cargos=[3,5,6,8 if uf=='DF' else 7]
        for cod in cargos:
            rows,url=carregar_lista(uf,cod)
            fontes.append(url)
            nome=CARGOS[cod]
            for c in rows:
                item=parse_candidate(c,nome,uf)
                if item['sq_candidato']:
                    candidatos[item['sq_candidato']]=item
            print(uf,nome,len(rows))
            time.sleep(0.20)

    result=list(candidatos.values())
    result.sort(key=lambda x:(x['cargo'],x['uf'],x['nome_urna'] or x['nome'],x['sq_candidato']))
    cargos=Counter(x['cargo'] for x in result)
    por_camada=Counter(x['camada'] for x in result)
    por_situacao=Counter(x['situacao_candidatura'] or 'Não informado' for x in result)

    if len(result)<10000:
        raise SystemExit(f'Validação falhou: apenas {len(result)} candidatos principais encontrados.')
    for obrig in ['Presidente','Governador','Senador','Deputado Federal','Deputado Estadual','Deputado Distrital']:
        if cargos.get(obrig,0)==0:
            raise SystemExit(f'Validação falhou: cargo {obrig} ausente.')

    doc={
        'ano':ANO,
        'eleicao_id':ELEICAO,
        'fonte':'Tribunal Superior Eleitoral — DivulgaCandContas',
        'fonte_portal':'https://divulgacandcontas.tse.jus.br/',
        'fonte_dados_abertos':'https://dadosabertos.tse.jus.br/dataset/candidatos-2026',
        'metodo':'API pública usada pelo DivulgaCandContas, consultada por cargo e unidade eleitoral.',
        'atualizado_em_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'politica_de_camadas':{
            'profunda':'Presidente e Governador — mesma profundidade factual prevista no projeto.',
            'intermediaria':'Senador e Deputado Federal — TSE + histórico parlamentar federal quando houver.',
            'basica':'Deputado Estadual/Distrital — perfil eleitoral TSE no MVP; histórico das assembleias em fase posterior.'
        },
        'quantidade':len(result),
        'por_cargo':dict(sorted(cargos.items())),
        'por_camada':dict(sorted(por_camada.items())),
        'por_situacao_candidatura':dict(sorted(por_situacao.items())),
        'quantidade_consultas':len(fontes),
        'minimizacao':'CPF, e-mail, data de nascimento, título eleitoral e outros campos pessoais não necessários não são publicados neste catálogo.',
        'candidatos':result,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(OUT)
    print('OK',len(result),'candidatos',dict(cargos),dict(por_camada))

if __name__=='__main__':
    main()
