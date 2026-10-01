# M31 — Cards de ferramentas: evidência da correção

Executor: pane-308. Data: 2026-10-01. Branch compartilhada: main.
skills: inline [oc-builder, oc-blackbox, oc-stamp]

## Causa e reprodução

As descrições de Google Drive, OneDrive, SharePoint e Notion ficavam entre ícone e
seta, com 69px de recuo. O texto longo centralizava ícones em posições diferentes;
rodapés não acompanhavam o fundo dos cards. Airtable usava uma estrutura diferente.

Antes da mudança, `/tmp/m31-onboarding-cards.cjs` falhou nas quatro larguras
(1440, 768, 390 e 320; exit 1). Após a correção de estrutura, os cinco cards passam
a ter o mesmo recuo de 17px, título em 14px e descrição em 13px/22px.

A fixture de contas conectadas revelou também scrollWidth 459px em viewports
390/320: a regra mobile global alinhava o rodapé à esquerda, deixando a área de
status crescer pelo tamanho do e-mail. `width: 100%`, `min-width: 0` e flex no campo
de conta eliminam essa causa. O valor completo continua disponível no tooltip.

## Verificação final

| Comando | Resultado novo |
| --- | --- |
| `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/tool-cards-check.cjs` | **16 casos e 7 interações aprovados; exit 0** |
| `cd frontend && npx tsc --noEmit` | Sem erros; exit 0 |
| `cd frontend && npx eslint app/product-app.tsx` | Sem erros/avisos; exit 0 |
| `cd frontend && node --import tsx --test tests/*.test.mjs` | **42 passed, 0 failed; exit 0** |
| `node --check artifacts/onboarding/tool-cards-check.cjs` | Exit 0 |
| `git diff --check` | Exit 0 |
| `graphify update .` | Exit 0; 6069 nós, 17653 arestas, 362 comunidades na execução |

O teste de navegador usa o frontend fonte e fixtures de API no Playwright.
Cruza as quatro larguras com disponível/conectado/reconexão necessária/desconectado;
verifica tipografia, alinhamento, ausência de scroll horizontal com e-mail longo,
alvos de toque de 44px e ausência de erros de página.
As sete interações cobrem Gerenciar nas quatro fontes, desconectar Notion,
abrir Google Drive sem conta e reconectar OneDrive preservando `source_id`.
As ações foram interceptadas nas fixtures; nenhuma conta externa foi alterada.

## Escopo e limites

- Mudanças de produto restritas ao markup dos cards e `integration-cards.css`.
- Preservados arquivos da LP pertencentes a pane-307 e arquivos gerados do grafo
  fora do commit. O grafo já estava alterado no início desta tarefa.
- Não houve rebuild/recreate de containers nem build de produção. A coordenação
  solicitou QA integrado após o resultado da LP.
- Notion e apresentação hierárquica da biblioteca não foram alterados nesta etapa;
  a implementação e revisão anteriores constam em `notion-page-library.md`.
