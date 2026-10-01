# F-007 — Evidência local de correção

Executor: pane-311. Data: 2026-10-01. Branch compartilhada: main.
skills: inline [oc-builder, oc-blackbox, oc-stamp]

## Causa e alteração

O seletor descendente `.landing-source-row svg:last-child` também encontrava o SVG
que é último filho do span `.provider-logo`. A regra mobile aplicava `display: none`
aos quatro logos. A reprodução mostrou todos com dimensões 0×0 em 320, 390 e 720;
768 e 1440 já funcionavam. A única alteração de produto é adicionar `>` à regra
mobile, restringindo-a ao chevron filho direto em `frontend/app/landing.css:196`.

Não houve alteração de markup, grid, onboarding, backend, dados ou credenciais.
O finding existente foi reivindicado pelo executor e encerrado após evidências;
não foi aberto achado duplicado. Os avisos baixos de onboarding ficam fora do escopo.

## Verificação fresca

| Comando | Exit | Resultado |
| --- | --- | --- |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:3000 QA_LABEL=before-container node TASK/evidence/f007/landing-check.cjs` | 1 | Regressão reproduzida; 12 logos ocultos em 320/390/720 |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:5173 QA_LABEL=after-host node TASK/evidence/f007/landing-check.cjs` | 0 | 5 larguras; 20 logos visíveis; sem overflow/erros |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:3000 QA_LABEL=after-container node TASK/evidence/f007/landing-check.cjs` | 0 | Mesmos checks e capturas reais do container |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:5173 QA_OUTPUT=TASK/evidence/f007/onboarding-host-results.json node artifacts/onboarding/tool-cards-check.cjs` | 0 | 16 casos e 7 interações; zero overflow/erros |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:3000 QA_OUTPUT=TASK/evidence/f007/onboarding-container-results.json node artifacts/onboarding/tool-cards-check.cjs` | 0 | 16 casos e 7 interações; zero overflow/erros |
| `cd frontend && npx tsc --noEmit` | 0 | Sem erros |
| `cd frontend && npx eslint app/landing-page.tsx app/provider-logo.tsx` | 0 | Sem erros/avisos |
| `cd frontend && node --import tsx --test tests/*.test.mjs` | 0 | 42 passed, 0 failed |
| `docker compose build frontend && docker compose up -d --no-deps frontend` | 0 | Somente frontend local reconstruído/recriado |
| `graphify update .` | 0 | AST atualizado: 6089 nós, 17673 arestas, 367 comunidades |
| `node --check TASK/evidence/f007/landing-check.cjs` | 0 | Script válido |
| `git diff --check` | 0 | Sem erros de whitespace |

| Largura | Logo SVG | Chevron | Organização das fontes | scrollWidth |
| --- | --- | --- | --- | --- |
| 320 | 4 visíveis, 18×18 | 4 ocultos | Grid de 2 colunas | 320 |
| 390 | 4 visíveis, 18×18 | 4 ocultos | Grid de 2 colunas | 390 |
| 720 | 4 visíveis, 18×18 | 4 ocultos | Grid de 2 colunas | 720 |
| 768 | 4 visíveis, 22×22 | 4 visíveis | Grid de 4 colunas | 768 |
| 1440 | 4 visíveis, 22×22 | 4 visíveis | Sidebar flex | 1440 |

Os JSONs `before-container-results.json`, `after-host-results.json` e
`after-container-results.json` contêm as medidas de cada fonte, do grid e da página.
O teste confere também overflow de cada linha e ausência de erros de página.

## Capturas reais para conferência

| Viewport | Fontes | Prévia completa | Página inteira |
| --- | --- | --- | --- |
| 320 | [Fontes](after-container-sources-320.png) | [Prévia](after-container-preview-320.png) | [LP](after-container-full-320.png) |
| 390 | [Fontes](after-container-sources-390.png) | [Prévia](after-container-preview-390.png) | [LP](after-container-full-390.png) |
| 720 | [Fontes](after-container-sources-720.png) | [Prévia](after-container-preview-720.png) | [LP](after-container-full-720.png) |
| 768 | [Fontes](after-container-sources-768.png) | [Prévia](after-container-preview-768.png) | [LP](after-container-full-768.png) |
| 1440 | [Fontes](after-container-sources-1440.png) | [Prévia](after-container-preview-1440.png) | [LP](after-container-full-1440.png) |

Comparação anterior: [390 antes](before-container-sources-390.png).
Onboarding conectado: [390](onboarding-390.png) e [1440](onboarding-1440.png).
As capturas vêm de Playwright/Chrome headless contra o frontend local real.
As cinco capturas das fontes e a prévia estreita foram inspecionadas visualmente.
Para onboarding, a cópia temporária `/tmp/f007-tool-cards-with-captures.cjs` adiciona
somente screenshots antes das interações; a cópia também passou nos 16 casos/7 interações.
O script original não foi alterado e passou separadamente em cada ambiente.
Todos os endpoints de autenticação/contas usados nos testes são fixtures locais.

## Host/container e preservação

`environment.json` comprova CSS host/container idêntico (SHA256 registrado), frontend
recriado, seis outros containers com mesmos IDs/imagens, e volume PostgreSQL igual.
HTTP da LP: 200; API `/health/live`: 200; healthcheck Docker da API: healthy.
A sondagem inicial de `/health` retornou 404 porque o endpoint real é `/health/live`;
a consulta do healthcheck do container confirmou a rota correta.
Sem push, deploy externo ou mutações de contas. Não foi executado build de produção;
o build local Docker usa o servidor dev previsto no Dockerfile do projeto.
Os artefatos do grafo já estavam sujos ao receber a tarefa e ficam fora do commit.
