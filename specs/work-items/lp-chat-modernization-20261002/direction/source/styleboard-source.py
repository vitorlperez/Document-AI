from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from fontTools.ttLib import TTFont as FTFont
from fontTools.varLib.instancer import instantiateVariableFont
import json,fitz
D=Path(__file__).resolve().parents[1]
for name,file,axes in [('Display','Manrope-variable.ttf',{'wght':650}),('Body','IBMPlexSans-variable.ttf',{'wght':400,'wdth':100}),('Medium','IBMPlexSans-variable.ttf',{'wght':600,'wdth':100}),('Alt','SpaceGrotesk-variable.ttf',{'wght':600})]:
 f=FTFont(D/'fonts'/file);f=instantiateVariableFont(f,axes,inplace=True);p='/tmp/oc-direction-'+name+'.ttf';f.save(p);pdfmetrics.registerFont(TTFont(name,p))
pdfmetrics.registerFont(TTFont('Brand','/System/Library/Fonts/Supplemental/Arial Bold.ttf'))
W,H=1080,810; c=canvas.Canvas(str(D/'STYLEBOARD.pdf'),pagesize=(W,H));c.setTitle('Arquivio | Direção da LP | Contexto vivo e Farol de conhecimento');c.setAuthor('Arquivio · Missão 37 · Direção');
bg='#f5f7f4'; ink='#142b25'; accent='#1c6052'; muted='#51635a'; lime='#d9f279'; line='#d5dfd7'; white='#ffffff';dark='#102f27'
def box(x,y,w,h,color,r=0,stroke=None):
 c.setFillColor(HexColor(color));c.setStrokeColor(HexColor(stroke or color));c.setLineWidth(.7)
 if r:c.roundRect(x,H-y-h,w,h,r,fill=1,stroke=bool(stroke))
 else:c.rect(x,H-y-h,w,h,fill=1,stroke=bool(stroke))
def text(x,y,t,size=14,font='Body',color=ink):c.setFillColor(HexColor(color));c.setFont(font,size);c.drawString(x,H-y-size*.82,t)
def para(x,y,t,w,size=14,font='Body',color=ink,leading=None):
 st=ParagraphStyle('x',fontName=font,fontSize=size,leading=leading or size*1.4,textColor=HexColor(color),spaceAfter=0);p=Paragraph(t,st);_,h=p.wrap(w,1000);p.drawOn(c,x,H-y-h);return h

def brand(x,y,size=26,inverse=False):
 sc=size/26
 if inverse:box(x-9,y-8,30*sc+pdfmetrics.stringWidth('arquivio.','Brand',size)+18,size+16,white,6)
 col='#243b35'
 for k in range(3):
  c.setStrokeColor(HexColor(accent));c.setLineWidth(1.5*sc);p=c.beginPath();p.moveTo(x,H-y-(4+k*5)*sc);p.lineTo(x+11*sc,H-y-(k*5)*sc);p.lineTo(x+22*sc,H-y-(4+k*5)*sc);p.lineTo(x+11*sc,H-y-(9+k*5)*sc);p.close();c.drawPath(p,stroke=1,fill=0)
 text(x+30*sc,y-1,'arquivio',size,'Brand',col);tw=pdfmetrics.stringWidth('arquivio','Brand',size);text(x+30*sc+tw,y-1,'.',size,'Brand',accent)
def pill(x,y,t,w=None,color=accent,fg=white,size=13,h=40):
 w=w or pdfmetrics.stringWidth(t,'Medium',size)+28;box(x,y,w,h,color,8);text(x+14,y+(h-size)/2-1,t,size,'Medium',fg);return w

def header(n,kicker,title,subtitle=None,color=bg):
 box(0,0,W,H,color);text(48,26,'ARQUIVIO / DIREÇÃO LP',11,'Medium',accent);text(785,26,'02 OUT 2026 · H2 PENDENTE',11,'Medium',muted);text(48,66,kicker,11,'Medium',muted);text(48,91,title,31,'Display');
 if subtitle:para(48,139,subtitle,975,13,color=muted)
 box(48,H-41,984,1,line);text(48,H-31,'Estudo autoral · Somente LP · Sem implementação ou mídia gerada',10,color=muted);text(996,H-31,f'{n:02}',10,'Medium',accent)
def end():c.showPage()
def sources(x,y,w,compact=False):
 names=[('Escopo do projeto.pdf','Google Drive'),('Reunião de alinhamento','Notion'),('Cronograma de entregas','OneDrive')]
 text(x,y,'Documentos utilizados',14 if not compact else 13,'Medium',accent);y+=25
 for i,(n,p) in enumerate(names):
  box(x,y,w,39 if not compact else 34,'#eaf2ec',7);text(x+11,y+10,str(i+1)+'.',12,'Medium',accent);text(x+31,y+10,n,13 if not compact else 12,'Medium');text(x+w-90,y+10,p,11,color=muted);y+=45 if not compact else 39
 return y

def chat(x,y,w,h,library=True,compact=False):
 box(x,y,w,h,white,16,line);brand(x+20,y+15,19);text(x+170,y+19,'Estúdio Aurora',12,'Medium');text(x+w-126,y+20,'Prévia ilustrativa',11,color=muted);box(x,y+49,w,1,line)
 rail=120 if library else 0
 if library:
  box(x+1,y+50,rail,h-52,'#eaf2ec',8);text(x+13,y+71,'Biblioteca',13,'Medium');text(x+13,y+91,'Arquivos sincronizados',10,color=muted)
  for k,t in enumerate(['Google Drive','Projeto Aurora','Notion','OneDrive','SharePoint']):text(x+13,y+125+k*30,t,11,color=muted)
  para(x+13,y+294,'A conversa usa somente as ferramentas e menções selecionadas na mensagem.',94,10,color=muted)
 xx=x+rail+18; ww=w-rail-36;text(xx,y+63,'Nova conversa',11,color=muted)
 box(xx,y+91,ww,70,'#eaf2ec',8);text(xx+14,y+102,'Todas as ferramentas',11,color=muted);para(xx+14,y+122,'O que ficou definido para a primeira entrega?',ww-28,15,'Medium')
 text(xx,y+179,'Arquivio',14,'Medium',accent);para(xx,y+204,'A primeira entrega inclui o diagnóstico de marca e a proposta de posicionamento.',ww,16,leading=24)
 sy=sources(xx,y+273,ww,True)
 text(xx,sy+3,'Ver mais 2 documentos',11,color=muted)
 if h>510:
  box(xx,sy+30,ww,68,'#f5f7f4',8,line);para(xx+12,sy+41,'O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta',ww-24,12,color=muted);text(xx+12,sy+76,'Todas as ferramentas',11,color=muted)
  text(xx,sy+110,'Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.',10,color=muted)

def desktop(kind,x,y,width):
 global H
 old=H;c.saveState();c.translate(x,old-y-780*width/1440);c.scale(width/1440,width/1440);H=780
 stage=kind=='B';box(0,0,1440,780,dark if stage else bg);brand(54,25,28,stage)
 col=white if stage else ink
 for xx,t in [(402,'Produto'),(495,'Integrações'),(620,'Como funciona'),(775,'Dúvidas')]:text(xx,34,t,14,color=col)
 text(1170,34,'Entrar',14,color=col);pill(1240,20,'Criar conta ↗',144,lime if stage else accent,ink if stage else white,14)
 if not stage:
  text(64,136,'SEU CONHECIMENTO, COM CONTEXTO',12,'Medium',accent)
  para(64,177,'A resposta está<br/>nos arquivos.<br/><font color="#1c6052">Agora você<br/>sabe onde.</font>',470,53,'Display',leading=58)
  para(64,438,'Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.',446,18,color=muted,leading=27)
  pill(64,544,'Começar com o Arquivio →',260,size=16,h=48);text(64,616,'Já tenho uma conta',16,'Medium',accent);text(64,658,'✓ Conexões de leitura · originais preservados',13,color=muted)
  text(576,117,'VEJA A EXPERIÊNCIA',11,'Medium',accent);para(576,138,'Converse com seus documentos. Confira a origem.',788,24,'Display')
  pill(576,191,'Resposta com fontes',178,'#eaf2ec',accent,13,40);pill(762,191,'Com menção @',148,white,accent,13,40);pill(918,191,'Sem evidência suficiente',224,white,accent,13,40)
  chat(576,250,800,437,True)
  box(576,699,800,45,white,8,line);text(594,711,'Buscar arquivos',12,'Medium');text(718,711,'Encontre arquivos e pastas pelo nome em todas as fontes conectadas.',12,color=muted)
  text(576,755,'Prévia da área de consultas do Arquivio. Exemplos fictícios.',12,color=muted)
 else:
  text(505,110,'SEU CONHECIMENTO, COM CONTEXTO',12,'Medium',lime)
  para(269,151,'A resposta está nos arquivos.<br/>Agora você sabe onde.',905,52,'Alt',white,leading=59)
  para(384,289,'Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.',672,18,color='#eaf2ec')
  pill(440,353,'Começar com o Arquivio →',267,lime,ink,16,46);text(741,365,'Já tenho uma conta',16,'Medium',white)
  text(490,413,'✓ Conexões de leitura · originais preservados',13,color='#eaf2ec')
  text(258,461,'Converse com seus documentos. Confira a origem.',24,'Alt',white)
  pill(258,505,'Resposta com fontes',178,lime,ink,13,38);pill(446,505,'Com menção @',148,'#eaf2ec',ink,13,38);pill(604,505,'Sem evidência suficiente',224,'#eaf2ec',ink,13,38)
  box(258,561,924,196,white,16);brand(280,575,18);text(455,579,'Estúdio Aurora · Prévia ilustrativa',12,color=muted)
  para(282,619,'O que ficou definido para a primeira entrega?',416,15,'Medium');para(282,648,'A primeira entrega inclui o diagnóstico de marca e a proposta de posicionamento.',416,16)
  text(754,611,'Documentos utilizados',14,'Medium',accent)
  for k,t in enumerate(['1. Escopo do projeto.pdf · Google Drive','2. Reunião de alinhamento · Notion','3. Cronograma de entregas · OneDrive']):text(754,645+k*25,t,12,color=ink)
  text(282,732,'Prévia da área de consultas do Arquivio. Exemplos fictícios.',11,color=muted)
 c.restoreState();H=old

def mobile(kind,x,y,width):
 global H
 old=H;c.saveState();c.translate(x,old-y-844*width/390);c.scale(width/390,width/390);H=844;stage=kind=='B';box(0,0,390,844,bg);box(0,0,390,443 if stage else 56,dark if stage else bg);brand(16,17,23,stage);box(347,23,20,1,white if stage else ink);box(347,29,20,1,white if stage else ink);box(347,35,20,1,white if stage else ink)
 col=white if stage else ink
 text(16,79,'SEU CONHECIMENTO, COM CONTEXTO',10,'Medium',lime if stage else accent)
 para(16,104,'A resposta está<br/>nos arquivos.<br/>Agora você sabe onde.',355,34,'Alt' if stage else 'Display',col,leading=37)
 para(16,260,'Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.',350,16,color='#eaf2ec' if stage else muted,leading=22)
 pill(16,340,'Começar com o Arquivio →',358,lime if stage else accent,ink if stage else white,15,44);text(16,397,'Já tenho uma conta',14,'Medium',col);text(16,423,'✓ Conexões de leitura · originais preservados',12,color='#eaf2ec' if stage else muted)
 para(16,451,'Converse com seus documentos.<br/>Confira a origem.',356,20,'Alt' if stage else 'Display',leading=24)
 pill(16,501,'Resposta com fontes',169,'#eaf2ec',accent,12,32);pill(195,501,'Com menção @',179,white,accent,12,32);pill(16,541,'Sem evidência suficiente',358,white,accent,12,32)
 box(16,589,358,237,white,12,line);text(28,600,'Estúdio Aurora · Prévia ilustrativa',11,color=muted);text(28,624,'O que ficou definido para a primeira entrega?',13,'Medium')
 para(28,653,'A primeira entrega inclui o diagnóstico de marca e a proposta de posicionamento.',328,16,leading=22);text(28,714,'Documentos utilizados',12,'Medium',accent)
 box(28,739,334,40,'#eaf2ec',6);text(38,750,'1. Escopo do projeto.pdf',12,'Medium');text(38,767,'Google Drive',11,color=muted)
 text(28,797,'Exemplos fictícios.',12,color=muted)
 c.restoreState();H=old

def swatches(x,y,colors,cell=142):
 for i,(name,h) in enumerate(colors):box(x+i*cell,y,cell-12,55,h,8);text(x+i*cell,y+66,name,11,'Medium');text(x+i*cell,y+84,h.upper(),11,color=muted)

# 1
header(1,'FASE DIREÇÃO / SITE-MVP','Uma resposta. O caminho até a fonte.','Duas direções concretas para a LP pública. Marca, copy e interações preservadas. A decisão H2 escolhe a expressão; o produto continua intocado.')
box(48,205,622,398,dark,20);brand(79,236,36,True);text(80,309,'Chat + fontes.',56,'Display',white);text(80,378,'Desde a dobra.',56,'Display',lime)
para(80,471,'Modernizar a presença do Arquivio com o próprio produto no centro: resposta legível, documento identificável e limites de evidência visíveis.',531,19,color=white)
text(712,225,'A / CONTEXTO VIVO',14,'Medium',accent);para(712,260,'Clareza SaaS.<br/>Produto protagonista.',302,31,'Display');para(712,396,'Superfície clara, verde original e sinal lima discreto. Melhor continuidade futura com o app.',299,15,color=muted);pill(712,477,'RECOMENDADA',194,lime,ink,13)
text(712,551,'B / FAROL DE CONHECIMENTO',13,'Medium',accent);para(712,582,'Palco escuro, produto claro. Mais contraste de campanha; maior custo de transição visual.',300,15,color=muted)
text(48,680,'4 referências reais · DOM + pixels · tokens portáteis · estudo vetorial próprio',14,'Medium',accent);end()
#2
header(2,'PESQUISA / OBSERVED','Quatro referências, escolhas diferentes.','Capturadas em 02/10/2026 (America/Manaus). Prints reais, não assets para reutilização. Apps autenticados e citações internas não foram testados.')
refs=[('dust','Dust','dust.tt','Tipo forte + hero dividido. A cena conceitual compete com o chat.'),('glean','Glean Assistant','glean.com/ai-assistant','Produto na dobra. Relevo e cenas devem virar UI legível do Arquivio.'),('claude','Claude Product','claude.com/product/overview','Respiro + interação discreta. Não importar fotos, órbita ou serif proprietária.'),('notebook','Notebook / Gemini Notebook','notebook.google','Fontes como modelo mental. Hero rotativo mostra formatos; não copiar slides/áudio.')]
for i,(sid,name,url,note) in enumerate(refs):
 x=48+(i%2)*500;y=204+(i//2)*227;box(x,y,484,210,white,12,line);c.drawImage(str(D/'screenshots/references'/f'{sid}-hero.png'),x+12,H-y-173,width=260,height=162.5,mask='auto');text(x+287,y+17,name,13,'Medium');para(x+287,y+45,note,181,12,color=muted);para(x+287,y+141,url,181,10,'Medium',accent);c.linkURL('https://'+url,(x+285,H-y-190,x+478,H-y-138),relative=0)
text(48,656,'Perplexity: Cloudflare, excluída. Banners e frames dinâmicos anotados em source/evidence.md.',11,color=muted);end()
#3
header(3,'A / RECOMENDADA / INFERRED','Contexto vivo','Desktop: benefício à esquerda, resposta e documentos à direita. Uma única prévia; todos os três casos continuam disponíveis.')
desktop('A',86,177,908)
text(48,690,'Manrope 650 + IBM Plex Sans · #F5F7F4 / #142B25 / #1C6052 · UI em texto e vetores',12,'Medium',accent)
text(48,713,'Estudo de dobra 1440×780. Faixa Biblioteca/Busca/composer completa segue no contrato; toda copy deve permanecer na implementação.',10,color=muted);end()
#4
header(4,'A / MOBILE E ESTADOS','A fonte continua perto da resposta.','Mobile não vira screenshot do app. Empilhar primeiro o núcleo chat/fontes; Biblioteca e Busca continuam abaixo, com seu conteúdo intacto.')
mobile('A',60,187,214)
text(328,209,'390 × 844 / META DE DOBRA',12,'Medium',accent);para(328,244,'Pergunta → resposta →<br/>documentos utilizados.',660,33,'Display');para(328,342,'CTA primário pleno; link de login permanece. Casos quebram sem truncar. A primeira fonte traz nome e provedor; as demais fontes seguem com rolagem normal.',614,16,color=muted)
box(328,431,320,187,white,12,line);text(350,451,'Com menção @',16,'Medium',accent);para(350,483,'Quais são os prazos previstos neste documento?',273,14,'Medium');para(350,529,'Arquivo: Escopo do projeto.pdf<br/>Resposta e fonte preservadas integralmente no contrato.',273,13,color=muted)
box(670,431,344,187,'#eaf2ec',12);text(692,451,'Sem evidência suficiente',16,'Medium',accent);para(692,488,'Não encontrei evidência nos documentos selecionados para confirmar o orçamento de mídia.',298,15);text(692,587,'Sem inventar fontes, animação ou loading.',11,color=muted)
text(328,640,'13 px para avisos · 16 px para chat · alvo 44 px · foco 3 px',13,'Medium',accent);end()
#5
header(5,'B / ALTERNATIVA / INFERRED','Farol de conhecimento','Um palco verde profundo enquadra o produto claro. Mais presença de campanha; menos proximidade imediata com a superfície clara do app.')
desktop('B',86,177,908)
text(48,690,'Space Grotesk 600 + IBM Plex Sans · #102F27 / #F5F7F4 / #D9F279 · sem hero gradiente',12,'Medium',accent)
text(48,713,'Estudo parcial da dobra. Caso normal e fontes visíveis; figura completa/copy, Biblioteca, Busca e estados continuam abaixo sem cortes.',10,color=muted);end()
#6
header(6,'B / MOBILE E TRADEOFF','Impacto com uma fronteira clara.','O palco pertence à LP. O app futuro herdaria a linguagem do chat claro, não um tema escuro imposto por marketing.')
mobile('B',60,187,214)
text(328,207,'PALETA E TIPO DA ALTERNATIVA',12,'Medium',accent);swatches(328,238,[('Palco','#102f27'),('Texto','#f5f7f4'),('Sinal','#d9f279'),('UI','#ffffff')],169)
para(328,365,'Menos procura.<br/>Mais contexto.',661,39,'Alt');para(328,471,'Força: contraste memorável e uma assinatura própria sem cenários emprestados. Custo: maior altura de hero e tratamento de marca sobre escuro. A meta de fonte na dobra móvel exige composição compacta.',615,16,color=muted)
box(328,582,684,66,'#eaf2ec',10);para(346,596,'Recomendação continua A: melhor equilíbrio entre impacto, leitura de fontes e continuidade com o app.',642,15,'Medium',accent);end()
#7
header(7,'TOKENS / PROPOSTA A','Uma linguagem portátil, por função.','Hexes e famílias abaixo são decisões autorais. Verde original preservado; demais valores propostos, com confiança e origem por token.')
swatches(48,201,[('Fundo','#f5f7f4'),('Tinta','#142b25'),('CTA / marca','#1c6052'),('Fontes','#eaf2ec'),('Sinal','#d9f279'),('Foco','#965b0d')],164)
text(48,329,'MANROPE 650 / DISPLAY',11,'Medium',accent);text(48,363,'A resposta está nos arquivos.',36,'Display');text(48,409,'Agora você sabe onde.',36,'Display',accent)
text(48,470,'IBM PLEX SANS / CORPO E UI',11,'Medium',accent);para(48,501,'Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.',595,18);text(48,570,'4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96',22,'Medium',accent);text(48,612,'Spacing 4px base · Radius 8 / 16 / 24 · Body 16 / 1.55',13,color=muted)
box(704,337,310,309,white,12,line);text(726,358,'Contraste calculado',20,'Display');ratios=json.loads((D/'source/contrast-report.json').read_text())
for k,row in enumerate([ratios[0],ratios[3],ratios[4],ratios[5],ratios[6],ratios[8]]):text(726,404+k*34,row['pair'][:22],12,color=muted);text(932,404+k*34,str(row['ratio'])+':1',12,'Medium',accent)
text(726,617,'11 pares aprovados · sRGB/WCAG',11,'Medium',accent);end()
#8
header(8,'COERÊNCIA / MIGRAÇÃO FUTURA','A LP inaugura. O app decide depois.','Nada muda no app agora. Tokens portáteis permitem uma fase posterior sem acoplar CSS público, auth ou estado de organização.')
layers=[('A1 / IDENTIDADE','--accent #1C6052<br/>--font-display Manrope<br/>--font-body IBM Plex Sans'),('A1 / ESTRUTURA','Type scale fluid<br/>Container 1280px<br/>Espaço de seção 48/80/112px'),('A2 / FALLBACK','Spacing, radius e status<br/>Motion 140/180/240ms<br/>Foco + mono + sombras'),('B + C / SEMÂNTICA','--chat-surface → surface<br/>--source-ink → accent<br/>--signal-lime, extensão LP')]
for i,(t,b) in enumerate(layers):x=48+i*247;box(x,204,232,180,white,12,line);text(x+18,226,t,11,'Medium',accent);para(x+18,263,b,200,15,color=muted)
text(48,420,'MOTION AUTORAL: FEEDBACK PRIMEIRO',12,'Medium',accent)
for i,(t,d) in enumerate([('140 ms','Cor/borda em hover.'),('180 ms','FAQ / troca de caso.'),('240 ms','Reveal inferior opcional.')]):x=48+i*327;box(x,454,312,121,'#eaf2ec',12);text(x+20,472,t,29,'Display',accent);para(x+20,522,d,269,14)
para(48,602,'Reduced-motion: zero delays, transform none, opacity 1. Hero e fontes visíveis no primeiro paint. Sem typewriter, autoplay, parallax de texto ou scroll-jacking.',977,15,'Medium',accent);end()
#9
header(9,'H2 / DECISÃO HUMANA','Aprovar a direção, preservar o contrato.','A execução só começa depois de H2. Este PDF e o DNA são a proposta revisável; nada foi instalado ou implementado no produto.')
box(48,203,619,408,white,12,line);text(72,227,'Preservação vinculante',23,'Display')
items=['Marca arquivio. + Layers3 + verde original.','Todos os CTAs e dois handlers de autenticação.','5 âncoras, navegação desktop/mobile e links legais.','3 casos da prévia, aria-pressed e aria-live polite.','7 FAQ e toda copy comercial, sem preços novos.','Avisos fictícios, de leitura e de acesso compartilhado.','Biblioteca/Busca/composer seguem ilustrativos.','Somente arquivos LP, após H2; app intocado.']
for i,t in enumerate(items):text(73,278+i*37,'✓',15,'Medium',accent);para(99,278+i*37,t,540,14)
text(712,223,'DECISÕES H2',12,'Medium',accent);para(712,258,'A / Contexto vivo<br/>ou<br/>B / Farol de conhecimento',302,25,'Display')
para(712,426,'Aprovar famílias e pesos, paleta, composição desktop/mobile e motion discreto. Slot próprio I-01 é opcional; layout funciona sem ele.',303,15,color=muted)
box(712,567,302,92,'#eaf2ec',12);para(730,584,'Imagem: disponível, não gerar agora.<br/>Vídeo e áudio: indisponíveis sem key; nenhuma fase planejada.',267,13,'Medium',accent)
text(48,690,'Contrato e evidências: DESIGN.md · research.md · source/evidence.md · tokens.css · implementation-handoff.md',11,color=muted);end()
#10
header(10,'RASTREABILIDADE / EVIDÊNCIA','A direção pode ser auditada.','Dados brutos separados de decisões novas. Referências são pesquisa, nunca material de campanha ou código de produto.')
rows=[('REFERÊNCIAS LIVE','source/references/*-desktop.json + DOM','1440×900 / 390×844; URLs finais e timestamps ISO.'),('PIXELS REAIS','screenshots/references/*','Hero, full, mobile e estados restritos; consent banners preservados.'),('MOTION + VOCABULÁRIO','source/motion.json + components.discovered.json','Dust: corpos de keyframes, hooks, estados com diffs e frame strip.'),('LIMITES DA PROVA','source/motion-preview-proof/report.json','53/70 swatches passaram; gaps da pesquisa declarados. Não usar kit Dust na LP.'),('CONTRATO DERIVADO','tokens.css + source/token-contract.report.json','Cada token tem origem/confiança/linha. JSON/Tailwind derivados, sem drift.'),('INTEGRIDADE / ESCOPO','source/preservation-lock.json','Hashes de produto/baseline protegidos. Mudanças limitadas a direction/.')]
for i,(t,p,b) in enumerate(rows):y=202+i*70;box(48,y,984,60,white,8,line);text(67,y+12,t,11,'Medium',accent);text(338,y+10,p,13,'Medium');text(338,y+33,b,12,color=muted)
para(48,640,'Observed = captura real. Provided = baseline/brief. Inferred = proposta autoral para Arquivio. O gate técnico não substitui H2 humano.',973,12,'Medium',accent);end()
c.save()
proof=D/'source/pdf-proof';proof.mkdir(exist_ok=True)
doc=fitz.open(D/'STYLEBOARD.pdf');checks=[]
for i,p in enumerate(doc):
 pix=p.get_pixmap(matrix=fitz.Matrix(1.25,1.25));pix.save(proof/f'page-{i+1:02}.png');checks.append({'page':i+1,'textChars':len(p.get_text()),'width':p.rect.width,'height':p.rect.height})
(D/'source/pdf-report.json').write_text(json.dumps({'pages':len(doc),'textSelectable':all(x['textChars']>300 for x in checks),'checks':checks},indent=2));print('PDF',len(doc),'pages, text selectable, rendered',proof)
