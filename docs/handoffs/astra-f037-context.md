# Handoff — F-037 Arquivio: produto, UI e landing page

**Atualizado:** 2026-09-21  
**Status do work item:** `done` — gate local aprovado em 2026-09-21.  
**Arquivo fonte:** `specs/work-items/F-037.md`

## Retomada concluída (2026-09-21)

- Textos visíveis Company/Companies e grants ajustados para organização/autorizações; contratos e identificadores preservados.
- Revisão independente encontrou resposta antiga reaparecendo após envio de busca vazia. Corrigido com cancelamento explícito e limpeza de loading; harness focal independente passou.
- Build e lint finais passaram; validador independente executou backend (186 passed, 6 skipped, 2 warnings) e Ruff, sem bloqueantes.
- Browser nesta retomada: landing → `/login`; landing desktop e landing/login em 390px sem overflow horizontal. Fluxos autenticados sintéticos abaixo são evidência da sessão anterior.
- Critérios e gate preenchidos em `specs/work-items/F-037.md`; Graphify AST atualizado (2427 nós, 6224 arestas). Documentação semântica não é atualizada pelo comando AST-only.
- WorkOS/Google Drive/OpenAI reais continuam sem validação; PostgreSQL mantém evidência histórica. Nenhum deploy, commit ou push foi realizado nesta retomada.

As seções seguintes preservam o contexto histórico e o roteiro que já foi executado. Consulte o dossiê para o estado final.

## Objetivo aprovado

Evoluir o MVP Arquivio para uma experiência de produto mais coerente, manter a
marca em português, criar uma landing page pública na rota `/` e direcionar
entrada para `/login`. Não criar novo provedor, billing, mudança de tenancy,
retenção de dados ou deploy de produção.

## Onde o Astra parou

Foram iniciados dois subagentes Astra:

1. **Produto/UI** — dono de `frontend/app/product-app.tsx` e
   `frontend/app/globals.css`.
2. **Landing page** — dona de `frontend/app/landing-page.tsx` e
   `frontend/app/landing.css`.

Ambos foram interrompidos por limite de uso. Eles deixaram alterações no disco,
mas não fizeram uma entrega final nem concluíram a validação. O trabalho
posterior foi deliberadamente delegado a modelos menores:

- Terra concluiu estilos, paginação, proteção contra respostas obsoletas e
  correção de lint em `product-app.tsx`/`globals.css`.
- Luna revisou a landing e removeu a promessa de salvar consultas que não fosse
  refletida claramente na interface naquele momento.
- Luna validou backend/rotas; Terra fez uma revisão independente de frontend.

Portanto, não retome do "último pensamento" do Astra: retome do estado do
repositório e desta lista de pendências.

## Estado implementado no repositório

### Landing e autenticação

- `frontend/app/landing-page.tsx` + `frontend/app/landing.css`: landing pública
  em português, com CTAs de entrar/criar conta, fluxo Google Drive somente
  leitura, fontes/citações e aviso de acesso uniforme.
- `frontend/app/login/page.tsx`: rota explícita de entrada que monta
  `ProductApp`.
- `frontend/app/layout.tsx`: metadados Arquivio em português.
- Visitante anônimo em `/` vê a landing; sessão existente é encaminhada para a
  organização; falha de sessão mostra mensagem e botão de tentativa novamente.

### Produto e UX

- `frontend/app/product-app.tsx`: `useLatestRequest` cancela requisições
  anteriores, evitando que navegação/busca obsoleta sobrescreva a tela atual.
- Biblioteca suporta paginação de filhos e busca por nome.
- Conversa preserva mensagem já enviada ao editar o campo da próxima pergunta.
- Perguntas salvas aparecem no contexto da pasta selecionada.
- Seleção de contexto está antes do composer em tela móvel.
- Painéis, estados vazios, foco e erro de sessão receberam estilos em
  `frontend/app/globals.css`.
- Testes fakes de autenticação foram atualizados para aceitar
  `screen_hint`/`max_age` sem alterar o comportamento de produção:
  `backend/tests/api/test_auth_and_invitations.py`,
  `backend/tests/api/test_company_library_api.py`,
  `backend/tests/api/test_text_search_api.py`.

## Evidência já coletada

### Automática

```text
cd frontend && npm run lint        # passou
cd frontend && npm run build       # passou
cd backend && .venv/bin/pytest -q --tb=short
# 186 passed, 6 skipped, 2 warnings
cd backend && .venv/bin/ruff check app tests
# passou
```

Integração PostgreSQL descartável também foi executada antes:

```text
TEST_DATABASE_URL=postgresql+psycopg://postgres:<disposable>@127.0.0.1:15437/f037 \
  .venv/bin/pytest -q tests/integration --tb=short
# 6 passed
```

O contêiner PostgreSQL usado nesse teste foi parado. Não presumir que exista.

### Browser com dados sintéticos locais

- LP anônima → `/login` → OAuth simulado → organização: passou.
- Pergunta em `Projeto Aurora` retornou resposta com fonte; rascunho seguinte
  não apagou a conversa; salvar pergunta funcionou.
- Busca por `Planejamento 54` funcionou.
- Uma fixture com 155 documentos confirmou abertura da segunda página.
- Em 390×844 não houve overflow horizontal; contexto ficou acima do composer.
- Logout retornou à landing.

Esses testes **não** validam WorkOS, Google Drive ou OpenAI reais. A fixture e a
API temporária foram removidas ao fim do teste.

## Validação independente atual

Sem bloqueantes técnicos identificados nos diffs revisados. A revisão apontou
um resíduo importante de produto: há textos visíveis com `Company` no lugar de
`organização`/`espaço`, principalmente em `frontend/app/product-app.tsx`:

- `TeamScreen` (remoção, acesso e explicação de papéis);
- confirmação de acesso uniforme do Google Drive;
- `IntegrationScreen`/Tools;
- `StaffCenter` (onde o termo pode ser "organização" para usuários comuns;
  "Company" só deve permanecer se for um nome deliberado do modo operacional).

O type interno `Company`, rotas `/companies/:companyId` e contratos de API não
precisam ser renomeados nesta feature. Ajustar apenas o texto apresentado.

O dossiê F-037 ainda tem a tabela de critérios marcada como `Pending` e o bloco
final de validator vazio. Atualize isso apenas depois de corrigir os textos e
rodar novamente a validação relevante.

## Próximo roteiro seguro

1. Substituir somente os textos visíveis `Company` por linguagem de produto em
   `product-app.tsx`; não mudar tipos, rotas, payloads ou nomes de API.
2. Rodar `cd frontend && npm run lint && npm run build`.
3. Fazer validação independente com `validator-lite` e, se possível, browser
   local em desktop + 390px.
4. Preencher critérios/evidências/gate em `specs/work-items/F-037.md` e mudar
   o status para `done` somente sem bloqueantes.
5. Rodar `.tools/graphify/bin/graphify update .` após a alteração; é AST-only.

## Contexto do Graphify e delegação econômica

- Grafo disponível em `graphify-out/graph.json`; use primeiro
  `.tools/graphify/bin/graphify query "<pergunta>" --budget 900` antes de
  leituras amplas.
- Perfis leves estão em `.codex/agents/`:
  `graph-navigator`, `impact-scout`, `test-designer`, `ui-qa`,
  `validator-lite` e `small-change-implementer`.
- O CLI Graphify está isolado em `.tools/graphify/bin/graphify`; não assumir que
  o comando global `graphify` está no PATH.
- O grafo atual é principalmente estrutural. Relações inferidas e o alerta de
  integridade do relatório não devem ser tratados como fatos.

## Estado de Git

Há muitas alterações não commitadas de F-036, F-037, integração Graphify e
arquivos de deploy. Não fazer `git add .`, commit ou push em massa. Separe F-037
dos itens de deploy antes de qualquer commit.
