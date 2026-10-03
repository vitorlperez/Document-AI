# COPY — contrato de conteúdo e narrativa chat-first

**Work item:** `lp-chat-modernization-20261002`  
**Fase:** DIREÇÃO/copy; não autoriza implementação  
**Fonte canônica da copy visível:** `frontend/app/landing-page.tsx` em `design/lp-chat-modernization-20261002`  
**Decisão humana aplicada:** preservar literalmente conteúdo comercial, marca, público, CTAs, preços existentes e todos os botões/destinos; modernizar somente a LP/site público  
**Status de texto novo para o build:** nenhum texto novo proposto ou aprovado

## 1. Regra de uso deste contrato

Este documento é a lista fechada de conteúdo da LP modernizada. O redesign pode mudar composição, tipografia, cor, escala, espaçamento, quebras de linha, ordem visual responsiva e motion, mas não pode substituir, resumir, “melhorar”, acrescentar ou remover as palavras inventariadas abaixo. Em particular:

- a grafia, capitalização, acentos, números e pontuação permanecem literais;
- quebras de linha e elementos de ênfase podem ser recompostos visualmente sem alterar a sequência textual;
- ícones de seta, check, busca, envio e expansão são affordances visuais, não caracteres da copy;
- a marca visual continua sendo `arquivio.` — minúscula e com ponto — enquanto o nome em frases continua sendo `Arquivio`;
- a prévia continua explicitamente ilustrativa e fictícia;
- os três casos da prévia, inclusive `Com menção @` e `Sem evidência suficiente`, continuam igualmente descobríveis;
- avisos de indexação, sincronização, leitura, permissões, compartilhamento e uso de IA não podem ser escondidos, suavizados ou convertidos em promessa;
- não existem planos nem preços na LP. Nenhum preço, desconto, gratuidade, período de teste ou comparação de plano pode ser criado.

## 2. Voz da marca e público

### Voz

O Arquivio fala em pt-BR com clareza calma, objetiva e profissional. A voz parte do resultado que a equipe procura — encontrar uma resposta — e imediatamente mostra como conferi-la nos documentos, sem superlativos. Ela trata limites como parte da confiança: diz quando falta evidência, o que já foi indexado, quem pode conectar e quem pode consultar. Não usa urgência artificial, jargão promocional, promessa absoluta, humor excessivo nem linguagem de “IA mágica”.

### Público preservado

A LP continua dirigida a equipes e organizações em pt-BR cujo conhecimento está distribuído em Google Drive, OneDrive, Notion e SharePoint. A linguagem fala com `sua equipe` e `sua organização`; não muda o foco para consumidor individual, desenvolvedor ou um segmento empresarial novo. Owner/Admin conecta as fontes, enquanto a própria copy esclarece que os membros da organização podem consultar o conteúdo sincronizado. Essa definição orienta a hierarquia, mas não cria uma nova frase visível.

## 3. Oferta preservada

### Resultado desejado

O estado final já descrito pela LP é encontrar uma resposta direta no conhecimento da equipe e conseguir voltar aos documentos que a sustentam.

### Ângulos já existentes — todos literais

1. **Resposta + rastreabilidade**  
   `A resposta está nos arquivos. Agora você sabe onde.`  
   `Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.`
2. **Conversa + conferência**  
   `Converse com seus documentos. Confira a origem.`
3. **Menos procura + mais contexto**  
   `Da procura à resposta, sem perder o caminho.`  
   `Menos procura. Mais contexto.`

### Promessa dominante

> Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.

Essa é a frase que deve comandar a hierarquia. Ela contém o resultado e o mecanismo de confiança sem adicionar claim.

### Por que isto / por que agora

- **Por que isto:** a própria LP articula o valor como `Menos procura. Mais contexto.` e organiza o uso em encontrar, delimitar e conferir.
- **Por que agora:** o conteúdo aprovado não contém razão temporal, escassez ou urgência. Não criar uma.

## 4. Narrativa e hierarquia para o redesign chat-first

### 4.1 Mapa de conteúdo aprovado

| Ordem | Bloco preservado | Papel narrativo | Prioridade visual | Contrato estrutural |
| --- | --- | --- | --- | --- |
| 1 | Header | Orientação e entrada | Alta | Marca, quatro âncoras, `Entrar` e `Criar conta`; versões desktop e móvel mantêm os mesmos destinos. |
| 2 | Hero + Produto `#produto` | Promessa e prova no mesmo primeiro contato | Máxima | O H1, a descrição, os dois CTAs e a nota de leitura formam o lado da promessa; a prévia do chat forma o lado da prova. Em desktop, os dois podem ocupar a mesma dobra; em mobile, hero vem imediatamente seguido da prévia, sem seção intermediária. |
| 3 | Integrações `#integracoes` | Delimitar de onde vem o conhecimento | Alta | O número `4` deve aparecer junto da lista fechada Google Drive, OneDrive, Notion e SharePoint e do aviso sobre originais. |
| 4 | Rotina | Explicar o ganho na perspectiva do usuário | Média | Manter a sequência `ENCONTRE` → `DELIMITE` → `CONFIRA`; esta seção é a história de uso, não configuração. |
| 5 | Como funciona `#como-funciona` | Explicar o fluxo operacional e seus limites | Alta | Manter `Conecte` → `Aguarde` → `Pergunte`; a nota de acesso por toda a organização permanece visualmente ligada ao fluxo. |
| 6 | FAQ `#perguntas` | Responder objeções e registrar compromissos | Alta | Sete perguntas e sete respostas literais, sem resumo. Owner/Admin, SharePoint, formatos não indexados, nova sincronização e provedor de IA continuam presentes. |
| 7 | Fechamento | Repetir o resultado e converter | Máxima | `Menos procura. Mais contexto.` + `Criar minha conta`, usando o mesmo `onSignUp`. |
| 8 | Footer | Marca e acesso legal | Base | Marca, assinatura, Privacidade e Termos de uso com destinos preservados. |

### 4.2 Coreografia da demonstração de conversa

1. **Abrir com a prova, não com uma alegação adicional.** A primeira dobra deve deixar visíveis a promessa dominante e parte material da prévia; não inserir headline intermediária.
2. **Manter os três seletores simultaneamente visíveis.** `Resposta com fontes`, `Com menção @` e `Sem evidência suficiente` não podem virar dropdown, paginação sem rótulo ou carousel que corte os títulos. Podem continuar como botões com um transcript expandido por vez, preservando `aria-pressed` e o efeito de troca do baseline.
3. **Default preservado:** `Resposta com fontes`. A pergunta, a resposta e `Documentos utilizados` formam uma cadeia visual única; nome, provedor e contagem adicional não podem ser dissociados da resposta.
4. **Menção como delimitação, não como integração nova.** No segundo caso, `Arquivo: Escopo do projeto.pdf`, o escopo `Google Drive` e o texto do composer com `@` precisam permanecer legíveis. A menção não pode ser reduzida a um ícone.
5. **Ausência de evidência como estado de confiança.** No terceiro caso, a resposta negativa permanece completa e não recebe documentos, selo de sucesso ou texto inventado. O seletor `Sem evidência suficiente` fica tão descobrível quanto o primeiro.
6. **Limites sempre anexos à demonstração.** `Prévia ilustrativa`, `Exemplos fictícios.`, a nota de escopo, `Somente conteúdo já indexado...` e a nota da busca continuam na região da prévia em todos os breakpoints.
7. **Mobile sem perda semântica.** Os três seletores podem quebrar em linhas ou empilhar, mas nenhum fica fora da área rolável sem sinalização; pergunta, resposta e fontes mantêm essa ordem; aviso e legenda não são removidos para economizar altura.
8. **Controles cenográficos não viram novos CTAs.** `Nova conversa`, o composer, `Enviar`, o gatilho de escopo e a busca são partes ilustrativas do produto. O redesign não lhes atribui rota ou ação comercial nova.

### 4.3 Distinção entre as duas sequências de três passos

- **Rotina** é benefício e comportamento: encontrar uma resposta, delimitar o universo consultado e conferir a origem.
- **Como funciona** é operação e expectativa: conectar materiais, esperar sincronização/indexação e só então perguntar.

Elas podem compartilhar ritmo visual, mas não devem ser fundidas mediante corte ou paráfrase, porque o contrato humano exige preservação integral da copy.

## 5. Inventário literal completo

Tudo entre crases é texto final aprovado. Contagens e notas de ocorrência ajudam a implementação, mas não fazem parte da copy.

### 5.1 Marca, skip link e header

- Wordmark renderizado por `Brand`: `arquivio.`
- Skip link: `Pular para o conteúdo`
- Navegação desktop e móvel, na mesma ordem:
  - `Produto`
  - `Integrações`
  - `Como funciona`
  - `Dúvidas`
- Ações desktop e móvel:
  - `Entrar`
  - `Criar conta`

### 5.2 Hero

- Eyebrow: `SEU CONHECIMENTO, COM CONTEXTO`
- H1, em sequência: `A resposta está nos arquivos.` + `Agora você sabe onde.`
- Descrição: `Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.`
- CTA primário: `Começar com o Arquivio`
- CTA secundário: `Já tenho uma conta`
- Nota: `Conexões de leitura · originais preservados`

### 5.3 Produto / prévia de conversa (`#produto`)

#### Abertura e shell

- Eyebrow: `VEJA A EXPERIÊNCIA`
- H2, em sequência: `Converse com seus documentos.` + `Confira a origem.`
- Seletores, nesta ordem:
  - `Resposta com fontes`
  - `Com menção @`
  - `Sem evidência suficiente`
- Marca compacta: `arquivio.`
- Organização fictícia: `Estúdio Aurora`
- Selo: `Prévia ilustrativa`
- Título do painel esquerdo: `Biblioteca`
- Subtítulo do painel esquerdo: `Arquivos sincronizados`
- Breadcrumb: `Biblioteca`
- Fontes/pasta no painel esquerdo, nesta ordem:
  - `Google Drive`
  - `Projeto Aurora`
  - `Notion`
  - `OneDrive`
  - `SharePoint`
- Aviso de escopo: `A conversa usa somente as ferramentas e menções selecionadas na mensagem.`
- Ação ilustrativa da toolbar: `Nova conversa`
- Autor da resposta: `Arquivio`
- Cabeçalho da lista de evidências: `Documentos utilizados`
- Composer: `O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta`
- Contador ilustrativo: `0/1000`
- Ação ilustrativa: `Enviar`
- Ajuda do composer: `Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.`
- Título do painel direito: `Buscar arquivos`
- Explicação da busca: `Encontre arquivos e pastas pelo nome em todas as fontes conectadas.`
- Campo ilustrativo: `Nome de arquivo ou pasta`
- Limite da busca: `A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.`
- Legenda, em duas partes: `Prévia da área de consultas do Arquivio.` + `Exemplos fictícios.`

#### Caso 1 — `Resposta com fontes`

- Escopo, repetido no balão do usuário, autoria e composer: `Todas as ferramentas`
- Pergunta: `O que ficou definido para a primeira entrega?`
- Resposta: `A primeira entrega inclui o diagnóstico de marca e a proposta de posicionamento.`
- Ênfases internas preservadas: `diagnóstico de marca`; `proposta de posicionamento`
- Fontes visíveis, com ordinais gerados `1.`, `2.` e `3.`:
  1. `Escopo do projeto.pdf` — `Google Drive`
  2. `Reunião de alinhamento` — `Notion`
  3. `Cronograma de entregas` — `OneDrive`
- Expansão: `Ver mais 2 documentos`

#### Caso 2 — `Com menção @`

- Escopo, repetido no balão do usuário, autoria e composer: `Google Drive`
- Pergunta: `Quais são os prazos previstos neste documento?`
- Menção em linha própria: `Arquivo: Escopo do projeto.pdf`
- Resposta: `O documento prevê o diagnóstico de marca na primeira etapa e a proposta de posicionamento na etapa seguinte.`
- Ênfases internas preservadas: `diagnóstico de marca`; `proposta de posicionamento`
- Fonte visível, com ordinal gerado `1.`: `Escopo do projeto.pdf` — `Google Drive`

#### Caso 3 — `Sem evidência suficiente`

- Escopo, repetido no balão do usuário, autoria e composer: `Notion`
- Pergunta: `Qual foi o orçamento aprovado para mídia?`
- Resposta: `Não encontrei evidência nos documentos selecionados para confirmar o orçamento de mídia.`
- Fontes: nenhuma. Não renderizar `Documentos utilizados`, documento substituto ou contagem adicional nesse estado.

### 5.4 Integrações (`#integracoes`)

- Eyebrow: `INTEGRAÇÕES DISPONÍVEIS`
- H2, em sequência: `4 fontes.` + `1 lugar para perguntar.`
- Apoio: `Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas.`
- Lista fechada, nesta ordem:
  - `Google Drive`
  - `OneDrive`
  - `Notion`
  - `SharePoint`

### 5.5 Rotina

- Eyebrow: `O QUE MUDA NA ROTINA`
- H2, em sequência: `Da procura à resposta,` + `sem perder o caminho.`
- Introdução: `O conhecimento da equipe já está nos documentos. O Arquivio ajuda a encontrar o trecho certo e a voltar à fonte sempre que você precisar de mais detalhes.`
- Passo 1:
  - Marcador: `01 / ENCONTRE`
  - Título: `Pergunte como você perguntaria a um colega.`
  - Corpo: `Recupere decisões, entregas e informações registradas sem abrir cada arquivo por conta própria.`
- Passo 2:
  - Marcador: `02 / DELIMITE`
  - Título: `Escolha onde buscar.`
  - Corpo: `Consulte todo o conteúdo indexado ou restrinja a pergunta a uma ferramenta ou pasta específica.`
- Passo 3:
  - Marcador: `03 / CONFIRA`
  - Título: `Volte aos documentos.`
  - Corpo: `Veja as fontes apresentadas com a resposta e abra os originais para verificar o contexto completo.`

### 5.6 Como funciona (`#como-funciona`)

- Eyebrow: `COMO FUNCIONA`
- H2, em sequência: `Seus arquivos continuam onde estão.` + `As respostas ficam mais perto.`
- Passo 1:
  - Marcador: `01`
  - Título: `Conecte as fontes`
  - Corpo: `Escolha materiais compartilháveis no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura e preservam os originais.`
- Passo 2:
  - Marcador: `02`
  - Título: `Aguarde a sincronização`
  - Corpo: `O Arquivio processa o conteúdo selecionado em segundo plano. A consulta considera o que já foi sincronizado e indexado.`
- Passo 3:
  - Marcador: `03`
  - Título: `Pergunte com contexto`
  - Corpo: `Defina o escopo, faça sua pergunta e confira os documentos que sustentam a resposta.`
- Aviso de compartilhamento: `Todos na organização podem consultar o conteúdo sincronizado. Selecione apenas materiais compartilháveis com a equipe.`

### 5.7 FAQ (`#perguntas`)

- Eyebrow: `ANTES DE COMEÇAR`
- H2, em sequência: `O que você` + `precisa saber.`

1. Pergunta: `Quais ferramentas posso conectar?`  
   Resposta: `Google Drive, OneDrive, Notion e SharePoint. Somente Owner/Admin da organização no Arquivio pode conectar fontes. No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso.`
2. Pergunta: `O Arquivio altera meus arquivos?`  
   Resposta: `Não. Os originais continuam no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura.`
3. Pergunta: `Quem pode consultar os documentos?`  
   Resposta: `Todos os membros da organização podem consultar o conteúdo sincronizado. O Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe.`
4. Pergunta: `E se faltar informação?`  
   Resposta: `O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta.`
5. Pergunta: `Que conteúdo é compatível?`  
   Resposta: `Documentos Google, PDFs com texto, DOCX, páginas do Notion e Markdown. Imagens escaneadas, planilhas e apresentações ainda não são indexadas.`
6. Pergunta: `Quando os documentos ficam disponíveis?`  
   Resposta: `Depois da sincronização e do processamento em segundo plano. Alterações nos originais exigem uma nova sincronização.`
7. Pergunta: `Como a IA usa o conteúdo?`  
   Resposta: `O texto necessário para busca e resposta é processado pelo provedor de IA configurado. Confira se esse uso atende às políticas da sua organização.`

### 5.8 Fechamento

- Eyebrow: `COMECE PELOS SEUS DOCUMENTOS`
- H2, em sequência: `Menos procura.` + `Mais contexto.`
- CTA: `Criar minha conta`

### 5.9 Footer

- Wordmark: `arquivio.`
- Assinatura: `Conhecimento que encontra o seu contexto.`
- Links:
  - `Privacidade`
  - `Termos de uso`

### 5.10 Nomes acessíveis existentes

Estes textos não são todos visuais, mas fazem parte do contrato de linguagem e acessibilidade da LP:

- Marca no header: `Arquivio, início`
- Navegação desktop: `Navegação principal`
- Menu mobile: `Abrir navegação`
- Navegação mobile: `Navegação móvel`
- Grupo de casos: `Escolha um exemplo da demonstração`
- Painel esquerdo: `Biblioteca ilustrativa`
- Região central: `Exemplo de conversa com documentos`
- Lista de fontes: `Documentos utilizados`
- Painel direito: `Busca de arquivos ilustrativa`
- Lista de integrações: `Ferramentas que você pode conectar`
- Marca no footer: `Arquivio, voltar ao início`
- Navegação legal: `Informações legais`

## 6. Contrato de ações, rotas e estados

| Texto/elemento | Ocorrência | Destino ou efeito que deve permanecer |
| --- | --- | --- |
| `Pular para o conteúdo` | Topo | `href="#landing-main"` |
| `arquivio.` | Header e footer | `href="#landing-main"` |
| `Produto` | Nav desktop e móvel | `href="#produto"` |
| `Integrações` | Nav desktop e móvel | `href="#integracoes"` |
| `Como funciona` | Nav desktop e móvel | `href="#como-funciona"` |
| `Dúvidas` | Nav desktop e móvel | `href="#perguntas"` |
| `Entrar` | Header desktop e menu móvel | `onLogin` → `router.push("/login")` |
| `Criar conta` | Header desktop e menu móvel | `onSignUp` → `${API_BASE}/auth/login?screen_hint=sign-up` via `window.location.assign` |
| `Começar com o Arquivio` | Hero | Mesmo `onSignUp` |
| `Já tenho uma conta` | Hero | Mesmo `onLogin` → `/login` |
| Três seletores da prévia | Produto | Botões com `aria-pressed`; mudam somente `activeCase` local |
| Sete perguntas | FAQ | `<details>/<summary>`; expandem/recolhem a resposta correspondente |
| `Criar minha conta` | Fechamento | Mesmo `onSignUp` |
| `Privacidade` | Footer | `href="/privacidade"` |
| `Termos de uso` | Footer | `href="/termos"` |
| Menu mobile | Header | `<details>/<summary aria-label="Abrir navegação">` |

O componente continua recebendo exatamente `LandingPage({ onLogin, onSignUp })`. A copy não autoriza alterar auth, criar novo destino, transformar CTA em âncora alternativa ou implementar ação nos controles ilustrativos.

## 7. Itens, preços e CTA concreto

- **Itens comerciais / planos:** não existem.
- **Preços:** não existem; não há valor a exibir nem `[TO CONFIRM]` a preencher.
- **Horário / localização:** não se aplica a este produto digital e não deve ser criado.
- **CTA primário real:** criação de conta pelo handler `onSignUp`, que encaminha a `${API_BASE}/auth/login?screen_hint=sign-up`.
- **CTA de acesso real:** `onLogin`, que encaminha a `/login`.
- **Links legais reais:** `/privacidade` e `/termos`.

## 8. Copy opcional não aprovada

Nenhuma. Este contrato não propõe alternativas de headline, subheadline, CTA, labels ou microcopy. Qualquer frase futura deve passar por nova aprovação humana e não pode entrar no build desta modernização por inferência.

## 9. Rastreabilidade

- Conteúdo literal e estados: `frontend/app/landing-page.tsx:14-193`
- Wordmark: `frontend/app/brand.tsx:5-6`
- Wiring de auth/LP: `frontend/app/product-app.tsx:87-91`
- Decisão de preservação: `specs/work-items/lp-chat-modernization-20261002/brief-baseline.md:7-11`
- Inventário/destinos do baseline: `specs/work-items/lp-chat-modernization-20261002/brief-baseline.md:37-69`
- Gate e critérios: `specs/work-items/lp-chat-modernization-20261002/work-item.md:1-20,39-48`
