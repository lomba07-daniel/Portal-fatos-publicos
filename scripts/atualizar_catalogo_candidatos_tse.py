#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

URL='https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip'
OUT=Path('dados/candidatos_2026.json')
MAX_TENTATIVAS=5
CARGOS={'PRESIDENTE','GOVERNADOR','SENADOR','DEPUTADO FEDERAL','DEPUTADO ESTADUAL','DEPUTADO DISTRITAL'}


def fetch_bytes(url:str)->bytes:
    ultimo=None
    headers={
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36',
        'Referer':'https://dadosabertos.tse.jus.br/',
        'Accept':'application/zip,application/octet-stream,*/*;q=0.8',
        'Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8',
        'Cache-Control':'no-cache',
    }
    for i in range(1,MAX_TENTATIVAS+1):
        try:
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=180) as r:
                return r.read()
        except Exception as exc:
            ultimo=exc
            print(f'Tentativa {i}/{MAX_TENTATIVAS} falhou: {type(exc).__name__}: {exc}')
            if i<MAX_TENTATIVAS:
                time.sleep(3*i)
    raise RuntimeError(f'Falha ao baixar TSE após {MAX_TENTATIVAS} tentativas: {ultimo}') from ultimo


def norm(v):
    return (v or '').strip()


def camada(cargo:str)->str:
    if cargo in {'PRESIDENTE','GOVERNADOR'}:
        return 'profunda'
    if cargo in {'SENADOR','DEPUTADO FEDERAL'}:
        return 'intermediaria'
    return 'basica'


def first(row,*names):
    for n in names:
        if n in row and norm(row[n]):
            return norm(row[n])
    return ''


def main():
    raw=fetch_bytes(URL)
    z=zipfile.ZipFile(io.BytesIO(raw))
    csvs=[n for n in z.namelist() if n.lower().endswith('.csv')]
    if not csvs:
        raise SystemExit('ZIP do TSE não contém CSV.')

    candidatos={}
    arquivos=[]
    for name in csvs:
        arquivos.append(name)
        data=z.read(name)
        text=data.decode('latin-1')
        reader=csv.DictReader(io.StringIO(text),delimiter=';')
        for row in reader:
            cargo=first(row,'DS_CARGO').upper()
            if cargo not in CARGOS:
                continue
            sq=first(row,'SQ_CANDIDATO')
            if not sq:
                continue
            item={
                'sq_candidato':sq,
                'nome':first(row,'NM_CANDIDATO'),
                'nome_urna':first(row,'NM_URNA_CANDIDATO'),
                'cargo':cargo.title(),
                'cargo_codigo':first(row,'CD_CARGO'),
                'uf':first(row,'SG_UF'),
                'unidade_eleitoral':first(row,'NM_UE','SG_UE'),
                'numero':first(row,'NR_CANDIDATO'),
                'partido_sigla':first(row,'SG_PARTIDO'),
                'partido_nome':first(row,'NM_PARTIDO'),
                'federacao_sigla':first(row,'SG_FEDERACAO'),
                'federacao_nome':first(row,'NM_FEDERACAO'),
                'coligacao_nome':first(row,'NM_COLIGACAO'),
                'coligacao_composicao':first(row,'DS_COMPOSICAO_COLIGACAO'),
                'situacao_candidatura':first(row,'DS_SITUACAO_CANDIDATURA'),
                'detalhe_situacao':first(row,'DS_DETALHE_SITUACAO_CAND'),
                'situacao_pleito':first(row,'DS_SITUACAO_CANDIDATO_PLEITO'),
                'situacao_urna':first(row,'DS_SITUACAO_CANDIDATO_URNA'),
                'reeleicao':first(row,'ST_REELEICAO'),
                'ocupacao':first(row,'DS_OCUPACAO'),
                'grau_instrucao':first(row,'DS_GRAU_INSTRUCAO'),
                'camada':camada(cargo),
            }
            candidatos[sq]=item

    rows=sorted(candidatos.values(),key=lambda x:(x['cargo'],x['uf'],x['nome_urna'] or x['nome'],x['sq_candidato']))
    if len(rows)<100:
        raise SystemExit(f'Validação falhou: apenas {len(rows)} candidatos principais encontrados.')
    cargos=Counter(x['cargo'] for x in rows)
    for obrig in ['Presidente','Governador','Senador','Deputado Federal','Deputado Estadual']:
        if cargos.get(obrig,0)==0:
            raise SystemExit(f'Validação falhou: cargo {obrig} ausente.')

    por_camada=Counter(x['camada'] for x in rows)
    por_situacao=Counter(x['situacao_candidatura'] or 'Não informado' for x in rows)
    doc={
        'ano':2026,
        'fonte':'Tribunal Superior Eleitoral — Portal de Dados Abertos',
        'fonte_dataset':'https://dadosabertos.tse.jus.br/dataset/candidatos-2026',
        'fonte_arquivo':URL,
        'atualizado_em_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'politica_de_camadas':{
            'profunda':'Presidente e Governador — mesma profundidade factual prevista no MVP.',
            'intermediaria':'Senador e Deputado Federal — TSE + histórico parlamentar federal quando houver.',
            'basica':'Deputado Estadual/Distrital — perfil eleitoral TSE no MVP; histórico das assembleias em fase posterior.'
        },
        'quantidade':len(rows),
        'por_cargo':dict(sorted(cargos.items())),
        'por_camada':dict(sorted(por_camada.items())),
        'por_situacao_candidatura':dict(sorted(por_situacao.items())),
        'arquivos_processados':arquivos,
        'minimizacao':'CPF, e-mail, data de nascimento e título eleitoral não são publicados neste catálogo.',
        'candidatos':rows,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(OUT)
    print('OK',len(rows),'candidatos',dict(cargos),dict(por_camada))

if __name__=='__main__':
    main()
