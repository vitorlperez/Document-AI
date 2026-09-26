# Botões de desconexão e bordas das telas de integrações e equipe

**Status:** done

## Fonte e critérios

- Pedido do usuário nesta missão; referência funcional: `specs/001-mvp-document-intelligence.md`, F2/F2a e gestão da organização.
- Owner/Admin visualiza Desconectar nos cartões de Google Drive, OneDrive e Notion quando há fonte ativa ou que exige reconexão.
- A ação usa a confirmação e o endpoint de exclusão já existentes; fonte desconectada não mostra o botão. O estado de progresso é identificado por fonte.
- Os cartões e controles de integrações, equipe e outras superfícies do produto usam bordas suaves da paleta. O grid de integrações cresce conforme o conteúdo.

## Decisões e propriedade

- Mudança de apresentação no frontend, sem alteração de API, dados ou autorização.
- Implementação: `frontend/app/product-app.tsx`. Auditoria de telas semelhantes: pane-53, somente leitura. Validação independente: pane-53 após integração.
- Falha da API mantém a fonte e apresenta a mensagem de erro existente; o botão fica desabilitado durante desconexão.

## Verificação

| Critério | Evidência |
| --- | --- |
| Ações visíveis nos três cartões e ausentes em desconectados | revisão do JSX; revisão independente aprovada |
| Falha/negação preserva a fonte | fluxo `disconnect` existente; validação independente pendente |
| Padrão de borda uniforme | classes `border-line-soft`/`border-line` e regra `.page-surface` corrigida; revisão independente aprovada |
| Lint do arquivo | `cd frontend && ./node_modules/.bin/eslint app/product-app.tsx`: 0 erros, 2 avisos preexistentes |
| Build frontend | `cd frontend && npm run build`: concluído |
| Diff | `git diff --check`: sem erros |
| Tipagem global | `cd frontend && ./node_modules/.bin/tsc --noEmit`: bloqueada por TS7006 em `app/api/[...path]/route.ts:40`, fora do escopo |

## Validação independente

Primeira revisão h-1d apontou 4 warnings (bordas dos controles, override de `.page-surface`, estado global e altura do grid); todos corrigidos. Segunda revisão resolveu os 4 warnings iniciais, mas detectou concorrência entre botões de desconexão. Todos os botões agora ficam desabilitados durante uma desconexão; somente a fonte ativa mostra o progresso. Terceira validação independente APROVADA: 0 critical, 0 warnings; confirmou bloqueio global dos quatro botões, progresso apenas no source.id ativo e ausência de outro caminho frontend. Lint e diff check repetidos pelo validador.
