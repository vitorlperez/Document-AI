# Verificação dos ajustes existentes do chat — Missão 22

Resultado: os dois ajustes visuais solicitados já estavam implementados, mas não commitados, no início deste worker. A versão HEAD reproduz a sobreposição de Nova conversa; a árvore local atual não sobrepõe o texto nos cenários testados e mostra ferramentas deduplicadas. Nenhum arquivo de aplicação foi editado, adicionado ao index ou commitado por este worker, respeitando a instrução de não tocar os arquivos sujos do chat/input. Este commit contém somente evidência produzida por este worker; a integração dos arquivos de aplicação permanece pendente.

## Estado inicial e busca da outra missão

- Main local: c092cd1. Lidos git status e git log -20.
- Arquivos de código sujos: frontend/app/product-app.tsx e frontend/app/question-scope.tsx, exatamente os ajustes de toolbar/contador; os seis arquivos de feature mencionados no briefing já não estavam pendentes. Feature de remoção da Biblioteca integrada em aec0e901aaabfdc64c6ab988e584139bda4d9c93; integrações em c092cd1.
- git branch -a: main e feat/integracoes, além de origin/main. Ambas as branches locais apontavam c092cd1.
- Worktree de integrações: /Users/vitorperez/Documents/Document-AI-integracoes, limpa; nenhum ajuste extra.
- Stash 91a2917194359687e755d82723be3bae12c06baf, On main: wip-outra-missao-antes-merge-integracoes, contém somente o ajuste da toolbar no seu diff de código. Autor: vitor perez. Sua alteração já estava aplicada na árvore atual; não é um commit dedicado pronto com ambos os ajustes, portanto nenhum cherry-pick foi feito.
- git log --all --oneline -40 foi consultado para product-app.tsx, question-scope.tsx, chat-workspace.css, question-scope.css, mention-composer.tsx e message-scroller.tsx. Não encontrado commit dedicado com ambos os fixes. chat-history.txt retém a consulta dos dois arquivos principais.
- specs/work-items/chat-available-tools-count.md já existia como arquivo não rastreado e registra a implementação/validação do contador da outra missão, sem screenshots. Não foi alterado.
- preexisting-fixes.patch registra somente o diff já existente, sem edição deste worker.

## Causa e comportamento existentes

- Nova conversa: a versão HEAD usa absolute right-3 top-2 z-10, sem reservar espaço no transcript. A alteração local usa uma barra flex shrink-0 própria, irmã anterior do transcript; a rolagem do transcript não passa por baixo dela.
- Contagem anterior: ready contabiliza pastas. O ajuste local readyTools deduplica providerKey nas pastas prontas selecionadas, com singular/plural. google e google_drive representam a mesma ferramenta.
- Observação de escopo: o ajuste reaproveitado conta ferramentas prontas da seleção atual, conforme o dossiê anterior. O array available do menu também inclui no_compatible_embeddings; logo providers sem embeddings podem constar no menu e não aumentar readyTools. Se o pedido exigir igualdade absoluta com todas as opções do menu em todos os estados, isso ainda requer uma alteração autorizada em question-scope.tsx. Nenhuma alteração foi feita por causa da restrição dos arquivos sujos.

## Evidência visual fresca

- Chrome headless real, frontend dev separado em 3012 (árvore atual) e 3013 (worktree detached de HEAD c092cd1 em /tmp/document-ai-chat-baseline), sem modificar/reiniciar Docker.
- Fixtures somente no browser: sessão, três pastas prontas (google, google_drive e notion) e conversa restaurada com 45 parágrafos e uma fonte clicável. As respostas da API são interceptadas; nenhum dado real é escrito.
- Desktop 1440x900 e mobile 390x900, topo e rolagem em 25/50/75/100%. No desktop, transcript scrollTop; no mobile, workspace-frame scrollTop (1184 a 4793 px, conforme cenário).
- HEAD: uma interseção entre texto e botão no topo de cada viewport. Árvore atual: nenhuma interseção no topo e nas quatro posições de cada viewport. Rects de texto e clipping do transcript registrados em visual-results.json.
- Inspeção humana por view_image: comparação desktop/mobile do topo, versão atual ao final da rolagem e composer antes/depois, confirmando barra separada e rótulo 2 ferramentas disponíveis. Fontes permanecem visíveis ao final da fixture.
- Seletor: 2 opções de providers para três pastas; Google Drive selecionado => 1 ferramenta disponível; seleção vazia => 0 ferramentas disponíveis; todas => 2 ferramentas disponíveis. Nova conversa limpa mensagens/sessionStorage e exibe estado inicial.
- 12 screenshots: before/after-{1440,390}-{top,scrolled,composer}.png neste diretório.

## Comandos e resultados

| Comando | Exit / resultado |
| --- | --- |
| node --import /tmp/document-ai-chat-qa/node_modules/tsx/dist/loader.mjs --test tests/*.test.mjs (cwd frontend) | 0; 30 testes passaram, 0 falhas |
| npm run lint (cwd frontend) | 0; nenhum erro/warning ESLint |
| npx tsc --noEmit (cwd frontend) | 0; sem erros |
| CHAT_TEST_ROOT=/tmp/document-ai-chat-baseline/frontend node artifacts/chat-ui/scope-check.cjs | 1 esperado; baseline renderiza 4 pastas disponíveis, falha na expectativa de 2 ferramentas |
| node artifacts/chat-ui/scope-check.cjs | 0; deduplicação/aliases, seleção, singular/plural, vazio/não pronto, cobertura parcial, retry/loading |
| NODE_PATH=/tmp/document-ai-chat-qa/node_modules node artifacts/chat-ui/visual-check.cjs | 0; reprodução before, zero overlap after, labels/menu/reset; 12 screenshots |
| git diff --check -- frontend/app/product-app.tsx frontend/app/question-scope.tsx | 0 |
| curl localhost:3000/ | HTTP 200; stack Docker preservada |
| graphify update . | 0; AST-only, 5582 nodes / 16147 edges / 326 communities; artefatos do grafo não commitados |

Para repetir visual-check, instalar playwright e tsx em diretório transitório (npm install --prefix /tmp/document-ai-chat-qa playwright tsx --no-audit --no-fund), iniciar o frontend atual em 3012 e baseline c092cd1 em 3013. Script usa Google Chrome local e NODE_PATH para a dependência transitória; nenhuma dependência/package-lock do projeto mudou. scope-check requer apenas as dependências já existentes do frontend.

Os dev servers de QA foram encerrados após a verificação. Nenhum push/deploy. Arquivos/backend de outro pane não tocados. Nenhum claim de alteração do código pelo worker; é uma validação do trabalho anterior.

skills: inline [oc-builder, oc-blackbox, oc-stamp]
