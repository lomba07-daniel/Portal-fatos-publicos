#!/usr/bin/env python3
from pathlib import Path

P=Path('index.html')
s=P.read_text(encoding='utf-8')
if 'PILOTO v0.10 web' in s:
    print('v0.10 já aplicada')
    raise SystemExit(0)
if 'PILOTO v0.9 web' not in s:
    raise SystemExit('Versão esperada v0.9 não encontrada; nenhuma alteração aplicada.')

s=s.replace('PILOTO v0.9 web','PILOTO v0.10 web',1)
style_old='.search button,.btn{border:0;background:var(--accent);color:#fff;border-radius:10px;padding:10px 13px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}'
style_new=style_old+'.btn.secondary{background:#fff;color:var(--accent);border:1px solid var(--line);margin-top:6px}.answeritem{padding:10px 0;border-bottom:1px solid var(--line)}.answeritem:last-child{border-bottom:0}.matchwhy{font-size:11px;color:var(--muted);margin-top:4px}'
if style_old not in s:
    raise SystemExit('Bloco CSS esperado não encontrado.')
s=s.replace(style_old,style_new,1)

vs=s.index('function voteCard(v)')
ve=s.index('\nfunction recordCard',vs)
new_vote="""function senateMatterUrl(v,suffix=''){const id=String(v.codigo_materia||'').trim();return /^\\d+$/.test(id)?`https://www25.senado.leg.br/web/atividade/materias/-/materia/${id}${suffix}`:(v.url||'#')}
function voteCard(v){const cls=v.status_voto==='sim'?'sim':v.status_voto==='nao'?'nao':'';const voteUrl=senateMatterUrl(v,'/votacoes'),matterUrl=senateMatterUrl(v);return `<div class=\"record vote\"><div><div class=\"status ${cls}\">${esc(v.voto)}</div><div class=\"source\">${esc(v.data||'')} · ${esc(v.ano_arquivo||'')}</div></div><div><b>${esc(v.materia)}</b><div class=\"muted\">${esc(v.objeto||'')}</div><div class=\"source\">${esc(v.contexto||'')}</div></div><div><a class=\"btn\" href=\"${esc(voteUrl)}\" target=\"_blank\" rel=\"noopener\">Ver votação</a><br><a class=\"btn secondary\" href=\"${esc(matterUrl)}\" target=\"_blank\" rel=\"noopener\">Ver matéria</a></div></div>`}"""
s=s[:vs]+new_vote+s[ve:]

start=s.index(" const q=document.getElementById('q'),answer=document.getElementById('answer');")
end=s.index("}\nloadData().then(render)",start)
new_search=r''' const q=document.getElementById('q'),answer=document.getElementById('answer');q.addEventListener('focus',()=>q.value='');
 const STOP=new Set(['a','ao','aos','as','o','os','de','da','das','do','dos','e','em','na','nas','no','nos','um','uma','uns','umas','para','por','pela','pelas','pelo','pelos','com','sem','sobre','que','qual','quais','como','ele','ela','dele','dela','se','sua','seu','suas','seus','foi','foram','ser','esta','este','isso','isto','mais','menos','muito','muita','muitos','muitas','relacao','respeito','posiciona','posicionou','posicao','tema','assunto','contra','favor']);
 const CONCEPTS=[
  {id:'violencia_mulher',label:'violência contra a mulher',triggers:['violencia contra a mulher','violencia mulher','violencia domestica','feminicidio','maria da penha'],aliases:['lei maria da penha','maria da penha','violencia domestica','violencia contra a mulher','violencia de genero','feminicidio','medida protetiva','medidas protetivas','protecao a mulher','protecao da mulher','agressor de mulher']},
  {id:'armas',label:'armas e munições',triggers:['arma','armas','armamento','municao','municoes','porte de arma','posse de arma'],aliases:['arma','armas','armamento','municao','municoes','porte de arma','posse de arma','registro de armas','cac','cacs']},
  {id:'seguranca',label:'segurança pública',triggers:['seguranca publica','policia','policial','crime','criminalidade'],aliases:['seguranca publica','policia','policial','crime','criminal','presidio','sistema penal']},
  {id:'educacao',label:'educação',triggers:['educacao','escola','ensino','universidade'],aliases:['educacao','escola','ensino','universidade','professor','aluno']},
  {id:'saude',label:'saúde',triggers:['saude','sus','hospital','medico','medicamento'],aliases:['saude','sus','hospital','medico','medicamento','doenca']},
  {id:'meio_ambiente',label:'meio ambiente',triggers:['meio ambiente','ambiental','amazonia','desmatamento'],aliases:['meio ambiente','ambiental','amazonia','desmatamento','floresta','clima']}
 ];
 const words=n=>n.split(/[^a-z0-9]+/).filter(x=>x.length>2&&!STOP.has(x));
 const conceptsFor=n=>CONCEPTS.filter(c=>c.triggers.some(t=>n.includes(strip(t))));
 const scoreRecord=(r,terms,concepts)=>{const title=strip(r.titulo||''),fact=strip(r.registro_factual||''),tema=strip(r.tema||''),ctx=strip(r.contexto||''),id=strip(r.id_oficial||''),all=[title,fact,tema,ctx,id].join(' ');let score=0,matched=new Set(),why=[];for(const t of terms){if(id.includes(t)){score+=12;matched.add(t)}if(tema.includes(t)){score+=8;matched.add(t)}if(title.includes(t)){score+=6;matched.add(t)}if(fact.includes(t)){score+=4;matched.add(t)}if(ctx.includes(t)){score+=2;matched.add(t)}}for(const c of concepts){const found=c.aliases.filter(a=>all.includes(strip(a)));if(found.length){score+=14+Math.min(found.length,3)*3;why.push(c.label)}}if(matched.size>=2)score+=8;const enough=concepts.length?score>=14:(terms.length<=1?score>=4:matched.size>=2);return enough?{score,matched:matched.size,why}:null};
 const searchRecords=n=>{const terms=words(n),concepts=conceptsFor(n);return R.map(r=>{const x=scoreRecord(r,terms,concepts);return x?{r,...x}:null}).filter(Boolean).sort((a,b)=>b.score-a.score||String(b.r.data).localeCompare(String(a.r.data))).slice(0,6)};
 const recordResult=x=>`<div class="answeritem"><b>${esc(x.r.data)} · ${esc(x.r.titulo)}</b><br><span class="source">${esc(x.r.registro_factual||'')}</span>${x.why.length?`<div class="matchwhy">Correspondência temática: ${esc(x.why.join(', '))}</div>`:''}${x.r.url_fonte?`<div style="margin-top:6px"><a href="${esc(x.r.url_fonte)}" target="_blank" rel="noopener">Fonte oficial</a></div>`:''}</div>`;
 const voteResult=v=>`<div class="answeritem">${esc(v.data)} · <b>${esc(v.materia)}</b> — ${esc(v.voto)}<br><span class="source">${esc(v.objeto)}</span><div style="margin-top:6px"><a href="${esc(senateMatterUrl(v,'/votacoes'))}" target="_blank" rel="noopener">Ver votação no Senado</a></div></div>`;
 const ask=()=>{const raw=q.value.trim(),n=strip(raw);if(!raw)return;let html='';if(/vot|pec|plp|\bpl\b|mpv|pdl|msf|rqs/.test(n)){const year=(n.match(/\b(2019|2020|2021|2022|2023|2024|2025|2026)\b/)||[])[1];const stopVote=new Set([...STOP,'votou','voto','votacao','votacoes','flavio','bolsonaro']);const terms=n.split(/[^a-z0-9]+/).filter(x=>x.length>1&&!stopVote.has(x)&&x!==year);let hits=V.filter(v=>(!year||String(v.data).startsWith(year))&&(!terms.length||terms.every(t=>strip([v.materia,v.objeto].join(' ')).includes(t))));if(!hits.length&&terms.length>1)hits=V.filter(v=>(!year||String(v.data).startsWith(year))&&terms.filter(t=>strip([v.materia,v.objeto].join(' ')).includes(t)).length>=Math.min(2,terms.length));hits=hits.slice(0,8);html=hits.length?`<b>${hits.length} resultado(s)${year?' em '+year:''}:</b>`+hits.map(voteResult).join(''):'Não encontrei votação suficientemente correspondente na base de 2019–2026.'}else if(/emenda|recurso|dinheiro publico/.test(n)){html=`Há <b>${E.length}</b> emendas carregadas nesta amostra, com ${money(er.empenhado)} empenhados e ${money(er.pago)} pagos. A amostra ainda não representa o total do mandato.`}else if(/campanha|fornecedor|despesa eleitoral|receita/.test(n)){html=`No snapshot da campanha de 2026: <b>${money(receita)}</b> em receitas e <b>${money(campanha)}</b> em despesas declaradas.`}else if(/patrimonio|bens/.test(n)){const last=hist.at(-1);html=last?`Último patrimônio total carregado: <b>${money(last.patrimonio_total)}</b> (${last.ano}). Veja a aba Patrimônio para o histórico.`:'Não há patrimônio carregado.'}else{const hits=searchRecords(n);html=hits.length?`<b>${hits.length} resultado(s) com correspondência suficiente:</b>`+hits.map(recordResult).join(''):'Não encontrei correspondência temática suficientemente forte na base carregada. Prefiro não mostrar resultados fracos ou apenas coincidentes por palavras genéricas.'}answer.innerHTML=html};document.getElementById('ask').onclick=ask;q.onkeydown=e=>{if(e.key==='Enter')ask()};
'''
s=s[:start]+new_search+s[end:]
P.write_text(s,encoding='utf-8')
print('v0.10 aplicada ao index.html')
