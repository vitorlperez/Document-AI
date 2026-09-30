# M27 — Preparação do dono e tour dos convidados

A preparação da organização (Boas-vindas + Integrações) pertence somente ao dono atual. Admins e membros convidados entram diretamente na conversa e recebem apenas o tour na primeira visita àquela organização, mesmo se o dono ainda não terminou a preparação. Concluir ou pular o tour persiste em `membership.tour_completed_at`; os logins seguintes abrem a conversa sem repetir os fluxos.

A migration `20260930_0026` continua marcando organizações e memberships anteriores como concluídas. Nenhuma migration nova ou reset foi introduzido: convites novos mantêm o default pendente do tour. Os testes de migration provam backfill, defaults e downgrade.

## Correções por item

| Item | Commit | Evidência |
| --- | --- | --- |
| R-1 | `1bfe67b` | Membership atualizada via `populate_existing` e bloqueada antes de cada avanço. Regressão falhou antes para membership antiga; passou depois. A regra final foi restringida ao dono no commit próprio de M27. |
| R-2 | `e22bd82` | AbortController protege carregamento, erros, conclusão e callbacks antigos. `review-check.cjs` segurou a resposta de B, voltou para A e entregou B atrasada: falhou antes, passou depois. |
| F-001 | `53cde38` | Rodapé fixo no celular, com reserva de espaço e safe-area; três ações acessíveis na primeira dobra. |
| F-002 | `20e8dab` | Notice/error descartados junto da conclusão, antes do tour; toast ausente na mesma rota, sem esperar auto-dismiss. |
| F-003 | `2836745` | Limite/scroll do painel empilhado existem antes de M27. A nota duplicada fica oculta abaixo de 1024px; orientação no compositor e nota desktop preservadas. |
| F-004 | `8f76d10` | Navegar tem texto visível e nome acessível coerente no celular. |
| F-005 | `aca6b8e` | Jobs queued/syncing já carregados mostram aviso persistente no painel Biblioteca e compositor, sem depender do toast. |
| F-006 | `f56faf8` | Container compartilhado e foco sem deslocar scroll; x/largura de stepper, título e ações, além de y de stepper/título, iguais entre etapas. |

Cada finding de QA tem causa, arquivos, commit e validação em `TASK/items/F-001..F-006.md`. Não há finding pendente de decisão de produto.

## Verificação fresca

| Comando | Resultado |
| --- | --- |
| Backend `.venv/bin/pytest -q` | 919 passed, 13 skipped, exit 0 |
| Backend `.venv/bin/pytest -q tests/api/test_onboarding.py tests/unit/test_onboarding_migration.py` | 15 passed, exit 0 |
| Backend `.venv/bin/ruff check app/organizations/onboarding.py tests/api/test_onboarding.py` | 0 achados, exit 0 |
| Backend `.venv/bin/ruff check .` | 18 achados, exit 1; idênticos ao checkout base `f659262`, nenhum novo |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npm run lint` | exit 0 |
| Frontend `node --import /tmp/document-ai-onboarding-tools/node_modules/tsx/dist/loader.mjs --test tests/*.test.mjs` | 39 passed, 0 failed, exit 0 |
| Frontend `npm run build` | cinco etapas concluídas, exit 0 |
| `QA_API_URL=http://localhost:8012 QA_APP_URL=http://localhost:5174 NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/browser-check.cjs` | exit 0: 1440×900 e 390×844; captura adicional a 768×1024 |
| Mesmas variáveis + `node artifacts/onboarding/review-check.cjs` | R-1 e R-2 passaram, exit 0 |
| `graphify update .` | exit 0; 5900 nodes, 17209 edges, 340 communities |

`browser-check.cjs` cobre oito cenários: dono com preparação completa e dono que pula preparação/tour, admin convidado que pula o tour e membro convidado que conclui os quatro passos, em ambas as larguras. Todos fazem logout/login e abrem diretamente a conversa. Convites são criados e aceitos pelos handlers reais; a organização dos convidados permanece em welcome/required para o dono. Admins e membros recebem 403 ao tentar avançar sua preparação.

Os testes de API cobrem convites aceitos com preparação pendente ou completa, tour independente, idempotência, isolamento por org/membership, rebaixamento do dono para admin/membro com identity map antigo e persistência entre logins. Antes da mudança de requisito, dois casos de admin convidado falharam: bloqueado na preparação pendente e autorizado a avançar a completa. Depois, os 15 casos passaram.

## Capturas novas

Resultados: `qa/fixed/browser-results.json`. Comparação do lint: `qa/fixed/backend-lint-comparison.json`.

- F-001: `qa/fixed/integrations-first-fold-390.png` (cards carregados e rodapé na primeira dobra).
- F-002: `qa/fixed/tour-1440-1.png` e `tour-390-3.png` (alvos sem toast).
- F-003/F-005: `qa/fixed/chat-390.png`, `chat-768.png`, `chat-1440.png`.
- F-004: `qa/fixed/tour-390-4.png` (Navegar visível).
- F-006: `qa/fixed/welcome-1440.png` e `integrations-1440.png`; também capturadas a 390px.
- Convidados: `qa/fixed/invited-{admin,member}-{tour,second-login}-{1440,390}.png`.
- Revisão: `qa/fixed-R-1.png`, `qa/fixed-R-2.png`.

## Reproduzir

Instale Playwright e tsx fora do repo, em `/tmp/document-ai-onboarding-tools`. Em `backend/`, inicie `QA_API_PORT=8012 QA_APP_URL=http://localhost:5174 PYTHONPATH=. .venv/bin/python ../artifacts/onboarding/qa-server.py`. Em uma cópia temporária de `frontend/` com o mesmo source e dependências, inicie `VITE_API_BASE_URL=http://localhost:8012 npm run dev -- --port 5174`. Rode os dois comandos de navegador acima a partir do repo. Os defaults continuam sendo 8011/5173.

A cópia temporária foi usada porque o Vinext já estava rodando no checkout; esse processo foi preservado. Os servidores isolados foram encerrados após a validação. Os logs dos servidores de QA e o navegador não mostraram erros novos.

## Limites

AuthKit, Google e envio de e-mail usam doubles; o worker não processa documentos externos. A API, as sessões, os convites, a autorização, o progresso, a fila/histórico e o frontend são reais em SQLite temporário. Os 13 testes de PostgreSQL continuam pulados sem `TEST_DATABASE_URL`. O Ruff global ainda tem os 18 achados anteriores. Mudanças alheias e os artefatos anteriores de graphify permaneceram fora dos commits; nenhum push foi solicitado.

Skills: inline [qa-fix-protocol, oc-blackbox, oc-stamp].
