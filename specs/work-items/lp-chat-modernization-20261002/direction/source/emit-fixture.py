from pathlib import Path
import json,re
D=Path(__file__).resolve().parents[1];T=(D/'tokens.css').read_text()
css='''
* {box-sizing:border-box} body {margin:0;padding:var(--space-8);background:var(--bg);color:var(--fg);font:var(--text-base)/var(--leading-normal) var(--font-body)}
h1,h2,h3 {font-family:var(--font-display);line-height:var(--leading-tight);letter-spacing:var(--tracking-tight)} h1{font-size:var(--text-3xl)} h2{font-size:var(--text-2xl)} h3{font-size:var(--text-lg)}
section {margin-block:var(--space-8)} .row {display:flex;gap:var(--space-3);flex-wrap:wrap} .grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--chat-max)),1fr));gap:var(--space-4)}
.card,.chat {border:var(--border-width) solid var(--border);border-radius:var(--radius-md);background:var(--surface);padding:var(--space-6);max-width:var(--chat-max)}
.btn,.case {font:var(--weight-medium) var(--text-sm)/var(--leading-snug) var(--font-body);padding:var(--space-3) var(--space-4);min-height:var(--target-min);border-radius:var(--radius-sm);border:var(--border-width) solid var(--border-strong);cursor:pointer;transition:background-color var(--motion-fast) var(--ease-out);background:var(--surface);color:var(--accent)}
.btn-primary {background:var(--accent);color:var(--surface);border-color:var(--accent)} .btn-primary:hover {background:var(--accent-hover)} .btn:active {transform:translateY(var(--border-width))} .btn-secondary:hover,.case:hover {background:var(--surface-muted)}
:focus-visible {outline:var(--focus-width) solid var(--focus-ring);outline-offset:var(--focus-offset)} .btn:focus-visible,.case:focus-visible,a:focus-visible,.field input:focus-visible {outline:var(--focus-width) solid var(--focus-ring);outline-offset:var(--focus-offset)}
a{color:var(--link)} a:hover{text-decoration:underline} .case[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:var(--weight-bold)}
.badge {font-size:var(--text-xs);border-radius:var(--radius-sm);padding:var(--space-2) var(--space-3);background:var(--surface-muted);color:var(--fg-muted)} .question{padding:var(--space-4);background:var(--surface-muted);border-radius:var(--radius-sm)} .source{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3);background:var(--source-surface);margin-block:var(--space-2);border-radius:var(--radius-sm);font-size:var(--text-sm);overflow-wrap:anywhere}.source span{color:var(--source-ink)} .note{color:var(--fg-muted);font-size:var(--text-xs)} .error{color:var(--danger)}
summary {cursor:pointer;min-height:var(--target-min);padding:var(--space-3)} details {border-block-end:var(--border-width) solid var(--border)} details[open] summary{color:var(--accent)} .field{display:grid;gap:var(--space-2)} .field input {font:inherit;padding:var(--space-3);border:var(--border-width) solid var(--border-strong);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg)} .field [aria-invalid="true"] {border-color:var(--danger)}
@media (prefers-reduced-motion:reduce) {*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
'''
html='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Arquivio | Fixture técnico da direção</title><style>'''+T+css+'''</style><body><h1>Arquivio — espécimes de contrato</h1><p class="note">Proposta A, H2 pendente. Este arquivo é fixture técnico; não implementa a LP ou seu wiring. Os estados futuros abaixo não entram na LP.</p>
<section data-group="actions"><h2>Ações e foco</h2><div class="row"><button class="btn btn-primary">Começar com o Arquivio</button><button class="btn btn-secondary">Já tenho uma conta</button><a href="#specimens">Produto (fixture)</a></div><p class="note">Somente espécimes visuais; callbacks de auth não existem neste arquivo.</p></section>
<section id="specimens" data-group="cases"><h2>Casos preservados</h2><div class="row"><button class="case" aria-pressed="true">Resposta com fontes</button><button class="case" aria-pressed="false">Com menção @</button><button class="case" aria-pressed="false">Sem evidência suficiente</button></div></section>
'''
cases=[('source-answer','Resposta com fontes','Todas as ferramentas','O que ficou definido para a primeira entrega?','A primeira entrega inclui o <strong>diagnóstico de marca</strong> e a <strong>proposta de posicionamento</strong>.',[('Escopo do projeto.pdf','Google Drive'),('Reunião de alinhamento','Notion'),('Cronograma de entregas','OneDrive')]),('mention','Com menção @','Google Drive','Quais são os prazos previstos neste documento?','O documento prevê o <strong>diagnóstico de marca</strong> na primeira etapa e a <strong>proposta de posicionamento</strong> na etapa seguinte.',[('Escopo do projeto.pdf','Google Drive')]),('no-evidence','Sem evidência suficiente','Notion','Qual foi o orçamento aprovado para mídia?','Não encontrei evidência nos documentos selecionados para confirmar o orçamento de mídia.',[])]
for sid,label,scope,q,a,sources in cases:
 html+=f'<section data-group="chat" data-state="{sid}"><h2>{label}</h2><article class="chat"><p><b>arquivio.</b> · Estúdio Aurora <span class="badge">Prévia ilustrativa</span></p><p class="question"><small>{scope}</small><br>{q}'+('<br>Arquivo: Escopo do projeto.pdf' if sid=='mention' else '')+f'</p><b>Arquivio</b><p>{a}</p>'
 if sources: html+='<b>Documentos utilizados</b>'+''.join(f'<div class="source"><span>{i+1}.</span><b>{n}</b><small>{p}</small></div>' for i,(n,p) in enumerate(sources))+('<p class="note">Ver mais 2 documentos</p>' if sid=='source-answer' else '')
 html+='<p class="note">Prévia da área de consultas do Arquivio. Exemplos fictícios.</p></article></section>'
html+='<section data-group="faq"><h2>FAQ e menu nativos</h2><details><summary>O Arquivio altera meus arquivos?</summary><p>Não. Os originais continuam no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura.</p></details><details open><summary>E se faltar informação?</summary><p>O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta.</p></details><details><summary>Abrir navegação (fixture)</summary><p>Produto · Integrações · Como funciona · Dúvidas · Entrar · Criar conta</p></details></section>'
for state,msg in [('Loading','Carregando conteúdo — espécime futuro, não simular na LP.'),('Empty','Sem conteúdo — espécime futuro de app.'),('Error','Erro recuperável — espécime futuro de app.'),('Populated','Conteúdo disponível — espécime futuro de app.'),('Edge','Nome muito longo: Escopo do projeto com revisão final da equipe e anexos.pdf — permitir quebra sem ocultar o provedor.')]:html+=f'<section data-group="future-data" data-state="{state}"><article class="card"><h3>{state} — app futuro</h3><p>{msg}</p><span class="badge">inferred · fora da LP</span></article></section>'
for state in ['Untouched','Dirty-valid','Submitted-pending']:html+=f'<section data-group="future-form" data-state="{state}"><article class="card"><h3>{state} — app futuro</h3><label class="field">Consulta de fixture<input '+('value="Pergunta de espécime"' if state!='Untouched' else 'placeholder="Somente espécime"')+(' readonly' if state=='Submitted-pending' else '')+'></label><p class="note">inferred · Não inserir formulário na LP.</p></article></section>'
html+='</body></html>';(D/'components.html').write_text(html)
selectors=re.findall(r'([^{}]+)\{[^{}]*\}',css)
selectors=[s.strip() for block in selectors for s in block.strip().split(',') if not s.strip().startswith('@')]
classes=sorted(set(re.findall(r'\.([A-Za-z][\w-]*)',css)))
groups=[]
for g in ['actions','cases','chat','faq','future-data','future-form']:
 groups.append({'id':g,'label':g,'selectors':selectors,'classes':classes,'elements':{'actions':['button','a'],'cases':['button'],'chat':['article','p','div'],'faq':['details','summary'],'future-data':['article'],'future-form':['label','input']}[g],'tokenReferences':sorted(set(re.findall(r'var\((--[\w-]+)\)',css)))})
manifest={'derivedFrom':'components.html CSS + data-group/data-state; generated /tmp/oc-direction-fixture.py','confidence':'inferred','scope':'Technical specimens only. Future 5+3 states are not shipped LP states.','classes':classes,'selectors':selectors,'groups':groups,'states':re.findall(r'data-state="([^"]+)"',html),'literals':{'colorExpressions':len(re.findall(r'#[0-9a-fA-F]{3,8}',css)),'pixelValues':len(re.findall(r'\d+px',css)),'hardcodedFontFamilies':0}}
(D/'components.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
def lum(h):
 rgb=[int(h[i:i+2],16)/255 for i in (1,3,5)];return sum(w*(x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4) for w,x in zip([.2126,.7152,.0722],rgb))
pairs=[('Texto principal','#142b25','#f5f7f4',4.5),('Texto UI','#142b25','#ffffff',4.5),('Secundário','#51635a','#f5f7f4',4.5),('Secundário UI','#51635a','#ffffff',4.5),('CTA branco/verde','#ffffff','#1c6052',4.5),('Fonte verde/painel','#1c6052','#eaf2ec',4.5),('Foco contra página','#965b0d','#f5f7f4',3),('Foco contra branco','#965b0d','#ffffff',3),('Borda controle','#718379','#ffffff',3),('B palco','#f5f7f4','#102f27',4.5),('B CTA lima/tinta','#142b25','#d9f279',4.5)]
r=[]
for label,a,b,minv in pairs:
 x,y=sorted([lum(a),lum(b)]);ratio=(y+.05)/(x+.05);r.append({'pair':label,'foreground':a,'background':b,'ratio':round(ratio,2),'minimum':minv,'pass':ratio>=minv,'confidence':'inferred','source':'sRGB WCAG luminance calculation of proposed hexes'})
(D/'source/contrast-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));assert all(x['pass'] for x in r);print('Fixture derived; literals zero;',len(r),'contrast pairs pass')
# Re-derive each group's actual selectors and token references from its CSS.
manifest=json.loads((D/'components.manifest.json').read_text())
fixture=(D/'components.html').read_text();style=fixture.split('</style>')[0];style=style[style.index('* {'):]
blocks=re.findall(r'([^{}]+)\{([^{}]*)\}',style)
scopes={'actions':['.btn','a'],'cases':['.case'],'chat':['.chat','.question','.source','.badge','.note'],'faq':['details','summary'],'future-data':['.card','.error','.badge'],'future-form':['.field','.card','.note']}
for g in manifest['groups']:
 matched=[(s,b) for s,b in blocks if any(p in s for p in scopes[g['id']]) or s.strip() in ['body','h1,h2,h3','h2','h3']]
 g['selectors']=[t.strip() for s,b in matched for t in s.split(',') if not t.strip().startswith('@')]
 g['classes']=sorted(set(re.findall(r'\.([a-zA-Z][\w-]*)',' '.join(s for s,b in matched))))
 g['tokenReferences']=sorted(set(re.findall(r'var\((--[\w-]+)\)',' '.join(b for s,b in matched))))
manifest['derivedFrom']='components.html; source/emit-fixture.py groups selectors/declaration token references from fixture CSS'
(D/'components.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
