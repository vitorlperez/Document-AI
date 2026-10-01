# chat-available-tools-count - Contagem de ferramentas disponíveis no compositor

**Status:** done — escopo aprovado pelo pedido do usuário em 2026-09-29; gate independente aprovado, sem findings bloqueantes.

## Source and outcome

- Source specification: `specs/001-mvp-document-intelligence.md` F4; `specs/adr/ADR-0007-indexed-question-scopes.md`; `specs/work-items/chat-composer-context.md`.
- User outcome: o contador junto ao seletor mostra ferramentas disponíveis, deduplicadas por provider normalizado, com pelo menos uma pasta pronta na seleção atual.
- Non-goals: alterar seleção, recuperação, API, indexação, autorização ou política de fontes desconectadas. Cobertura parcial continua contando pastas.

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |
| Deduplicar os providers das pastas prontas e corrigir singular/plural | Pedido do usuário / implementação | Aprovada | Identidade de ferramenta já definida em ADR-0007 |

## Ready checklist

- [x] Acceptance criteria written in Given/When/Then form.
- [x] Owning module: compositor frontend; sem impacto de API/dados; estados existentes preservados.
- [x] Sem alteração de autorização, tenant ou workspace-folder.
- [x] Contagem linear local; sem nova telemetria necessária.
- [x] Sem novas decisões protegidas: mantém identidade normalizada e elegibilidade existentes.

## Ownership

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | Ready checklist and test matrix |
| Implementation owner | `frontend/app/question-scope.tsx`, este dossiê | Contagem deduplicada e rótulo |
| Test engineer | Verificação transitória por renderização do componente | Fixtures de múltiplas pastas/providers e estados negativos |
| Feature validator | Read-only | Independent gate decision |

## Acceptance criteria and test matrix

| Criterion | Test layer | Evidence |
| --- | --- | --- |
| Várias pastas prontas de duas ferramentas / todas selecionadas / exibir 2 ferramentas disponíveis, incluindo normalização google/google_drive | Renderização React | Passou: quatro pastas prontas, dois providers normalizados |
| Uma ferramenta selecionada / várias pastas prontas / exibir 1 ferramenta disponível | Renderização React | Passou: seleção Google Drive |
| Nenhuma pasta pronta / renderizar / exibir 0 ferramentas disponíveis e aviso existente | Renderização React | Passou: vazio, seleção vazia, somente pendente |
| Pasta pendente ou sem embedding / renderizar / não aumentar ferramentas prontas; manter aviso de cobertura em pastas e erro/retry | Renderização React | Passou: providers extras não prontos, aviso de duas pastas, erro/retry e loading |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `node /tmp/document-ai-question-scope-check.cjs` | Exit 0; renderização real do componente em fixtures; script transitório, sem dependências novas | Implementação | Validador: exit 0 |
| `cd frontend && npm run lint` | Exit 0, sem findings ESLint | Implementação | Validador: exit 0 |
| `git diff --check` | Exit 0 | Implementação | Validador: exit 0 |
| `cd frontend && npx tsc --noEmit` | Exit 0 | Implementação | Não repetido |
| `.tools/graphify/bin/graphify update .` | Exit 0; grafo atualizado via AST | Implementação | Não repetido |

## Validator report

- Blocking: nenhum.
- Important: nenhum.
- Suggestions: nenhuma.
- Independent evidence: subagente `validate_tools_count` inspecionou o diff e reexecutou renderização React, lint e diff-check, todos com exit 0. Confirmou normalização/deduplicação, seleção, singular/plural, negativos e preservação da cobertura por pastas.
- Gate decision: aprovado. Não houve alteração de API, acesso a dados, autorização ou isolamento. Verificação do componente por renderização e análise estática; não houve inspeção visual no browser autenticado.

## Aplicação na instância Docker

- Em 2026-09-30, por solicitação explícita do usuário, executado `docker compose up -d --no-deps --build frontend` (exit 0). Imagem `arquivio-frontend:local` reconstruída e container `document-ai-frontend-1` recriado na porta 3000, sem reiniciar os demais serviços.
- `http://localhost:3000/` respondeu HTTP 200; leitura de `/app/app/question-scope.tsx` dentro do container confirmou o contador deduplicado e o rótulo de ferramentas. A alteração está na imagem reconstruída, sem depender do servidor extra.
- Servidor local deste projeto em 3011 encerrado com SIGTERM; nenhuma escuta restante nessa porta. Instância de referência para alterações futuras nesta sessão: Docker em `localhost:3000`.
