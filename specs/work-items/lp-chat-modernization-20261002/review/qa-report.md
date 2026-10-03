# QA final — Arquivio LP, direção A / Contexto vivo

## Parecer

**PASS — sem blockers P0/P1; 2 findings P2 não bloqueantes.** O preview de produção configurado abre para visitante anônimo com a API real, sem mocks, alerta de sessão ou erros de console. A copy, as ações e as rotas públicas verificadas estão preservadas. Permanecem dois desvios visuais da direção aprovada, registrados em `TASK/items/F-206.md` e `TASK/items/F-207.md`.

**Escopo e base:** branch `design/lp-chat-modernization-20261002`, comparada ao commit `a43dbdd09ae1673adc088b84a4a56b5ea8665f5f` (base `main` no início da revisão). Revisado o diff real de `frontend/app/landing-page.tsx` e `frontend/app/landing.css`, mais assets locais e `frontend/tests/landing-contract.test.mjs`. Nenhuma implementação foi editada durante a revisão.

**URL verificada:** http://127.0.0.1:5181/ — build de produção próprio; Docker em `:3000` não representa este diff. Os screenshots de veredito são [`desktop 1440×900`](evidence/verdict-desktop-1440x900.png) e [`mobile 390×844`](evidence/verdict-mobile-390x844.png). O JSON de captura registra HTTP 200, `/api/session` 200 e nenhuma falha de console, página ou request.

## Preview anônimo e camada 0

A primeira visita foi feita sem mocks nem interceptação. O build com configuração padrão abriu `/`, mas chamou `http://localhost:8000/me` diretamente. O browser em `http://127.0.0.1:5181` recebeu bloqueio CORS (`No Access-Control-Allow-Origin`), falha de request e alerta fixo de sessão. Essa experiência cobre a configuração inicial incorreta e está documentada em `evidence/preview-unmocked.json` e `preview-unmocked-viewports.json`; o alerta sobrepõe conteúdo do composer em desktop, a resposta/fontes em 768 px e os casos no mobile.

Ajuste local de preview, sem alterar auth ou backend: reconstruir com `VITE_API_BASE_URL=/api` e iniciar o servidor de produção com `API_UPSTREAM_URL=http://127.0.0.1:8000`. Assim, `/api/session` é servido pelo BFF same-origin e consulta o backend real. A segunda visita também foi feita sem mocks/interceptação: `/api/session` respondeu `200 null`, sem alertas, erros de console, page errors ou requests falhos. A configuração de produção `/api` e upstream runtime está documentada em `frontend/README.md`. O finding canônico anterior `F-200` já cobre a configuração CORS do preview; não foi duplicado ou reaberto. Nenhuma lógica de autenticação ou backend foi alterada.

O curl do documento e da sessão configurada respondeu HTTP 200. As duas capturas finais usam essa configuração e confirmam visualmente a experiência sem alerta.

## Lente 1 — design/UX, direção A e migração futura

A composição implementa o vocabulário aprovado de superfície clara, verdes do produto, acento lima discreto, Manrope/IBM Plex Sans locais e UI de produto em texto/vetores. Há uma única prévia, os três estados precedem a conversa e a sequência inferior continua presente. O screenshot desktop mantém benefício à esquerda e chat/fontes à direita; no desktop 1440×900 a resposta começa em y434 e a primeira fonte em y575, dentro da meta de y310–520 e y≤620. As fontes e o asset local carregaram por HTTP 200. O CSS e a tipografia ficam limitados à LP; os arquivos compartilhados de marca, globals, layout, auth, legal e aplicação principal não aparecem no diff frente à base.

O styleboard PDF foi aberto e comparado ao contrato escrito. Ele sustenta a superfície clara, Manrope/IBM Plex Sans, foco no chat legível e fontes próximas da resposta; a sua página 4 chama 390×844 de meta de dobra. O cabeçalho do PDF ainda traz “H2 PENDENTE” embora este review siga a aprovação A fornecida no briefing. A implementação alcança a hierarquia e a leitura propostas, mas não a meta de dobra mobile nem o breakpoint desktop em 1024 px.

| Viewport | Grade medida | Resposta (y) | Primeira fonte (y) | Fonte na dobra? |
|---|---:|---:|---:|---|
| 375×667 | 343 px, uma coluna | 873 | 1014 | Não |
| 390×844 | 358 px, uma coluna | 873 | 1014 | Não |
| 768×1024 | 704 px, uma coluna | 852 | 993 | Sim |
| 1024×900 | 960 px, uma coluna | 887 | 1003 | Não |
| 1440×900 | 517.4 / 714.6 px, duas colunas | 434 | 575 | Sim |

As medições são posições no documento e constam em `evidence/preview-configured-unmocked.json`. Não há copy cortada: em mobile a página rola normalmente e mantém fonte de chat em 16 px. O primeiro P2 é uma meta inferida de composição, não perda de conteúdo, mas deixa a evidência principal do produto fora da primeira dobra a 390 px. O ajuste deve recuperar aproximadamente 204 px sem remover copy, fonte, casos ou fontes; isso requer retunar espaçamento vertical e tem custo moderado. O segundo P2 é localizado: alinhar o breakpoint ao contrato `>=1024` exige trocar a regra atual até 1099 px e retunar a grade para 1024; custo baixo a moderado, com validação de legibilidade da coluna estreita. Findings apontam o caminho de correção, sem reduzir corpo abaixo de 16 px nem cortar conteúdo.

## Lente 2 — acessibilidade, responsividade e robustez

- **PASS:** sem overflow horizontal em 375, 390, 768, 1024 e 1440 px; ações visíveis com alvos mínimos de 44 px.
- **PASS:** navegação por Tab alcança ações visíveis, skip link funciona e o foco aparece com anel de 3 px; FAQ e menu móvel abrem com Enter e fecham com Espaço.
- **PASS:** contraste de texto amostrado mínimo 5.7:1, acima de 4.5:1; foco amostrado 5.13:1, acima de 3:1.
- **PASS:** `prefers-reduced-motion` remove transições/reveals sem ocultar conteúdo; mudanças de estado seguem acessíveis por teclado.
- **PASS:** sem JavaScript a copy, os casos e a FAQ nativa continuam disponíveis. Requests locais de imagem/fonte deliberadamente falhados mantêm fallback legível, sem imagem quebrada nem overflow. Fontes e imagem reais são locais e carregaram no build de veredito.
- **PASS no preview corrigido:** zero console errors, page errors e requests falhos. A falha CORS da configuração inicial é relatada acima e não foi mascarada; não persiste com o modo de preview documentado.

## Lente 3 — conteúdo, comportamento e integrações

- **PASS:** sequência literal e ordem das 24 ações desktop do baseline preservadas; em mobile a navegação acrescenta a ação responsiva esperada (25). Todas as âncoras internas chegam a um destino existente.
- **PASS:** os três estados — resposta com fontes, menção `@` e evidência insuficiente — aparecem com texto literal. Estado negativo não mostra documentos; caso `@` mantém `Arquivo: Escopo do projeto.pdf` e escopo Google Drive; default mostra três fontes com provedores e `Ver mais 2 documentos`.
- **PASS:** todas as 87 strings de contrato encontradas no conteúdo renderizado entre os estados e a FAQ. As 7 perguntas e respostas abrem; limites de Owner/Admin, conteúdo SharePoint/permissões, leitura dos originais e conteúdo indexado aparecem. As quatro integrações são Google Drive, OneDrive, Notion e SharePoint, sem integração extra.
- **PASS com limite de prova:** CTAs de cadastro apontam para `${API_BASE}/auth/login?screen_hint=sign-up`; o destino foi testado com a chamada interceptada antes do serviço de auth e isso comprova o wiring do frontend, não o fluxo real de criação de conta. CTAs de login levam a `/login`, cuja tela real carregou. Não houve login autenticado, envio de mensagem, alteração de conta ou uso de dados reais.
- **PASS:** skip link, navegações desktop/mobile, âncoras `#produto`, `#integracoes`, `#como-funciona`, `#perguntas` e páginas `/privacidade` e `/termos` resolvem; ambas as páginas legais responderam 200.

## Findings

**P0: 0 · P1: 0 · P2: 2.** Os P2 são não bloqueantes porque a página mantém conteúdo íntegro e rolagem normal, mas ambos são desvios mensuráveis do contrato visual aprovado.

| ID | Severidade | Evidência | Reprodução | Correção objetiva |
|---|---|---|---|---|
| [F-206](../../../../TASK/items/F-206.md) | P2 / média | `frontend/app/landing.css:293-304` e screenshot mobile; resposta y873, fonte y1014 vs meta y810 | 390×844, visitante anônimo em `/` | Reduzir o ritmo vertical para aproximar resposta/fonte da dobra, preservando toda copy e texto do chat em 16 px ou mais. |
| [F-207](../../../../TASK/items/F-207.md) | P2 / média | `frontend/app/landing.css:253-255`; em browser, uma coluna de 960 px a 1024 | 1024×900, `/` ou `/#produto` | Empilhar até 1023 px e ativar o grid 42/58 aprovado a partir de 1024 px; validar colunas e legibilidade. |

## Diff e preservação

`git diff --name-status a43dbdd -- frontend backend` lista somente `frontend/app/landing-page.tsx` e `frontend/app/landing.css`. Assets locais novos em `frontend/public/landing/` e o teste focado `frontend/tests/landing-contract.test.mjs` são as adições esperadas. `git diff --check` passou. Nenhum caminho app/backend/brand/globals/layout/auth/legal foi alterado.

Os hashes de arquivos protegidos de implementação no preservation lock correspondem à base. O hash de `work-item.md` diverge porque o branch adicionou as seções de implementação/validação em `work-item.md:90-101`; é anotação de execução, não alteração de implementação protegida. Não foi criado finding duplicado: `TASK/items/F-2XX` foi pesquisado; `F-206` e `F-207` são os IDs seguintes livres na faixa do reviewer.

## Comandos e resultado

Todos os comandos abaixo foram executados no diretório `frontend/`, exceto Graphify e diffs.

| Verificação | Resultado |
|---|---|
| `graphify query "How do the Arquivio landing page implementation, its assets, tests and authentication or legal app wiring relate to the approved A/Contexto vivo direction?"` | exit 0 |
| `npx tsc --noEmit -p .` | exit 0 |
| `npm run lint` | exit 0 |
| `node --test tests/landing-contract.test.mjs` | exit 0; 5/5 |
| `npm run build` | exit 0 |
| `VITE_API_BASE_URL=/api npm run build` | exit 0; build usado em `:5181` |
| `API_UPSTREAM_URL=http://127.0.0.1:8000 npm run start -- --port 5181` | servidor de produção iniciou e serviu o build; URL HTTP 200 |
| `node --experimental-strip-types --test tests/*.test.mjs` | exit 1; 79/80; falha em `.tsx` |
| `node --import tsx --test tests/answer-markdown.test.mjs` | exit 0; 9/9 |
| `node --import tsx --test tests/*.test.mjs` | exit 0; 88/88 |
| `git diff --check a43dbdd -- frontend/app/landing-page.tsx frontend/app/landing.css` | exit 0 |
| `curl http://127.0.0.1:5181/` e `curl http://127.0.0.1:5181/api/session` | HTTP 200 para ambos; sessão anônima `null` |

A falha 79/80 foi reproduzida com Node v24.3.0: `ERR_UNKNOWN_FILE_EXTENSION` para `frontend/app/answer-markdown.tsx`. `answer-markdown.test.mjs`, `answer-markdown.tsx`, `tsconfig.json` e `package.json` são idênticos à base `a43dbdd`; o teste comenta o runner `node --import tsx`. Com esse runner, o caso isolado passou 9/9 e a suíte completa 88/88. Portanto, o resultado 79/80 é incompatibilidade da invocação sem o loader `tsx`, preexistente ao diff da LP.

## Evidências

- `evidence/preview-unmocked.json` e `preview-unmocked-viewports.json` — primeira experiência crua, sem mocks, com erro CORS/alerta.
- `evidence/preview-configured-unmocked.json` — cinco viewports, conteúdo geométrico, fonts/assets reais, sessão anônima via API real e zero falhas.
- `evidence/browser-checks.json` — 28 checks funcionais, visuais e de acessibilidade: 26 passam; os dois desvios P2 são os únicos fails.
- `evidence/verdict-screenshots.json` — captura final da URL de preview sem interceptação.
- `evidence/verdict-desktop-1440x900.png` e `verdict-mobile-390x844.png` — um screenshot por viewport de veredito.
