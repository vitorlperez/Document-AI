# Microcopy e invariantes de QA — LP Arquivio

Este checklist transforma `COPY.md` em critérios verificáveis para o build futuro. Ele não autoriza implementação nesta fase.

## 1. Regra de comparação literal

- Comparar texto normalizado apenas quanto a espaços criados por layout e quebras de linha.
- Não normalizar palavras, acentos, caixa, pontuação, barras, arroba, ponto médio ou números.
- Elementos visuais (`ArrowRight`, `ArrowUpRight`, `Check`, chevrons e demais SVGs) não entram na comparação textual.
- Tags de ênfase podem mudar, mas os fragmentos destacados e a ordem das palavras devem permanecer.
- Toda string de `frontend/app/landing-page.tsx:14-193` inventariada em `COPY.md` deve continuar representada; nenhuma string comercial nova pode aparecer sem aprovação.

## 2. Invariantes críticos de microcopy

### MC-01 — Marca

- [ ] O wordmark visível no header, na prévia e no footer é `arquivio.`.
- [ ] Em frase/autoria, o nome é `Arquivio`.
- [ ] O ponto final da marca não desaparece nem muda de posição.

### MC-02 — Promessa de abertura

- [ ] O H1 contém, nessa ordem, `A resposta está nos arquivos.` e `Agora você sabe onde.`.
- [ ] A descrição é exatamente `Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.`.
- [ ] A nota é exatamente `Conexões de leitura · originais preservados`, incluindo o ponto médio `·`.
- [ ] Não há número, superlativo, prova social ou promessa temporal anexada ao hero.

### MC-03 — CTAs

- [ ] Header desktop: `Entrar` e `Criar conta`.
- [ ] Menu móvel: `Entrar` e `Criar conta`.
- [ ] Hero: `Começar com o Arquivio` e `Já tenho uma conta`.
- [ ] Fechamento: `Criar minha conta`.
- [ ] Setas visuais não foram incorporadas ao valor textual/acessível do CTA como caractere adicional.

### MC-04 — Três casos da demonstração

- [ ] Há exatamente três seletores e todos ficam simultaneamente descobríveis: `Resposta com fontes`, `Com menção @`, `Sem evidência suficiente`.
- [ ] A ordem dos casos é preservada.
- [ ] O estado inicial é `Resposta com fontes`.
- [ ] Cada seletor continua sendo botão e expõe `aria-pressed` coerente.
- [ ] A região atualizada continua anunciável com `aria-live="polite"` ou equivalente semântico aprovado.
- [ ] Mobile não converte os casos em dropdown sem rótulos persistentes nem corta `@`/`Sem evidência suficiente`.

### MC-05 — Caso com fontes

- [ ] Escopo: `Todas as ferramentas`.
- [ ] Pergunta: `O que ficou definido para a primeira entrega?`.
- [ ] Resposta: `A primeira entrega inclui o diagnóstico de marca e a proposta de posicionamento.`.
- [ ] A seção `Documentos utilizados` contém, nessa ordem:
  1. `Escopo do projeto.pdf` — `Google Drive`
  2. `Reunião de alinhamento` — `Notion`
  3. `Cronograma de entregas` — `OneDrive`
- [ ] O complemento é `Ver mais 2 documentos`.

### MC-06 — Caso com menção

- [ ] Seletor: `Com menção @`.
- [ ] Escopo: `Google Drive`.
- [ ] Pergunta: `Quais são os prazos previstos neste documento?`.
- [ ] Menção visível, não apenas ícone: `Arquivo: Escopo do projeto.pdf`.
- [ ] Resposta: `O documento prevê o diagnóstico de marca na primeira etapa e a proposta de posicionamento na etapa seguinte.`.
- [ ] Fonte: `Escopo do projeto.pdf` — `Google Drive`.
- [ ] O composer mantém `Digite @ para mencionar um arquivo ou pasta` e a ajuda mantém `@ menciona arquivos e pastas; / abre comandos.`.

### MC-07 — Caso sem evidência

- [ ] Seletor: `Sem evidência suficiente`.
- [ ] Escopo: `Notion`.
- [ ] Pergunta: `Qual foi o orçamento aprovado para mídia?`.
- [ ] Resposta: `Não encontrei evidência nos documentos selecionados para confirmar o orçamento de mídia.`.
- [ ] Não existe bloco `Documentos utilizados`, fonte, ordinal, contagem adicional ou selo de sucesso nesse estado.
- [ ] A resposta não é substituída por mensagem de erro genérica.

### MC-08 — Enquadramento ilustrativo

- [ ] `Estúdio Aurora` continua identificado apenas dentro da prévia.
- [ ] `Prévia ilustrativa` fica visível em todos os casos.
- [ ] A legenda mantém `Prévia da área de consultas do Arquivio.` e `Exemplos fictícios.`.
- [ ] Nenhum elemento trata a organização, os arquivos, as respostas ou os resultados como caso real/depoimento.

### MC-09 — Escopo, indexação e busca

- [ ] Aviso: `A conversa usa somente as ferramentas e menções selecionadas na mensagem.`.
- [ ] Ajuda: `Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.`.
- [ ] Busca: `Encontre arquivos e pastas pelo nome em todas as fontes conectadas.`.
- [ ] Limite: `A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.`.
- [ ] Os avisos permanecem legíveis e próximos dos controles ilustrados, inclusive em 375 px.

### MC-10 — Integrações

- [ ] Headline: `4 fontes.` + `1 lugar para perguntar.`.
- [ ] Há exatamente quatro nomes comerciais na lista: `Google Drive`, `OneDrive`, `Notion`, `SharePoint`.
- [ ] A ordem da lista é preservada.
- [ ] O texto `Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas.` permanece completo.
- [ ] Não há card, logo ou claim de GitHub, Airtable ou Microsoft Teams como conector independente.

### MC-11 — Rotina e processo não se confundem

- [ ] Rotina contém `01 / ENCONTRE`, `02 / DELIMITE`, `03 / CONFIRA`, com os três títulos e corpos literais de `COPY.md` §5.5.
- [ ] Como funciona contém `01`/`Conecte as fontes`, `02`/`Aguarde a sincronização`, `03`/`Pergunte com contexto`, com os três corpos literais de `COPY.md` §5.6.
- [ ] Nenhuma das duas sequências foi eliminada, resumida ou fundida mediante perda de texto.
- [ ] `Todos na organização podem consultar o conteúdo sincronizado. Selecione apenas materiais compartilháveis com a equipe.` continua visível fora do accordion de FAQ.

### MC-12 — FAQ regulatória/operacional

- [ ] Existem exatamente sete `<details>/<summary>` na ordem abaixo.
- [ ] Cada resposta é literal e integral, incluindo a segunda frase quando houver.

1. `Quais ferramentas posso conectar?`  
   `Google Drive, OneDrive, Notion e SharePoint. Somente Owner/Admin da organização no Arquivio pode conectar fontes. No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso.`
2. `O Arquivio altera meus arquivos?`  
   `Não. Os originais continuam no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura.`
3. `Quem pode consultar os documentos?`  
   `Todos os membros da organização podem consultar o conteúdo sincronizado. O Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe.`
4. `E se faltar informação?`  
   `O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta.`
5. `Que conteúdo é compatível?`  
   `Documentos Google, PDFs com texto, DOCX, páginas do Notion e Markdown. Imagens escaneadas, planilhas e apresentações ainda não são indexadas.`
6. `Quando os documentos ficam disponíveis?`  
   `Depois da sincronização e do processamento em segundo plano. Alterações nos originais exigem uma nova sincronização.`
7. `Como a IA usa o conteúdo?`  
   `O texto necessário para busca e resposta é processado pelo provedor de IA configurado. Confira se esse uso atende às políticas da sua organização.`

### MC-13 — Ausências obrigatórias

- [ ] Não há preço, moeda, plano, desconto, trial ou gratuidade.
- [ ] Não há claim de integração adicional.
- [ ] Não há claim de OCR, planilha ou apresentação indexada.
- [ ] Não há claim de permissões originais reproduzidas.
- [ ] Não há claim de sincronização em tempo real.
- [ ] Não há claim de segurança/compliance novo.
- [ ] Não há urgência ou escassez.

## 3. Invariantes de ação e destino

### ACT-01 — Âncoras públicas

- [ ] Skip link → `#landing-main`.
- [ ] Marca do header → `#landing-main`.
- [ ] `Produto` → `#produto`.
- [ ] `Integrações` → `#integracoes`.
- [ ] `Como funciona` → `#como-funciona`.
- [ ] `Dúvidas` → `#perguntas`.
- [ ] Marca do footer → `#landing-main`.

### ACT-02 — Auth

- [ ] `Entrar` (header e mobile) e `Já tenho uma conta` chamam `onLogin` e chegam a `/login`.
- [ ] `Criar conta` (header e mobile), `Começar com o Arquivio` e `Criar minha conta` chamam o mesmo `onSignUp`.
- [ ] `onSignUp` mantém `${API_BASE}/auth/login?screen_hint=sign-up` via `window.location.assign`.
- [ ] `LandingPage({ onLogin, onSignUp })` mantém exatamente os dois handlers do contrato.

### ACT-03 — Legal e controles locais

- [ ] `Privacidade` → `/privacidade`.
- [ ] `Termos de uso` → `/termos`.
- [ ] Os três casos alteram apenas o estado local da prévia.
- [ ] As sete perguntas apenas expandem/recolhem seus conteúdos.
- [ ] O menu mobile abre/fecha a navegação.
- [ ] `Nova conversa`, composer, `Enviar` e busca continuam ilustrativos e não ganham destino novo.

## 4. Invariantes acessíveis

- [ ] `Arquivio, início`
- [ ] `Navegação principal`
- [ ] `Abrir navegação`
- [ ] `Navegação móvel`
- [ ] `Escolha um exemplo da demonstração`
- [ ] `Biblioteca ilustrativa`
- [ ] `Exemplo de conversa com documentos`
- [ ] `Documentos utilizados`
- [ ] `Busca de arquivos ilustrativa`
- [ ] `Ferramentas que você pode conectar`
- [ ] `Arquivio, voltar ao início`
- [ ] `Informações legais`
- [ ] Foco visível existe para todos os links, botões e summaries.
- [ ] `prefers-reduced-motion` continua eliminando transições/animações não essenciais.

## 5. Invariantes responsivos e de hierarquia

- [ ] Em 1440 px, a promessa e uma porção informativa da prévia de conversa aparecem na primeira dobra.
- [ ] Em 375/390 px, a prévia segue imediatamente o hero; nenhum bloco comercial se interpõe.
- [ ] Em 375, 768, 1024 e 1440 px não há overflow horizontal.
- [ ] Os três seletores da prévia, a menção e o estado sem evidência são descobríveis sem depender de hover.
- [ ] A lista de fontes permanece associada à resposta correspondente.
- [ ] Avisos e permissões não ficam apenas em tooltip, texto truncado ou interação hover-only.
- [ ] A ordem semântica continua coerente mesmo que a composição desktop use colunas.

## 6. Critérios Given/When/Then para validação futura

1. **Dado** um visitante anônimo em `/`, **quando** a LP carrega, **então** o hero exibe a promessa literal, a prévia é enquadrada como fictícia e os três casos ficam descobríveis.
2. **Dado** o caso default, **quando** `Resposta com fontes` está pressionado, **então** aparecem a pergunta, a resposta, três fontes e `Ver mais 2 documentos` exatamente como contratados.
3. **Dado** o caso de menção, **quando** `Com menção @` é acionado, **então** `Arquivo: Escopo do projeto.pdf` e o escopo `Google Drive` ficam visíveis.
4. **Dado** o caso sem evidência, **quando** `Sem evidência suficiente` é acionado, **então** aparece a resposta negativa literal e não aparece lista de documentos.
5. **Dado** qualquer CTA de cadastro, **quando** é acionado, **então** usa `onSignUp` e chega a `${API_BASE}/auth/login?screen_hint=sign-up`.
6. **Dado** qualquer CTA de entrada, **quando** é acionado, **então** usa `onLogin` e chega a `/login`.
7. **Dado** o FAQ, **quando** cada item é expandido, **então** a resposta integral e literal correspondente fica disponível.
8. **Dado** viewport de 375, 768, 1024 ou 1440 px, **quando** a página é percorrida, **então** nenhuma copy, aviso ou ação obrigatória é cortada, omitida ou causa overflow horizontal.
9. **Dado** um usuário com redução de movimento ativa, **quando** estados e accordions mudam, **então** a experiência não depende de animação para revelar conteúdo.
10. **Dado** o DOM final da LP, **quando** sua copy é comparada ao inventário de `COPY.md`, **então** não há string comercial nova, preço ou integração adicional.

## 7. Evidência baseline para comparação

- DOM e destinos observados: `specs/work-items/lp-chat-modernization-20261002/baseline/baseline-dom.json`
- Capturas dos três estados: `specs/work-items/lp-chat-modernization-20261002/baseline/desktop-02-demo-case-{1,2,3}.png` e `mobile-02-demo-case-{1,2,3}.png`
- Menu/FAQ: `baseline/mobile-04-menu-open.png`, `baseline/desktop-03-faq-open.png`, `baseline/mobile-03-faq-open.png`
- Fonte literal: `frontend/app/landing-page.tsx:14-193`
- Wiring: `frontend/app/product-app.tsx:87-91`

