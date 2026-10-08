# Document-AI (Arquivio) — Análise de integrações e roadmap

Data: 2026-09-29 · Base de código: `main` @ `c9cebf0` (com alterações não commitadas em `backend/` e `frontend/`; citações refletem a working tree) · Escopo: análise somente leitura, sem código.

Convenção: **[FATO]** = verificado no código ou em fonte citada; **[INFERÊNCIA]** = dedução; **[ESTIMATIVA]** = esforço/impacto, julgamento com base no tamanho dos conectores atuais (dias-pessoa de um dev que conhece a base). Citações externas seguem `[Título](URL)`. Onde os três relatórios de origem divergiram entre si ou do código, a resolução está na §9.1.

---

## 1. Resumo executivo

O Arquivio é um RAG multi-tenant de "pastas de trabalho": conecta Drive/OneDrive/Notion, ingere texto, indexa e responde com citações verificáveis, para PMEs de serviços (20–150 pessoas) que compartilham conhecimento em pastas. Um conector novo custa pouco **quando é "mais uma árvore de arquivos"** (o pipeline, a biblioteca, o agente e o chat não mudam). O que limita o valor do produto hoje **não é o número de conectores**, é (a) **o que o pipeline consegue ler** (4 MIME types, sem OCR), (b) **um risco de go-to-market no Google** (`drive.readonly` é escopo restrito) e (c) **ausência de canais de saída** (sem API, MCP ou webhooks).

### Três recomendações principais

1. **Cobertura antes de conectores (0–30 dias).** Ampliar o que o pipeline lê: XLSX/CSV/TXT/PPTX e OCR em camadas para PDFs escaneados (pypdf primeiro; Docling self-host ou API de OCR como fallback). Junto, endurecer o núcleo: tratar 429/403-por-quota no Drive, `RemoteHttp` comum, chave de criptografia por provider, base de serviço OAuth e pgvector. É o maior ganho por esforço e não depende de aprovação de terceiros.
2. **SharePoint/M365 como próximo conector, e decidir já o caso do Google (0–30 dias, com lead time externo).** SharePoint reaproveita ~80% do OneDrive (Graph, delta, ID composto) por 3–5 dias. Em paralelo, iniciar o CASA da Google ou migrar para `drive.file` + Picker: sem isso, vender o conector Drive em produção pública pode ser bloqueado (prazo de semanas).
3. **Distribuição: API pública com chaves + servidor MCP remoto próprio, somente leitura (30–90 dias).** Reaproveita 100% do RAG (`LibraryToolExecutor`) e coloca a biblioteca dentro de Claude/ChatGPT/Cursor. Depois, bot Slack/Teams como canal de perguntas. **Não** indexar Slack/e-mail/WhatsApp antes de existir ACL por arquivo/canal, e **não** conectar o agente a MCPs de terceiros "ao vivo" antes do MCP próprio e de um desenho de segurança (quebra o invariante de escopo imposto pelo servidor).

**O que não recomendar** (foge da proposta ou não compensa): Salesforce, Trello/Asana/ClickUp/monday, plataformas de e-commerce, prontuários de clínicas, Ragie/Merge/Paragon (substituem ou encarecem o núcleo), assistente WhatsApp de "propósito geral", ingestão de Slack/Gmail sem ACL.

---

## 2. Proposta do app e arquitetura atual de conectores

### 2.1 Proposta e premissas de produto

- **O que é:** "connects document sources, ingests and indexes files, and provides a secure company library for search, retrieval, and AI-assisted questions" (`README.md:3`).
- **Para quem:** Spec 001 — empresas de serviços de 20–150 pessoas que já usam Drive; JTBD "confirmar uma informação sobre um cliente/projeto e verificar a fonte original rapidamente"; "uma pasta compartilhada é a unidade de conhecimento. O produto não substitui o Google Drive" (`specs/001-mvp-document-intelligence.md:6`).
- **Fluxo:** OAuth por Owner/Admin → `DataSource` (`backend/app/integrations/models.py:10-19`) → escopo por pasta (`WorkspaceFolder`/`Selection`, `backend/app/workspaces/models.py:60-106`) → Celery: `reconcile_workspace_folder` (`backend/app/ingestion/tasks.py`) → chunking + embeddings OpenAI → biblioteca (`LibraryNode`) → agente em 4 estágios classify/execute/synthesize/cite (`docs/agent-flow.md`) → chat.
- **Restrições que condicionam qualquer conector [FATO]:**
  - Sem ACL por arquivo: `uniform_access_confirmed` obriga o admin a confirmar que todos os membros podem ver tudo (`backend/app/workspaces/service.py:78-80`).
  - Somente 4 tipos: `ELIGIBLE_MIME_TYPES` = Google Doc, PDF, DOCX, `text/markdown` (`backend/app/ingestion/service.py:23-28`); o resto vira `ignored/unsupported_file_type` (`service.py:501`). O spec exclui OCR, PPTX, XLSX/CSV, e-mail, Dropbox e upload (`specs/001-mvp-document-intelligence.md:56-60`).
  - Extração: PDF via `page.extract_text() or ""` — PDF escaneado vira texto vazio (`backend/app/ingestion/google_drive.py:393`); `pyproject.toml` só traz `pypdf` e `python-docx` (linhas 13 e 16).
  - Limites de plano: 500 documentos ativos/org, 2 GB/mês, 1 M tokens de embedding/mês, 1.000 perguntas/mês (`backend/app/audit_usage/service.py:15-16`).
  - Vetor: `DocumentChunk.embedding` é coluna JSON (`backend/app/knowledge/models.py:59`); cosseno calculado em Python sobre as linhas do escopo (`backend/app/knowledge/questions.py:1215-1218`, top 100 semânticos `:45`). Sem pgvector/ANN.
  - Agente: o LLM só classifica intenção e sintetiza com `json_schema`; as ferramentas são funções Python locais, somente leitura do catálogo, sempre escopadas pelo servidor (`backend/app/knowledge/intent.py:29` `ALLOWED_TOOLS`; `backend/app/knowledge/agent.py:225` `LibraryToolExecutor`; `docs/agent-flow.md:14-17`).
  - **Não existem** webhooks, MCP, chaves de API ou API pública: busca por `webhook|mcp|api_key` em `backend/app` só retorna chaves de fornecedores (WorkOS, Resend, OpenAI) — [FATO, verificado]. Rotas do app usam cookie de sessão WorkOS (`backend/app/identity/auth.py`).

### 2.2 Contrato e registry

- **Contrato** (`backend/app/integrations/base.py:10-30`): `ProviderCapabilities(supports_oauth, supports_hierarchical_scopes, supports_incremental_sync)` e `SourceProvider` (Protocol) com `key`, `capabilities`, `discover(*, encrypted_credentials, selections, force_file_ids=None, force_full=False) -> list[DiscoveredDocument] | DiscoveryResult` e `folders(*, encrypted_credentials)`. `ProviderNotConfigured` em `base.py:33`.
- **Dados** em `backend/app/ingestion/service.py`: `DiscoveredDocument` (id externo, nome, mime, `source_url`, `modified_at`, `text`, `blocks`, `error_code`, `parent_ids`), `DiscoveryResult` (`documents`, `removed_file_ids`, `delta_links`, `full_snapshot`), `ExtractedBlock` (texto + `page_number` + `section_path`, que alimenta citações).
- **Registry** (`backend/app/integrations/registry.py`): adapters `GoogleDriveProviderAdapter` (`:13`, incremental=True), `NotionProviderAdapter` (`:52`, **incremental=False** `:57`), `OneDriveProviderAdapter` (`:86`, incremental=True `:91`); fábricas em `IntegrationRegistry` (`:126-132`); `get()` levanta `ProviderNotConfigured` (`:134-137`).
- **O Protocol é convenção, não contrato aplicado [FATO]:** o worker instancia o Google **fora** do registry (`backend/app/ingestion/tasks.py:241-260`, comentário "Keep the established injection point for Google") e injeta `known_documents` apenas se `source_provider == "notion"` (`tasks.py:299-304`), argumento que o Protocol não declara. Quem lê só `base.py` subestima o acoplamento.

### 2.3 Comparativo dos três conectores

| Aspecto | Google Drive | OneDrive | Notion |
|---|---|---|---|
| Código | `integrations/google_drive.py` (663 l.) + `ingestion/google_drive.py` (453 l.) | `integrations/onedrive.py` (866 l.) | `integrations/notion.py` (320 l.) |
| Escopo OAuth | `drive.readonly` (`integrations/google_drive.py:25`), **restrito** | `openid profile offline_access User.Read Files.Read` (`onedrive.py:37`) | sem escopos; OAuth `owner=user` |
| Sync incremental | `changes.list` + `startPageToken` por seleção | Graph `delta` por seleção; 410 → snapshot | **nenhum**: `POST /v1/search` lista todas as páginas a cada sync (`notion.py:104-113`), relê só as com `last_edited_time` diferente |
| Escopos de seleção | pasta, arquivos da raiz, tudo acessível (`api/integrations.py:483-501`) | idem; só `me/drive` (SharePoint fora, `docs/integrations-roadmap.md:14`) | páginas ou tudo acessível; `root_files` indisponível (`api/integrations.py:463`) |
| 429 | **sem tratamento**; `401/403` → `GoogleRemoteUnauthorized` (`integrations/google_drive.py:173,205,222,246,364,385`) | retry 4x com `Retry-After` (`onedrive.py:327-333,392-398`) | só espaçamento de 0,35 s; 429 cai em `raise_for_status` |
| Cobertura | Doc→texto; PDF/DOCX/MD | reusa o extrator do Google | blocos→`text/markdown`; databases, tabelas e anexos não entram [INFERÊNCIA] (`list_pages` filtra `object=page`) |
| Chave de cifra | `GOOGLE_TOKEN_ENCRYPTION_KEY` | `MICROSOFT_TOKEN_ENCRYPTION_KEY` | chave própria **ou fallback para a do Google** (`registry.py:60`) |

**Risco latente [INFERÊNCIA sobre FATO]:** o Drive devolve 403 também para `rateLimitExceeded`/`userRateLimitExceeded`; como todo 403 vira `GoogleRemoteUnauthorized`, um pico de quota pode marcar a fonte como `reauth_required` indevidamente. Vale corrigir antes de escalar clientes.

### 2.4 Custo real de um conector novo

**O que já vem pronto [FATO]:** `DataSource`/`WorkspaceFolder`/`Selection`, cifra Fernet + cursor cifrado, `OAuthConnectionState` (CSRF), fila com lease e idempotência (`ProcessingJob`), agendador (beat de 15 min, frescor 24 h, máx. 3 jobs/org: `backend/app/core/config.py:48-52`), re-sync manual com progresso (`backend/app/library/manual_sync.py`), chunking/embeddings/limites, projeção na biblioteca, @menções, agente e chat, RBAC e auditoria. **Um conector novo não toca no agente nem no chat.**

**O que é escrito por conector:**

| Item | Onde | Esforço [ESTIMATIVA] |
|---|---|---|
| Client OAuth + provider `discover/folders` (+ delta) | novo módulo em `integrations/` (referências: Notion 320 l., OneDrive 866 l.) | 2–5 d |
| Serviço de conexão OAuth (`begin/complete/disconnect/reauth`) | 3 cópias quase idênticas: `notion.py:179-230`, `onedrive.py:607-797`, `google_drive.py:434-635`; não há classe base | 1–2 d (0,5 d após extrair base) |
| Ramificações por provider fora do registry | rotas OAuth em `api/integrations.py:105-318`; `if provider == "onedrive"/"notion"` em `:366,:400,:447,:466,:556,:563`; casos especiais em `tasks.py:241-262,299`; nomes de exibição em `library/service.py:~780` | 1 d (0,5 d após base) |
| Frontend | catálogo hard-coded (`frontend/app/product-app.tsx:~785-799`), `ProviderLogoName` (`frontend/app/provider-logo.tsx:3`) | 1–2 d |
| Testes | padrão `tests/unit/test_notion_integration.py`, `test_onedrive.py` | 1–2 d |
| Cadastro/verificação do app no fornecedor | Entra/Google/Atlassian/Slack/Meta… | 0,5 d de config **+ lead time externo** |

**Total realista:** 5–10 d para o **primeiro** conector novo com OAuth completo (inclui extrair a base); **3–6 d** para os seguintes quando são "árvore de arquivos" ou "páginas" (SharePoint, Dropbox, Box); 3–6 d para "texto direto" por chave de API (Omie), sem árvore. Conectores de **registros** (CRM/ERP/jurídico) e **mensagens** não cabem no contrato atual sem modelar "registro → documento" e "escopo por entidade" (ver §3 e §5).

### 2.5 Lacunas transversais

| Lacuna | Evidência | Impacto |
|---|---|---|
| Webhooks/push | inexistente; polling 15 min | ok para docs, ruim para chat/e-mail |
| Rate limit unificado | políticas diferentes por client (tabela 2.3) | risco de `reauth_required` espúrio, 429 sem backoff |
| ACL por arquivo | `workspaces/service.py:80` | bloqueia Slack, e-mail, SharePoint com permissões heterogêneas; maior decisão de produto |
| Parsers/OCR | `_extract_blocks` só PDF/DOCX/MD | planilhas, PPTX, escaneados ignorados |
| Limite de 500 docs | `audit_usage/service.py:15` | inviável para e-mail/mensagens sem agrupar (thread/dia = 1 doc); também apertado ao liberar XLSX/PPTX |
| Vetor em JSON/Python | `questions.py:1215`, `models.py:59` | migrar para pgvector antes de volume |
| Sem base de serviço OAuth | 3 cópias | economiza 1–2 d por conector seguinte |
| Segredos | Notion cai na chave do Google | chave por provider |

---

## 3. Panorama das ferramentas mais usadas por PMEs

**Ressalva de qualidade dos dados:** não há levantamento independente e atual de participação por ferramenta entre PMEs brasileiras. Os "shares" abaixo vêm de agregadores por detecção em sites, de avaliações de software ou de pesquisas antigas: são **indicativos**, não medições de uso interno.

### 3.1 Contexto de mercado

| Dado | Valor | Fonte |
|---|---|---|
| Aberturas de pequenos negócios no Brasil, 2025 | ~4,95 mi; MEI ≈ 3,81 mi (76,9%); ME 933 mil; EPP 209 mil | [Data Sebrae — resumo executivo 2025](https://datasebrae.com.br/wp-content/uploads/2026/01/13012026_resumo_executivo_aberturas_pn_anual.pdf) |
| WhatsApp como canal principal (serviços, MEI/MPE) | 82% | [Agência Sebrae](https://agenciasebrae.com.br/cultura-empreendedora/whatsapp-e-o-principal-meio-de-comunicacao-para-80-dos-negocios-de-servico/) |
| Importância atribuída a CRM | <10% dos pesquisados (6% dos empreendedores) | mesma fonte |
| Suíte de escritório | divergem por metodologia: 6sense Google 73,4% × Microsoft 16,4%; Enlyft 7,75 mi de empresas em M365 × 7,33 mi em Google; avaliações de pequenas empresas: Google 46,3%, Microsoft 35,1% no mid-market | [Interdatalink 2026](https://interdatalink.com/microsoft-365-vs-google-workspace-smb-2026/), [Fit Small Business](https://fitsmallbusiness.com/g-suite-vs-office-365/) |
| Armazenamento SMB (≤50 func.) | Dropbox 40%, Google 24%, Box 10% — pesquisa Spiceworks **antiga, sem ano confirmado**; usar só como indício | [Channel Futures](https://channelfutures.com/cloud/dropbox-microsoft-office-365-gain-smb-cloud-momentum) |

**Leituras (juízo da síntese):**
- Google e Microsoft têm base comparável; cobrir **os dois** é necessário. O gap real no ecossistema Microsoft é **SharePoint/Teams**, não OneDrive.
- A base BR é dominada por MEI (solo). O ICP do Arquivio (20–150 pessoas, ≥3 membros ativos) é uma fatia menor; **o dado de WhatsApp (82%) descreve MEI/MPE, não necessariamente o ICP** — cuidado ao usá-lo para priorizar.
- Só Drive/OneDrive/SharePoint aparecem de forma consistente em todos os ramos; isso sustenta priorizar armazenamento e formatos antes de sistemas verticais.

### 3.2 Por ramo (ferramentas prováveis onde vivem os documentos)

Mistura de dados verificados com inferência sobre onde os documentos vivem (marcado onde não há dado).

| Ramo | Documentos | Sistema-núcleo | Comunicação | Observação |
|---|---|---|---|---|
| Contabilidade | Drive/OneDrive; portal do sistema contábil | Domínio/Onvio, Alterdata, Omie, Conta Azul | WhatsApp, e-mail | assinatura (Clicksign, D4Sign); APIs de Domínio/Alterdata não verificadas |
| Advocacia | Drive/OneDrive/SharePoint | ADVBOX, Astrea, Projuris | WhatsApp, e-mail | ADVBOX: API paga por escritório; sem endpoint de documentos confirmado |
| Clínicas | Drive/OneDrive | Feegow, iClinic, Amplimed | WhatsApp | prontuário é dado sensível (LGPD); mercado fragmentado; APIs não verificadas |
| Imobiliárias | Drive | Jetimob, Kenlo, Vista | WhatsApp | assinatura de contratos |
| Construção | SharePoint/Drive; Autodesk ACC | Sienge (>5 mil construtoras), Procore | WhatsApp, e-mail | Procore 3.600 req/h por padrão |
| Varejo/e-commerce | Drive | Bling, Tiny, Omie | WhatsApp | dados transacionais, pouco documento |
| Agências/marketing | Drive, Notion | RD Station, HubSpot | Slack/Teams, e-mail | Trello/ClickUp/Asana |
| Indústria | SharePoint | Sankhya, TOTVS | e-mail | ERP local |
| Educação | Google Workspace for Education | LMS (Classroom, Moodle, Canvas) | e-mail | cai no conector Drive existente |
| Serviços/consultoria (ICP central) | Drive/OneDrive/SharePoint, Notion, Confluence | Conta Azul, Omie | WhatsApp, Teams, Slack | CRM, assinatura |

Fontes por ramo: ERP/contábil — [Apideck Brasil](https://www.apideck.com/integrations/country/brazil/lang/pt), [Mundo do Marketing — Omie](https://mundodomarketing.com.br/a-estrategia-da-omie-para-crescer-em-um-mercado-limitado-pelas-planilhas-de-excel) (verificar data), [Jornal Contábil](https://jornalcontabil.com.br/noticia/thomson-reuters-anuncia-solucao-para-microempresas-que-faz-integracao-com-o-sistema-do-contador/); CRM — [Acontecendo Aqui (ranking Reportei)](https://acontecendoaqui.com.br/inovacao/rd-station-lidera-uso-de-plataformas-de-crm/), [B2B Stack](https://www.b2bstack.com.br/categoria/crm-para-pequenas-empresas); clínicas — [Brazil Journal](https://braziljournal.com/por-que-o-softbank-esta-investindo-na-iclinic) (dado antigo), [Startups.com.br](https://startups.com.br/negocios/doctoralia-compra-brasileira-feegow-e-mira-gestao-para-clinicas/); construção — [Sienge](https://sienge.com.br/blog/apis-do-sienge/); e-commerce — [wmtips](https://www.wmtips.com/technologies/e-commerce/country/br/) (duas medições divergem); suporte — [wmtips](https://www.wmtips.com/technologies/customer-support/country/br/) (Zendesk 62,8% por detecção), [idatalabs — Movidesk](https://idatalabs.com/tech/products/movidesk); jurídico — [ADVBOX](https://advbox.com.br/api), [Aurum — Astrea](https://www.aurum.com.br/astrea/).

---

## 4. Matriz de viabilidade por integração candidata

Escala de esforço: dias-pessoa [ESTIMATIVA], já incluindo backend + frontend + testes, **excluindo lead time externo**. Impacto 1–5 = aderência ao ICP × tamanho da base × diferenciação. Limites de API mudam com frequência (Slack e Atlassian mudaram em 2025–2026): revalidar antes de comprometer prazos.

### 4.1 Fontes de arquivos e páginas (cabem no contrato atual)

| Integração | API / auth | Delta / webhook | Rate limit | Gates | Esforço | Impacto | Risco |
|---|---|---|---|---|---|---|---|
| **SharePoint / bibliotecas de site (M365)** | mesmo Graph e app Entra do OneDrive; `Sites.Read.All`/`Files.Read.All`; `/sites/{id}/drive/root/delta` ([site delta](https://learn.microsoft.com/en-us/graph/api/site-delta)) | delta já implementado; change notifications por webhook ([Graph webhooks](https://learn.microsoft.com/graph/api/resources/webhooks)) | Graph: 3.500–8.000 RU/10 s por app+tenant ([Graph throttling](https://learn.microsoft.com/en-gb/graph/throttling-limits)); SharePoint: 18.750–93.750 RU/5 min conforme licenças ([SharePoint throttling](https://learn.microsoft.com/it-it/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online)) | possível consentimento de admin do tenant (a validar em tenant de teste); publisher verification não pesquisada | **3–5 d** (trocar `/me/drive` por `/drives/{id}`, ID composto `driveId!itemId` que o código já antecipa em `onedrive.py:409-411`, catálogo de sites) | 5 | baixo |
| **Dropbox** | OAuth 2 + PKCE, `files.content.read`; `list_folder` com cursor | cursor `list_folder/continue` ↔ `encrypted_delta_link`; webhook só avisa a conta ([webhooks](https://www.dropbox.com/developers/webhooks/tutorial)) | não publicado; 429 com `Retry-After` ([Dropbox Forum](https://www.dropboxforum.com/discussions/101000014/api-limits-on-rpc-endpoints/334768)) | app nasce em "development"; ao vincular 50 usuários, ~2 semanas para status de produção ([Dropbox Forum](https://www.dropboxforum.com/discussions/101000014/does-a-dropbox-app-have-a-limit-on-development-users/846671)) | **4–6 d** | 3 | baixo |
| **Box** | OAuth 2 | webhooks/events: **não verificado** | 1.000 req/min por usuário ([Box rate limits](https://developer.box.com/guides/api-calls/permissions-and-errors/rate-limits/)) | não verificado | 4–6 d | 2 (perfil mais corporativo) | baixo |
| **Notion (melhorias)** | já existe | webhooks em beta público, payload só de IDs ([Truto](https://truto.one/blog/how-to-integrate-with-the-notion-api-architecture-guide-for-b2b-saas.md)) | 180 req/min (600 no Business/Enterprise) + limite por workspace ([Notion limits](https://developers.notion.com/reference/request-limits)) | — | **3–5 d** (databases, tabelas, evitar `search` completo) | 3 | baixo |
| **Confluence Cloud** | REST v2 + OAuth 3LO | sem delta simples; polling por `lastModified`/CQL [INFERÊNCIA] | cotas por pontos desde 02/03/2026; **pool global de 65.000 pontos/h** compartilhado entre todos os tenants do app; cota por tenant só por revisão da Atlassian ([Atlassian](https://developer.atlassian.com/cloud/confluence/rate-limiting)) | revisão para cota por tenant | 5–8 d (conversão ADF→texto) | 2–3 (pouca presença em PME BR) | médio (teto global) |
| **Google Drive (existente)** | — | — | 12.000 consultas/60 s; `changes.watch` conta na cota ([limites](https://developers.google.com/workspace/drive/api/guides/limits)) | **`drive.readonly` é escopo restrito** ([classificação de escopos do Drive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), verificado: `drive.file` = non-sensitive; `drive.readonly` e `drive.metadata.readonly` = restricted) → verificação + avaliação CASA anual ([restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)) | 2–4 d de eng. + lead time | 5 (bloqueia go-to-market) | **alto** |

### 4.2 Planilhas e formatos (parser, não conector)

| Item | Situação | Esforço | Impacto | Risco |
|---|---|---|---|---|
| **XLSX/CSV/TXT/PPTX** | já chegam via Drive/Graph, mas são descartados como `unsupported_file_type` (`ingestion/service.py:501`) | 4–7 d (openpyxl/CSV → blocos por linha com cabeçalho; mesma técnica das tabelas DOCX em `ingestion/google_drive.py:412-422`) | 5 | qualidade de chunking de tabelas; pressão sobre o limite de 500 docs |
| **OCR em camadas** | PDF escaneado hoje vira texto vazio | 4–7 d + suíte de avaliação PT-BR (`agent_eval.py` pode ser estendido) | 5 | baixo; LGPD se usar API nos EUA |

### 4.3 Comunicação e mensagens (exigem contrato/ACL novos)

| Integração | API / auth | Delta / webhook | Rate limit | Gates | Esforço | Impacto | Risco |
|---|---|---|---|---|---|---|---|
| **Slack como fonte** | OAuth 2, `channels:history` | Events API | desde 29/05/2025, apps distribuídos fora do Marketplace: `conversations.history/replies` = **1 req/min, 15 itens**; instalações existentes migradas em 03/03/2026 ([changelog](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps)) | **Marketplace**; ACL por canal | 10–15 d | 3 | alto |
| **Slack como canal (bot de perguntas)** | slash command/menção | Events | o limite pesa pouco (não ingere histórico) | revisão do Marketplace (semanas); mapear usuário Slack ↔ membro da org [INFERÊNCIA] | 3–6 d | 4 | baixo-médio |
| **Teams como canal** | Microsoft 365 Agents SDK/Teams SDK (Bot Framework arquivado, suporte encerrado em 31/12/2025); SDK Python em preview ([migração](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/bf-migration-guidance)) | — | — | manifesto + aprovação do admin do tenant | 7–12 d | 3–4 | médio (SDK em transição) |
| **Gmail** | escopos de leitura **restritos** → CASA; push por Pub/Sub, `watch` renovado a cada ≤7 dias ([push](https://developers.google.com/gmail/api/guides/push)) | `historyId` | 250 unidades/s por conta ([quota](https://developers.google.com/workspace/gmail/api/reference/quota)) | CASA; ACL | 10–15 d | 3 (agora); 5 (após ACL) | alto |
| **Outlook (Graph)** | mesmo Graph | change notifications; ≤1.000 assinaturas Outlook/caixa ([Outlook notifications](https://learn.microsoft.com/da-dk/Graph/outlook-change-notifications-overview)) | Graph | ACL | 10–15 d | 3 | alto |
| **WhatsApp Business (Cloud API)** | Meta Cloud API; webhooks | webhook para mensagens novas; **sem histórico retroativo** [INFERÊNCIA — confirmar] | cobrança por mensagem desde 01/07/2025; faturamento em BRL desde 01/07/2026 ([Meta pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)) | política Meta: desde 15/01/2026 proíbe assistentes de IA de propósito geral como produto principal ([respond.io](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban)); WABA/BSP por cliente | 10–15 d + operação | 3 como **canal**; 1–2 como fonte | alto |

### 4.4 ERP/CRM/jurídico/assinatura (exigem contrato de registros)

| Integração | API / auth | Rate limit | Gates | Esforço | Impacto | Risco |
|---|---|---|---|---|---|---|
| **Conta Azul** | OAuth 2.0 + PKCE, REST/OpenAPI ([Conta Azul](https://contaazul.com/blog/api-conta-azul-integracoes-para-o-seu-negocio/), [Nango](https://nango.dev/docs/api-integrations/conta-azul/how-to-register-your-own-conta-azul-api-oauth-app)) | não verificado | registro do app no portal | 5–8 d (+ contrato de registros) | 4 BR | médio |
| **Bling** | API v3 OAuth 2.0 | 3 req/s, 120.000/dia; bloqueio de IP de 10 min (600 req/10 s ou 300 erros/10 s) e 60 min (20 pedidos de token/60 s) ([Bling](https://developer.bling.com.br/limites)) | — | 5–8 d | 3–4 BR | médio |
| **Omie** | `app_key`/`app_secret` (sem OAuth), somente POST, SOAP/JSON ([Omie](https://ajuda.omie.com.br/pt-BR/articles/5412721-caracteristicas-e-recomendacoes-das-apis-do-omie)) | 960 req/min/IP; 240/min por IP+app+método; 4 simultâneas; mesma consulta em <60 s é bloqueada ([Omie](https://ajuda.omie.com.br/pt-BR/articles/8112984-limites-de-consumo-da-api-do-omie)) | tela de credencial em vez de OAuth | 4–7 d | 3 BR | médio |
| **Clicksign / D4Sign / ZapSign** | Clicksign: API v3 (envelopes), Bearer, webhooks HMAC, sandbox ([Clicksign](https://developers.clicksign.com)); D4Sign: REST + webhook ([D4Sign](https://docapi.d4sign.com.br/v2.0)); ZapSign: API só em plano pago (US$ 39–224/mês) ([ZapSign](https://zapsign.co/pricing)) | limites não explícitos | conta do cliente | 4–7 d | 3 (contratos assinados são documento de alto valor, mas costumam já cair no Drive) | baixo |
| **RD Station CRM / HubSpot / Pipedrive** | RD: APIs públicas (limites **não verificados**); HubSpot: 110 req/10 s por conta em apps OAuth ([HubSpot](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines)); Pipedrive: limites por token em janelas de 2 s ([Pipedrive](https://pipedrive.readme.io/docs/core-api-concepts-rate-limiting)) | ver ao lado | — | 6–10 d cada | 2–3 (CRM: 6% de importância entre MEI) | médio |
| **ADVBOX** | REST Bearer; API paga por escritório (R$ 280/mês; parceiros R$ 3.500/mês) ([ADVBOX](https://advbox.com.br/api)) | não verificado | sem endpoint de documentos confirmado | 6–10 d | 2–3 | médio |
| **Movidesk / Zendesk / Freshdesk** | tokens por conta | Movidesk **10 req/min** ([Movidesk](https://atendimento.movidesk.com/kb/en/article/130599/api-do-movidesk)); Zendesk 200–2.500/min ([Zendesk](https://developer.zendesk.com/api-reference/introduction/rate-limits/)) | — | 6–10 d | 2 | alto (limite inviabiliza volume) |
| **Salesforce, Trello, Asana, ClickUp, monday, Jira** | — | — | — | — | 1–2 | fora de foco (baixo valor documental) |
| **Clínicas, imobiliário, obras (verticais)** | APIs **não verificadas** (exceção: Sienge lista 30+ APIs, auth/limites não verificados; Vista tem API Key) | — | parceria, DPA; prontuário = dado sensível | — | 3 | alto; só sob demanda de cliente-âncora |

---

## 5. Integrações de extensão

### 5.1 Servidor MCP próprio (recomendado)

- **Valor:** o cliente consulta a biblioteca dentro de Claude/ChatGPT/Cursor, com citações. É canal de distribuição sem custo de licença. Tools sugeridas, somente leitura: `search` e `fetch` (contrato clássico exigido pelo ChatGPT), `list_sources`, opcionalmente `ask`. Reaproveita `LibraryToolExecutor` (`backend/app/knowledge/agent.py:225`) e os endpoints `POST /workspace-folders/{id}/search` (`api/ingestion.py:262`) e `POST /organizations/{id}/questions` (`:333`).
- **Spec:** ver §9.1-C2. Há revisão **2026-07-28** (protocolo sem estado, sem `Mcp-Session-Id`, Roots/Sampling/Logging depreciados) ([MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)) além da 2025-11-25. Implementar com o SDK Python oficial na revisão mais recente que Claude/ChatGPT aceitem no momento da entrega.
- **Autorização:** servidor MCP = *resource server* OAuth 2.1; deve implementar Protected Resource Metadata (RFC 9728), validar `audience` (RFC 8707) e **não repassar tokens** ([MCP Authorization 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)). O app já usa WorkOS; o **AuthKit funciona como authorization server OAuth 2.0 compatível com MCP** ([WorkOS — MCP](https://workos.com/docs/authkit/mcp)), o que evita construir AS próprio (não validei em detalhe a integração com o fluxo atual de sessão).
- **Requisitos no app:** token por usuário+organização (nunca aceitar o cookie de sessão como credencial do MCP); mapear token → `OrganizationScope`/workspace e reutilizar as mesmas checagens; `readOnlyHint` nas tools; rate limit e auditoria (`audit_usage`). Testes de isolamento de tenant já têm base em `tests/integration/test_organization_tenant_isolation.py`.
- **Clientes:** Claude aceita conector customizado por URL e listagem no Directory ([Claude Docs — Build an MCP server](https://claude.com/docs/connectors/building.md)); ChatGPT exige HTTPS público e modo search/fetch ([FastMCP — ChatGPT](https://gofastmcp.com/v2/integrations/chatgpt), fonte de terceiro — confirmar na doc da OpenAI).
- **Esforço:** **8–12 d** para MCP remoto com OAuth (ver C1). Riscos: segurança/ACL (médio); prompt injection (ver §8).

### 5.2 API pública com chaves + webhooks de saída (pré-requisito de automação)

Hoje só existem rotas de sessão de navegador. Uma API versionada (`/v1/search`, `/v1/ask`), chaves de serviço por organização com escopos e rate limit, OpenAPI (FastAPI já gera) e webhooks de saída assinados por HMAC (`document.indexed`, `sync.failed`). **Esforço 4–8 d** (o maior é chaves/escopos/rate limit); **12–18 d** se feita junto com o MCP (a camada "token → escopo" é compartilhada, então a soma é menor que os itens separados). Habilita Zapier/Make/n8n: Zapier cobra por task (US$ 19,99/750 tasks), Make por operação (US$ 9/10 mil), n8n grátis self-host ([Automation Atlas](https://automationatlas.io/guides/zapier-vs-make-vs-n8n-comparison/), fonte de terceiro). Publicar app oficial no Zapier/Make é etapa posterior (revisão do parceiro). Impacto médio; alavanca de retenção sem construir conector a conector.

### 5.3 MCPs de terceiros (cliente MCP no agente)

| Servidor | Estado | Observação |
|---|---|---|
| Atlassian Rovo MCP | GA desde 04/02/2026, OAuth, admins controlam clientes ([Atlassian](https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga)) | alternativa a construir Confluence/Jira como fonte "ao vivo" |
| Slack MCP | oficial, só apps do Directory ou internos ([Slack MCP](https://docs.slack.dev/ai/slack-mcp-server/)) | depende de Marketplace |
| HubSpot | remoto, OAuth ([HubSpot](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server)) | CRM de PME |
| Google Workspace | Developer Preview desde 01/05/2026 ([Workspace Updates](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html)) | não substitui o conector Drive |
| Conta Azul (comunitário) | [mcpservers.org](https://mcpservers.org/pt-BR/servers/douglac/contaazul-mcp) | só referência, não dependência de produção |

**Recomendação:** consumir MCPs de terceiros **só como ferramentas explícitas, somente leitura, com aprovação e allow-list por org**, e **nunca como fonte de indexação** (MCP não dá ACL, sync incremental nem re-ingestão). Isso **quebra o invariante atual** (respostas 100% do catálogo local, escopo imposto pelo servidor — `docs/agent-flow.md:14-17`) e amplia a superfície de exfiltração: fazer só depois do MCP próprio e com citação rotulada "fonte externa ao vivo". Esforço 8–15 d + desenho de segurança; impacto 2–3.

### 5.4 OCR/parsing

Arquitetura em 2 níveis dentro de `_extract_blocks` (`ingestion/google_drive.py:390`): (1) `pypdf`; (2) se o texto por página ficar abaixo de um limiar, cair para OCR.

| Opção | Preço / 1.000 págs | Notas |
|---|---|---|
| **Docling** (self-host, MIT) | grátis (CPU/GPU no worker Celery) | cobre PDF, DOCX, PPTX, XLSX, HTML; dados não saem da infra (bom para LGPD) ([IBM Research](https://research.ibm.com/blog/docling-generative-AI)) |
| Azure Document Intelligence Read | ~US$ 1,50 | ([Azure](https://azure.microsoft.com/en-in/pricing/details/form-recognizer)) |
| Google Document AI | OCR US$ 1,50; Layout Parser US$ 10 | ([Google](https://cloud.google.com/document-ai/pricing)) |
| AWS Textract | US$ 1,50 (texto) | ([AWS](https://aws.amazon.com/fr/textract/pricing/)) |
| Mistral OCR 3 | US$ 2 (US$ 1 em batch) | Markdown com tabelas ([Mistral](https://mistral.ai/news/mistral-ocr-3)) |
| LlamaParse / Unstructured | ~US$ 1,25 por 1.000 créditos / ~US$ 30 | preços de agregadores em parte ([LlamaParse](https://developers.llamaindex.ai/llamaparse/general/pricing/)) |

Recomendação: **Docling self-host como padrão** (custo zero por página, sem novo sub-processador) e API de OCR como opção por plano. Para 10 mil páginas escaneadas/mês, US$ 10–20 se via API. Esforço 4–7 d. Não medi benchmarks em português.

### 5.5 Transcrição de áudio/vídeo

Deepgram Nova-3 ~US$ 0,26/h, AssemblyAI ~US$ 0,15/h (+US$ 0,02/h com diarização), OpenAI gpt-4o-transcribe por tokens de áudio ([Deepgram/terceiro](https://convertaudiototext.com/blog/deepgram-nova-3-explained), [Gladia](https://gladia.io/blog/assemblyai-pricing), [OpenAI](https://developers.openai.com/api/docs/models/gpt-4o-transcribe)); Whisper self-host sem custo por hora. Reuniões gravadas em Drive/OneDrive/Teams viram conhecimento, com timestamp como "página" da citação. Esforço 5–8 d; impacto médio-alto; risco: voz é dado pessoal (DPA do fornecedor). Fora do MVP atual (spec exclui); fica para a onda 3.

### 5.6 E-mail

Ver §4.3 (Gmail/Outlook). Só depois de ACL e OCR; começar por "anexos de uma pasta/rótulo", não caixa inteira.

### 5.7 Slack/Teams/WhatsApp como canais de saída

Tratados na §4.3. Como **canal de perguntas** (bot com citações), Slack e Teams são coerentes com a proposta e evitam o limite de ingestão. Cuidado de produto: o bot responde a quem está no Slack/Teams, não necessariamente a membros da org; é preciso mapear identidade (e-mail) e respeitar `uniform_access_confirmed` [INFERÊNCIA]. WhatsApp: só após pesquisa de demanda e validação da política Meta, com WABA por cliente.

### 5.8 Conectores unificados: construir ou comprar

| Plataforma | Modelo / preço | Adequação |
|---|---|---|
| **Nango** | grátis (10 conexões); pay-go US$ 50/mês + US$ 0,29/conexão; self-host só Enterprise; SOC 2 Type II ([Nango](https://www.nango.dev/pricing)) | melhor candidato: auth + proxy + sync sem impor modelo unificado |
| **Unified.to** | pass-through, sem armazenar dados; storage API cobre Drive, Dropbox, Box, OneDrive, SharePoint ([Unified](https://unified.to/blog/unified_file_storage_api_integrations_guide)); **preço não verificado** | bom para storage rápido; menos controle de delta/ACL |
| Composio / Pipedream Connect | foco em **ações** de agente, US$ 29–228/mês / US$ 99/mês ([Composio](https://www.trustradius.com/products/composio/pricing), [Pipedream](https://pipedream.com/docs/pricing.md)) | não resolvem ingestão em massa |
| Merge.dev / Paragon | por conta/usuário; Merge ≈ US$ 650/mês até 10 contas, US$ 30–55 mil/ano no Professional ([Knit — blog de concorrente](https://getknit.dev/blog/understanding-merge-dev-pricing-finding-the-right-unified-api-for-your-integration-needs)); Paragon ~US$ 30 mil/ano ([Paragon](https://useparagon.com/pricing)) | caros para ARPU de PME; Merge armazena dados (mais um sub-processador) |
| Ragie | RAG-as-a-service, US$ 250/conector/mês ([Ragie](https://ragie.ai/pricing)) | **substitui o núcleo do produto**; não recomendado |
| Carbon | descontinuada como produto independente após aquisição pela Perplexity ([The Decoder](https://the-decoder.com/perplexity-acquires-carbon-to-expand-external-data-connections/)) | exemplo do risco de fornecedor |

**Decisão:** manter conectores próprios para Drive/OneDrive/Notion e construir SharePoint, Dropbox e Box (cabem no contrato; 3–6 d cada). Reavaliar **Nango** apenas se a fila de novas fontes passar de ~3–4 conectores de cauda longa/registros (CRM, ERP, tickets), quando o custo de OAuth/refresh/rate limit por conector supera o custo por conexão. Todo intermediário entra na lista de sub-processadores (LGPD).

---

## 6. Matriz impacto × esforço

Impacto 1–5; esforço em dias-pessoa [ESTIMATIVA]; consolida os três relatórios.

| # | Iniciativa | Impacto | Esforço | Quadrante |
|---|---|---|---|---|
| A | Endurecer o núcleo (403/429 do Drive, `RemoteHttp`, chave por provider, base OAuth) | 4 | 3–5 d | **Fazer já** |
| B | XLSX/CSV/TXT/PPTX | 5 | 4–7 d | **Fazer já** |
| C | OCR em camadas (Docling) | 5 | 4–7 d | **Fazer já** |
| D | Decisão CASA vs `drive.file`+Picker | 5 | 2–4 d + 4–8 sem externas | **Fazer já (paralelo)** |
| E | SharePoint / M365 | 5 | 3–5 d | **Fazer já** |
| N | pgvector / índice ANN | 4 | 3–5 d | **Fazer já** (antes de volume) |
| F | API pública + chaves | 4 | 4–8 d | Próximo |
| G | MCP server remoto próprio | 5 | 8–12 d (12–18 com F) | Próximo |
| H | Bot Slack (canal) | 4 | 3–6 d + Marketplace | Próximo (submeter cedo) |
| I | Dropbox | 3 | 4–6 d | Próximo |
| J | Notion (databases, tabelas, sem search total) | 3 | 3–5 d | Próximo |
| K | Webhooks de entrada (Drive/Graph/Notion) | 3 | 4–6 d por provider | Depois |
| L | Auditoria anti prompt-injection do RAG | 4 (habilita G/H) | 2–4 d | Próximo (pré-requisito de G) |
| M | Bot Teams | 3–4 | 7–12 d | Depois |
| O | Transcrição | 3–4 | 5–8 d | Depois |
| P | Contrato de registros + Conta Azul → Bling → Omie | 4 BR / 2 global | 8–12 d (contrato) + 5–8 d cada | Depois |
| Q | Clicksign/D4Sign/ZapSign | 3 | 4–7 d | Sob demanda |
| R | Confluence | 2–3 | 5–8 d | Sob demanda (ou Rovo MCP) |
| S | **ACL por arquivo/canal** | 5 (destrava Slack/e-mail/SharePoint sensível) | 15–25 d | **Estratégico** |
| T | Slack como fonte / Gmail / Outlook | 3 | 10–20 d cada + gates | Só após S |
| U | WhatsApp (canal) | 3 | 10–15 d + operação | Condicionado a demanda e política Meta |
| V | Nango/Unified.to | 3 | 5–8 d (primeira) | Condicionado a >3–4 fontes novas |
| W | Cliente MCP no agente (tools ao vivo) | 2–3 | 8–15 d | Depois de G |
| X | SOC 2 Type II | habilita enterprise | US$ 25–60 mil no 1º ano | Quando um cliente exigir |

Leitura por quadrante:

```
Impacto alto ─┬─ Fazer já: B, C, D, E, N, A ─┬─ Próximo: G, F, H, L ─┬─ Estratégico: S
              │                               │                        │
Impacto médio ┼─ Próximo: I, J ──────────────┼─ Depois: K, M, O, P ──┼─ Condicionado: U, V, T
              │                               │                        │
Impacto baixo ┴─ (ignorar) Salesforce, PM ────┴─ Sob demanda: Q, R ────┴─
              Esforço baixo (≤7 d)             Esforço médio (8–15 d)    Esforço alto (>15 d)
```

---

## 7. Roadmap em ondas

Premissa de capacidade: 1–2 desenvolvedores; ordem pode ser paralelizada onde não há dependência.

### Onda 1 — 0 a 30 dias: cobertura e chão firme

- **Pré-requisitos de plataforma:** (a) `RemoteHttp` comum com 429/`Retry-After`/backoff+jitter e distinção 403-quota vs 403-auth no Drive (`integrations/google_drive.py:173…385`); (b) base de serviço OAuth extraída das 3 cópias; (c) chave de criptografia por provider (`registry.py:60`); (d) pgvector no lugar do JSON (`models.py:59`, `questions.py:1215`); (e) OCR em camadas + parsers em `_extract_blocks` e `ELIGIBLE_MIME_TYPES` (`service.py:23`), com suíte de avaliação PT-BR.
- **Entregas:** XLSX/CSV/TXT/PPTX (B) e OCR (C); **SharePoint** (E); decisão e **início do CASA** ou plano `drive.file`+Picker (D); pacote LGPD (DPA, lista de sub-processadores, cláusulas ANPD); auditoria de prompt injection no RAG (L).
- **Atualizar o spec:** OCR, planilhas e PPTX estão em "Excluído" no spec 001 (`:56-60`); esta onda exige revisar essa decisão explicitamente.
- **Saída:** % de arquivos `ignored/unsupported_file_type` por org (deve cair); taxa de `reauth_required` espúrio (→ 0); nº de orgs com SharePoint conectado.

### Onda 2 — 30 a 90 dias: distribuição e canais

- **Pré-requisitos:** API pública com chaves por organização (escopos, rate limit, auditoria) — F; tokens OAuth de máquina via WorkOS AuthKit; webhook de entrada assinado + renovação de canais (Drive `changes.watch` expira em ≤7 dias) para K quando a latência importar.
- **Entregas:** **MCP remoto somente leitura** (G) com `search`/`fetch`; **bot Slack** (H; submeter ao Marketplace já no início da onda, é o item mais lento); Dropbox (I); melhorias do Notion (J); webhooks de Drive/Graph se houver demanda de frescor; ajuste do limite de 500 docs/org para acomodar planilhas e PPTX.
- **Saída:** consultas via API/MCP por semana; nº de orgs com ≥2 fontes; frescor médio por fonte.

### Onda 3 — 90 a 180 dias: profundidade e verticais

- **Pré-requisitos:** **ACL por arquivo/canal** (S) — decisão de produto que muda `uniform_access_confirmed`; contrato de "registro → documento" e escopo por entidade; avaliação de Nango se >3–4 fontes novas de cauda longa.
- **Entregas:** ACL (S) → só então Slack como fonte e e-mail com escopos mínimos (T); bot Teams (M) após estabilizar o SDK Python; transcrição (O); **Conta Azul primeiro, depois Bling, depois Omie** (P); Clicksign sob demanda (Q); WhatsApp como canal se a pesquisa de demanda e a política Meta permitirem (U); SOC 2 quando um cliente enterprise exigir (X); cliente MCP no agente (W) só com allow-list e rótulo "fonte externa ao vivo".
- **Saída:** nº de contas com ACL ativa; cobertura de ERP/assinatura entre clientes-âncora.

---

## 8. Riscos e conformidade

### 8.1 Google: escopo restrito e CASA

`drive.readonly` (`integrations/google_drive.py:25`) e `drive.metadata.readonly` são **restritos**; `drive.file` é non-sensitive ([Google — escopos do Drive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)) [verificado]. Apps que acessam dados restritos e passam por servidor de terceiros exigem verificação + avaliação CASA por laboratório, renovada a cada 12 meses ([Google — restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)). Isenções: uso pessoal, teste, dados do próprio serviço, uso interno no Workspace. **Custo incerto** (ver C3): fee do assessor US$ 500–4.500 vs materiais de marketing de US$ 15–75 mil/ano — cotar com o assessor. Gmail entra quase no mesmo processo. Alternativa: `drive.file` + Picker elimina o escopo restrito ao custo de UX de seleção (o usuário escolhe arquivos), o que conflita parcialmente com "pasta como unidade" e sync por pasta; é decisão de produto. Não há evidência no repo de que o CASA já foi feito [não encontrado].

### 8.2 LGPD

- O app deve assumir o papel de **operador** (cliente = controlador) e ter DPA, lista pública de sub-processadores e regiões.
- Transferência internacional (OpenAI, APIs de OCR/transcrição nos EUA): base legal + cláusulas-padrão da Resolução ANPD 19/2024, com adequação de contratos anteriores encerrada em 23/08/2025 ([Mattos Filho](https://www.mattosfilho.com.br/unico/regulamentacao-transferencia-internacional-dados/)).
- Cada novo intermediário (Nango, Unified, OCR em API, transcrição) é sub-processador. **Docling self-host evita esse custo.**
- Dados sensíveis: prontuários (clínicas), voz, e-mails pessoais — exigem base legal específica; evitar verticais de saúde sem cliente-âncora e jurídico.

### 8.3 SOC 2

Type II exige janela de observação de 3–6 meses; primeiro ano típico US$ 25–60 mil, depois US$ 15–40 mil/ano ([Beancount](https://beancount.io/ja/blog/2026/07/14/soc-2-type-ii-small-saas-audit-cost-guide), fonte de terceiro). Só quando um cliente/enterprise exigir. Fornecedores como Nango já têm SOC 2 Type II, o que ajuda na cadeia.

### 8.4 Segurança de agentes e MCP

- **Prompt injection ("lethal trifecta")**: dado privado + conteúdo não confiável + capacidade de exfiltrar. Caso real em maio/2025 no MCP oficial do GitHub ([DevClass](https://devclass.com/2025/05/27/researchers-warn-of-prompt-injection-vulnerability-in-github-mcp-with-no-obvious-fix/)). **Aplica-se ao Arquivio**: um PDF ou página Notion ingerido com instruções escondidas é conteúdo não confiável dentro do RAG. Mitigações: chunks como dados (delimitadores + instrução de sistema), sem ferramentas de escrita/envio no mesmo turno em que se lê conteúdo ingerido, sem renderizar links/imagens de URLs arbitrárias, confirmação humana para ações com efeito colateral. Hoje o desenho ajuda: o agente só tem ferramentas de leitura locais (`agent.py:225`).
- **MCP:** proibido repassar tokens, validar audience, bloquear IPs privados/metadata ao buscar URLs de descoberta, sessões nunca como autenticação, escopos mínimos ([MCP — Security Best Practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)).
- **Plataformas:** Slack Marketplace, Meta business verification, revisão Atlassian e aprovação de admin Microsoft são gates de distribuição, não de engenharia — iniciar cedo.

### 8.5 Riscos de produto

- ACL: sem ela, fontes com dados privados por usuário (Slack DM, e-mail, SharePoint heterogêneo) contradizem a premissa "todos os membros veem tudo".
- Escala: busca vetorial em Python e limite de 500 docs quebram com fontes de volume.
- Dependência de APIs de terceiros que mudam limites (Slack 2025, Atlassian 2026).

---

## 9. O que ficou incerto

### 9.1 Contradições encontradas e como foram resolvidas

| # | Contradição | Resolução |
|---|---|---|
| C1 | **Esforço do MCP:** 5–8 d (h-8t) vs 8–12 d (h-8v). | Diferença de escopo. h-8t contava API+chaves à parte (3–5 d); h-8v incluía authorization server e mapeamento token→escopo. Adotado: **MCP com OAuth 8–12 d; API pública com chaves 4–8 d; juntos 12–18 d** (camada de auth compartilhada). |
| C2 | **Versão da spec MCP:** h-8v tratou 2025-11-25 como vigente. | Busca nesta síntese encontrou a revisão **2026-07-28** (protocolo sem estado, sem `Mcp-Session-Id`, Roots/Sampling/Logging depreciados) ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). Registrado como **incerto**: o suporte de Claude/ChatGPT à 2026-07-28 e o suporte do WorkOS AuthKit a ela não foram verificados. Usar o SDK oficial e testar na entrega. |
| C3 | **Custo do CASA:** "quatro dígitos" (h-8t), US$ 15–75 mil (h-8u), US$ 500–4.500 do assessor vs US$ 15–75 mil de marketing (h-8v). | Faixa **não confiável**: as fontes são secundárias e medem coisas diferentes (fee do assessor vs custo total anual). Adotado: orçar entre US$ 500 e US$ 75 mil e **cotar com assessor credenciado**. Não influencia a recomendação (ação imediata é decidir CASA vs `drive.file`). |
| C4 | **`drive.readonly` é restrito?** h-8u disse que a página do Google não lista quais escopos do Drive são restritos; h-8t citava a mesma página como prova. | **Verificado nesta síntese**: a página de escopos do Drive classifica `drive.readonly` e `drive.metadata.readonly` como restritos e `drive.file` como non-sensitive. Fato, não inferência. |
| C5 | **Custo de um conector:** 5–10 d (h-8t) vs 3–6 d (h-8v) vs "B/M" (h-8u). | Ambos certos para casos diferentes: 5–10 d para o **primeiro** conector com OAuth completo (inclui extrair a base OAuth, hoje copiada 3 vezes); 3–6 d para os seguintes tipo árvore/páginas. Código confirma o acoplamento fora do registry (§2.4). |
| C6 | **O Protocol é o contrato?** h-8u/h-8v: "adicionar fonte = implementar o Protocol". h-8t: há divergência. | **h-8t está certo** (verificado): Google fora do registry (`tasks.py:241-260`), `known_documents` só para Notion (`tasks.py:299-304`), ramificações em `api/integrations.py`. Custo real inclui essas ramificações. |
| C7 | **Suíte de escritório:** 50/45 (h-8t) vs 73/16 e 7,75 mi×7,33 mi (h-8u). | Metodologias diferentes. Decisão inalterada: cobrir Google e Microsoft; nenhum número foi usado como base de priorização. |
| C8 | **Throttling Graph/SharePoint:** 3.500–8.000 RU/10 s (h-8t) vs 18.750–93.750 RU/5 min (h-8u). | Limites de escopos distintos (por app+tenant no Graph vs tenant SharePoint por licença); não são excludentes. Citados ambos, com as fontes. |
| C9 | **Impacto do WhatsApp:** 5 (h-8u) vs médio-baixo como fonte (h-8t) vs risco de política (h-8v). | O dado de 82% descreve MEI/MPE, e o ICP é 20–150 pessoas (Spec 001). Adotado: **impacto 3 como canal, 1–2 como fonte**, condicionado a demanda e à política Meta de 15/01/2026. |
| C10 | **Slack:** 10–15 d (h-8t, fonte) vs 3–6 d (h-8v, bot). | Não é contradição: fonte (ingestão, limite de 1 req/min, precisa ACL) ≠ canal (bot). Adotado: canal na onda 2, fonte só após ACL. |
| C11 | **WorkOS e MCP OAuth:** h-8v não verificou. | Busca confirma que **AuthKit oferece authorization server OAuth 2.0 para MCP** ([WorkOS](https://workos.com/docs/authkit/mcp)); a integração com o fluxo de sessão atual do app fica por validar. |
| C12 | **Escopos OneDrive:** h-8v citou `Files.Read offline_access`. | Código (`onedrive.py:37`): `openid profile offline_access User.Read Files.Read`. Sem impacto. |

### 9.2 Lacunas restantes

- **Market share** por ferramenta em PMEs brasileiras: sem fonte primária (Sebrae/IBGE); ranking BR de ERPs é inferência.
- **APIs não verificadas:** Astrea, Projuris, Domínio, Questor, Contmatic, Tiny (limites), RD Station (limites), Feegow, iClinic, Amplimed, Jetimob, Kenlo, Sienge (auth/limites), Box (webhooks), D4Sign (limites), DocuSign (go-live), Bling e Conta Azul (webhooks), WhatsApp (leitura de histórico).
- **Não pesquisados:** Zoho, Freshsales, Pipefy, Sankhya (API), preços dos planos que habilitam API em cada ERP.
- **Microsoft:** se `Sites.Read.All`/`Files.Read.All` delegados exigem consentimento de admin no tenant do cliente, e regras de publisher verification: validar em tenant de teste.
- **Não validado empiricamente:** desempenho da busca em Python com volume real; qualidade de OCR/transcrição em português; região BR de Azure/Google para OCR; `drive.file`+Picker vs UX de pasta.
- **MCP:** compatibilidade dos clientes com a spec 2026-07-28 (C2); confirmar na doc da OpenAI os requisitos de ChatGPT (fonte usada é de terceiros).
- **Preços de terceiros** (Merge, Paragon, Composio, Unstructured, Deepgram, AssemblyAI, SOC 2) vêm de agregadores/concorrentes; Unified.to sem preço. Confirmar nas páginas oficiais antes de decisão comercial.
- **Estimativas de esforço** são julgamento, não medição. O `graphify` CLI não estava disponível nos relatórios de origem; o código foi lido diretamente. Alterações não commitadas (`manual_sync.py`, migração `0018`) podem mudar.
- Escolhas de produto pendentes do dono: (1) aceitar ACL por arquivo/canal (S), (2) CASA vs `drive.file`, (3) ampliar o spec 001 para OCR/planilhas/Dropbox/e-mail.

---

## 10. Fontes (URLs)

**Google**
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- https://developers.google.com/workspace/drive/api/guides/limits
- https://developers.google.com/workspace/drive/api/guides/push
- https://developers.google.com/gmail/api/guides/push
- https://developers.google.com/workspace/gmail/api/reference/quota
- https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html
- https://cloud.google.com/document-ai/pricing
- https://www.gmass.co/blog/google-oauth-verification-security-assessment/
- https://nango.dev/docs/api-integrations/google-shared/google-security-review
- https://deepstrike.io/blog/google-casa-security-assessment-2025

**Microsoft**
- https://learn.microsoft.com/en-us/graph/api/site-delta
- https://learn.microsoft.com/en-gb/graph/throttling-limits
- https://learn.microsoft.com/it-it/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online
- https://learn.microsoft.com/graph/api/resources/webhooks
- https://learn.microsoft.com/da-dk/Graph/outlook-change-notifications-overview
- https://learn.microsoft.com/en-us/graph/permissions-overview
- https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/bf-migration-guidance
- https://azure.microsoft.com/en-in/pricing/details/form-recognizer

**Armazenamento e wikis**
- https://www.dropbox.com/developers/webhooks/tutorial
- https://www.dropboxforum.com/discussions/101000014/api-limits-on-rpc-endpoints/334768
- https://www.dropboxforum.com/discussions/101000014/does-a-dropbox-app-have-a-limit-on-development-users/846671
- https://docs.dropboxapi.com/dropbox-api/docs/performance
- https://developer.box.com/guides/api-calls/permissions-and-errors/rate-limits/
- https://developers.notion.com/reference/request-limits
- https://truto.one/blog/how-to-integrate-with-the-notion-api-architecture-guide-for-b2b-saas.md
- https://developer.atlassian.com/cloud/confluence/rate-limiting
- https://community.developer.atlassian.com/t/2026-point-based-rate-limits/97828
- https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga

**Comunicação**
- https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps
- https://docs.slack.dev/ai/slack-mcp-server/
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- https://respond.io/blog/whatsapp-general-purpose-chatbots-ban
- https://www.messagecentral.com/blog/whatsapp-business-api-pricing-brazil

**ERP, CRM, jurídico, assinatura, suporte (Brasil e global)**
- https://developer.bling.com.br/limites
- https://developers.koncili.com/en/docs/direct-erp-integration/bling/technical-information/
- https://contaazul.com/blog/api-conta-azul-integracoes-para-o-seu-negocio/
- https://nango.dev/docs/api-integrations/conta-azul/how-to-register-your-own-conta-azul-api-oauth-app
- https://ajuda.omie.com.br/pt-BR/articles/8112984-limites-de-consumo-da-api-do-omie
- https://ajuda.omie.com.br/pt-BR/articles/5412721-caracteristicas-e-recomendacoes-das-apis-do-omie
- https://advbox.com.br/api
- https://developers.clicksign.com
- https://docapi.d4sign.com.br/v2.0
- https://zapsign.co/pricing
- https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines
- https://pipedrive.readme.io/docs/core-api-concepts-rate-limiting
- https://atendimento.movidesk.com/kb/en/article/130599/api-do-movidesk
- https://developer.zendesk.com/api-reference/introduction/rate-limits/
- https://www.apideck.com/integrations/country/brazil/lang/pt

**Mercado**
- https://datasebrae.com.br/wp-content/uploads/2026/01/13012026_resumo_executivo_aberturas_pn_anual.pdf
- https://agenciasebrae.com.br/cultura-empreendedora/whatsapp-e-o-principal-meio-de-comunicacao-para-80-dos-negocios-de-servico/
- https://interdatalink.com/microsoft-365-vs-google-workspace-smb-2026/
- https://fitsmallbusiness.com/g-suite-vs-office-365/
- https://channelfutures.com/cloud/dropbox-microsoft-office-365-gain-smb-cloud-momentum
- https://acontecendoaqui.com.br/inovacao/rd-station-lidera-uso-de-plataformas-de-crm/
- https://www.b2bstack.com.br/categoria/crm-para-pequenas-empresas
- https://mundodomarketing.com.br/a-estrategia-da-omie-para-crescer-em-um-mercado-limitado-pelas-planilhas-de-excel
- https://jornalcontabil.com.br/noticia/thomson-reuters-anuncia-solucao-para-microempresas-que-faz-integracao-com-o-sistema-do-contador/
- https://sienge.com.br/blog/apis-do-sienge/
- https://braziljournal.com/por-que-o-softbank-esta-investindo-na-iclinic
- https://startups.com.br/negocios/doctoralia-compra-brasileira-feegow-e-mira-gestao-para-clinicas/
- https://www.aurum.com.br/astrea/
- https://www.wmtips.com/technologies/e-commerce/country/br/
- https://www.wmtips.com/technologies/customer-support/country/br/
- https://idatalabs.com/tech/products/movidesk

**MCP e segurança**
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- https://modelcontextprotocol.io/specification/2025-11-25/changelog
- https://modelcontextprotocol.io/specification/2026-07-28/changelog
- https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices
- https://claude.com/docs/connectors/building.md
- https://gofastmcp.com/v2/integrations/chatgpt
- https://workos.com/docs/authkit/mcp
- https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server
- https://mcpservers.org/pt-BR/servers/douglac/contaazul-mcp
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- https://devclass.com/2025/05/27/researchers-warn-of-prompt-injection-vulnerability-in-github-mcp-with-no-obvious-fix/

**OCR, transcrição, conectores unificados, automação, conformidade**
- https://research.ibm.com/blog/docling-generative-AI
- https://aws.amazon.com/fr/textract/pricing/
- https://mistral.ai/news/mistral-ocr-3
- https://developers.llamaindex.ai/llamaparse/general/pricing/
- https://convertaudiototext.com/blog/deepgram-nova-3-explained
- https://gladia.io/blog/assemblyai-pricing
- https://developers.openai.com/api/docs/models/gpt-4o-transcribe
- https://www.nango.dev/pricing
- https://unified.to/blog/unified_file_storage_api_integrations_guide
- https://getknit.dev/blog/understanding-merge-dev-pricing-finding-the-right-unified-api-for-your-integration-needs
- https://useparagon.com/pricing
- https://www.trustradius.com/products/composio/pricing
- https://pipedream.com/docs/pricing.md
- https://ragie.ai/pricing
- https://the-decoder.com/perplexity-acquires-carbon-to-expand-external-data-connections/
- https://automationatlas.io/guides/zapier-vs-make-vs-n8n-comparison/
- https://www.mattosfilho.com.br/unico/regulamentacao-transferencia-internacional-dados/
- https://beancount.io/ja/blog/2026/07/14/soc-2-type-ii-small-saas-audit-cost-guide
