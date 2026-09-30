# Plano 02 — SharePoint/Microsoft 365 e decisão Google (CASA vs `drive.file` + Picker)

Data: 2026-09-29 · Base: `main` @ `c9cebf0` **mais alterações não commitadas** (working tree; citações `path:line` refletem o disco de hoje) · Origem: Recomendação 2 de `specs/research/integracoes-analise-2026-09-29.md` (§1, §2.3–2.5, §4.1, §6 D/E, §7 Onda 1, §8.1, §9) · Convenção: **[FATO]** verificado em código ou doc oficial aberta nesta sessão; **[INFERÊNCIA]** dedução; **[VALIDAR]** depende de tenant de teste / Google / lab; **[ESTIMATIVA]** julgamento.

> Revisão (2026-09-29, pane-243): as alterações "não commitadas" já estão no `HEAD` `f5f3a1e` (e a renovação de token do Google em `25091aa`); `alembic heads` = `20260929_0018`. Numeração de ADR e de migração foi realinhada com os planos 01/03 (ver `00-indice.md`). Correções marcadas com "> Revisão:" ou "(Revisão: …)".

> Using oc-route to write the implementation plan.

# SharePoint + Google OAuth Implementation Plan

**Goal:** conectar bibliotecas de documentos do SharePoint/Teams (M365) reaproveitando o conector OneDrive e destravar o go-to-market do Google Drive decidindo — e executando — CASA para `drive.readonly` ou migração para `drive.file` + Picker.

**Architecture:** Parte A adiciona o provider `sharepoint` (novo módulo `integrations/sharepoint.py`) que **herda** cliente Graph, cifra, provider e serviço OAuth do OneDrive por parametrização mínima, muda o endereçamento de `/me/drive` para `/drives/{driveId}`, usa ID composto `driveId|itemId` e um delta por raiz de biblioteca com filtro de pertencimento. Parte B é majoritariamente **trilha externa** (verificação OAuth Google + avaliação CASA) com poucas mudanças de código (política de privacidade, revogação/expurgo, evidências de segurança); `drive.file` + Picker fica como contingência especificada, não construída agora.

**Stack:** FastAPI + SQLAlchemy + Alembic + Celery (`backend/`), Next.js/React (`frontend/app/product-app.tsx`), `httpx`, `cryptography.Fernet`, Microsoft Graph v1.0, Google OAuth/Drive v3, pytest + ruff.

## Global constraints

- Backend: rodar `cd backend && pytest <arquivo> -q` e `ruff check .` (README:118-119). > Revisão: neste ambiente `pytest` não está no PATH (`pytest: command not found`); use `cd backend && .venv/bin/python -m pytest <arquivo> -q` e `.venv/bin/ruff check .` (baseline conferido: `tests/unit tests/api` → 459 passed). Sem CI no repositório (`.github/` não existe) [FATO].
- Nomes de provider: `sharepoint` (novo), `onedrive`, `google_drive`, `notion` — `DataSource.provider` é `String(40)` sem enum (`integrations/models.py:13`).
- Escopos Microsoft **somente delegados e somente leitura**; nunca `*.ReadWrite.*`, `Sites.FullControl.All` nem permissão de aplicativo nesta entrega (ADR-0008 dec. 2/3, ADR-0009 dec. 3).
- Tokens e cursores sempre cifrados com Fernet; chave `MICROSOFT_TOKEN_ENCRYPTION_KEY` (`config.py:46`) para toda a família Microsoft; **proibido** fallback para a chave do Google (contraste: `registry.py:61`; Revisão: era `:60`).
- IDs externos em `String(255)` (`knowledge/models.py:32`, `library/models.py:24`, `workspaces/models.py:24,55`): o ID composto SharePoint tem que caber (≈100 chars) [INFERÊNCIA — medir no spike A0].
- Sem ACL por arquivo: `uniform_access_confirmed` continua obrigatório (`workspaces/service.py:78-80`, relatório §2.1). SharePoint **não** oferece `all_accessible` nem `root_files`.
- Nenhum plano deste arquivo altera o agente, o chat ou o pipeline de chunking/embedding.
- Após qualquer mudança de código: `graphify update .` (AGENTS.md). O CLI `graphify` **não existia** neste ambiente (`command not found`) — a análise abaixo foi feita lendo o código direto.
- Migrações Alembic: encadear no **head vigente no dia do merge** (`alembic heads`; hoje `20260929_0018`). > Revisão: os três planos reservavam `…_0019`; pela ordem do índice, o plano 01 ocupa 0019–0021 (`pgvector_expand`, `extraction_cache`, `pgvector_contract`) e esta entrega fica com **0022 `sharepoint_tenant_binding`** (esperado), `down_revision` = cabeça vigente — se a ordem real de merge mudar, usar o próximo número livre.

---

## 0. Scope check e ordem interna

Dois subsistemas independentes, cada um entrega valor sozinho → **duas partes, executáveis em paralelo por pessoas diferentes**:

| Parte | Entrega | Depende de | Lead time externo |
|---|---|---|---|
| **A — SharePoint/M365** | provider `sharepoint` ponta a ponta (OAuth, catálogo, delta, ingestão, UI, runbook) | Plano 01 (base OAuth, `RemoteHttp`) — **fallback definido em §2** | Verificação de publisher Microsoft + consentimento de admin por tenant |
| **B — Google** | decisão registrada em ADR + execução da trilha escolhida (CASA) | nenhum (paralelo) | **Semanas**: verificação Google + laboratório CASA (§B.2) |

**Pré-requisito comum P0 (bloqueia as duas trilhas externas):** domínio próprio. O frontend de produção está em `https://frontend-production-e02d.up.railway.app` e as páginas públicas ainda respondiam 404 em 28/09 (`docs/operacao/sync-credenciais-retencao-recomendacao.md`, checklist final) [FATO]. Google exige domínio autorizado e verificado no Search Console para home/privacidade/termos; Microsoft exige domínio verificado para *publisher verification* [VALIDAR nas docs — ver §7]. Um subdomínio da Railway não é domínio que a empresa controle. **Tarefa P0 (dono: produto/infra, 0,5 d + propagação DNS):** registrar/apontar domínio, publicar `/privacidade` e `/termos` (já existem: `frontend/app/privacidade/page.tsx`, `frontend/app/termos/page.tsx`), atualizar `PUBLIC_APP_URL` (`config.py:34`).

---

## 1. Estado atual ancorado (o que o plano assume e reutiliza)

> Revisão: âncoras conferidas contra o `HEAD` `f5f3a1e`. Há trabalho **não commitado** em andamento (Notion disconnect, remoção de pasta do catálogo) que desloca `api/integrations.py` +8 a partir de `:366` (ex.: ramos `onedrive` 366/400/466/563 → 374/408/474/571; `scope-catalog` 431 → 439) e `library/service.py` +25 a partir de `:196` (ex.: projeção 714 → 729, rótulos 779 → 804). Reancorar pelo símbolo (`scope_catalog`, `project_successful_sync`, `provider_name`) ao executar.

| Fato | Evidência |
|---|---|
| Escopos OneDrive: `openid profile offline_access User.Read Files.Read`; autoridade `common` | `integrations/onedrive.py:35,37` |
| Todo endereçamento Graph do OneDrive é `/me/drive…` | `onedrive.py:209,216,233,260,262,285,290,317,339` |
| 429 com `Retry-After` (4 tentativas, teto 30 s) já existe no cliente Graph (JSON e download); **503 não é tratado** | `onedrive.py:316-336,373-402` |
| `_external_id` devolve o ID cru do item; comentário: "fonte vinculada ao drive de um usuário" — o parâmetro `fallback_drive_id` já existe e é ignorado | `onedrive.py:404-411` (o relatório §4.1 diz que o ID composto é "antecipado" ali; na verdade só o parâmetro/comentário existem — o composto é trabalho novo) |
| `_parent_ids` usa `parentReference.id`/`path`; delta de OneDrive/SharePoint **não devolve `path`** | `onedrive.py:413-421`; doc `driveItem: delta` → "parentReference … won't include a value for path" [FATO, doc aberta] |
| `OneDriveDocumentProvider._read_one` chama `self.client._external_id`, `_parent_ids`, `read_file` → polimorfismo por cliente permite reuso | `onedrive.py:577-604` |
| Provider e serviço têm literal `"onedrive"` em 425, 639, 729, 737, 759, 804, 851 (Revisão: eram 640/736/757 e faltava `key` do provider em 425) e `client.drive_id` em 723; vínculo de identidade = `provider_account_id` (drive id) | `onedrive.py:632-644,721-771,798-808,846-854` |
| `MAX_PAGE_WORKERS = 4` downloads paralelos (constante de módulo) | `onedrive.py:38,574` |
| Registry: um adapter por provider + fábrica | `registry.py:86-124,126-132` |
| Worker resolve providers ≠ Google via registry; injeta `known_documents` só para Notion; chama `provider.folders(...)` **sem seleções**; grava cursores via `encrypt_delta_link` | `ingestion/tasks.py:261-262,299-304,315,374-384` |
| Projeção da biblioteca: usa `folders` para montar árvore; nó desconhecido cai na raiz da fonte; **apaga** `LibraryNode` da fonte que não esteja no resultado do sync corrente | `library/service.py:714-770,800-855` |
| Rótulo de provider na biblioteca (dicionário com 3 chaves; fallback `replace("_"," ").title()`) | `library/service.py:779-783` |
| Rotas OAuth por provider e ramificações `if provider == "onedrive"` | `api/integrations.py:89-102,105-181,366,400,466,563` |
| Seleção valida `folder_ids ⊆ available_folder_names`; `all_accessible`/`root_files` são aceitos por padrão | `workspaces/service.py:142-154`; CHECK de `kind` em `workspaces/models.py:59-63` |
| Catálogo: `scope-catalog` devolve `folders/root_files/all_accessible`; frontend mantém **uma fonte por provider** (`latestSourcePerProvider`) | `api/integrations.py:431-502`; `frontend/app/product-app.tsx:39,731-733,747-765,780-799` |
| Frontend: `ProviderLogoName`, `labels`, cartão OneDrive hard-coded | `frontend/app/provider-logo.tsx:3,5`; `product-app.tsx:733,765,795-799` |
| Google: escopo único `drive.readonly`, `prompt=consent`, `access_type=offline` | `integrations/google_drive.py:25,106-118,484` |
| Google: `disconnect` apaga credenciais mas **não revoga** o token no Google nem apaga o índice | `integrations/google_drive.py:591-633`; `docs/operacao/sync-credenciais-retencao-recomendacao.md` (tabela "Exclusão") |
| Google: renovação de token **já existe no disco (não commitado)** — o doc de 28/09 está defasado nesse ponto | `ingestion/google_drive.py:332-379` (Revisão: já commitado em `25091aa feat(sync): renovar token do Google Drive`; não há mais `M` no `git status`) |
| Política pública já declara `drive.readonly`, sem a declaração de *Limited Use* | `frontend/app/privacidade/page.tsx:12,14` |
| ADRs vigentes que esta entrega revisa: ADR-0008 dec. 2 (SharePoint fora), ADR-0009 dec. 5 (uma fonte OneDrive/org, SharePoint fora); `docs/integrations-roadmap.md:14` | `specs/adr/ADR-0008…`, `ADR-0009…` |

**Correção ao relatório:** o link citado em §4.1 (`graph/api/site-delta`) descreve o delta da **coleção de sites**, não de arquivos. O delta de arquivos é `driveItem: delta` (`GET /drives/{drive-id}/root/delta` ou `/sites/{siteId}/drive/root/delta`) [FATO].

---

## 2. Dependência do Plano 01 e o que fazer se ainda não existir

O plano 01 (em paralelo) vai extrair (i) **base de serviço OAuth** comum (`begin/cancel/complete/disconnect/folders` hoje copiados em `google_drive.py:434-663`, `onedrive.py:607-866`, `notion.py:179-230`) e (ii) **`RemoteHttp`** com 429/`Retry-After`/backoff+jitter. Na escrita deste plano, `specs/plans/integracoes/01-*.md` **não existe no disco**; nomes e caminhos finais são do plano 01.

> Revisão (o plano 01 agora existe — `01-cobertura-e-nucleo.md`): mapeamento do contrato abaixo para os nomes reais. (1) Base OAuth = `backend/app/integrations/oauth_base.py::OAuthConnectionServiceBase` (01-T2.2), com atributo **`provider`** (não `provider_key`), `access_denied`, `invalid`, `retain_identity_on_disconnect`, `_new_state/_find_valid_state/_consume_state/_own_source/_on_disconnect/disconnect`; **não** tem `bind_identity` — a checagem de conta (`OneDriveAccountMismatch`/`provider_account_id`) continua na subclasse (01-T2.3), então A1 adiciona `bind_identity` em `OneDriveConnectionService` (não na base). (2) `RemoteHttp` = `backend/app/integrations/http.py` (01-T1.1) cobre 429/500/502/503/504 e `Retry-After` (segundos e data HTTP); **não** injeta `User-Agent`: passar `headers={"User-Agent": …}` em cada `request(...)` (repasse de `**httpx_kwargs`) ou via um cliente SharePoint que os acrescente. O Graph passa a usar `RemoteHttp` em 01-T1.4. (3) Chave por provider = `backend/app/integrations/keyring.py::build_fernet` (01-T2.6); `sharepoint` usa as chaves Microsoft. (4) **Lacuna herdada:** 01-T1.4 mantém 401/403 do Graph como `SourceRemoteUnauthorized` e delega a este plano a distinção 403-consentimento × 403-item; este plano não a tratava (A.16 item 4 diz "401/403 → `reauth_required`"). Acrescentar em A3 um teste: 403 `accessDenied` em **um** item durante o download ⇒ documento `failed` (código `source_item_forbidden`), fonte segue `connected`; 403 no `/sites/root`/catálogo ⇒ `reauth_required`. **Dependências duras do 01:** T1.1, T1.4, T2.2, T2.3 e T2.6 antes de A1/A5; A0, A2–A4 e toda a Parte B podem andar antes.

**Contrato assumido (o que o Plano 02 exige do 01):**

1. Base OAuth parametrizável por `provider_key` e por "vínculo de identidade" (`bind_identity(credentials) -> str`), preservando `OAuthConnectionState`, `AuditLog data_source.connected|disconnected` e as exceções que `api/integrations.py` já mapeia.
2. `RemoteHttp` cobrindo **429 e 503** com `Retry-After`, teto de espera, `User-Agent` decorado (D-A9; Revisão: a referência era "§A.3-D5", que não existe) e 403 ≠ 401 (quota vs autorização).
3. Registry aceitando chave de criptografia **por provider** (`sharepoint` → chave Microsoft).

**Regras de sequenciamento:**

| Situação | O que fazer |
|---|---|
| Plano 01 já mergeou base + `RemoteHttp` | **A1 vira "herdar da base"** (sem parametrizar `OneDriveConnectionService`); A2 usa `RemoteHttp` no lugar de `_get_json`. Só rebasear e ajustar imports. |
| Plano 01 ainda não mergeou (caso de hoje) | Executar **A1 como escrito** (parametrização mínima por atributos de classe — comportamento idêntico, provado pelas suítes OneDrive). Quando o 01 chegar, re-parentar `SharePointConnectionService` na base sem mudar contrato público. Registrar dívida em `docs/integrations-roadmap.md`. |
| Conflito de arquivos | Plano 01 e A1 tocam `onedrive.py`, `registry.py`, `api/integrations.py`, `tasks.py`, `config.py`. **Merge do 01 primeiro**; A0, A2, A3, A4 (arquivos novos) podem andar em paralelo sem conflito. |

---

# PARTE A — SharePoint / Microsoft 365

## A.1 Decisões de projeto (registrar na ADR-0016)

> Revisão: os planos 01 (ADR-0011…0015), 02 (ADR-0011/0012) e 03 (ADR-0011) usavam o mesmo número. Alocação global: 01 → 0011–0015; **02 → 0016 (SharePoint) e 0017 (Google)**; 03 → 0018.

| # | Decisão | Motivo / âncora |
|---|---|---|
| D-A1 | **Provider novo `sharepoint`**, não "OneDrive com mais drives". `DataSource` separado, com botão e status próprios. | ADR-0009 dec. 5 fixa "uma fonte OneDrive por org"; `complete()` escolhe a fonte mais recente do provider (`onedrive.py:733-741`). Um provider novo evita migrar fontes/IDs existentes e permite escopos e autoridade diferentes. |
| D-A2 | **Autoridade `organizations`** (não `common`): SharePoint Online não existe para conta pessoal. Mesmo app Entra do OneDrive, **redirect URI adicional** `/data-sources/sharepoint/oauth/callback`. | `onedrive.py:35`; ADR-0009. |
| D-A3 | **Um `DataSource` = uma conexão a um tenant M365**; vínculo de identidade `provider_account_id` = hostname do SharePoint do tenant (`GET /sites/root` → `siteCollection.hostname`, ex. `contoso.sharepoint.com`). Reconexão a outro tenant → recusar (espelha `OneDriveAccountMismatch`, `onedrive.py:744-755`). | `provider_account_id` existe (migração `20260923_0016`). Alternativa mais forte (`tid` do `id_token`) fica como melhoria — exigiria capturar o `id_token` em `_token_request` (`onedrive.py:178-199` hoje o descarta). |
| D-A4 | **ID externo composto `"{driveId}|{itemId}"`**, separador `|`. Não usar `!` (o relatório sugere `driveId!itemId`): IDs de drive SharePoint têm o formato `b!…` [VALIDAR no spike], então `!` seria ambíguo. Nós virtuais de site: `"site|{siteId}"`. | `onedrive.py:404-411`. |
| D-A5 | **Árvore da biblioteca**: `Fonte → Site → Biblioteca → pastas`. Nó de site = `RemoteFolder("site|{siteId}", nome, ())`; nó de biblioteca = `RemoteFolder("{driveId}|{rootItemId}", nome, (site_node,))`; pastas e arquivos com `parent_ids=("{driveId}|{parentId}",)`. Só **biblioteca** e **pasta** são selecionáveis (site não). | `library/service.py:800-855` (pais desconhecidos caem na raiz → precisa de todos os nós). |
| D-A6 | **Escopo OAuth padrão: `Sites.Read.All`** (delegado) + `openid profile offline_access User.Read`. Sem `Files.Read.All`. Modo restrito `Sites.Selected` como fase posterior (A9). Ver comparação em A.2. | `driveItem: delta` lista `Sites.Read.All` entre as permissões delegadas que autorizam delta/download em conta corporativa [FATO, doc aberta]. |
| D-A7 | **Delta por raiz de biblioteca + filtro de pertencimento**, snapshot inicial por travessia `children` precedida de `?token=latest`. Não depender de delta em pasta interna. | Doc atual só lista `…/root/delta` para drives; a nota histórica "delta só na raiz em OneDrive for Business/SharePoint" **não apareceu** na versão aberta, mas o exemplo de `latest` (Exemplo 3) é oficial [VALIDAR item-delta no spike A0]. Detalhe em A.4. |
| D-A8 | **SharePoint sem `all_accessible` e sem `root_files`**; confirmação de acesso uniforme com texto reforçado. | SharePoint tem permissões heterogêneas; token delegado enxerga tudo que o admin conector enxerga → todos os membros passariam a consultar. Relatório §2.5/§8.5. |
| D-A9 | **Throttling**: honrar `Retry-After` em 429 **e 503**, `User-Agent` decorado `ISV|Arquivio|DocumentAI/1.0`, downloads paralelos configuráveis (padrão 2). | Doc SharePoint throttling [ver §7]; `onedrive.py:38`. |
| D-A10 | **Pré-requisito de produto (vale ler antes de vender):** conexão delegada depende de **uma pessoa**; se o admin conector sair/for desativado, o refresh token morre e a fonte vira `reauth_required`. Mitigação futura: modo aplicativo com `Sites.Selected` (fora do escopo, registrado como risco R-A5). | Modelo delegado herdado do OneDrive (ADR-0008 dec. 2). |

## A.2 Permissões: `Sites.Selected` vs `Sites.Read.All` vs `Files.Read.All` (delegadas)

| Critério | `Sites.Read.All` (padrão) | `Sites.Selected` (modo restrito, A9) | `Files.Read.All` |
|---|---|---|---|
| Alcance | todas as coleções de sites que **o usuário** enxerga | só sites em que o **app** recebeu concessão explícita (interseção com o que o usuário enxerga) | todos os arquivos que o usuário enxerga (inclui OneDrive de outros compartilhados) |
| Consentimento | [VALIDAR] a doc de permissões marca "admin consent" como *não obrigatório* p/ `Sites.Read.All` delegado, mas o consentimento **de usuário** depende da política do tenant e de o publisher estar verificado; na prática, tratar como **necessário consentimento de admin** em tenants restritos | **exige admin** (consentimento no Entra **e** concessão por site) | idem `Sites.Read.All` |
| Passos extras | nenhum | `POST /sites/{siteId}/permissions` com `roles:["read"]` para o app (exige `Sites.FullControl.All` de quem concede) | — |
| Enumerar sites no catálogo | `GET /sites?search=*` funciona | **não enumera**; admin informa a URL do site | — |
| Melhor para | pilotos, PME sem TI dedicada | clientes com política de menor privilégio | não usar (escopo maior que o necessário) |
| Fonte | [Graph — Selected permissions](https://learn.microsoft.com/en-us/graph/permissions-selected-overview) [FATO: 3 passos — consentimento, `POST …/permissions`, token com o escopo; delegado = interseção usuário∩app] | | [Graph — permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) |

**Confirmar em tenant de teste (§9.2 do relatório):** (i) se `Sites.Read.All` delegado dispara "Need admin approval" em tenant com consentimento de usuário restrito; (ii) o efeito de *publisher verification* — pela doc de consentimento, multi-tenant sem publisher verificado é bloqueado para consentimento de usuário [VALIDAR]. Resultado vai para o runbook (A10).

## A.3 File map (decomposição travada)

| Arquivo | Ação | Responsabilidade única |
|---|---|---|
| `backend/app/integrations/sharepoint.py` | **criar** | IDs compostos, `SharePointGraphClient` (catálogo de sites/bibliotecas, travessia, delta por raiz, pertencimento), `SharePointDocumentProvider`, `SharePointConnectionService` |
| `backend/app/integrations/onedrive.py` | modificar (A1) | atributos de classe `AUTHORITY`, `SCOPES`, `max_workers`; `provider_key`/`bind_identity` no serviço; 503 no retry |
| `backend/app/integrations/registry.py` | modificar (`:126-132`) | `SharePointProviderAdapter` + fábrica `"sharepoint"` |
| `backend/app/core/config.py` | modificar (`:43-46`) | `microsoft_sharepoint_redirect_uri`, `sharepoint_download_workers`, `sharepoint_max_file_bytes`, `sharepoint_catalog_max_sites` |
| `backend/app/api/integrations.py` | modificar (`:89-181,352-415,431-502,537-603`) | rotas `/data-sources/sharepoint/oauth/*`, ramos `sharepoint`, validações D-A8 |
| `backend/app/ingestion/tasks.py` | modificar (`:315`) | usar `folders_for_selections` quando o provider oferecer |
| `backend/app/library/service.py` | modificar (`:779-783`) | rótulo "SharePoint" |
| `backend/alembic/versions/AAAAMMDD_0022_sharepoint_tenant_binding.py` | **criar** | índice único parcial: um `DataSource` `sharepoint` por (org, tenant) |
| `frontend/app/provider-logo.tsx` | modificar (`:3,5`) | logo `sharepoint` |
| `frontend/app/product-app.tsx` | modificar (`:733,747-765,780-799` + texto de escopo) | cartão SharePoint, rótulos, erros de OAuth, lista de bibliotecas |
| `backend/tests/unit/test_sharepoint.py` | **criar** | IDs, URLs, catálogo, pertencimento, delta/snapshot |
| `backend/tests/api/test_sharepoint_integration.py` | **criar** | OAuth, catálogo, seleção, isolamento de tenant, RBAC |
| `backend/tests/unit/test_sharepoint_ingestion_task.py` | **criar** | worker ponta a ponta com provider fake |
| `README.md` (`:82-84`), `docs/integrations-roadmap.md`, `frontend/app/privacidade/page.tsx:12,14` | modificar | env, roadmap, política |
| `specs/adr/ADR-0016-sharepoint-connector.md`, `docs/integracoes/sharepoint-*.md` | **criar** | ADR, spike, runbook (ver §7) |

## A.4 Design do sync SharePoint (referência das tarefas A3–A6)

1. **Cursor por seleção** = `deltaLink` de `GET /drives/{driveId}/root/delta` (cifrado em `WorkspaceFolderSelection.encrypted_delta_link`, `workspaces/models.py:56`; gravação em `tasks.py:374-384`).
2. **Sem cursor / cursor expirado (410, `resyncChanges*`) / evento de pasta dentro do escopo / `force_full`** → *snapshot*: **primeiro** `GET …/root/delta?token=latest` (guarda o `deltaLink` novo), **depois** travessia `children` do escopo. Qualquer mudança ocorrida durante a travessia reaparece no próximo delta (idempotente).
3. **Delta incremental**: para cada item alterado: `deleted` → remoção; arquivo → `within_scope(parent)`? *sim* → mudança, *não* → remoção (movido para fora); pasta dentro do escopo (ou apagada) → força snapshot (delta não devolve descendentes: doc "renaming a folder doesn't result in any descendants … returned").
4. **`within_scope`** sobe `parentReference.id` via `GET /drives/{d}/items/{id}?$select=id,parentReference` com memoização por pasta, até achar a raiz do escopo (True), a raiz do drive (False) ou 404 (False). Escopo = raiz da biblioteca → sempre True, sem chamadas.
5. **Worker**: `folders_for_selections(encrypted_credentials, selections)` devolve nós site + biblioteca + pastas **só dos drives tocados pelas seleções** (o `folders()` sem seleções do worker, `tasks.py:315`, não sabe quais bibliotecas listar).
6. **Risco pré-existente a caracterizar (A0):** `project_successful_sync` apaga `LibraryNode` da fonte fora do resultado corrente (`library/service.py:755-770`); com vários espaços na mesma fonte SharePoint isso pode limpar a biblioteca de outro espaço até o sync dele [INFERÊNCIA — teste de caracterização em A0.3 diz se já ocorre com OneDrive].

---

## A.5 Fase A0 — Pré-requisitos e spike (0,5–1 d + externo)

### Task A0.1: Registro do app Entra + tenant de teste

**Files:** Create `docs/integracoes/sharepoint-spike-tenant-teste.md`
**Interfaces:** Produces: valores confirmados (formato de `driveId`, comprimento do ID composto, comportamento de consentimento, delta em pasta) que A2–A6 assumem.

- [ ] Step 1 — Obter tenant M365 de teste com ≥2 sites (1 Team, 1 Communication site), ≥1 biblioteca com subpastas, 1 usuário Global Admin e 1 usuário comum. Programa de desenvolvedor Microsoft 365 pode fornecer o tenant [VALIDAR disponibilidade; doc: https://developer.microsoft.com/microsoft-365/dev-program].
- [ ] Step 2 — No app Entra existente (mesmo `MICROSOFT_OAUTH_CLIENT_ID`, `config.py:43`): adicionar redirect URI `https://<api>/data-sources/sharepoint/oauth/callback` e permissão delegada `Sites.Read.All` (sem conceder admin ainda).
- [ ] Step 3 — Com um cliente HTTP simples (`curl`/`httpx` no scratchpad, **fora do repo**) registrar, e colar (mascarando tokens) em `docs/integracoes/sharepoint-spike-tenant-teste.md`:
  1. login como usuário comum → aparece "Need admin approval"? (resposta ao §2 A.2-i)
  2. `GET /sites?search=*&$select=id,displayName,webUrl`; `GET /sites/{id}/drives`; `GET /drives/{d}/root?$select=id`
  3. formato e tamanho de `driveId`; `len("{driveId}|{itemId}")`
  4. `GET /drives/{d}/root/delta?token=latest` → 200 com `deltaLink` e `value: []`
  5. `GET /drives/{d}/items/{folderId}/delta` → funciona? (decide se D-A7 é necessário ou só otimização)
  6. delta sem `path` em `parentReference`; presença de `parentReference.driveId`
  7. `GET /sites/root?$select=siteCollection` → hostname
- [ ] Step 4 — Critério de saída: se (5) funcionar **e** o custo do snapshot inicial for aceitável, manter D-A7 (mais robusto); senão idem. Registrar a decisão no doc. Commit: `git add docs/integracoes/sharepoint-spike-tenant-teste.md && git commit -m "docs(sharepoint): resultados do spike no tenant de teste"`.

### Task A0.2: Iniciar verificação de publisher Microsoft (lead time)

**Files:** Modify `docs/integracoes/sharepoint-spike-tenant-teste.md` (seção "Publisher verification")

- [ ] Step 1 — Depende de P0 (domínio) e de conta no programa de parceiros Microsoft (MPN/Cloud Partner Program) [VALIDAR requisitos atuais na doc — §7]. Abrir o processo **agora**: é o item de prazo incerto da Parte A.
- [ ] Step 2 — Registrar data de início, responsável e status no doc. Sem código.

### Task A0.3: Teste de caracterização da projeção com dois espaços na mesma fonte

**Files:** Test `backend/tests/unit/test_company_library.py` (adicionar) — não altera código de produção
**Interfaces:** Consumes: `LibraryService.project_successful_sync(organization_id, source, documents, folders)` (`library/service.py:704`).

- [ ] Step 1 — Escrever teste `test_projection_of_a_second_sync_keeps_or_drops_nodes_of_other_workspace` que: cria fonte, projeta docs `a1` (espaço A); projeta docs `b1` (espaço B, mesma fonte); asserta o estado **observado**. Rodar `cd backend && pytest tests/unit/test_company_library.py -k second_sync -q`.
- [ ] Step 2 — O teste documenta o comportamento atual (passa de qualquer jeito). Se `a1` some após projetar `b1`, abrir item em `specs/security-hardening-followups.md` ("projeção apaga nós de outros espaços") e **bloquear o rollout multi-espaço do SharePoint** até resolver (risco R-A2). Commit: `git commit -m "test(library): caracteriza projeção entre espaços da mesma fonte"`.

---

## A.6 Fase A1 — Parametrizar o conector OneDrive (sem mudar comportamento) (0,5 d)

### Task A1: atributos de classe e ponto de vínculo de identidade

**Files:** Modify `backend/app/integrations/onedrive.py:38,142-199,574,623-660,721-771,798-866` · Test `backend/tests/unit/test_onedrive.py` (adicionar 1 teste), suítes OneDrive existentes
**Interfaces:** Produces: `MicrosoftGraphClient.AUTHORITY: str`, `MicrosoftGraphClient.SCOPES: str`; `OneDriveDocumentProvider.max_workers: int`; `OneDriveConnectionService.provider_key: str = "onedrive"` e `OneDriveConnectionService.bind_identity(self, credentials: OneDriveCredentials) -> str` (padrão = `self.client.drive_id(credentials=credentials)`); 503 tratado como 429.

- [ ] Step 1 — Teste que trava o comportamento atual (adicionar ao fim de `backend/tests/unit/test_onedrive.py`):

```python
def test_onedrive_client_defaults_are_unchanged_by_parametrization() -> None:
    client = MicrosoftGraphClient(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
    assert MicrosoftGraphClient.AUTHORITY == MICROSOFT_AUTHORITY
    assert MicrosoftGraphClient.SCOPES == GRAPH_SCOPES
    assert httpx.URL(client.authorization_url(state="s")).path == "/common/oauth2/v2.0/authorize"
    assert OneDriveDocumentProvider.max_workers == 4


def test_graph_json_retries_503_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.integrations.onedrive.time.sleep", sleeps.append)
    url = f"{GRAPH_ROOT}/me/drive?$select=id"
    responses = iter([
        httpx.Response(503, headers={"Retry-After": "2"}, request=httpx.Request("GET", url)),
        _http_response(url, {"id": "drive-1"}),
    ])
    monkeypatch.setattr("app.integrations.onedrive.httpx.get", lambda *a, **k: next(responses))
    client = MicrosoftGraphClient(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
    creds = OneDriveCredentials("t", "r", datetime.now(UTC) + timedelta(hours=1))
    assert client.drive_id(credentials=creds) == "drive-1"
    assert sleeps == [2.0]
```

- [ ] Step 2 — Run `cd backend && pytest tests/unit/test_onedrive.py -k "unchanged_by_parametrization or retries_503" -q` → expected: FAIL `AttributeError: type object 'MicrosoftGraphClient' has no attribute 'AUTHORITY'` (e o segundo, sem sleep para 503).
- [ ] Step 3 — Implementação mínima em `onedrive.py`:
  - na classe `MicrosoftGraphClient` (`:128`) adicionar `AUTHORITY = MICROSOFT_AUTHORITY` e `SCOPES = GRAPH_SCOPES`; trocar `MICROSOFT_AUTHORITY`→`self.AUTHORITY` em `:144` e `:182`, e `GRAPH_SCOPES`→`self.SCOPES` em `:151,:163,:173`;
  - em `OneDriveDocumentProvider` (`:424`) adicionar `max_workers = MAX_PAGE_WORKERS` e usar `min(self.max_workers, len(files))` em `:574`;
  - em `_get_json` (`:392`) e `read_file` (`:327`) trocar `response.status_code == 429` por `response.status_code in {429, 503}`;
  - em `OneDriveConnectionService` (`:607`) adicionar `provider_key = "onedrive"`, método `bind_identity` e substituir os literais `"onedrive"` em `:639,:729,:737,:759,:804,:851` por `self.provider_key` (Revisão: linhas corrigidas; se o plano 01 T2.3 já mergeou, o atributo se chama `provider` — herdado de `OAuthConnectionServiceBase` — e `disconnect` (`:798-834`) já saiu da classe), e `drive_id = self.client.drive_id(...)` (`:723`) por `drive_id = self.bind_identity(credentials)`. O nome de variável `drive_id` permanece (grava em `provider_account_id`, `:763,:771`).
- [ ] Step 4 — Run `cd backend && pytest tests/unit/test_onedrive.py tests/api/test_onedrive_integration.py tests/unit/test_onedrive_ingestion_task.py -q && ruff check app/integrations` → expected: PASS (nenhuma mudança de contrato).
- [ ] Step 5 — `git add backend/app/integrations/onedrive.py backend/tests/unit/test_onedrive.py && git commit -m "refactor(onedrive): parametriza autoridade, escopos e vínculo; retry também em 503"`.

---

## A.7 Fase A2 — Cliente Graph do SharePoint (novo módulo) (1–1,5 d)

### Task A2: IDs compostos, autorização e catálogo de sites/bibliotecas

**Files:** Create `backend/app/integrations/sharepoint.py` · Test `backend/tests/unit/test_sharepoint.py`
**Interfaces:** Consumes: `MicrosoftGraphClient` (A1), `RemoteFolder` (`integrations/google_drive.py:69`). Produces:
`composite_id(drive_id: str, item_id: str) -> str` · `split_composite(value: str) -> tuple[str, str]` · `site_node_id(site_id: str) -> str` · `is_site_node(value: str) -> bool` · `SharePointIdInvalid(ValueError)` · `SHAREPOINT_AUTHORITY`, `SHAREPOINT_SCOPES` · `SharePointGraphClient.catalog(*, credentials) -> list[RemoteFolder]` · `SharePointGraphClient.tenant_hostname(*, credentials) -> str`.

- [ ] Step 1 — Teste falhando (`backend/tests/unit/test_sharepoint.py`):

```python
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import GRAPH_ROOT, OneDriveCredentials
from app.integrations.sharepoint import (
    SHAREPOINT_SCOPES,
    SharePointGraphClient,
    SharePointIdInvalid,
    composite_id,
    is_site_node,
    site_node_id,
    split_composite,
)

CREDS = OneDriveCredentials("token", "refresh", datetime.now(UTC) + timedelta(hours=1))


class FakeGraph(SharePointGraphClient):
    """Routes Graph GETs by URL suffix; records every call."""

    def __init__(self, routes: dict[str, dict]) -> None:
        super().__init__(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
        self.routes, self.calls = routes, []

    def _get_json(self, url, *, credentials, allow_expired_delta=False):
        path = url.removeprefix(GRAPH_ROOT)
        self.calls.append(path)
        if path not in self.routes:
            raise AssertionError(f"unexpected Graph call: {path}")
        return self.routes[path]


def test_composite_id_roundtrips_drive_ids_that_contain_a_bang() -> None:
    value = composite_id("b!AbC-dEf_123", "01ITEM")
    assert value == "b!AbC-dEf_123|01ITEM"
    assert split_composite(value) == ("b!AbC-dEf_123", "01ITEM")


@pytest.mark.parametrize("bad", ["", "01ITEM", "|01ITEM", "b!x|", "site|abc,1,2"])
def test_split_composite_rejects_plain_empty_or_site_node_values(bad: str) -> None:
    with pytest.raises(SharePointIdInvalid):
        split_composite(bad)


def test_authorization_url_uses_organizations_authority_and_read_only_scopes() -> None:
    client = SharePointGraphClient(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
    url = httpx.URL(client.authorization_url(state="st"))
    assert url.path == "/organizations/oauth2/v2.0/authorize"
    scopes = set(url.params["scope"].split())
    assert scopes == set(SHAREPOINT_SCOPES.split())
    assert "Sites.Read.All" in scopes
    assert not [s for s in scopes if "ReadWrite" in s or "FullControl" in s or s == "Files.Read.All"]


def test_catalog_lists_sites_and_document_libraries_with_composite_ids() -> None:
    site = "contoso.sharepoint.com,g1,g2"
    client = FakeGraph({
        "/sites?search=*&$select=id,displayName,webUrl": {
            "value": [{"id": site, "displayName": "Jurídico", "webUrl": "https://contoso.sharepoint.com/sites/j"}]},
        f"/sites/{site}/drives?$select=id,name,driveType": {
            "value": [{"id": "b!d1", "name": "Documentos", "driveType": "documentLibrary"},
                      {"id": "b!d2", "name": "Ativos", "driveType": "other"}]},
        "/drives/b%21d1/root?$select=id": {"id": "01ROOT"},
    })
    assert client.catalog(credentials=CREDS) == [
        RemoteFolder(site_node_id(site), "Jurídico", ()),
        RemoteFolder("b!d1|01ROOT", "Documentos", (site_node_id(site),)),
    ]
    assert is_site_node(site_node_id(site))


def test_catalog_skips_sites_without_document_libraries_and_deduplicates() -> None:
    site = "contoso.sharepoint.com,g1,g2"
    client = FakeGraph({
        "/sites?search=*&$select=id,displayName,webUrl": {
            "value": [{"id": site, "displayName": "A"}, {"id": site, "displayName": "A"}]},
        f"/sites/{site}/drives?$select=id,name,driveType": {"value": []},
    })
    assert client.catalog(credentials=CREDS) == []
    assert client.calls.count(f"/sites/{site}/drives?$select=id,name,driveType") == 1
```

- [ ] Step 2 — Run `cd backend && pytest tests/unit/test_sharepoint.py -q` → expected: FAIL `ModuleNotFoundError: No module named 'app.integrations.sharepoint'`.
- [ ] Step 3 — Implementação (`backend/app/integrations/sharepoint.py`, parte 1):

```python
"""Microsoft 365 / SharePoint Online document libraries over delegated Microsoft Graph."""

from typing import Any
from urllib.parse import quote

from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import (
    GRAPH_ROOT,
    MicrosoftGraphClient,
    OneDriveCredentials,
    OneDriveOAuthInvalid,
)

# SharePoint does not exist for personal accounts; work/school only.
SHAREPOINT_AUTHORITY = "https://login.microsoftonline.com/organizations/oauth2/v2.0"
SHAREPOINT_SCOPES = "openid profile offline_access User.Read Sites.Read.All"
COMPOSITE_SEP = "|"
SITE_PREFIX = "site"
ITEM_SELECT = "id,name,size,file,folder,parentReference,webUrl,lastModifiedDateTime,deleted"


class SharePointIdInvalid(ValueError):
    pass


def composite_id(drive_id: str, item_id: str) -> str:
    if not drive_id or not item_id or COMPOSITE_SEP in drive_id or COMPOSITE_SEP in item_id:
        raise SharePointIdInvalid("invalid SharePoint identifier")
    return f"{drive_id}{COMPOSITE_SEP}{item_id}"


def is_site_node(value: str) -> bool:
    return value.startswith(f"{SITE_PREFIX}{COMPOSITE_SEP}")


def site_node_id(site_id: str) -> str:
    return f"{SITE_PREFIX}{COMPOSITE_SEP}{site_id}"


def split_composite(value: str) -> tuple[str, str]:
    drive_id, sep, item_id = value.partition(COMPOSITE_SEP)
    if is_site_node(value) or not sep or not drive_id or not item_id or COMPOSITE_SEP in item_id:
        raise SharePointIdInvalid("invalid SharePoint identifier")
    return drive_id, item_id


def _drive(drive_id: str) -> str:
    return quote(drive_id, safe="")


class SharePointGraphClient(MicrosoftGraphClient):
    AUTHORITY = SHAREPOINT_AUTHORITY
    SCOPES = SHAREPOINT_SCOPES

    @staticmethod
    def _external_id(item: dict[str, Any], *, fallback_drive_id: str | None = None) -> str:
        parent = item.get("parentReference") or {}
        return composite_id(
            str(parent.get("driveId") or fallback_drive_id or ""), str(item.get("id") or "")
        )

    @staticmethod
    def _parent_ids(parent: dict[str, Any]) -> tuple[str, ...]:
        drive_id, parent_id = parent.get("driveId"), parent.get("id")
        return (composite_id(str(drive_id), str(parent_id)),) if drive_id and parent_id else ()

    def tenant_hostname(self, *, credentials: OneDriveCredentials) -> str:
        data = self._get_json(
            f"{GRAPH_ROOT}/sites/root?$select=siteCollection", credentials=credentials
        )
        hostname = (data.get("siteCollection") or {}).get("hostname")
        if not isinstance(hostname, str) or not hostname:
            raise OneDriveOAuthInvalid("Microsoft tenant response is invalid")
        return hostname.lower()

    def _sites(self, credentials: OneDriveCredentials) -> list[dict[str, Any]]:
        rows = self._all_pages(
            f"{GRAPH_ROOT}/sites?search=*&$select=id,displayName,webUrl", credentials=credentials
        )
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("id"):
                unique.setdefault(str(row["id"]), row)
        return list(unique.values())

    def catalog(self, *, credentials: OneDriveCredentials, max_sites: int = 200) -> list[RemoteFolder]:
        nodes: list[RemoteFolder] = []
        for site in self._sites(credentials)[:max_sites]:
            site_id = str(site["id"])
            drives = [
                drive
                for drive in self._all_pages(
                    f"{GRAPH_ROOT}/sites/{quote(site_id, safe=',')}/drives?$select=id,name,driveType",
                    credentials=credentials,
                )
                if drive.get("driveType") == "documentLibrary" and drive.get("id")
            ]
            if not drives:
                continue
            node = site_node_id(site_id)
            nodes.append(RemoteFolder(node, str(site.get("displayName") or "Site"), ()))
            for drive in drives:
                drive_id = str(drive["id"])
                root = self._get_json(
                    f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root?$select=id", credentials=credentials
                )
                nodes.append(
                    RemoteFolder(
                        composite_id(drive_id, str(root.get("id") or "")),
                        str(drive.get("name") or "Documentos"),
                        (node,),
                    )
                )
        return nodes
```

- [ ] Step 4 — Run `cd backend && pytest tests/unit/test_sharepoint.py -q && ruff check app/integrations/sharepoint.py` → expected: PASS. (O `_all_pages` herdado, `onedrive.py:347-360`, valida links `@odata.nextLink`.)
- [ ] Step 5 — `git add backend/app/integrations/sharepoint.py backend/tests/unit/test_sharepoint.py && git commit -m "feat(sharepoint): IDs compostos, autoridade organizations e catálogo de sites/bibliotecas"`.

---

## A.8 Fase A3 — Travessia, delta por raiz e pertencimento (1–1,5 d)

### Task A3: `list_files`, `latest_delta_link`, `delta_root`, `within_scope`, `read_file`, `get_item`

**Files:** Modify `backend/app/integrations/sharepoint.py` · Test `backend/tests/unit/test_sharepoint.py`
**Interfaces:** Consumes: A2. Produces (todos em `SharePointGraphClient`; `credentials: OneDriveCredentials`, `scope_id: str` = ID composto da raiz do escopo):
`list_files(*, credentials, scope_id) -> list[dict]` · `latest_delta_link(*, credentials, drive_id) -> str` · `delta_root(*, credentials, drive_id, cursor: str | None) -> DeltaPage` · `within_scope(*, credentials, drive_id, parent_id, scope_item_id, cache: dict[str, bool]) -> bool` · `read_file(*, credentials, item_id) -> bytes` (aceita ID composto) · `get_item(*, credentials, item_id) -> dict | None`.

- [ ] Step 1 — Testes falhando (acrescentar em `test_sharepoint.py`):

```python
from app.integrations.onedrive import DeltaPage, OneDriveDeltaExpired

DRIVE = "b!d1"


def test_list_files_walks_children_and_returns_only_files_with_composite_parents() -> None:
    client = FakeGraph({
        f"/drives/b%21d1/items/01ROOT/children?$select={ITEM_SELECT}&$top=200": {"value": [
            {"id": "01F", "name": "Contratos", "folder": {}, "parentReference": {"driveId": DRIVE, "id": "01ROOT"}},
            {"id": "01A", "name": "a.pdf", "file": {"mimeType": "application/pdf"},
             "parentReference": {"driveId": DRIVE, "id": "01ROOT"}}]},
        f"/drives/b%21d1/items/01F/children?$select={ITEM_SELECT}&$top=200": {"value": [
            {"id": "01B", "name": "b.docx", "file": {"mimeType": "x"},
             "parentReference": {"driveId": DRIVE, "id": "01F"}}]},
    })
    items = client.list_files(credentials=CREDS, scope_id="b!d1|01ROOT")
    assert sorted(client._external_id(i) for i in items) == ["b!d1|01A", "b!d1|01B"]
    assert client._parent_ids(items[0]["parentReference"])[0].startswith("b!d1|")


def test_latest_delta_link_uses_token_latest_and_validates_graph_host() -> None:
    link = f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=abc"
    client = FakeGraph({"/drives/b%21d1/root/delta?token=latest": {"value": [], "@odata.deltaLink": link}})
    assert client.latest_delta_link(credentials=CREDS, drive_id=DRIVE) == link


def test_within_scope_walks_parents_once_and_memoizes() -> None:
    client = FakeGraph({
        "/drives/b%21d1/items/01C?$select=id,parentReference": {"id": "01C", "parentReference": {"id": "01B"}},
        "/drives/b%21d1/items/01B?$select=id,parentReference": {"id": "01B", "parentReference": {"id": "01S"}},
    })
    cache: dict[str, bool] = {}
    kwargs = dict(credentials=CREDS, drive_id=DRIVE, scope_item_id="01S", cache=cache)
    assert client.within_scope(parent_id="01C", **kwargs) is True
    assert client.within_scope(parent_id="01B", **kwargs) is True  # served from cache
    assert len(client.calls) == 2


def test_within_scope_is_false_when_reaching_the_drive_root_or_a_missing_parent() -> None:
    client = FakeGraph({
        "/drives/b%21d1/items/01X?$select=id,parentReference": {"id": "01X", "parentReference": {"id": "01ROOT"}},
    })
    assert client.within_scope(credentials=CREDS, drive_id=DRIVE, parent_id="01X",
                               scope_item_id="01S", drive_root_id="01ROOT", cache={}) is False


def test_delta_root_raises_expired_on_410() -> None:
    class Gone(FakeGraph):
        def _get_json(self, url, *, credentials, allow_expired_delta=False):
            assert allow_expired_delta is True
            raise OneDriveDeltaExpired()
    with pytest.raises(OneDriveDeltaExpired):
        Gone({}).delta_root(credentials=CREDS, drive_id=DRIVE, cursor=f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=old")
```

(importar `ITEM_SELECT` de `app.integrations.sharepoint`; `within_scope` recebe também `drive_root_id: str | None = None`.)

- [ ] Step 2 — Run `cd backend && pytest tests/unit/test_sharepoint.py -q` → expected: FAIL `AttributeError: 'FakeGraph' object has no attribute 'list_files'`.
- [ ] Step 3 — Implementação (acrescentar à classe `SharePointGraphClient`):

```python
    def list_files(self, *, credentials, scope_id: str) -> list[dict[str, Any]]:
        drive_id, root_item = split_composite(scope_id)
        pending, visited, files = [root_item], set(), {}
        while pending:
            parent = pending.pop()
            if parent in visited:
                continue
            visited.add(parent)
            url = f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(parent, safe='')}/children?$select={ITEM_SELECT}&$top=200"
            for item in self._all_pages(url, credentials=credentials):
                if isinstance(item.get("folder"), dict):
                    pending.append(str(item.get("id") or ""))
                elif "file" in item:
                    files[self._external_id(item, fallback_drive_id=drive_id)] = item
        return list(files.values())

    def latest_delta_link(self, *, credentials, drive_id: str) -> str:
        data = self._get_json(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root/delta?token=latest", credentials=credentials
        )
        link = data.get("@odata.deltaLink")
        if not isinstance(link, str):
            raise OneDriveOAuthInvalid("Microsoft delta response is invalid")
        return self._validate_graph_url(link)

    def delta_root(self, *, credentials, drive_id: str, cursor: str | None) -> "DeltaPage":
        from app.integrations.onedrive import DeltaPage

        url = cursor or f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root/delta?$select={ITEM_SELECT}"
        items: list[dict[str, Any]] = []
        while url:
            data = self._get_json(url, credentials=credentials, allow_expired_delta=True)
            items.extend(i for i in data.get("value") or [] if isinstance(i, dict))
            if isinstance(data.get("@odata.nextLink"), str):
                url = self._validate_graph_url(data["@odata.nextLink"])
            elif isinstance(data.get("@odata.deltaLink"), str):
                return DeltaPage(items, self._validate_graph_url(data["@odata.deltaLink"]))
            else:
                raise OneDriveOAuthInvalid("Microsoft delta response is incomplete")
        raise OneDriveOAuthInvalid("Microsoft delta response is incomplete")

    def get_item(self, *, credentials, item_id: str) -> dict[str, Any] | None:
        drive_id, raw = split_composite(item_id)
        return self._get_or_none(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(raw, safe='')}?$select={ITEM_SELECT}",
            credentials,
        )

    def _get_or_none(self, url: str, credentials) -> dict[str, Any] | None:
        import httpx

        try:
            return self._get_json(url, credentials=credentials)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return None
            raise

    def within_scope(self, *, credentials, drive_id: str, parent_id: str, scope_item_id: str,
                     cache: dict[str, bool], drive_root_id: str | None = None) -> bool:
        chain, current, result = [], parent_id, False
        for _ in range(64):  # depth guard against cycles
            if not current:
                break
            if current in cache:
                result = cache[current]
                break
            if current == scope_item_id:
                result = True
                break
            if current == drive_root_id:
                break
            chain.append(current)
            data = self._get_or_none(
                f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(current, safe='')}?$select=id,parentReference",
                credentials,
            )
            current = str(((data or {}).get("parentReference") or {}).get("id") or "")
        for node in chain:
            cache[node] = result
        return result

    def read_file(self, *, credentials, item_id: str) -> bytes:
        drive_id, raw = split_composite(item_id)
        return self._download(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(raw, safe='')}/content", credentials
        )
```

(`_download` = corpo atual de `MicrosoftGraphClient.read_file` (`onedrive.py:316-336`) extraído para método reutilizável com `url`; **mover, não copiar**, e o `read_file` do OneDrive passa a chamar `self._download`. Rodar suítes OneDrive no Step 4.)

- [ ] Step 4 — Run `cd backend && pytest tests/unit/test_sharepoint.py tests/unit/test_onedrive.py -q` → expected: PASS.
- [ ] Step 5 — `git add backend/app/integrations/sharepoint.py backend/app/integrations/onedrive.py backend/tests/unit/test_sharepoint.py && git commit -m "feat(sharepoint): travessia, delta por raiz e filtro de pertencimento"`.

---

## A.9 Fase A4 — Provider e discover (1–1,5 d)

### Task A4: `SharePointDocumentProvider.discover` / `folders_for_selections`

**Files:** Modify `backend/app/integrations/sharepoint.py`, `backend/app/integrations/onedrive.py:592-596` (guarda de tamanho, via hook) · Test `backend/tests/unit/test_sharepoint.py`
**Interfaces:** Consumes: A2, A3, `OneDriveDocumentProvider` (`onedrive.py:424-604`), `DiscoveryResult` (`ingestion/service.py:60`), `WorkspaceFolderSelection` (`kind == "folder"`, `external_folder_id` = ID composto da raiz do escopo). Produces: `SharePointDocumentProvider(client, cipher)` com `key = "sharepoint"`, `max_workers` configurável, `discover(...)`, `folders(*, encrypted_credentials)` (catálogo para a UI/validação) e `folders_for_selections(*, encrypted_credentials, selections) -> list[RemoteFolder]` (nós para a projeção).

- [ ] Step 1 — Testes falhando (provider com cliente fake; sem rede). Casos obrigatórios, um teste por linha:
  1. `test_first_sync_takes_latest_token_before_traversal_and_returns_full_snapshot` — sem cursor: `calls` mostra `…/root/delta?token=latest` **antes** de `…/children`; resultado `full_snapshot=True`, `delta_links[sel.id] == link`.
  2. `test_incremental_delta_reads_only_changed_file_inside_scope` — cursor presente; delta traz 1 arquivo dentro do escopo e 1 fora → só o de dentro em `documents`; o de fora em `removed_file_ids`.
  3. `test_moved_out_of_scope_file_is_reported_as_removed` — arquivo cujo `within_scope` dá False → `removed_file_ids`.
  4. `test_deleted_item_is_removed_without_membership_calls` — item com `deleted` → removido, zero chamadas `get_item`.
  5. `test_folder_event_inside_scope_forces_snapshot` — delta com pasta dentro → `full_snapshot=True` e travessia executada.
  6. `test_expired_cursor_falls_back_to_snapshot_with_new_token` — `OneDriveDeltaExpired` → snapshot, `delta_links` novos.
  7. `test_library_root_scope_skips_membership_calls` — seleção = raiz da biblioteca → nenhuma chamada `get_item`.
  8. `test_force_file_ids_reads_unchanged_file_when_in_scope_and_removes_when_gone` (reprocesso manual, espelha `test_onedrive_manual_reprocess_forces_item_read_without_delta_change`, `test_onedrive.py:578`).
  9. `test_oversized_file_becomes_file_too_large_without_download` — `size > max_file_bytes` → `DiscoveredDocument(error_code="file_too_large")` e `read_file` não chamado.
  10. `test_folders_for_selections_returns_site_library_and_folder_nodes_only_for_selected_drives`.
  Escrever o corpo completo de cada teste no arquivo seguindo o modelo do teste 1 abaixo (fake `FakeGraph` estendido com `delta_root/latest_delta_link/list_files/within_scope` em memória):

```python
def test_first_sync_takes_latest_token_before_traversal_and_returns_full_snapshot() -> None:
    order: list[str] = []
    graph = InMemoryGraph(
        files=[{"id": "01A", "name": "a.pdf", "file": {"mimeType": "application/pdf"}, "size": 10,
                "webUrl": "https://c.sharepoint.com/a.pdf", "lastModifiedDateTime": "2026-09-01T10:00:00+00:00",
                "parentReference": {"driveId": "b!d1", "id": "01ROOT"}}],
        latest="https://graph.microsoft.com/v1.0/drives/b%21d1/root/delta?token=T1", order=order,
    )
    provider = make_provider(graph)   # cifra real + credenciais válidas, extrator fake
    selection = fake_selection(external_folder_id="b!d1|01ROOT", encrypted_delta_link=None)
    result = provider.discover(encrypted_credentials=provider.cipher.encrypt_credentials(CREDS),
                               selections=[selection])
    assert order == ["latest", "children"]
    assert result.full_snapshot is True
    assert [d.external_file_id for d in result.documents] == ["b!d1|01A"]
    assert result.documents[0].parent_ids == ("b!d1|01ROOT",)
    assert result.delta_links == {selection.id: graph.latest}
```

- [ ] Step 2 — Run `cd backend && pytest tests/unit/test_sharepoint.py -q` → expected: FAIL `ImportError: cannot import name 'SharePointDocumentProvider'`.
- [ ] Step 3 — Implementação (`sharepoint.py`, parte final; código completo):

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.ingestion.service import DiscoveredDocument, DiscoveryResult
from app.integrations.onedrive import OneDriveCipher, OneDriveCursorInvalid, OneDriveDeltaExpired, OneDriveDocumentProvider


class SharePointDocumentProvider(OneDriveDocumentProvider):
    key = "sharepoint"
    max_workers = 2
    max_file_bytes = 50 * 1024 * 1024

    def folders(self, *, encrypted_credentials):
        return self.client.catalog(credentials=self._credentials(encrypted_credentials))

    def folders_for_selections(self, *, encrypted_credentials, selections):
        credentials = self._credentials(encrypted_credentials)
        wanted = {split_composite(s.external_folder_id)[0] for s in selections}
        return [
            node for node in self.client.catalog(credentials=credentials)
            if is_site_node(node.id) or split_composite(node.id)[0] in wanted
        ] + self._folder_nodes(credentials, wanted)

    def _folder_nodes(self, credentials, drive_ids):
        nodes = []
        for drive_id in sorted(drive_ids):
            for item in self.client.list_folders(credentials=credentials, drive_id=drive_id):
                nodes.append(RemoteFolder(
                    self.client._external_id(item, fallback_drive_id=drive_id),
                    str(item.get("name") or "Untitled"),
                    self.client._parent_ids(item.get("parentReference") or {}),
                ))
        return nodes

    def discover(self, *, encrypted_credentials, selections, force_file_ids=None, force_full=False):
        credentials = self._credentials(encrypted_credentials)
        changes: dict[str, dict] = {}
        removals: set[str] = set()
        links: dict[UUID, str | None] = {}
        snapshot = force_full or any(not s.encrypted_delta_link for s in selections)
        if not snapshot:
            try:
                for selection in selections:
                    drive_id, scope_item = split_composite(selection.external_folder_id)
                    page = self.client.delta_root(
                        credentials=credentials, drive_id=drive_id,
                        cursor=self.cipher.decrypt_cursor(selection.encrypted_delta_link),
                    )
                    links[selection.id] = page.delta_link
                    root_id = self.client.drive_root_id(credentials=credentials, drive_id=drive_id)
                    cache: dict[str, bool] = {}
                    sel_changes, sel_removals = {}, set()
                    for item in page.items:
                        ext = self.client._external_id(item, fallback_drive_id=drive_id)
                        if "deleted" in item:
                            sel_changes.pop(ext, None)
                            sel_removals.add(ext)
                            snapshot = snapshot or isinstance(item.get("folder"), dict)
                            continue
                        parent_id = str((item.get("parentReference") or {}).get("id") or "")
                        inside = scope_item == root_id or item.get("id") == scope_item or (
                            self.client.within_scope(
                                credentials=credentials, drive_id=drive_id, parent_id=parent_id,
                                scope_item_id=scope_item, drive_root_id=root_id, cache=cache)
                        )
                        if isinstance(item.get("folder"), dict):
                            snapshot = snapshot or inside
                        elif "file" in item and inside:
                            sel_removals.discard(ext)
                            sel_changes[ext] = item
                        elif "file" in item:
                            sel_changes.pop(ext, None)
                            sel_removals.add(ext)
                    changes.update(sel_changes)
                    removals.update(sel_removals)
                    removals.difference_update(changes)
            except (OneDriveCursorInvalid, OneDriveDeltaExpired):
                snapshot = True
        if snapshot:
            files: dict[str, dict] = {}
            links = {}
            for selection in selections:
                drive_id, _ = split_composite(selection.external_folder_id)
                links[selection.id] = self.client.latest_delta_link(credentials=credentials, drive_id=drive_id)
                for item in self.client.list_files(credentials=credentials, scope_id=selection.external_folder_id):
                    files[self.client._external_id(item)] = item
            changes, removals = files, set()
        pending = (force_file_ids or set()) - set(changes) - removals
        for ext in pending:
            item = self.client.get_item(credentials=credentials, item_id=ext)
            if item is None or "file" not in item:
                removals.add(ext)
            else:
                changes[ext] = item
        return DiscoveryResult(
            documents=self._read_changed(credentials, changes),
            removed_file_ids=tuple(sorted(removals)),
            delta_links=links,
            full_snapshot=snapshot,
        )
```

  Notas de implementação **obrigatórias** (não são placeholders — são partes do código a escrever nesta task):
  - adicionar em `SharePointGraphClient`: `drive_root_id(*, credentials, drive_id) -> str` (`GET /drives/{d}/root?$select=id`, já usado no catálogo — fatorar) e `list_folders(*, credentials, drive_id) -> list[dict]` (travessia `children` que devolve só itens com facet `folder`);
  - `pending` de `force_file_ids`: verificar pertencimento com `within_scope` além de `get_item` (reprocesso não pode trazer arquivo fora do escopo; teste 8 cobre);
  - **guarda de tamanho**: em `OneDriveDocumentProvider._read_one` (`onedrive.py:592-594`) inserir, antes de `read_file`, `if self.max_file_bytes and int(item.get("size") or 0) > self.max_file_bytes: return DiscoveredDocument(**base, error_code="file_too_large")`; no `OneDriveDocumentProvider` `max_file_bytes = 0` (desligado → comportamento OneDrive inalterado). Verificar que `error_code` desconhecido vira `failed` sem quebrar (`ingestion/service.py:503-506` trata `discovered.error_code`);
  - `_credentials`, cifra e refresh são herdados (`onedrive.py:431-444`); `updated_encrypted_credentials` idem.
- [ ] Step 4 — Run `cd backend && pytest tests/unit/test_sharepoint.py tests/unit/test_onedrive.py tests/unit/test_onedrive_ingestion_task.py -q && ruff check app/integrations` → expected: PASS.
- [ ] Step 5 — `git add backend/app/integrations/sharepoint.py backend/app/integrations/onedrive.py backend/tests/unit/test_sharepoint.py && git commit -m "feat(sharepoint): provider com delta por raiz, snapshot com token latest e limite de tamanho"`.

---

## A.10 Fase A5 — Registry, worker, serviço OAuth e API (1 d)

### Task A5.1: serviço de conexão + vínculo de tenant + migração

**Files:** Modify `backend/app/integrations/sharepoint.py` · Create `backend/alembic/versions/AAAAMMDD_0022_sharepoint_tenant_binding.py` · Test `backend/tests/api/test_sharepoint_integration.py`
**Interfaces:** Consumes: `OneDriveConnectionService` (A1). Produces: `SharePointConnectionService(session, cipher, client)` com `provider_key="sharepoint"`, `bind_identity(credentials) -> str` (= `client.tenant_hostname`), reaproveitando `OneDriveAccountMismatch`, `OneDriveOAuthInvalid`, `OneDriveAccessDenied`, `OneDriveReauthRequired`.

- [ ] Step 1 — Teste falhando (`test_sharepoint_integration.py`), copiando a fixture `onedrive_api` (`test_onedrive_integration.py:38-200`) para `sharepoint_api` com: `microsoft_oauth_redirect_uri` de OneDrive **e** `microsoft_sharepoint_redirect_uri="http://app.example.test/data-sources/sharepoint/oauth/callback"`, token endpoint `…/organizations/oauth2/v2.0/token`. Casos:
  1. `test_sharepoint_oauth_hashes_state_encrypts_credentials_and_binds_tenant` (espelha `test_onedrive_oauth_hashes_state…:205`): após callback, `DataSource.provider == "sharepoint"`, `provider_account_id == "contoso.sharepoint.com"`, credenciais não em claro.
  2. `test_sharepoint_reconnect_to_other_tenant_is_rejected_with_html_redirect` (espelha `:407`): redireciona `?error=sharepoint_tenant_mismatch`.
  3. `test_member_cannot_start_sharepoint_oauth` (espelha `:442`) → 403.
  4. `test_sharepoint_source_of_org_a_is_invisible_to_org_b_owner` (espelha `:489`).
  5. `test_second_source_for_same_tenant_in_same_org_violates_unique_index` (usa a migração via metadata: o índice parcial precisa estar em `__table_args__` de `DataSource`? — **não**: SQLite dos testes usa `Base.metadata`; declarar o índice também em `integrations/models.py` com `Index(..., postgresql_where=..., sqlite_where=...)`).
- [ ] Step 2 — Run `cd backend && pytest tests/api/test_sharepoint_integration.py -q` → expected: FAIL (`404 /data-sources/sharepoint/oauth/start`).
- [ ] Step 3 — Implementar: `class SharePointConnectionService(OneDriveConnectionService)` (5 linhas: atributo + `bind_identity`); migração:

```python
"""One SharePoint data source per organization and Microsoft tenant."""

import sqlalchemy as sa
from alembic import op

revision = "AAAAMMDD_0022"  # Revisão: era "20260930_0019" (colidia com os planos 01 e 03)
down_revision = "<saída de `alembic heads` no merge; esperado AAAAMMDD_0021 (pgvector_contract do plano 01)>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_data_sources_sharepoint_tenant",
        "data_sources",
        ["organization_id", "provider_account_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'sharepoint' AND provider_account_id IS NOT NULL"),
        sqlite_where=sa.text("provider = 'sharepoint' AND provider_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_data_sources_sharepoint_tenant", table_name="data_sources")
```

  e o mesmo `Index(...)` em `backend/app/integrations/models.py` (após `DataSource`). Índice **parcial só para `sharepoint`**: não toca linhas existentes (Google/OneDrive/Notion) → migração segura e reversível.
- [ ] Step 4 — (a API vem em A5.2; este passo roda só os testes 1–2 unitários de serviço se a rota ainda não existir) Run `cd backend && pytest tests/unit/test_migration_sql.py tests/integration/test_foundation_migration.py -q` → PASS (a migração aplica em Postgres de teste, se disponível; caso contrário o passo é registrado como não executado).
- [ ] Step 5 — `git add backend/app/integrations/sharepoint.py backend/app/integrations/models.py backend/alembic/versions/AAAAMMDD_0022_sharepoint_tenant_binding.py backend/tests/api/test_sharepoint_integration.py && git commit -m "feat(sharepoint): serviço de conexão e vínculo único por tenant"`.

### Task A5.2: config, registry, rotas OAuth e ramos da API

**Files:** Modify `backend/app/core/config.py:43-46`, `backend/app/integrations/registry.py:126-132`, `backend/app/api/integrations.py:89-181,352-415,431-502,537-603`, `backend/app/ingestion/tasks.py:315`, `backend/app/library/service.py:779-783` · Test `backend/tests/api/test_sharepoint_integration.py`, `backend/tests/unit/test_sharepoint_ingestion_task.py`, `backend/tests/unit/test_health_and_config.py`
**Interfaces:** Produces: settings `microsoft_sharepoint_redirect_uri: str | None`, `sharepoint_download_workers: int = 2`, `sharepoint_max_file_bytes: int = 52_428_800`, `sharepoint_catalog_max_sites: int = 200`; rotas `GET /data-sources/sharepoint/oauth/start`, `GET /data-sources/sharepoint/oauth/callback`; `IntegrationRegistry.get("sharepoint")`; `scope-catalog` de SharePoint devolve `{"folders":[…], "root_files":{"available":False,…}, "all_accessible":{"available":False,…}}`.

- [ ] Step 1 — Testes falhando: (a) `test_sharepoint_scope_catalog_lists_sites_libraries_and_disables_all_accessible` (`root_files.available is False`, `all_accessible.available is False`, sites com flag `selectable: false`); (b) `test_sharepoint_selection_rejects_all_accessible_and_root_files_with_422`; (c) `test_sharepoint_selection_accepts_library_and_persists_selection_kind_folder`; (d) `test_worker_uses_folders_for_selections_when_provider_supports_it` (em `test_sharepoint_ingestion_task.py`, modelo `test_onedrive_ingestion_task.py`): provider fake com `folders_for_selections`; assert que `project_successful_sync` recebeu os nós dele e que `folders()` **não** foi chamado; (e) `test_provider_without_folders_for_selections_still_uses_folders` (regressão OneDrive/Notion/Google); (f) `test_library_root_label_for_sharepoint` (`library/service.py:779`); (g) `test_sharepoint_settings_defaults`.
- [ ] Step 2 — Run `cd backend && pytest tests/api/test_sharepoint_integration.py tests/unit/test_sharepoint_ingestion_task.py -q` → expected: FAIL.
- [ ] Step 3 — Implementar:
  - `config.py`: 4 campos acima após `:46`.
  - `registry.py`: `SharePointProviderAdapter` (cópia estrutural de `OneDriveProviderAdapter`, `registry.py:86-123`, com `SharePointGraphClient`, `redirect_uri=settings.microsoft_sharepoint_redirect_uri`, cifra `settings.microsoft_token_encryption_key`, `provider.max_workers = settings.sharepoint_download_workers`, `provider.max_file_bytes = settings.sharepoint_max_file_bytes`, `capabilities = ProviderCapabilities(True, True, True)`, delegando também `folders_for_selections`) e `"sharepoint": lambda: SharePointProviderAdapter(settings)` em `:128-132`. **Se o plano 01 já tiver base de adapters, usar a base.**
  - `tasks.py:315`: substituir por
    ```python
    folders_for = getattr(provider, "folders_for_selections", None)
    source_folders = (
        folders_for(encrypted_credentials=source.encrypted_credentials, selections=selections)
        if folders_for
        else provider.folders(encrypted_credentials=source.encrypted_credentials)
    )
    ```
    (`selections` já existe, `tasks.py:263-271`). O provider `sharepoint` cai no ramo `else` de `tasks.py:261-262` (registry) — sem tratamento especial de Google.
  - `api/integrations.py`: fábrica `sharepoint_service(request, session)` (modelo `:89-102`, com `SharePointGraphClient`, `SharePointConnectionService`, `microsoft_sharepoint_redirect_uri`, mesma chave Microsoft); duas rotas clonando `:105-181` com mensagens/`?error=sharepoint|sharepoint_tenant_mismatch|sharepoint_admin_consent` e `?connected=sharepoint`; nos ramos `:366,:400,:466,:563` trocar `== "onedrive"` por `in {"onedrive", "sharepoint"}` escolhendo a fábrica por `source.provider`; em `select_scope` (`:537`) antes de chamar `WorkspaceService.select_scope`: `if selected_source.provider == "sharepoint" and (payload.mode == "all_accessible" or payload.include_root_files): raise ValueError("SharePoint requires explicit libraries or folders")` (o `except ValueError` de `:601-602` devolve 422); `remote` para SharePoint = `provider.folders(...)` **filtrado a nós selecionáveis** (`not is_site_node`) para `available_folder_names`.
  - `scope-catalog` SharePoint: `"folders": [{"id","name","selectable": not is_site_node(id), "parent_ids": [...]}]` (campo extra aditivo; OneDrive/Google não mudam).
  - `library/service.py:779-783`: adicionar `"sharepoint": "SharePoint"`.
- [ ] Step 4 — Run `cd backend && pytest tests/api tests/unit -q && ruff check .` → expected: PASS (suíte inteira; é a proteção contra regressão nos outros providers).
- [ ] Step 5 — `git add backend/app backend/tests && git commit -m "feat(sharepoint): registry, rotas OAuth, catálogo e worker com folders_for_selections"`.

---

## A.11 Fase A6 — Frontend (1 d)

### Task A6: cartão SharePoint, rótulos, erros e lista de bibliotecas

**Files:** Modify `frontend/app/provider-logo.tsx:3,5`, `frontend/app/product-app.tsx:39,733,747-765,780-799` · Test `frontend/tests/provider-labels.test.mjs` (novo) · **antes**: extrair rótulos para função pura em `frontend/app/provider-labels.ts` (novo) para ser testável com o runner atual (`frontend/tests/*.test.mjs` testam módulos puros, ex. `mention-label.ts`)
**Interfaces:** Produces: `providerLabel(provider: string): string` (`google_drive→"Google Drive"`, `onedrive→"OneDrive"`, `notion→"Notion"`, `sharepoint→"SharePoint"`), `oauthErrorMessage(code: string | null): string | null`, tipo `RemoteFolder` com `selectable?: boolean`.

- [ ] Step 1 — Teste falhando `frontend/tests/provider-labels.test.mjs` (formato dos testes existentes: `node:test` + import do módulo TS já usado por `mention-label.test.mjs`):

```js
import test from "node:test";
import assert from "node:assert/strict";
import { providerLabel, oauthErrorMessage } from "../app/provider-labels.ts";

test("providerLabel names every provider", () => {
  assert.equal(providerLabel("sharepoint"), "SharePoint");
  assert.equal(providerLabel("onedrive"), "OneDrive");
  assert.equal(providerLabel("google_drive"), "Google Drive");
  assert.equal(providerLabel("notion"), "Notion");
});

test("oauthErrorMessage explains tenant mismatch and admin consent for SharePoint", () => {
  assert.match(oauthErrorMessage("sharepoint_tenant_mismatch"), /outro tenant|outra organização Microsoft/i);
  assert.match(oauthErrorMessage("sharepoint_admin_consent"), /administrador/i);
  assert.equal(oauthErrorMessage(null), null);
});
```

- [ ] Step 2 — Run `cd frontend && node --test tests/provider-labels.test.mjs` (mesmo runner dos testes atuais) → expected: FAIL `Cannot find module`.
- [ ] Step 3 — Implementar `provider-labels.ts`; em `product-app.tsx` substituir as 4 expressões ternárias duplicadas (`:733,:748,:765,:772`) por `providerLabel(source.provider)`; `connectSharePoint(sourceId?)` clonando `connectOneDrive` (`:747`) com rota `/data-sources/sharepoint/oauth/start`; cartão SharePoint na categoria "Arquivos" ao lado do OneDrive (`:797-799`), texto: "Conecte bibliotecas de documentos de sites SharePoint e Teams da sua organização Microsoft 365. Requer uma conta corporativa/escolar; o administrador do Microsoft 365 pode precisar aprovar o acesso."; `ProviderLogoName` + `labels` + SVG `sharepoint` em `provider-logo.tsx:3,5`; `oauthFailure` (`:141-145`) com os novos códigos; incluir `sharepoint` na condição de auto-abrir catálogo (`:751`: `connectedProvider !== "notion" && !== "onedrive"` → incluir); na lista de escopos: ocultar opções `all_accessible`/`root_files` quando `available === false`, mostrar bibliotecas agrupadas por site (nós `selectable:false` viram cabeçalhos); texto de confirmação de acesso uniforme para SharePoint: "Todos os membros da organização poderão consultar o conteúdo desta biblioteca, mesmo que no SharePoint ele tenha permissões diferentes." Nada a ver com `latestSourcePerProvider` (uma fonte por provider já é o comportamento desejado).
- [ ] Step 4 — Run `cd frontend && node --test tests/provider-labels.test.mjs && npm run lint` → PASS. Verificação visual/responsiva: **depende de liberação do usuário** (o doc de 28/09 registra que a validação no navegador foi interrompida); registrar como pendente no PR.
- [ ] Step 5 — `git add frontend/app frontend/tests && git commit -m "feat(frontend): cartão e catálogo SharePoint, rótulos por provider"`.

---

## A.12 Fase A7 — Refinamentos de UX e escala (opcional, 1 d)

### Task A7: navegação por pastas (lazy) e busca de sites

**Files:** Modify `backend/app/integrations/sharepoint.py`, `backend/app/api/integrations.py` (nova rota `GET /data-sources/{source_id}/scope-catalog/children?parent_id=&organization_id=`), `frontend/app/product-app.tsx` · Test `backend/tests/api/test_sharepoint_integration.py`
**Interfaces:** Produces: `SharePointGraphClient.children_folders(*, credentials, parent_id: str) -> list[RemoteFolder]`; `resolve_folder_names(*, credentials, folder_ids) -> dict[str, str]` para validar seleções de pastas profundas sem enumerar a biblioteca; parâmetro `q` no catálogo (`/sites?search={q}`).

- [ ] Step 1 — Testes: `test_children_endpoint_lists_only_subfolders_of_a_library`, `test_selection_of_deep_folder_is_validated_by_resolving_that_folder_only`, `test_children_endpoint_rejects_foreign_organization_source`.
- [ ] Step 2 — Run → FAIL 404.
- [ ] Step 3 — Implementar; `select_scope` usa `resolve_folder_names` para IDs que não estejam no catálogo raso.
- [ ] Step 4 — Run `cd backend && pytest tests/api/test_sharepoint_integration.py -q` → PASS.
- [ ] Step 5 — Commit `feat(sharepoint): navegação lazy por pastas e busca de sites`.
- **Gate:** só executar se o spike A0 mostrar > ~200 sites/tenant de teste **ou** cliente-âncora tiver bibliotecas grandes (limite `sharepoint_catalog_max_sites`, A.10).

## A.13 Fase A8 — Link de consentimento de administrador (0,5 d)

### Task A8: rota que gera o link de admin consent e recebe o retorno

**Files:** Modify `backend/app/integrations/sharepoint.py`, `backend/app/api/integrations.py`, `frontend/app/product-app.tsx` · Test `backend/tests/api/test_sharepoint_integration.py`
**Interfaces:** Produces: `SharePointGraphClient.admin_consent_url(*, state: str, tenant: str = "organizations") -> str` = `https://login.microsoftonline.com/{tenant}/v2.0/adminconsent?client_id=…&scope=<SHAREPOINT_SCOPES sem openid/profile/offline_access>&redirect_uri=…&state=…`; rotas `GET /data-sources/sharepoint/admin-consent-url?organization_id=` (Owner/Admin; devolve `{"url": …}` e grava `OAuthConnectionState`) e `GET /data-sources/sharepoint/admin-consent/callback` (`admin_consent=True` → redireciona `?admin_consent=done`).

- [ ] Step 1 — Testes: `test_admin_consent_url_contains_client_id_scope_and_hashed_state`; `test_member_cannot_generate_admin_consent_url`; `test_admin_consent_callback_rejects_unknown_state`; `test_admin_consent_callback_redirects_on_success`.
- [ ] Step 2 — Run → FAIL 404.
- [ ] Step 3 — Implementar reaproveitando `OAuthConnectionState` (sem migração). O redirect URI de consentimento **precisa estar registrado** no app Entra (entra no runbook A10). Referência: doc `v2-admin-consent` [ver §7; conteúdo do endpoint não foi aberto nesta sessão — validar parâmetros no spike].
- [ ] Step 4 — Run `cd backend && pytest tests/api/test_sharepoint_integration.py -q` → PASS.
- [ ] Step 5 — Commit `feat(sharepoint): link de consentimento de administrador do Microsoft 365`.

## A.14 Fase A9 — Modo `Sites.Selected` (restrito) (1–1,5 d, **depois** da validação com cliente)

### Task A9: escopo `Sites.Selected` + "adicionar site por URL"

**Files:** Modify `backend/app/integrations/sharepoint.py`, `backend/app/api/integrations.py`, `frontend/app/product-app.tsx`, `backend/app/core/config.py` (`sharepoint_access_mode: Literal["sites_read_all","sites_selected"] = "sites_read_all"`) · Test `backend/tests/unit/test_sharepoint.py`, `backend/tests/api/test_sharepoint_integration.py`
**Interfaces:** Produces: `SHAREPOINT_SCOPES_SELECTED = "openid profile offline_access User.Read Sites.Selected"`; `SharePointGraphClient.site_by_url(*, credentials, web_url: str) -> dict` (`GET /sites/{hostname}:/{server-relative-path}`); catálogo em modo selected = apenas sites adicionados por URL (persistidos como `RemoteFolder` de site em… **decisão em aberto**: onde guardar a lista de sites permitidos? Proposta: coluna JSON `data_sources.provider_settings` (migração: próximo número livre — Revisão: `0020` já é do plano 01) — **decidir no ADR-0016 antes de codar**; sem essa decisão a task não inicia).

- [ ] Step 1 — Testes: `test_selected_mode_requests_sites_selected_only`; `test_selected_mode_catalog_lists_only_added_sites`; `test_add_site_by_url_rejects_other_tenant_hostname`; `test_add_site_returns_actionable_error_when_app_not_granted_on_site` (Graph 403/`accessDenied` → mensagem orientando o admin a executar o `POST /sites/{id}/permissions`, doc [`site-post-permissions`](https://learn.microsoft.com/en-us/graph/api/site-post-permissions)).
- [ ] Step 2–5 — ciclo padrão (FAIL → implementar → PASS → commit `feat(sharepoint): modo Sites.Selected com sites adicionados por URL`).
- **Gate:** executar quando (a) um cliente exigir menor privilégio **ou** (b) o consentimento amplo (`Sites.Read.All`) for barrado em ≥1 tenant real.

## A.15 Fase A10 — Endurecimento, documentação e piloto (0,5–1 d)

### Task A10: ADR, runbook, docs e rollout

**Files:** Create `specs/adr/ADR-0016-sharepoint-connector.md`, `docs/integracoes/sharepoint-runbook-consentimento-admin.md` · Modify `README.md:82-84`, `docs/integrations-roadmap.md` (linhas 3-5, 14-15: "SharePoint … fora desta versão" → estado novo), `frontend/app/privacidade/page.tsx:12,14`, `.env.example`, `.env.production.example`

- [ ] Step 1 — Escrever a ADR-0016 (contexto, decisões D-A1…D-A10, consequências, "supersede parcialmente ADR-0008 dec. 2 e ADR-0009 dec. 5"). Numeração: confirmar a próxima livre ao criar (`specs/adr/`; hoje o último é ADR-0010).
- [ ] Step 2 — Runbook de consentimento (conteúdo mínimo — ver §7-b): pré-requisitos, link de admin consent, texto para e-mail ao TI, `Sites.Selected` por site, revogação, troubleshooting `AADSTS65001/90094/50105`, reconexão quando o admin sai.
- [ ] Step 3 — `README.md`: linha nova `MICROSOFT_SHAREPOINT_REDIRECT_URI` (deve casar com o app Entra `/data-sources/sharepoint/oauth/callback`), nota "a mesma `MICROSOFT_TOKEN_ENCRYPTION_KEY` cifra SharePoint"; `.env*.example` idem.
- [ ] Step 4 — `privacidade/page.tsx:12,14`: incluir "Microsoft SharePoint (Microsoft 365)" na lista de integrações e explicar que o acesso segue as permissões do administrador que conecta e que todos os membros da organização no Arquivio verão o conteúdo indexado do escopo escolhido.
- [ ] Step 5 — Piloto: 1 tenant real (cliente-âncora), 1 biblioteca, medir: tempo do snapshot, nº de 429/503 (log `ingestion_sync`), % arquivos `ignored/unsupported_file_type`, `reauth_required` espúrio. Commit `docs(sharepoint): ADR-0016, runbook de consentimento e configuração`.

## A.16 Critérios de aceite (Parte A)

1. Owner/Admin conecta um tenant M365 (autoridade `organizations`) e vê sites → bibliotecas; **não** vê/usa `all_accessible` nem `root_files`; membro comum recebe 403.
2. Seleção de biblioteca ou pasta cria `WorkspaceFolderSelection(kind="folder", external_folder_id="{driveId}|{itemId}")`; sync inicial indexa PDF/DOCX/MD da biblioteca; a biblioteca da empresa mostra `SharePoint → Site → Biblioteca → pastas` (nenhum arquivo cai na raiz da fonte).
3. Segundo sync sem mudanças: **0 downloads** e cursor renovado; arquivo alterado/movido para dentro/fora/apagado reflete no índice; evento de pasta força snapshot.
4. 429 e 503 com `Retry-After` são honrados; 401/403 → `reauth_required`; nunca `reauth_required` por throttling.
5. Reconexão a **outro tenant** é recusada (`?error=sharepoint_tenant_mismatch`); dois `DataSource sharepoint` do mesmo tenant na mesma org são impossíveis (índice único).
6. Suítes OneDrive/Notion/Google **inalteradas e verdes** (`cd backend && pytest -q && ruff check .`); `graphify update .` executado.
7. Nenhum token/cursor em claro no banco ou em logs; chave = `MICROSOFT_TOKEN_ENCRYPTION_KEY`.
8. Piloto: 1 tenant real sincroniza sem intervenção por 7 dias (scheduler `sync_freshness_hours` 24 h, `config.py:48-52`).

## A.17 Riscos (Parte A)

| ID | Risco | Prob./Impacto | Mitigação |
|---|---|---|---|
| R-A1 | Consentimento de admin barra o piloto (tenant restrito / publisher não verificado) | alta / alto | A0.2 (publisher verification) já no dia 1; link de admin consent (A8); runbook; `Sites.Selected` (A9) para TI exigente |
| R-A2 | `project_successful_sync` apaga nós de outros espaços da mesma fonte (`library/service.py:755-770`) | média / alto (dados "somem" da biblioteca) | teste de caracterização A0.3; se confirmado, corrigir **antes** de liberar multi-espaço (item próprio, fora deste plano) |
| R-A3 | Vazamento de conteúdo restrito: token do admin enxerga mais do que os membros deveriam | média / **alto** | D-A8 (sem `all_accessible`), confirmação reforçada, texto de política; ACL por arquivo é a solução estrutural (item S do relatório, fora de escopo) |
| R-A4 | Snapshot inicial lento/caro em bibliotecas grandes; throttling | média / médio | `token=latest` + travessia por escopo (não a biblioteca inteira), workers=2, `Retry-After`, `User-Agent` decorado, limite de tamanho; medir no piloto |
| R-A5 | Conexão delegada morre quando o admin conector sai (refresh token inválido) | alta (com o tempo) / médio | alerta `reauth_required` (já existe), runbook de reconexão; modo aplicativo (`Sites.Selected` app-only) como evolução — **fora de escopo**, registrar em ADR |
| R-A6 | `folders_for_selections` re-enumera pastas dos drives selecionados a cada sync (custo O(itens) como o OneDrive) | média / médio | medir no piloto; otimização futura: derivar pastas dos eventos delta + `LibraryNode` já persistidos |
| R-A7 | Delta em pasta interna/`token=latest` se comportam diferente do esperado no SharePoint | baixa / médio | spike A0 antes de A3; testes de A4 cobrem o fallback |
| R-A8 | Conflito de merge com plano 01 em `onedrive.py`/`registry.py`/`tasks.py`/`api/integrations.py` | alta / baixo | §2: merge do 01 primeiro; A2–A4 são arquivos novos |
| R-A9 | Extensões `.md` com MIME `application/octet-stream` no SharePoint viram `unsupported_file_type` | média / baixo | resolver junto com a ampliação de formatos do plano 01 (fallback por extensão), não aqui |
| R-A10 | Arquivos com rótulo de sensibilidade/IRM viram `text_extraction_failed` | média / baixo | comportamento aceitável; documentar no runbook |

## A.18 Estimativa (Parte A) [ESTIMATIVA]

| Fase | Dias |
|---|---|
| A0 spike + A0.3 caracterização | 0,5–1 |
| A1 refatoração OneDrive | 0,5 |
| A2 cliente/catálogo | 1–1,5 |
| A3 travessia/delta/pertencimento | 1–1,5 |
| A4 provider/discover | 1–1,5 |
| A5 serviço + API + worker + migração | 1 |
| A6 frontend | 1 |
| A10 ADR/runbook/piloto | 0,5–1 |
| **Núcleo (A0–A6, A10)** | **≈ 6,5–9 d** |
| A7 / A8 / A9 (opcionais) | 1 / 0,5 / 1–1,5 |

O relatório estimou 3–5 d (§4.1, E); o acréscimo vem de catálogo em 3 níveis, ID composto, `folders_for_selections` e pertencimento por delta de raiz — pontos que o relatório tratou como "trocar `/me/drive` por `/drives/{id}`". Prazo corrido inclui **lead time externo** (publisher verification + consentimento do cliente): [VALIDAR] semanas.

---

# PARTE B — Google: CASA (`drive.readonly`) vs `drive.file` + Picker

## B.1 Fatos que sustentam a decisão

- `drive.readonly` e `drive.metadata.readonly` são **restritos**; `drive.file` é **non-sensitive** [FATO — [Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), aberta nesta sessão].
- Apps com escopo restrito que acessam dados **por servidor de terceiros** exigem verificação + **avaliação de segurança CASA** e reavaliação **a cada 12 meses** contados da Letter of Assessment; isenções: uso pessoal, dev/test, dados do próprio serviço, uso interno no Workspace, instalação de domínio inteiro [FATO — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)]. **O Arquivio não se enquadra em nenhuma isenção**: armazena texto extraído, trechos e vetores em servidor próprio (`privacidade/page.tsx:12`) e serve orgs de terceiros.
- `drive.file` dá acesso **por arquivo**: arquivos criados pelo app ou que o usuário abre/compartilha com o app via Picker [FATO — mesma página de escopos]. A doc **não** afirma que escolher uma pasta libera seus filhos; fonte secundária indica que não [VALIDAR em PoC de 1 dia — é a variável que decide a Opção B].
- CASA: labs autorizados (TAC Security, Leviathan, DEKRA); Tier 2 = scan validado pelo lab; faixa de preço **secundária e divergente**: US$ 540–1.800 (TAC) e US$ 3.000–6.000 (Leviathan) [fonte secundária: [Switch Labs](https://www.switchlabs.dev/post/casa-tier-2-tier-3-security-review-providers-pricing-and-the-cheapest-option); processo: [App Defense Alliance — CASA Tier 2](https://appdefensealliance.dev/casa/tier-2/tier2-overview)]. O relatório (§9.1-C3) orça US$ 500–75.000 e manda **cotar** — este plano mantém a regra: **cotar com 2 labs na semana 1**.
- Sem verificação, app em *Testing* tem refresh token de 7 dias para escopos além de perfil básico (`docs/operacao/sync-credenciais-retencao-recomendacao.md`, "Continuidade das autorizações") [FATO citado do repo; ver doc oficial em §7].
- Não há evidência no repositório de CASA/verificação já feitas [não encontrado].

## B.2 As duas opções

| Dimensão | **Opção A — CASA + `drive.readonly`** (manter) | **Opção B — `drive.file` + Google Picker** (migrar) |
|---|---|---|
| **Escopo pedido** | `drive.readonly` (restrito) — `integrations/google_drive.py:25,484` | `drive.file` (non-sensitive) |
| **Impacto no código** | **Mínimo** (< 1 d): sem mudança de fluxo. Extras exigidos por revisão: revogação no `disconnect` (`google_drive.py:591-633`), expurgo opcional, política, evidências | **Grande (≈ 8–12 d)**: (1) escopo e `account_email` — `drive/v3/about` (`:166-177`) pode não valer com `drive.file` → pedir `openid email` [VALIDAR]; (2) **`list_folders` (`:179-196`) e listagens `:264-331` deixam de enumerar** (só arquivos abertos pelo app) → catálogo vira "arquivos escolhidos"; (3) novo tipo de seleção `picked_file`: alterar CHECK `workspaces/models.py:59-63` + migração + `_normalize_scope` (`workspaces/service.py:142-154`) + `api/integrations.py:483-501`; (4) `changes.list` (`:230-262`) só traz o que o app já enxerga → pasta **nova** ou arquivo novo em pasta existente **não entra** sem novo Picker; (5) `all_accessible`/`root_files` deixam de existir (`api/integrations.py:501`); (6) Picker no frontend: carregar `api.js`/GIS, API key, App ID, origens autorizadas, token de curta duração no navegador, CSP; (7) migrar fontes existentes (re-consentimento) e `Document`/`LibraryNode` já indexados |
| **UX** | Igual à atual: escolhe **pastas** e o sync as acompanha (unidade de conhecimento = pasta, Spec 001) | Escolher **arquivos** um a um; novos arquivos exigem nova seleção → **contradiz** "uma pasta compartilhada é a unidade de conhecimento" (`specs/001-mvp-document-intelligence.md:6`); atrito recorrente para admin de PME |
| **Tela de consentimento do usuário final** | Escopo restrito → tela mais assustadora ("ver e baixar todos os arquivos"); é o texto já refletido em `privacidade/page.tsx:14` | Mais branda, escolha explícita |
| **Prazo** | Eng. 2–4 d (pacote + evidências) + **externo: 4–8 sem** (verificação de marca 2–3 dias úteis; verificação de escopo restrito e laboratório "semanas" [FATO doc: "several weeks"; lab TAC 1–3 sem [VALIDAR]]) | Eng. 8–12 d + verificação **só de marca** (2–3 dias úteis); risco de re-trabalho se o PoC do Picker com pastas falhar |
| **Custo** | Taxa do lab (US$ 0,5–6 mil por rodada, fonte secundária; cotar) + **anual** + ~2–4 d de eng./ano; orçar teto US$ 5–10 mil/ano até haver cotação | Sem taxa de lab; custo = 8–12 d + suporte contínuo ("por que meu arquivo novo não indexou?") + queda de valor percebido |
| **Risco principal** | Rejeição/atraso da Google ou do lab; renovação anual | Produto regride para "upload assistido"; PoC do Picker pode invalidar a opção |
| **Reversibilidade** | Alta (nada muda no produto) | Baixa (muda modelo de seleção e dados) |
| **Compatível com `all_accessible`/sync por pasta** | Sim | Não |

## B.3 Recomendação

**Opção A — iniciar o CASA agora e manter `drive.readonly`.** Motivos: (1) preserva a proposta do produto (pasta como unidade, sync automático); (2) custo/prazo são **externos e previsíveis**, ao passo que a Opção B tem custo interno alto e risco de produto; (3) a Opção B depende de um comportamento (Picker + pasta) que a doc oficial não confirma; (4) o motor de sync incremental (`changes.list`) já está pronto para o modelo atual.

**Contingência formal (não construir agora):** acionar a Opção B **somente** se um destes gatilhos ocorrer — (G1) laboratório/Google reprovar ou o custo cotado exceder o teto aprovado pelo dono; (G2) > 8 semanas sem aprovação **e** cliente-âncora aguardando; (G3) Google exigir Tier que a empresa não sustente. Antes de qualquer decisão de migrar, executar o **PoC de 1 dia** de B7.

**Ponte enquanto não verificado (piloto):** manter o app em *Testing* com usuários de teste e reconexão semanal, **ou** publicar sem verificação (tela "app não verificado", teto de 100 usuários) [VALIDAR na doc oficial], **ou** pedir a admins de Workspace piloto que marquem o app como *Trusted* no Admin console [VALIDAR se dispensa o aviso/teto]. Registrar a escolha na ADR-0017.

## B.4 Plano de execução da Opção A

### Task B0: decisão, dono e orçamento

> Decisão do piloto 29/09: **Opção A (CASA com `drive.readonly`)**, contingência `drive.file` + Picker pelos gatilhos G1–G3. ADR-0017 escrita (`specs/adr/ADR-0017-google-restricted-scope-strategy.md`); B1, B3 (rascunho em `docs/legal/`) e B4 (checklist) entregues como documentação em `docs/integracoes/google-oauth-verificacao-checklist.md`. **B2 (revogação e expurgo) registrado e adiado.** Ações humanas: `docs/integracoes/acoes-humanas-externas.md`.

**Files:** Create `specs/adr/ADR-0017-google-restricted-scope-strategy.md`

- [ ] Step 1 — Dono de produto decide A vs B usando §B.2/B.3 (pendência §9.2 do relatório: "CASA vs `drive.file`"). Registrar: opção, teto de orçamento, gatilhos G1–G3, ponte do piloto.
- [ ] Step 2 — Ata na ADR-0017 (contexto, opções, decisão, consequências). Commit: `git add specs/adr/ADR-0017-google-restricted-scope-strategy.md && git commit -m "docs(adr): estratégia para escopo restrito do Google (CASA vs drive.file)"`.

### Task B1: mapa de fluxo de dados Google (base para questionário, política e CASA)

**Files:** Create `docs/integracoes/google-oauth-verificacao-checklist.md`

- [ ] Step 1 — Documentar, com `path:line`: onde o token é obtido/guardado (`integrations/google_drive.py:120-137,391-431`), lido (`ingestion/google_drive.py:332-379`), o que é baixado (`:369-388`), o que é armazenado (texto/trechos/vetores — `knowledge/models.py:59`), para onde sai (OpenAI para embeddings/respostas — `privacidade/page.tsx:12` e `config.py`), retenção (`docs/operacao/sync-credenciais-retencao-recomendacao.md`, tabela "Exclusão").
- [ ] Step 2 — Preencher a **checklist de verificação OAuth Google** (abaixo, B.5). Commit `docs(google): mapa de dados e checklist de verificação`.

### Task B2: testes e código mínimo antes de submeter (tests-first)

**Files:** Modify `backend/app/integrations/google_drive.py:106-118,591-633`, `backend/app/api/integrations.py:352-384` · Test `backend/tests/unit/test_google_drive_connection.py`, `backend/tests/api/test_google_integrations.py`
**Interfaces:** Produces: `GoogleDriveOAuthClient.revoke_token(self, *, token: str) -> None` (best effort, `POST https://oauth2.googleapis.com/revoke`); `GoogleConnectionService.disconnect(..., revoke: Callable[[str], None] | None = None)`; endpoint `DELETE /data-sources/{id}?organization_id=&purge=true` apaga índice do source (usa `IngestionService.remove_workspace`, `ingestion/service.py:319`, para cada `WorkspaceFolder` do source).

- [ ] Step 1 — Testes falhando:

```python
def test_authorization_requests_only_the_drive_readonly_scope() -> None:
    client = GoogleDriveOAuthClient(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
    url = httpx.URL(client.authorization_url(state="st", scope=GOOGLE_DRIVE_READONLY_SCOPE))
    assert url.params["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert url.params["access_type"] == "offline"


def test_revoke_token_posts_to_google_and_never_raises(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.integrations.google_drive.httpx.post",
                        lambda url, **kw: calls.append((url, kw["data"])) or httpx.Response(200))
    client = GoogleDriveOAuthClient(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
    client.revoke_token(token="refresh-1")
    assert calls == [("https://oauth2.googleapis.com/revoke", {"token": "refresh-1"})]
    monkeypatch.setattr("app.integrations.google_drive.httpx.post",
                        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    client.revoke_token(token="refresh-1")  # best effort: no exception
```

  e, em `test_google_integrations.py`: `test_disconnect_revokes_refresh_token_and_clears_credentials`, `test_disconnect_with_purge_removes_indexed_documents_of_the_source_only` (isolamento: outra org e outro source intactos), `test_disconnect_without_purge_keeps_index` (comportamento atual preservado).
- [ ] Step 2 — Run `cd backend && pytest tests/unit/test_google_drive_connection.py tests/api/test_google_integrations.py -q` → expected: FAIL `AttributeError: … has no attribute 'revoke_token'`.
- [ ] Step 3 — Implementar `revoke_token` (POST com `data={"token": token}`, `timeout=10`, engolir `httpx.HTTPError`); `disconnect` decripta o refresh token **antes** de zerar `encrypted_credentials` (`google_drive.py:602`) e revoga; `purge` opcional na rota `disconnect_source` (`api/integrations.py:352-384`) — só Owner/Admin (já garantido por `require_admin`, `google_drive.py:438-448`).
- [ ] Step 4 — Run `cd backend && pytest tests -q && ruff check .` → PASS.
- [ ] Step 5 — `git add backend/app backend/tests && git commit -m "feat(google): revoga token ao desconectar e permite expurgo do índice"`. Frontend: caixa "Apagar também o conteúdo indexado" no diálogo de desconexão (`product-app.tsx:765`) — task B2b com o mesmo formato de A6 (teste de módulo puro `disconnectQuery(purge: boolean): string`).

### Task B3: política de privacidade com declaração de *Limited Use*

**Files:** Modify `frontend/app/privacidade/page.tsx:12,14` · Test `frontend/tests/privacy-page.test.mjs`
**Interfaces:** Consumes: texto exigido pela [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy).

- [ ] Step 1 — Teste falhando (lê o arquivo-fonte; não há infra de renderização no runner atual):

```js
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/privacidade/page.tsx", import.meta.url), "utf8");

test("privacy page states Google Limited Use and the OAuth scope", () => {
  assert.match(page, /Google API Services User Data Policy/);
  assert.match(page, /Limited Use/);
  assert.match(page, /drive\.readonly/);
});

test("privacy page covers retention, deletion and third-party processors for Google data", () => {
  assert.match(page, /revog/i);
  assert.match(page, /exclus/i);
  assert.match(page, /OpenAI/);
  assert.match(page, /n[ãa]o (usamos|utilizamos).*(treinar|treinamento)/is);
});
```

- [ ] Step 2 — Run `cd frontend && node --test tests/privacy-page.test.mjs` → expected: FAIL (sem "Limited Use" hoje; `privacidade/page.tsx:14`).
- [ ] Step 3 — Editar a seção 4: incluir a frase padrão em inglês ("The use of information received from Google APIs will adhere to the Google API Services User Data Policy, including the Limited Use requirements."); dizer que dados do Google **não** são usados para treinar modelos de IA generalizados nem vendidos; nomear o processador de IA (**OpenAI**, conforme `docs/operacao/…` "store=false") e o fim para o qual o dado é enviado; descrever revogação (`disconnect` + revogação no Google, B2) e exclusão (expurgo, B2); contato para pedidos de titular. **Conferir cada frase contra o código antes de publicar** (a política não pode prometer o que não está implementado: retenção real está "em proposta", `docs/operacao/…`).
- [ ] Step 4 — Run `cd frontend && node --test tests/privacy-page.test.mjs && npm run lint` → PASS.
- [ ] Step 5 — `git add frontend/app/privacidade/page.tsx frontend/tests/privacy-page.test.mjs && git commit -m "docs(legal): declaração de Limited Use e tratamento de dados do Google"`.

### Task B4: evidências de segurança para o CASA (sem CI hoje)

**Files:** Create `docs/seguranca/casa-evidencias.md`, `scripts/security-scan.sh`, `.github/workflows/security-scan.yml` (se o repositório passar a usar GitHub Actions; caso contrário só o script)

- [ ] Step 1 — Listar controles já existentes com evidência: tokens cifrados (Fernet), CSRF/origem (`backend/tests/api/test_csrf_origin.py`), isolamento de tenant (`tests/integration/test_organization_tenant_isolation.py`), logs sem segredos (`tests/unit/test_auth_log_redaction.py`), estados OAuth com hash e uso único.
- [ ] Step 2 — Script `scripts/security-scan.sh`: `pip-audit` no backend, `npm audit --omit=dev` no frontend, SAST (`semgrep --config auto` ou `bandit -r backend/app`), DAST baseline (OWASP ZAP baseline contra staging). **Usar exatamente as ferramentas e o formato de relatório que o laboratório escolhido exigir** (confirmar no kickoff do lab; o Tier 2 valida scans feitos pelo desenvolvedor [FATO — resumo do processo]).
- [ ] Step 3 — Rodar, anexar relatórios em `docs/seguranca/` (sem segredos), tratar críticos/altos; lacuna conhecida a avaliar: rotação de chave Fernet (usar `MultiFernet`) — abrir item se o lab pedir gestão de chaves.
- [ ] Step 4 — Commit `chore(security): scans e evidências para avaliação CASA`.

### Task B5: configuração do Google Cloud e submissão (externo)

Ver checklist B.5. Ordem: P0 domínio → B5.1 verificação de marca → B5.2 verificação do escopo restrito (vídeo + justificativa) → B5.3 CASA (cotar 2 labs; escolher; scans; LOA) → B5.4 envio da LOA ao Google → B5.5 publicar em *Production*.

### Task B6: pós-aprovação e renovação anual

- [ ] Step 1 — Registrar data da LOA; **criar lembrete a 90 dias do vencimento de 12 meses** (dono: eng. + produto); orçar a reavaliação (mesma faixa).
- [ ] Step 2 — Trocar app para *Production*; validar refresh token > 7 dias em conta real; remover usuários de teste; reconectar fontes do piloto.
- [ ] Step 3 — Monitorar `reauth_required` (`ingestion/tasks.py:400-419`) como indicador; atualizar `docs/operacao/sync-credenciais-retencao-recomendacao.md` (renovação de token **já implementada**, `ingestion/google_drive.py:332-379`).

### Task B7 (CONTINGÊNCIA — só se G1/G2/G3): PoC e migração para `drive.file` + Picker

**Files (se acionada):** Modify `backend/app/integrations/google_drive.py:25,106-118,166-196,264-331`, `backend/app/workspaces/models.py:59-63`, `backend/app/workspaces/service.py:142-154`, `backend/app/api/integrations.py:431-502,537-603`, `frontend/app/product-app.tsx`; Create migração `20260930_0020_picked_file_selection.py`, `frontend/app/google-picker.tsx` · Test `backend/tests/unit/test_google_drive_connection.py`, `backend/tests/api/test_google_integrations.py`, `frontend/tests/google-picker-config.test.mjs`
Esta task é uma **especificação de contingência** (não um plano executável passo a passo): antes de codar, o dono reabre este plano e detalha as tasks.

- [ ] **B7.0 PoC (1 d, executável já se quiser reduzir incerteza):** app de teste com `drive.file` + Picker (view de pastas habilitada): (i) selecionar uma pasta com 3 arquivos → `files.list` com `'<pasta>' in parents` devolve os filhos? (ii) adicionar arquivo novo na pasta depois → aparece em `changes.list`? (iii) `about.get` funciona com `drive.file`? (iv) arquivo em shared drive. Resultado em `docs/integracoes/google-picker-poc.md`. Se (i) e (ii) forem "não": B fica **descartada** para o caso de uso de pastas.
- [ ] B7.1 testes: escopo `drive.file` exclusivo na URL; `picked_file` aceito por CHECK; catálogo = arquivos escolhidos; `changes` só de IDs escolhidos; migração de fontes antigas exige reconexão (`reauth_required` + aviso).
- [ ] B7.2 backend/frontend/migração conforme tabela B.2; rollout com *feature flag* por org.
- [ ] B7.3 critérios: nenhum escopo restrito no consentimento; documentos já indexados preservados; UX explica "adicionar arquivos".

## B.5 Checklist de verificação OAuth do Google (executar; marcar e datar)

**Pré-requisitos (P0):**
- [ ] Domínio próprio, apontado ao frontend; `PUBLIC_APP_URL` atualizado (`config.py:34`, `README.md:87`).
- [ ] Domínio **verificado no Google Search Console** pela mesma conta dona do projeto Cloud; adicionado em "Authorized domains".
- [ ] Páginas públicas no domínio: home com descrição do app e link de privacidade; `/privacidade` e `/termos` (existem em `frontend/app/`); **deploy feito** (28/09 ainda retornava 404 em produção).

**Configuração do Google Auth Platform / Cloud Console:**
- [ ] Projeto dedicado de produção; tipo de usuário **External**; e-mail de suporte e de contato de desenvolvedor monitorados.
- [ ] Nome do app **igual ao produto** (Arquivio), logo 120×120, URLs de home/privacidade/termos no domínio verificado.
- [ ] Redirect URIs de produção (`/data-sources/google/oauth/callback`, `api/integrations.py:293`); remover `localhost`/URIs de teste do cliente de produção.
- [ ] Escopos declarados: **somente `https://www.googleapis.com/auth/drive.readonly`** (teste B2 impede regressão).
- [ ] **Justificativa por escopo** (texto em `docs/legal/google-api-data-use-declaracao.md`, a criar): por que `drive.readonly` e não `drive.file`; por que a leitura de conteúdo é indispensável (indexar para busca/Q&A com citação); que arquivos não são alterados; que o admin escolhe pastas; que a Opção B foi avaliada e descartada (link para ADR-0017).
- [ ] **Vídeo de demonstração** (YouTube não listado): fluxo completo em produção — clicar em Conectar → tela de consentimento **em inglês** com o *client ID* visível na URL → concessão → escolha de pastas → sincronização → pergunta com citação → desconectar/revogar. Narrar o uso de cada dado.
- [ ] Conteúdo do formulário: como o dado é armazenado (Postgres, cifra de tokens), quem acessa, retenção e exclusão (alinhado à política e ao B2), subprocessadores (OpenAI, hospedagem Railway).
- [ ] Declaração de conformidade com a **Google API Services User Data Policy / Limited Use** (B3): sem publicidade, sem venda, sem treinamento de modelos generalizados, transferência a terceiros apenas para fornecer a funcionalidade ao usuário.
- [ ] Testar com conta Google **sem** relação com o projeto (janela anônima): consentimento, tokens, reconexão, revogação em `myaccount.google.com/permissions`.

**Etapas de aprovação:**
- [ ] B5.1 Brand verification (nome/logo/domínio) — 2–3 dias úteis [FATO doc].
- [ ] B5.2 Submissão da verificação de escopo restrito; responder e-mails do OAuth review team (prazo de resposta curto; caixa monitorada).
- [ ] B5.3 **CASA**: Google indica tier e laboratório/portal quando pedir a avaliação [FATO: "the OAuth review team will reach out"]. Cotar TAC Security, Leviathan e um terceiro; escolher; enviar scans (B4); corrigir achados; obter **Letter of Assessment**.
- [ ] B5.4 Enviar a LOA no processo de verificação; aguardar aprovação.
- [ ] B5.5 Publicar em *Production*; conferir que a tela de "app não verificado" sumiu e o limite de 100 usuários não se aplica.
- [ ] B5.6 Calendário: renovação anual (B6).

## B.6 Critérios de aceite (Parte B)

1. ADR-0017 aprovada pelo dono, com opção, teto de orçamento, gatilhos G1–G3 e ponte do piloto.
2. Domínio verificado; `/privacidade` e `/termos` ativas em produção; política contém declaração de *Limited Use* e reflete só o que o código faz (teste `privacy-page.test.mjs` verde).
3. `disconnect` revoga o token no Google (best effort) e oferece expurgo; suíte de backend verde; isolamento de tenant provado por teste.
4. Escopo pedido = exatamente `drive.readonly` (teste automatizado).
5. Verificação de marca aprovada; submissão do escopo restrito enviada com vídeo e justificativas; CASA contratado com data.
6. **Fechamento da trilha:** LOA emitida e aceita pela Google **ou** gatilho de contingência acionado com PoC B7.0 registrado.

## B.7 Riscos (Parte B)

| ID | Risco | Prob./Impacto | Mitigação |
|---|---|---|---|
| R-B1 | Domínio próprio inexistente/ não verificável (hoje `*.up.railway.app`) | alta / **bloqueia tudo** | P0 no dia 1 |
| R-B2 | Reprovação/atraso da verificação ou do lab | média / alto | submeter cedo, caixa monitorada, cotar 2–3 labs, gatilhos G1–G3 |
| R-B3 | Custo real do CASA fora da faixa (fontes divergem: US$ 0,5–6 mil vs até 75 mil/ano) | média / médio | cotar por escrito antes de contratar; teto na ADR-0017 |
| R-B4 | Política de privacidade prometer mais do que o código faz (retenção/exclusão ainda "em proposta") | média / alto (reprova a revisão) | B2 (expurgo/revogação) antes de B3; revisar frase a frase contra o código |
| R-B5 | Google exigir mudanças de produto durante a revisão (ex.: reduzir o escopo) | baixa / alto | B7.0 PoC pronto; contingência formal |
| R-B6 | Refresh token expira em 7 dias enquanto em *Testing* → syncs quebram no piloto | alta (até a aprovação) / médio | ponte B.3; alerta de `reauth_required` |
| R-B7 | Renovação anual esquecida → perda de acesso | média / alto | B6 lembrete a 90 dias + dono nomeado |
| R-B8 | Envio de conteúdo a OpenAI conflitar com *Limited Use* | baixa / alto | declarar processador, `store=false` (`docs/operacao/…`), sem treino; validar contratualmente [VALIDAR com jurídico] |

## B.8 Estimativa (Parte B) [ESTIMATIVA]

| Item | Eng. | Externo |
|---|---|---|
| B0 decisão + ADR | 0,5 d | — |
| B1 mapa de dados + checklist | 0,5–1 d | — |
| B2 revogação + expurgo (+ UI) | 1–1,5 d | — |
| B3 política | 0,5 d | revisão jurídica |
| B4 scans/evidências | 1–2 d | — |
| B5 submissão (marca → escopo → CASA → LOA) | 1 d (vídeo, formulários, respostas) | **4–8 sem** (marca 2–3 d; escopo restrito e lab: semanas) |
| B6 pós-aprovação | 0,5 d | anual |
| **Total Opção A** | **≈ 5–7 d** | **4–8 sem + renovação anual** |
| B7.0 PoC (contingência) | 1 d | — |
| B7 migração completa (contingência) | 8–12 d | verificação de marca |

Relatório D: "2–4 d + 4–8 sem externas" — coerente para a trilha de decisão/submissão; o acréscimo (revogação/expurgo, política, scans) é o que a revisão costuma cobrar [INFERÊNCIA].

---

## 6. Ordem de execução e calendário sugerido (as duas partes em paralelo)

| Semana | Trilha A (SharePoint) | Trilha B (Google) | Comum |
|---|---|---|---|
| 0 (dias 1–3) | A0.1 tenant/spike, A0.2 publisher verification, A0.3 caracterização | B0 decisão + ADR-0017; cotar 2–3 labs | **P0 domínio + deploy de `/privacidade` `/termos`** |
| 1 | A1 (após merge do plano 01 em `onedrive.py`), A2 | B1 mapa de dados; B2 revogação/expurgo | — |
| 2 | A3, A4 | B3 política; B4 scans; **B5.1 marca**; **B5.2 submissão escopo restrito** | — |
| 3 | A5 (serviço/API/worker/migração) | B5.3 CASA contratado, scans enviados | — |
| 4 | A6 frontend, A10 docs; piloto em tenant real | achados do lab corrigidos | revisão cruzada de política (Microsoft + Google) |
| 5–8 | A8/A7/A9 conforme demanda; medir | LOA → envio à Google → Production (B5.4–5.5) | — |

Ordem entre planos (índice mestre é do plano de integração): Plano 01 (base OAuth/`RemoteHttp`) **antes** de A1; A2–A4 e toda a Parte B **independem** do 01.

> Revisão: no cronograma do plano 01, `RemoteHttp`/Graph (T1.1/T1.4) sai na semana 1 e a base OAuth + chave por provider (T2.2–T2.6) na semana 2 dele; logo "semana 1: A1" acima só vale se o 01 começar ≥ 2 semanas antes. No calendário consolidado (`00-indice.md`), A0/A2–A4 e a Parte B começam junto com o 01, e A1/A5 entram depois do merge de 01-F1+F2.

## 7. Documentação necessária

### (a) Documentação externa (URLs oficiais)

Legenda: ✅ = aberta e lida nesta sessão · ◻ = URL oficial citada do relatório/busca, **abrir e confirmar antes de usar como fonte de decisão**.

**Microsoft (SharePoint / Graph / Entra)**
- ✅ [driveItem: delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta) — `/drives/{id}/root/delta`, `token=latest`, sem `path` no `parentReference`, 410 + `resyncChanges*`, permissões delegadas aceitas.
- ✅ [Overview of Selected permissions](https://learn.microsoft.com/en-us/graph/permissions-selected-overview) — `Sites.Selected`, 3 passos, delegado = interseção usuário∩app, `POST /sites/{siteId}/permissions`.
- ◻ [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) — coluna "admin consent required" de `Sites.Read.All`, `Sites.Selected`, `Files.Read.All` (delegadas). *Tentativa de leitura truncou; confirmar.*
- ◻ [Graph throttling limits](https://learn.microsoft.com/en-gb/graph/throttling-limits) e [SharePoint — evitar throttling/bloqueio](https://learn.microsoft.com/it-it/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online) (URLs do relatório; decoração de tráfego `ISV|…`, `Retry-After`).
- ◻ [site: search](https://learn.microsoft.com/en-us/graph/api/site-search), [drive: list (bibliotecas de um site)](https://learn.microsoft.com/en-us/graph/api/drive-list), [site: get (por hostname:path)](https://learn.microsoft.com/en-us/graph/api/site-get) — endpoints do catálogo; confirmar limites do delegado em `search=*`.
- ◻ [site: delta](https://learn.microsoft.com/en-us/graph/api/site-delta) — **delta de sites, não de arquivos** (correção do relatório §4.1).
- ◻ [site: create permission](https://learn.microsoft.com/en-us/graph/api/site-post-permissions) — concessão por site para `Sites.Selected` (A9).
- ◻ [Graph change notifications / webhooks](https://learn.microsoft.com/graph/api/resources/webhooks) — futuro (relatório item K).
- ◻ Entra: [registrar aplicativo](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) · [consentimento de administrador (endpoint `/adminconsent`)](https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent) · [publisher verification](https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview) · [configurar consentimento de usuário](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent) · [workflow de consentimento de admin](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/admin-consent-workflow-overview).
- ◻ [Microsoft 365 Developer Program](https://developer.microsoft.com/microsoft-365/dev-program) — tenant de teste (confirmar elegibilidade atual).

**Google**
- ✅ [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) — CASA, LOA, reverificação a cada 12 meses, isenções.
- ✅ [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) — `drive.file` non-sensitive; `drive.readonly`/`drive.metadata.readonly` restricted.
- ✅ [Google Picker — visão geral](https://developers.google.com/workspace/drive/picker/guides/overview) (a página não explica acesso a filhos de pasta) e ◻ [novo método de pré-seleção no Picker](https://workspaceupdates.googleblog.com/2024/11/new-file-picker-method-for-pre-selecting-google-drive-files.html).
- ✅ [App Defense Alliance — CASA Tier 2](https://appdefensealliance.dev/casa/tier-2/tier2-overview) (resultado de busca; abrir integralmente para tiers/labs vigentes).
- ◻ [Google API Services User Data Policy (Limited Use)](https://developers.google.com/terms/api-services-user-data-policy) · [OAuth 2.0 — expiração de refresh tokens](https://developers.google.com/identity/protocols/oauth2) · páginas de *brand verification* e *sensitive/restricted scope verification* em `developers.google.com/identity/protocols/oauth2/production-readiness/`.
- ◻ Preços de CASA: [Switch Labs — comparativo](https://www.switchlabs.dev/post/casa-tier-2-tier-3-security-review-providers-pricing-and-the-cheapest-option) — **fonte secundária**; só cotação do lab vale.

### (b) Documentação interna a criar

| Arquivo | Conteúdo mínimo | Task |
|---|---|---|
| `specs/adr/ADR-0016-sharepoint-connector.md` | decisões D-A1…D-A10; supersede parcial de ADR-0008 dec. 2 e ADR-0009 dec. 5; decisão pendente da coluna de configuração (A9) | A10 |
| `specs/adr/ADR-0017-google-restricted-scope-strategy.md` | A vs B, custo/prazo, gatilhos G1–G3, ponte do piloto, orçamento | B0 |
| `docs/integracoes/sharepoint-spike-tenant-teste.md` | resultados do A0.1 (formato de `driveId`, consentimento, delta) e status da publisher verification | A0 |
| `docs/integracoes/sharepoint-runbook-consentimento-admin.md` | **Runbook de consentimento de admin M365**: quem precisa aprovar; link de admin consent (A8); texto pronto para o TI; `Sites.Selected` por site (`POST /sites/{id}/permissions`); revogação; erros `AADSTS65001/90094/50105`; reconexão quando o admin conector sai; o que o Arquivio enxerga e não enxerga | A10 |
| `docs/integracoes/google-oauth-verificacao-checklist.md` | mapa de dados + checklist B.5 com datas e responsáveis | B1 |
| `docs/legal/google-api-data-use-declaracao.md` | justificativa por escopo, resposta às perguntas de dados/retenção, declaração de Limited Use | B5 |
| `docs/seguranca/casa-evidencias.md` (+ relatórios de scan) | controles com evidência (testes, `path:line`) e resultados de scans | B4 |
| `docs/integracoes/google-picker-poc.md` | (contingência) resultado do PoC B7.0 | B7 |
| **Atualizar:** `frontend/app/privacidade/page.tsx` (**política de privacidade**, Limited Use + SharePoint), `README.md:80-87`, `docs/integrations-roadmap.md`, `docs/operacao/sync-credenciais-retencao-recomendacao.md` (renovação do token Google já implementada), `.env.example`/`.env.production.example` | conforme tasks A10/B3/B6 | — |

## 8. Auto-revisão (oc-route §8)

1. **Cobertura do pedido:** (A) SharePoint reaproveitando OneDrive — Graph, delta, ID composto, sites/drives/bibliotecas, `Sites.Selected` vs `Sites.Read.All`, admin consent, throttling → A.1/A.2, A2–A10. (B) duas opções com impacto em código/UX/prazo/custo, recomendação e execução com checklist de verificação (privacy policy, domínio, vídeo, CASA) → B.2–B.5. Dependência do plano 01 e fallback → §2. Pré-requisitos, testes primeiro, migrações (`0019`; `0020` só contingência/A9), frontend (A6/B2b/B3), aceite, riscos, estimativa, documentação → presentes.
2. **Placeholders:** a **Task B7** é declarada explicitamente como especificação de contingência (não executável) e a **Task A9** tem um bloqueio explícito ("decidir a coluna na ADR antes de codar"); A7/A8 têm testes nomeados mas corpo de testes resumido em uma linha — **o implementador escreve o corpo seguindo o modelo do primeiro teste da task**. Esses são os pontos onde o plano não é "cold-start completo"; nada mais foi deixado como TBD.
3. **Nomes:** `composite_id/split_composite/site_node_id/is_site_node`, `SharePointGraphClient.{catalog,list_files,latest_delta_link,delta_root,within_scope,get_item,read_file,drive_root_id,list_folders}`, `SharePointDocumentProvider.{discover,folders,folders_for_selections}`, `SharePointConnectionService.bind_identity`, `OneDriveConnectionService.provider_key`, `MicrosoftGraphClient.{AUTHORITY,SCOPES}`, `OneDriveDocumentProvider.{max_workers,max_file_bytes}` — usados de forma consistente entre A1–A5. Inconsistência conhecida e aceita: o `_download` extraído em A3 é tocado em `onedrive.py` (A3) além de A1 — coberto pelas suítes OneDrive no Step 4.
4. **Fatos incertos** (marcados [VALIDAR]): formato de `driveId`; consentimento efetivo de `Sites.Read.All` por tenant; delta em pasta interna; `about.get` com `drive.file`; Picker com pasta; custo real do CASA; teto de 100 usuários sem verificação; elegibilidade do tenant de desenvolvedor.
5. **Não coberto:** webhooks/change notifications do Graph; Teams como canal; SharePoint listas/páginas (`.aspx`); OneDrive de outros usuários; modo aplicativo (client credentials); ACL por arquivo; correção de R-A2 caso confirmado; ampliação de formatos/OCR (plano 01); API pública/MCP (plano 03); teste em tenant real (nenhum tenant foi acessado nesta sessão — todo comportamento de SharePoint acima é derivado de docs e do código do OneDrive).

## 9. Handoff de execução

Duas formas: **(a)** um worker novo por task, com revisão entre tasks — no Overclock, um `oc-pilot` abrindo um `oc-builder` por task (A0→A1→…; a Parte B tem trilha de engenharia B2/B3/B4 e trilha humana B0/B5/B6); **(b)** execução inline com checkpoints após A1, A4, A5 e B3. Recomendação: **A e B em paralelo por pessoas diferentes**; dentro de A, começar por A0 (spike decide D-A7) e P0/B0 no dia 1 porque são os itens de lead time.

## Execução parcial — 2026-09-30, pane-251

> Execução: A0.3 passou (1 passed, exit 0) e confirmou R-A2: sincronizar B
apaga nós de A na mesma fonte. Commit 39262de registra a caracterização,
follow-up e spike real pendente. Rollout SharePoint multi-espaço bloqueado.

> Execução: A1 em fe64cae parametriza autoridade/escopos, vínculo de identidade,
workers e hooks de download/tamanho. O teste novo falhou antes da implementação
(AttributeError AUTHORITY, exit 1). O commit foi feito enquanto a execução
de regressão ainda estava pendente; ela terminou com erro de ambiente, não
com testes verdes. Portanto A1 NÃO está validada nem entregue pelo aceite.

> Execução: o worktree e backend/.venv contêm arquivos macOS compressed,dataless.
pytest/__init__.py tem tamanho metadata 5373, mas read_bytes retorna zero;
pytest termina com AttributeError console_main (exit 1). brctl download não
hidratou os arquivos. uv pip --reinstall pytest e graphify update posterior
a A1 ficaram pendentes. Graphify após A0 concluiu (exit 0, 4582 nodes).
A2/A3 têm rascunhos não commitados em sharepoint.py e test_sharepoint.py;
A4–A6 e A10 não executadas. Recuperar arquivos/venv antes de retomar e
validar A1, depois retomar os testes A2/A3. Nenhuma migração criada.

> Execução: tenant real, publisher verification, consentimento, formatos/limites
reais do Graph e piloto de sete dias continuam pendências externas explícitas.

## Execução — 2026-09-30, pane-255 (continuação)

> Execução: A1 validada fora do iCloud (venv novo no scratchpad + export `git archive`): OneDrive/company_library 35 passed; suíte completa 564 passed (exit 0).

> Execução: A2/A3 em 59b6c29 (rascunhos da pane-251 corrigidos por ruff; red ModuleNotFoundError → green). A4 em 92d1349 (10 testes do plano; `drive_root_id`/`list_folders` no client; reprocesso também checa pertencimento). A5 em b5af2af: serviço/rotas/registry/worker; início/callback OAuth Microsoft viraram helpers `_microsoft_*` compartilhados entre OneDrive e SharePoint (sem mudança de contrato; suítes OneDrive verdes); sites também dão 422 na seleção. Suíte completa 602 passed com a 0019 presente.

> Execução: migração = `20260930_0020_sharepoint_tenant_binding` (não 0022), `down_revision = 20260930_0019` (pgvector, pane F5, ainda não commitada no momento). Até a 0019 entrar no branch, o HEAD isolado falha em test_migration_sql/test_authentication_migration_sql (KeyError '20260930_0019'). Se a 0019 mudar de id, reencadear.

> Execução: A6 em 7def418 (tsc 0, eslint 0, `node --import tsx --test tests/*.test.mjs` 29/29, rodados num `npm ci` no scratchpad). Validação visual/responsiva pendente. A10 em 5a65534 + 8a2f7b9 (`.env.production.example` não tem variáveis Microsoft; não alterado). Rotas de admin consent (A8) e `Sites.Selected` (A9) não executadas (fora do escopo pedido). Piloto/tenant real: pendente.
