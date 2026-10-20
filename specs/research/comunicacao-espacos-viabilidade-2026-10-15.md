# ArquivIO — Fontes de comunicação e Espaços com acesso por pessoas: viabilidade e plano por fases

Data: 2026-10-15 · Base: `main` @ `b51fa01` (working tree com alterações alheias em `frontend/tests/` e `graphify-out/`) · Escopo: **somente leitura e pesquisa, nenhum código alterado** · Origem: pedido do usuário (missão 51) + handoff `h-sb` do pane-702, cujas lacunas este documento fecha.

Convenções: **[FATO]** = verificado em código (`path:line`) ou fonte oficial citada `[Título](URL)`; **[INFERÊNCIA]** = dedução minha a partir de fatos; **[ESTIMATIVA]** = julgamento, faixa preliminar; **[NÃO VERIFICADO]** = não confirmei em fonte primária — tratar como hipótese a testar num spike. Contagens de linha refletem a working tree de hoje.

---

## 1. Veredito em dez linhas

1. **Espaços com acesso por pessoas são viáveis e são o pré-requisito de tudo.** Hoje o conteúdo é plano por organização: quem é membro ativo vê tudo. O ponto de estrangulamento existe e é pequeno (`LibraryService.question_contexts`, `require_member`, `WorkspaceService.require_member_access`), mas a **superfície que o consome é grande**: 62 ocorrências em 24 arquivos [FATO, grep].
2. **O maior risco não é o filtro de consulta, é o conteúdo derivado que já foi gravado**: histórico de conversa devolvido tal qual (`api/ingestion.py:410-434`), `saved_queries.last_answer`, notificações, resultados de automação, e-mails e webhooks. Sem tratar isso, "remover pessoa do Espaço" só vale para perguntas novas.
3. **A análise anterior ("Slack primeiro") não se sustenta.** Os termos de API do Slack proíbem que um terceiro (SaaS multi-cliente como o ArquivIO) faça *bulk export* de mensagens e mantenha índices persistentes de dados de outras organizações obtidos pelo Real-time Search; as diretrizes do Marketplace dizem para IA: "Don't store any Slack data you obtain… zero-copy" ([Slack API ToS](https://slack.com/terms-of-service/api), [Marketplace guidelines](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements)). Indexar canais do Slack como o ArquivIO indexa Drive **não é um caminho que eu recomende sem acordo escrito com a Slack**.
4. **WhatsApp: 1:1 é possível, grupos existentes não (por via oficial).** A Coexistência (app Business + Cloud API) traz até 180 dias de histórico 1:1 e mensagens novas, mas exige que o ArquivIO seja Tech Provider; a sincronização de histórico **exclui grupos** e a Groups API só cria grupos novos (≤ 8 participantes) e não vale para número do app Business ([Groups API](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups), [onboarding Business app](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/)). A única via que cobre grupos existentes é a **exportação manual `.txt/.zip`**, e o repo não tem upload (§4.3).
5. **Teams é tecnicamente possível, com ressalvas reais**: permissões por *time* (não por canal), canais privados/compartilhados não verificados, consentimento e aprovação da Microsoft a confirmar num tenant real.
6. **Recomendação:** entregar **Fase 1 = Espaços sobre as fontes que já existem** (valor imediato, independe de chat), com a Fase 0 de spikes/decisões em paralelo, e só depois um **piloto de chat com um provedor, somente canais públicos explicitamente compartilhados**. Privados e DMs ficam adiados (ou, depois, "acesso preservado" por espelhamento de membros, nunca por confirmação do admin).
7. **"Níveis" = três coisas diferentes** que a conversa mistura: *permissão* (quem lê o quê), *limite de consumo* (quanto pode ser indexado/perguntado) e *hierarquia* (um espaço herda outro). O MVP resolve só a primeira; limites ficam no nível da organização; hierarquia vira "adicionar a pessoa aos dois espaços".
8. **Sem duplicação de conteúdo.** Um Espaço *referencia* pastas já sincronizadas (N:M). Duplica-se hoje só quando o admin cria dois escopos de sync que se sobrepõem (já é assim: `active_documents` conta linhas de `Document`, `audit_usage/service.py:90`).
9. **Estimativa preliminar do MVP (Fases 0–2): 38–69 dev-dias, confiança baixa-média**, com calendário que **não** cai pela metade com dois devs (§11). A faixa anterior (36–55 dev-dias incluindo Slack) subestima revogação e ignora o risco contratual do Slack.
10. **Nenhuma dúvida bloqueia a Fase 0/1.** Duas bloqueiam a Fase 2: *qual ferramenta de chat os clientes-piloto usam* e *qual postura adotar frente aos termos do Slack* (§13).

---

## 2. Conceitos que precisam ser separados antes de qualquer tela

| Conceito | Pergunta que responde | Hoje | Proposta |
|---|---|---|---|
| **Acesso ao conteúdo** | Esta pessoa pode ler *este* documento/mensagem (e ele pode aparecer numa resposta dela)? | Todo membro ativo lê tudo da organização (`library/service.py:162-171`) | Pertencer ao Espaço que recebeu a fonte, **e** a fonte estar saudável |
| **Administração da empresa** | Quem conecta fontes, convida pessoas, vê uso, gera chaves? | Papéis `owner/admin/member` (`organizations/models.py:11-14`); fontes só por Owner/Admin (`workspaces/service.py:113-118`) | Mantém. **Papel de admin não concede leitura de conteúdo de Espaço** |
| **Permissão** | Quem vê o quê | Binária por organização | Matriz pessoa × Espaço × fonte |
| **Limite de consumo** | Quanto pode ser sincronizado/perguntado | `ACTIVE_DOCUMENT_LIMIT = 500` e `MONTHLY_LIMITS` são **constantes globais** aplicadas por organização (`audit_usage/service.py:15-16`), não por plano nem por pessoa | Continua por organização no MVP; contadores por Espaço só informativos |
| **Hierarquia** | Diretoria "inclui" RH? | Não existe | Fora do MVP (§5.5) |

**Por que "administrar ≠ ler" importa agora:** a chave de API exige que o criador seja Owner/Admin ativo (`access/principal.py:78-85`) e, sem `node_ids`, alcança a organização inteira (`access/models.py:27`). Se o papel de admin concedesse leitura de todos os Espaços, **criar uma chave de API viraria um atalho para ler o Espaço da Diretoria**. Com a regra proposta, o alcance de qualquer credencial é a **interseção** com os Espaços do usuário a que ela está vinculada (esse vínculo já é a decisão D1 do plano 03: `specs/plans/integracoes/03-api-mcp-e-canais.md:51`).

---

## 3. Estado atual ancorado no código (fechando lacunas do handoff anterior)

### 3.1 Backend — o que o handoff anterior já tinha, confirmado

| Fato | Evidência |
|---|---|
| Acesso a conteúdo = membro ativo da organização | `library/service.py:162-171` (`require_member`); `workspaces/service.py:34-39` (`require_member_access`, só `Membership.is_active`) |
| `WorkspaceFolder` é o escopo de sincronização e a unidade em que chunks e consultas filtram | `workspaces/models.py:10-27`; `knowledge/retrieval.py:52-64` filtra por `workspace_folder_id.in_(selection.folder_ids)` |
| O admin atesta acesso uniforme, não existe ACL | `workspaces/service.py:80-81` (`uniform access confirmation is required`) |
| Limite de 500 documentos ativos conta linhas de `Document` | `audit_usage/service.py:15`, contagem em `:88-92` |
| `SourceProvider` é reaproveitável | `integrations/base.py:20-35` (`discover`, `folders`, `ProviderCapabilities`) |
| Árvore da biblioteca é por *fonte*, não por escopo de sync | `library/service.py:318-324` ("The tree itself is provider-centric…"); `LibraryNode` só tem `source_id` (`library/models.py:12-33`) |

### 3.2 Lacunas fechadas nesta sessão (não lidas antes)

**Credenciais programáticas já existem e confinam por nó, mas como *estreitamento*, não como ACL de pessoas.**
`ApiKey.node_ids` e `McpConnection.node_ids` (`access/models.py:27`, `:92`) são convertidos em *mentions* e resolvidos por `authorize_mentions` (`library/service.py:1158-1183`) → `resolve_question_selection` (`:1124-1156`). `ScopedAccess.selection` (`access/scope.py`) reaplica tudo. O MCP usa qualquer membro ativo (`mcp_server/auth.py:84-93`); a chave exige Owner/Admin. **Consequência:** o padrão "credencial ⊆ usuário" já existe; falta o usuário deixar de ser "tudo".

**Há marcadores de Slack/Teams no código, mas nenhuma implementação.** `OrganizationAccessSettings.slack_replies_in_channel` e `ApiAuditEvent.channel` aceitando `slack | teams` (`access/models.py:49`, `:60`); busca por `slack|teams` em `backend/app` só acha esses dois arquivos de acesso e o ClickUp. O dono decidiu em 29/09 que Slack e Teams estão **fora de escopo** como bot de perguntas (`specs/plans/integracoes/00-indice.md:5`). O pedido atual é diferente (ingerir conteúdo) e **reabre** a decisão: registrar isso como decisão explícita (§13, D-0).

**Automações já fazem a coisa certa na execução, mas persistem o resultado.** `automations/executor.py:73-195`: reavalia o acesso do criador a cada execução (`creator_access_lost`, `:100,104,124`) e de **cada destinatário** (`node_access`, `automations/scope.py`; destinatário sem acesso é pulado, `skipped_recipients`). Porém grava `AutomationRun.result` com resposta e citações (`:194`), cria `Notification` com os primeiros 600 caracteres da resposta (`:190`, `notifications/followed.py:26`) e dispara webhook com até 4.000 caracteres (`automations/webhooks.py:27,107-120`), além de e-mail/PDF opcionais.

**Perguntas "seguidas" reexecutam como o usuário, mas guardam a última resposta.** `notifications/followed.py:63-90` chama `QuestionService.ask(user_id=query.user_id…)`; `audit_usage/models.py:46` (`last_answer` JSON) e a notificação (`:84`) retêm texto derivado. Não há reconferência fora de `require_member_access` (só membership).

**Histórico de conversa devolve conteúdo gravado sem reavaliar fontes.** `GET /organizations/{id}/conversations/{id}` (`api/ingestion.py:410-434`) só exige membership e devolve `content`, `context` e `response` (citações com trecho). Exportação de resposta idem (`api/answer_export.py`, lê `message.content`). **[FATO] Vazamento latente após revogação.** A boa notícia: cada citação grava `document_id` (`knowledge/agent.py:1455-1475`, `_answer_provenance`), o que permite **reconferir na leitura** sem migração de dados.

**A evidência e o visualizador herdam o ponto de estrangulamento.** `api/evidence.py:21-37` (`scoped_document`) só entrega o documento se a pasta estiver em `question_contexts` e já esconde pastas `access_lost` do robô do Drive — **precedente de revogação fail-closed por estado de fonte** a reaproveitar (`library/service.py:194-213`, `DriveFolderLink` com `suspect/access_lost/purge_scheduled`).

**Caches/derivados de conteúdo:** `ExtractionCache` é por organização e chave de conteúdo, "client text, same retention class as chunks" (`ingestion/models.py:59-73`); só é lido na ingestão, não numa consulta de usuário → risco de leitura baixo, mas **precisa entrar na política de purga** quando uma fonte é revogada.

**`notifications`, `saved_queries`, `executor`** foram inspecionados (arquivos e linhas acima). **Não inspecionados em profundidade:** `automations/triggers.py`, `report_pdf.py`, `notifications/digest.py`, `api/answer_feedback.py`, `api/clickup_tasks.py` (apenas confirmei que chamam o ponto de estrangulamento) — entram no inventário de testes da Fase 1 (§10).

### 3.3 Frontend — lido pela primeira vez

- **Colisão de vocabulário [FATO]:** a UI já chama de **"Espaço"** o escopo de sincronização (`WorkspaceFolder`): `integrations-screen.tsx` ("Espaço: “${folder.name}”", "os espaços já indexados"), `new-space-options.ts` (`newSpaceOptions`, `ExistingSpace`). ≈42 ocorrências de "espaço" em 9 arquivos de `frontend/app` (grep, inclui cópias `* 2.tsx`). Criar "Espaços" com outro significado sem renomear gera confusão em tela e suporte (§13, D-3).
- **Escopo de pergunta hoje é por *ferramenta*, não por pasta nem espaço:** `question-scope.tsx` (`QuestionScopePicker`, `providerKey/toolLabel`); menções de pasta/arquivo em `mention-composer.tsx`/`chat-workspace.tsx`.
- **Papéis na UI:** `types-and-api.tsx:60` (`roleLabel`); `integrations-screen.tsx` restringe a Owner/Admin (`canManage = company.role !== "member"`); equipe só para Owner (`team-staff.tsx`).
- **Destinatários de automação já exibem `has_access`** (`automation-recipients.tsx`): bom precedente de UX "esta pessoa não verá o resultado".
- **Seletor de organização** (`org-picker.tsx`) — alternativa barata de "níveis": uma organização por nível (§5.6).

`graphify` (AGENTS.md): `graphify query` localizou as comunidades `Membership/LibraryService/automations` e os testes de acesso (`tests/access_helpers.py`, `test_principal.py`, `test_scope_invariant.py`, `test_agent_revocation_*`); `path`/`explain` retornaram "ambíguo/não encontrado" para símbolos qualificados. O grafo orientou a busca; as afirmações acima vêm de leitura direta do código.

---

## 4. O que as plataformas de chat realmente permitem (documentação oficial)

### 4.1 Slack — tecnicamente fácil, contratualmente o gargalo

| Ponto | O que a fonte oficial diz | Implicação |
|---|---|---|
| Uso de dados por terceiros | Apps oferecidos fora da organização instaladora não podem usar API Data para treinar LLM nem "bulk export Slack message and file data except where expressly allowed by an additional agreement" ([Slack API ToS](https://slack.com/terms-of-service/api), vigência 10/10/2025) | **Indexar canais de clientes num SaaS multi-cliente é a hipótese exata que esses termos restringem** [INFERÊNCIA — a leitura jurídica final é da Slack/jurídico] |
| Real-time Search API | "you may not create persistent copies, archives, indexes, or long-term data stores of other organizations' API Data" ([Slack API ToS](https://slack.com/terms-of-service/api)); a doc técnica é mais dura: "You must not store or copy any of the data retrieved from this API" ([RTS](https://docs.slack.dev/apis/web-api/real-time-search-api/)) | Caminho "zero-copy": só consulta em tempo real |
| Marketplace/IA | "Don't store any Slack data you obtain. Store metadata instead and pull in data in real time if needed, i.e. zero-copy" ([guidelines](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements)) | Mesma direção |
| Distribuição comercial | Marketplace é "the only appropriate channel for commercially distributing apps", inclusive não listados e "custom" templatizados ([changelog 29/05/2025](https://docs.slack.dev/changelog/2025/05/29/tos-updates/)) | App interno por cliente (BYO app) **não** é atalho seguro |
| Limites de `conversations.history/replies` | Apps comerciais fora do Marketplace: 1 req/min e `limit` 15; Marketplace e internos mantêm Tier 3 ([changelog](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/), [método](https://docs.slack.dev/reference/methods/conversations.history/)). **Divergência não resolvida:** a página do `api.slack.com` (via busca) fala em instalações existentes migradas em 03/03/2026, enquanto `docs.slack.dev` diz que instalações existentes não são afetadas | Irrelevante se não usarmos `history`; relevante se usarmos. Tratar como 1 req/min até confirmar |
| RTS: permissão por pessoa | Resultados "limited to content the searching user can access"; escopos de canais privados/DM exigem **token de usuário** e consentimento; só apps listados no diretório ou internos; "Workspace guests can't use apps with platform AI features" ([RTS](https://docs.slack.dev/apis/web-api/real-time-search-api/)); a página da doc não declara GA ([changelog 13/10/2025](https://docs.slack.dev/changelog/2025/10/13/api-terms-update/) chama de "limited release") | **Resolve o ACL por construção** (a Slack decide por pessoa, em tempo real), mas troca "índice próprio" por "busca ao vivo" e exige listagem no diretório |
| Bot lê só onde está | `conversations.history` exige estar no canal; escopos `channels:history/groups:history/im:history/mpim:history` ([método](https://docs.slack.dev/reference/methods/conversations.history/)) | Seleção de canal = convidar o bot |
| Eventos de ciclo de vida | `member_left_channel`, `channel_convert_to_private/public`, `channel_deleted`, `channel_archive`, `channel_id_changed`, `message_changed/deleted`, `app_uninstalled`, `tokens_revoked` ([eventos](https://docs.slack.dev/reference/events/)) | Base técnica para revogação reativa |
| Slack Connect | Apps recebem eventos de usuários externos; retenção pode diferir entre workspaces; canal compartilhado "doesn't belong to a single workspace"; sem regra explícita sobre armazenar mensagens de membros externos ([Slack Connect](https://docs.slack.dev/apis/slack-connect/)) | **Excluir canais Slack Connect do MVP** |
| Prazo de revisão do Marketplace | Não publicado; só SLA de suporte de 2 dias úteis ([guidelines](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements)) | Caminho crítico externo, sem estimativa honesta |

**Duas rotas Slack legítimas, nenhuma é "igual ao Drive":**
- **S-A: RTS zero-copy** (consulta em tempo real com token do usuário; sem índice; resposta cita permalink). Preserva o ACL da própria Slack. Perde recuperação semântica unificada com documentos e depende de listagem no diretório + disponibilidade GA [NÃO VERIFICADO].
- **S-B: acordo adicional com a Slack** autorizando indexação. Não é decisão de engenharia.

### 4.2 Teams / Microsoft Graph — permitido, mas o menor recorte é o *time*

| Ponto | Fonte | Implicação |
|---|---|---|
| Ler mensagens de um canal | `GET /teams/{id}/channels/{id}/messages`: delegada `ChannelMessage.Read.All`; **aplicação `ChannelMessage.Read.Group` (RSC)**, ou `.Read.All` ([API](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0)) | Há caminho com consentimento por time |
| Tenant inteiro | `getAllMessages` é só aplicação (`ChannelMessage.Read.All`) e devolve "all the messages in all the public and private channels" ([API](https://learn.microsoft.com/en-us/graph/api/channel-getallmessages?view=graph-rest-1.0)) | **Largo demais** para "o usuário escolhe canais": a permissão não limita ao escolhido |
| RSC | Consentimento concedido a *um time* e "the channels within those teams"; `ChannelMessage.Read.Group` = "Read this team's channel messages" ([RSC](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/rsc/resource-specific-consent)). A mesma página lista quem consente de formas que parecem divergir ("team owner or member" vs "Only resource owners can grant application RSC") | **Não existe permissão por canal**: a seleção de canais é **apenas nossa**. Comportamento em canais privados/compartilhados: **[NÃO VERIFICADO]** |
| Mudanças em tempo quase real | Assinatura em `/teams/{id}/channels/{id}/messages` com dados no payload exige certificado de criptografia; renovação >1 h exige `lifecycleNotificationUrl` ([change notifications](https://learn.microsoft.com/en-us/graph/teams-changenotifications-chatmessage)) | Webhook público assinado + renovação periódica |
| "Protected API" | A doc de export diz "Microsoft Teams APIs in Microsoft Graph that access sensitive data are considered protected APIs. You can call these APIs as long as the requirements for accessing without a user are met" e que "Evaluation Mode (default)… limited usage per each requesting application" ([Export APIs](https://learn.microsoft.com/en-us/microsoftteams/export-teams-content)). Threads do Q&A relatam 403 "Invoked API requires Protected API access in application-only context" e aprovação manual ([Q&A](https://learn.microsoft.com/en-us/answers/questions/254210/why-is-the-access-request-required-for-protected-a)); a cobrança medida foi encerrada em 25/08/2025 segundo o Q&A ([Q&A](https://learn.microsoft.com/en-nz/answers/questions/5828700/payment-for-teams-export-apis-getallmessages-and-g)) | **Fontes oficiais e fóruns divergem** sobre o formulário de aprovação e limites de uso. Tratar como risco de cronograma até testar num tenant real |
| Mensagens apagadas | Export API acessa mensagens apagadas até 21 dias; canais/times apagados até 30 dias ([Export APIs](https://learn.microsoft.com/en-us/microsoftteams/export-teams-content)) | Propagação de exclusão precisa de `deleted` + varredura periódica |
| Termos de uso do Graph para IA/indexação por terceiros | **Não verifiquei** | Item de parecer jurídico (§13) |

### 4.3 WhatsApp — viável em recortes; não para "integrar grupos existentes"

Detalhamento próprio e mais profundo (pane-706, lido em fonte da Meta): `specs/research/whatsapp-fonte-conhecimento-2026-10-15.md`. Abaixo, o que **eu mesmo verifiquei** nas páginas da Meta e o que adoto da nota do pane-706 (marcado como tal).

| Quer integrar… | Via oficial | Verificado por mim |
|---|---|---|
| Conversas **1:1** de número do app WhatsApp Business | **Coexistência** (Embedded Signup): histórico de até 180 dias + mensagens novas por webhook; exige ser Solution Partner/Tech Provider, assinar `history`, `smb_app_state_sync`, `smb_message_echoes`; sync de histórico **uma única vez**, dentro de 24 h do onboarding ([onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/)) | Sim (página lida) |
| Conversas 1:1 futuras de número na Cloud API | Webhook `messages` | Parcial (via nota do pane-706) |
| **Grupos existentes** | **Não**: grupos "will not be synchronized" e ficam fora do histórico (mesma página); Groups API "not available for WhatsApp Business app phone numbers" ([Groups API](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups)) | Sim |
| Grupos **novos** criados via API | Só por convite, ≤ 8 participantes, 10.000 por número, exige Official Business Account; mensagens chegam por webhook `messages` com `group_id` ([mensageria de grupos](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/)); não achei endpoint de histórico | Sim |
| Conta pessoal | Nenhuma API oficial nas páginas lidas | Pela nota do pane-706 |
| Exportação manual `.txt/.zip` por chat | Funcionalidade do app, sem API; cobre grupos e conta pessoal | Pela nota do pane-706 (Help Center não renderiza sem JS) |
| Conectores por QR não oficiais | Não recomendado em produto B2B | Pela nota do pane-706 |

**Termos da plataforma (seção 4.7, "AI Providers")**, versão em português com "Última atualização: 23 de setembro de 2026" ([Termos Meta](https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform)): barra provedores de IA de usar a plataforma, permite mantê-los como provedor de soluções e restringe usar dados da plataforma para treinar modelos. Reportagens falam em proibição de assistentes de IA de propósito geral desde 15/01/2026; o texto em inglês e o enquadramento do ArquivIO (RAG sobre dados do cliente, não assistente geral) **não foram confirmados** — risco aberto que precisa de parecer.

**Implicações para este plano:**
- Em ordem de aderência ao pedido ("escolher chats, grupos e conversas"), o WhatsApp só cobre *grupos* via **upload manual**. **[FATO]** O repositório não tem nenhum caminho de upload (grep por `UploadFile|multipart|File(...)` em `backend/app/**/*.py` = 0 ocorrências; confirma a nota do pane-706). Upload de conversa exportada é **recurso novo**: sem autor/hora por bloco do texto, sem ACL por Espaço (`uniform_access_confirmed`, `workspaces/service.py:80-81`) e com o teto de 500 documentos por organização (`audit_usage/service.py:15`).
- **Chat de WhatsApp exige Espaços antes.** Grupo de WhatsApp é, por natureza, privado (convite). Nem a Coexistência nem o upload têm ACL na origem: entrar só por Espaço restrito e **concessão explícita** (§7), tratando o upload como `private_in_source` que o *usuário que enviou* declara poder compartilhar — admin não substitui os participantes do grupo (LGPD, parecer necessário).
- Estimativas preliminares do pane-706 (não revalidadas por mim; sem prazo externo): upload manual 8–14 dev-dias; Coexistência 20–35 + prazo da Meta (Tech Provider, verificação de negócio, App Review); Groups API 10–18. Lacunas declaradas por ele: Coexistência no Brasil não confirmada, preço de grupos, LGPD.

### 4.4 Síntese comparativa

| | Indexar conteúdo (estilo Drive) | Acesso por pessoa disponível na origem | Principal bloqueio |
|---|---|---|---|
| Slack | Restringido pelos termos para SaaS de terceiros | Sim (RTS, token do usuário) | **Contratual** |
| Teams | Possível | Parcial (permissão por time; canais privados a verificar) | Aprovação/protected API + modelo de consentimento |
| WhatsApp | 1:1 sim via Coexistência (Tech Provider); grupos existentes só por upload manual | Nenhum na origem (grupo = convite) | **Plataforma + exigência de Tech Provider + termos de IA (§4.7)** |

---

## 5. Modelo de Espaços proposto

### 5.1 Princípios (invariantes testáveis)

- **I1 Fail-closed.** Sem resolução de Espaço, zero conteúdo. Erros de resolução nunca "abrem".
- **I2 Conteúdo = membership ativa na organização ∧ membership ativa no Espaço ∧ concessão (grant) não revogada da fonte ao Espaço ∧ fonte saudável.** Papel de admin não entra na fórmula.
- **I3 Uma função, todos os canais.** UI, chave de API, MCP, automação, perguntas seguidas, exportação, evidência, visualizador e árvore usam o mesmo resolvedor. Divergência entre caminhos é o bug a prevenir.
- **I4 Revogação em duas velocidades.** Leitura viva: efeito no **próximo request**. Derivados persistidos: **ocultos na leitura imediatamente** (pela proveniência já gravada) e **purgados por job** em prazo definido (§6).
- **I5 Selecionar ≠ autorizar divulgação** (§7). Todo compartilhamento de fonte com um Espaço é um ato registrado, com texto de divulgação versionado.
- **I6 Privado/DM nunca entram por confirmação do admin** (§7.3).
- **I7 Sem vazamento de existência.** Fora do alcance responde como "não encontrado" (padrão já usado: `api/evidence.py:21-37`, `access/principal.py:24-26`).
- **I8 Auditoria.** Eventos de criar espaço, adicionar/remover membro, conceder/revogar fonte, "admin entrou no espaço" (`AuditLog` existe: `audit_usage/models.py:21-33`).

### 5.2 Dados (migração aditiva, próxima revisão após `20261014_0034`)

| Tabela | Campos essenciais | Observação |
|---|---|---|
| `spaces` | `id`, `organization_id`, `name`, `kind` (`general`/`custom`), `archived_at`, `created_by` | `general` ("Geral") criado por backfill |
| `space_members` | `space_id`, `user_id`, `role` (`member`/`manager`), `added_by`, `created_at`, `removed_at` | `manager` pode administrar membros do próprio Espaço (opcional na Fase 1) |
| `space_source_grants` | `space_id`, `workspace_folder_id`, `granted_by`, `disclosure` JSON (`text_version`, `member_count`, `acknowledged_at`), `revoked_at` | **N:M**: a mesma pasta sincronizada pode estar em vários Espaços sem copiar nada |
| `source_item_acl` (Fase 3) | `workspace_folder_id`, `principal_kind`, `principal_ref`, `synced_at`, `valid_until` | Só para privados com "acesso preservado" |

Backfill: criar "Geral" por organização, com **todos os membros ativos** e **todas as pastas existentes** — nenhuma mudança de comportamento no dia do deploy. Regra contínua: novo membro entra em "Geral"; nova pasta exige escolher Espaço (pré-seleção "Geral" para preservar o comportamento atual).

### 5.3 Resolvedor único

`accessible_folder_ids(scope, user_id) -> frozenset[UUID]` numa consulta (membership ativa ∧ `space_members` ativo ∧ `space_source_grants` não revogado ∧ pasta não `access_lost`), consumido por:
`LibraryService.question_contexts` (`library/service.py:911`) → alimenta `resolve_question_selection`, `authorized_catalog`, `mention_candidates`, `ScopedAccess`, `McpPrincipalResolver`, automações e `scoped_document`; e por `WorkspaceService.require_member_access/folders` (`workspaces/service.py:30-47`) → alimenta `QuestionService.ask` (`knowledge/questions.py:1138`) e `SavedQueryService`.
**O trabalho difícil é a árvore da biblioteca (`roots/children/catalog_*/search_*`):** `LibraryNode` é por fonte, e um arquivo pode estar indexado em mais de um escopo (`workspace_provenance`, `library/service.py:318`). Regra proposta: **nó de arquivo visível ⇔ existe `Document` indexado dele em pasta acessível; pasta visível ⇔ tem descendente visível; raiz de fonte visível ⇔ tem pasta visível** [INFERÊNCIA — custo e paginação a validar na Fase 0].

### 5.4 Credenciais e automação

- `ApiKey`/`McpConnection`: alcance efetivo = (`node_ids` da credencial, se houver) ∩ (Espaços do usuário vinculado). Tela de criação mostra "esta chave alcançará N documentos em Espaços X, Y".
- Automação: o executor já reavalia criador e destinatários; passa a usar o resolvedor. Escopos cruzando Espaços só rodam se o **criador** tiver todos; destinatário sem acesso a algum é pulado (comportamento atual preservado, `executor.py:164-185`).
- Webhook de saída e e-mail: conteúdo que sai da plataforma é **irrevogável**; mitigação em §6.

### 5.5 Hierarquia e limites (por que o MVP é plano)

- **Hierarquia ("Diretoria inclui RH")**: é açúcar sobre membership. MVP: adicionar a pessoa aos dois Espaços. Depois: `space_includes(parent, child)` resolvido por expansão em tempo de escrita, com bloqueio de ciclo. Herança dinâmica em tempo de leitura multiplica os casos de revogação.
- **Limites por Espaço**: o consumo é de documentos/tokens/perguntas da *organização*; um mesmo `WorkspaceFolder` pode pertencer a vários Espaços, então "de quem é o consumo" é ambíguo. MVP: limite continua por organização; painel mostra consumo *atribuído* por Espaço só como informação. Limite por Espaço entra quando houver pedido real e regra de atribuição definida.
- **Chat não cabe nos 500 documentos**: um canal movimentado gera um "documento" por dia/thread e consome o teto em semanas. Fase 2 precisa de **unidade e métrica próprias** (`chat_units`), com janela de retenção.

### 5.6 Alternativa barata para o piloto: uma organização por nível

O produto já isola organizações (`OrganizationScope`, seletor de organização). Para um cliente-piloto urgente, criar "Acme Geral", "Acme RH" e "Acme Diretoria" como organizações separadas entrega isolamento perfeito **sem código**. Custos: reconectar fontes por organização, conta/quota duplicadas (500 docs *cada*), sem resposta que combine níveis, usuário alterna manualmente. Útil como ponte; **não como solução**.

---

## 6. Revogação: matriz por superfície

Legenda — **Viva**: calculada a cada request; **Snapshot**: texto derivado já gravado; **Externa**: já saiu da plataforma.

| Superfície | Tipo | Hoje | Ação na revogação (pessoa removida do Espaço, ou fonte revogada/privatizada) |
|---|---|---|---|
| Pergunta no chat / agente | Viva | Filtra por `question_contexts` | Herda o resolvedor; teste de regressão no padrão `test_agent_revocation_*` |
| Evidência / visualizador de arquivo | Viva | `scoped_document` (`api/evidence.py:21`) | Herda; 404 uniforme |
| Árvore e busca da biblioteca | Viva | Sem filtro de pasta | Filtro por proveniência (§5.3) |
| Histórico de conversa | **Snapshot** | `api/ingestion.py:410-434` devolve `content/context/response` | **Ocultar na leitura** mensagens cujas citações (`document_id`, `agent.py:1455`) saiam do alcance: substituir por "conteúdo ocultado por mudança de acesso"; manter a pergunta do usuário. Purga opcional por job |
| Exportar resposta (md/docx/pdf) | Snapshot | `answer_export.py` lê `message.content` | Mesmo filtro de proveniência antes de exportar |
| Pergunta seguida (`last_answer`) | Snapshot | `audit_usage/models.py:46` | Limpar `last_answer`/`last_checked_at` e pausar o seguimento quando a pasta sair do alcance; checar acesso em `refresh_followed_queries` |
| Notificações (corpo 600 chars + trechos de 240) | Snapshot | `notifications/models.py`, `followed.py:26,84` | Gravar `provenance` (ids de documento/pasta) e ocultar na leitura do sino; purga por job |
| Resultado de automação / PDF | Snapshot | `executor.py:194`; rota de PDF | Mesma ocultação; execução futura já cai em `creator_access_lost` |
| Chave de API / MCP | Viva | `access/principal.py`, `mcp_server/auth.py` | Interseção com Espaços do usuário; revogação de membership mata o alcance no próximo request |
| Criar tarefa no ClickUp a partir da resposta | Externa | Ação humana aprovada (ADR-0020) | Na aprovação, reconferir proveniência; depois de criada, irrevogável |
| E-mail e webhook de automação | **Externa** | Corpo/PDF enviados; webhook até 4.000 chars | Irrevogável. Mitigar: ao remover membro, **desativar automações dele/endereçadas a ele** que tocam o Espaço; registrar `space_ids` na entrega; permitir "este Espaço não pode sair da plataforma" (bloqueia webhook/e-mail para automações que o toquem) |
| Embeddings e chunks | Viva (dependem da pasta) | Pasta removida ⇒ cascata | Fonte revogada/privatizada ⇒ estado `access_lost` (precedente do robô do Drive, `library/service.py:194`) + `purge_after` |
| `ExtractionCache` | Interno | Por organização/chave de conteúdo | Entra no job de purga da fonte; não é lido por usuário |
| Caches de navegador | Cliente | Só organização ativa em `localStorage` | Sem conteúdo; nada a fazer |

**Prazos propostos [PREMISSA a confirmar]:** leitura viva = próximo request; ocultação de derivados = imediata (na leitura); purga = ≤ 24 h; fonte de chat privatizada/removida = esconder de imediato, apagar em ≤ 24 h.

---

## 7. Seleção de canal não equivale a autorização de divulgação

**O erro a evitar.** Hoje o admin marca "todos os membros podem ver isto" (`uniform_access_confirmed`, `workspaces/service.py:80-81`) e isso é aceitável porque o **modelo do produto** diz que a pasta é da empresa toda. Reaproveitar esse booleano para canais seria usar a confirmação do admin como substituto automático da ACL da origem.

### 7.1 Três perguntas diferentes

1. **A plataforma permite que o app leia?** (consentimento técnico, escopos, aprovação da Microsoft/Slack)
2. **Quem, na origem, já pode ler?** (membros do canal; público ≠ "todos os funcionários" em guest/Connect)
3. **Para quem o ArquivIO vai divulgar?** (membros do Espaço)

Selecionar o canal responde só à 1. O admin da empresa **não** é a pessoa que decide pela 2 em canal privado, nem para 3 em nome dos autores das mensagens (dados pessoais de funcionários — LGPD; avaliação jurídica fora deste documento).

### 7.2 Regra do MVP — classe de visibilidade da origem

| Classe | Exemplo | Elegível no MVP | Condição |
|---|---|---|---|
| `public_in_source` | Canal público do Slack; canal padrão do Teams (standard) | **Sim** | Concessão explícita a um Espaço, com ciência registrada |
| `private_in_source` | Canal privado/compartilhado | **Não** | Retorna `private_source_not_supported` |
| `dm` | DM, grupo, chat 1:1 | **Não** | idem |
| `external_mixed` | Slack Connect, Teams com convidados/federados | **Não** | idem (superfície extra de injeção de prompt e de LGPD) |

Se um canal público **vira privado** (`channel_convert_to_private`, [eventos](https://docs.slack.dev/reference/events/)) ou o app é removido, a fonte vai para `access_lost`, some das respostas na hora e entra em purga.

### 7.3 "Acesso preservado" (Fase 3, não MVP)

Privados só entram com **espelho de membros da origem**: conteúdo visível apenas a quem é membro na origem **e** membro do Espaço, com tabela de ACL sincronizada, `valid_until` curto e **fail-closed quando vencida**. Exige mapeamento identidade ArquivIO ↔ Slack/Entra (vínculo explícito pelo usuário logado, não por e-mail; decisão D8 do plano 03). A confirmação do admin **nunca** libera um item privado.

### 7.4 Texto de ciência (exemplo, mostrado antes da concessão)

> Você vai compartilhar **#rh-avisos** (canal público no Teams) com o Espaço **RH** (4 pessoas). Mensagens passadas e futuras ficarão pesquisáveis para essas pessoas e poderão aparecer em respostas e citações. Mensagens apagadas ou editadas no Teams serão atualizadas aqui. Isso **não** concede acesso a canais privados. [ ] Entendo e tenho autorização para compartilhar este conteúdo com RH.

Guardar `text_version`, `member_count`, usuário e horário em `space_source_grants.disclosure`.

---

## 8. UX com exemplo concreto: Geral / RH / Diretoria

**Empresa fictícia "Acme Serviços", 60 pessoas.** Eva (dona), Ana e Bruno (RH), Carla e Daniel (Diretoria), demais no operacional.

| Espaço | Membros | Fontes concedidas | Quem administra membros |
|---|---|---|---|
| **Geral** | todos (automático) | Drive `/Políticas`, Drive `/Manuais`, canal público **#avisos** | Eva |
| **RH** | Ana, Bruno | Drive `/RH-Contratos`, canal público **#rh-publico** | Eva (ou Ana como `manager`) |
| **Diretoria** | Carla, Daniel | Drive `/Diretoria` | Eva |

Cenas:

1. **Pergunta de operacional (só Geral):** "Qual o reajuste de 2027?" → o chat mostra a faixa *"Procurei em: Geral"* e responde só com políticas gerais. **Nunca** diz "há documentos que você não pode ver".
2. **Ana (Geral + RH):** mesma pergunta cita `/RH-Contratos` com selo **RH** na citação.
3. **Carla (Geral + RH + Diretoria):** como "níveis" no MVP = ser membro de vários Espaços; Carla foi adicionada a RH e a Diretoria. No futuro, "Diretoria inclui RH" evitaria a segunda inclusão.
4. **Eva (dona) sem estar em Diretoria:** configura tudo, mas não lê `/Diretoria`. Para ler: botão **"Entrar neste Espaço"**, que grava evento de auditoria visível aos membros do Espaço.
5. **Remover Bruno do RH:** diálogo de impacto — *"Bruno deixará de ver 214 documentos. 3 conversas dele citam conteúdo do RH; esses trechos serão ocultados. 1 automação endereçada a ele será pausada."* Confirmar.
6. **Adicionar o canal #rh-publico ao RH:** tela de fonte → escolher canal → texto de ciência (§7.4) → grant registrado. Canal privado aparece desabilitado com "Disponível numa fase futura: exige acesso preservado".
7. **Conversa antiga de Bruno:** ao abrir, as respostas do RH aparecem como "Conteúdo ocultado por mudança de acesso"; a pergunta dele continua visível.

Telas afetadas [FATO: arquivos lidos]: `integrations-screen.tsx` (escolher Espaço ao criar escopo; renomear "Espaço" atual), `team-staff.tsx` (membros e Espaços), `library-screen.tsx` (selos de Espaço), `question-scope.tsx`/`chat-workspace.tsx` (faixa "Procurei em"), `automation-folder-picker.tsx`/`automation-recipients.tsx` (alcance), `conversation-history.tsx` (placeholder de ocultação), `usage-panel.tsx` (consumo por Espaço, informativo), `organization-onboarding.tsx` (copy). Nova tela: **Espaços**.

---

## 9. MVP seguro recomendado

**MVP = Fase 1 + piloto da Fase 2 com um provedor, somente `public_in_source`, sem convidados.**

Entra:
- Espaços planos, membership explícita, "Geral" automático, concessão de **pastas já sincronizadas** a Espaços (por referência, sem cópia).
- Resolvedor único aplicado a todos os caminhos de leitura; ocultação de snapshots; auditoria.
- Piloto de chat: 1 provedor, canais públicos concedidos a 1+ Espaços, retenção por janela, propagação de edição/exclusão, desligar na privatização.

Fica de fora (e é dito na tela):
- Canais privados, DMs, Slack Connect, convidados/federados.
- Hierarquia entre Espaços, limites por Espaço, delegação ampla de gerente.
- WhatsApp (upload manual e Coexistência ficam na Fase 4; grupos existentes nunca ao vivo).
- Indexação de Slack (aguarda a decisão contratual D-1).

**Qual provedor no piloto de chat?** Depende de duas respostas do usuário (§13). Padrão da recomendação: **Teams, canais padrão, RSC por time**, se os clientes-piloto usam Microsoft 365; **Slack via RTS zero-copy** se usam Slack *e* o ArquivIO aceitar listagem no diretório. Não escolhi pelo usuário: as duas rotas têm riscos externos diferentes.

---

## 10. Plano por fases

### Fase 0 — Decisões e spikes (paralela; ~1–2 semanas de calendário)

| # | Tarefa | Saída |
|---|---|---|
| 0.1 | Confirmar com o usuário: ferramenta(s) de chat dos pilotos, postura Slack (D-1), nome do conceito (D-3), "admin não lê" (D-2) | Decisões registradas num ADR (próximo número livre: `ADR-0021`) |
| 0.2 | Spike da árvore: provar a regra de visibilidade por proveniência (§5.3) com 10k nós e paginação | Consulta + plano de índices; veredito de custo |
| 0.3 | Spike do provedor escolhido num **tenant/workspace real**: consentimento, escopos mínimos, comportamento em canal privado/compartilhado, limites, eventos de exclusão | Relatório com fatos que hoje estão `[NÃO VERIFICADO]` |
| 0.4 | Parecer jurídico: termos Slack (S-A × S-B), termos Graph/Teams para indexação por terceiros, LGPD de mensagens de funcionários | Documento do jurídico; sem ele a Fase 2 não inicia |
| 0.5 | Inventário final de call sites (62 ocorrências / 24 arquivos) em checklist com dono | Lista versionada |

Critério de saída: decisões D-0…D-3 aceitas; 0.2 com veredito; 0.3 e 0.4 com resposta escrita sobre o provedor escolhido.

### Fase 1 — Espaços sobre fontes existentes (sem chat)

| Pacote | Conteúdo | Arquivos principais |
|---|---|---|
| 1.1 Modelo | Migração aditiva + backfill "Geral" + modelos | `spaces`/`space_members`/`space_source_grants`; `alembic/versions/` |
| 1.2 Resolvedor | `accessible_folder_ids` + `accessible_document_ids`; integrar em `question_contexts`, `require_member_access`, `folders` | `library/service.py:911`, `workspaces/service.py:30-47`, novo módulo de acesso |
| 1.3 Árvore | Filtro por proveniência em `roots/children/catalog_*/search_*/mention_candidates` | `library/service.py` (arquivo de ~1.580 linhas: ponto de conflito) |
| 1.4 Derivados | Ocultação na leitura: conversa, exportação, seguidas, notificações, automações/PDF, ClickUp | `api/ingestion.py:410`, `api/answer_export.py`, `notifications/*`, `automations/executor.py`, `api/clickup_tasks.py` |
| 1.5 Credenciais | Interseção chave/MCP × Espaços; prévia de alcance | `access/principal.py`, `access/scope.py`, `mcp_server/auth.py`, `api/access_admin.py` |
| 1.6 Admin API/UI | CRUD de Espaços, membros, concessões; diálogo de impacto; renomear "espaço" legado | `api/` novo roteador + telas em §8 |
| 1.7 Testes | Matriz pessoa × Espaço × superfície; revogação por superfície; propriedade "nenhum caminho devolve documento fora do conjunto" | estende `test_scope_invariant.py`, `test_agent_revocation_*`, `test_principal.py`, `test_scoped_access.py` |
| 1.8 Docs | Atualizar threat model e ADR | `docs/seguranca/threat-model-api-mcp-canais.md`, `specs/adr/` |

**Critérios de aceite (todos automatizados, nenhum só manual):**
1. Em organização migrada, comportamento idêntico ao anterior (snapshot de respostas/árvore do "Geral" = antes).
2. Membro só de "Geral" não encontra documento de outro Espaço por chat, busca, menção, árvore, evidência, visualizador, exportação, API `/v1`, MCP — todos devolvem ausência/404 uniforme.
3. Remover Ana do RH: no **próximo request** todas as superfícies vivas deixam de devolver RH; conversas antigas passam a mostrar o placeholder; `last_answer` limpo; automação dela falha com `creator_access_lost`; chave/MCP perdem alcance.
4. Chave de API de um admin que **não** é membro de Diretoria não alcança Diretoria mesmo sem `node_ids`.
5. Usuário removido da *organização* continua sem acesso (comportamento atual preservado).
6. Falha do resolvedor (erro, tabela vazia) ⇒ zero conteúdo (fail-closed), com teste.
7. Evento de auditoria para criar/alterar Espaço, conceder/revogar fonte e "admin entrou no Espaço".
8. Consulta da árvore dentro do orçamento definido no spike 0.2 (p95 a fixar).
9. Nenhuma duplicação de `Document`/chunks ao conceder a mesma pasta a dois Espaços (teste de contagem).

### Fase 2 — Piloto de chat (1 provedor, só `public_in_source`)

| Pacote | Conteúdo |
|---|---|
| 2.1 Contrato | Extensão de `SourceProvider` para fontes de mensagens: unidade = *thread* ou janela diária; permalink para citação; tombstone de edição/exclusão |
| 2.2 Identidade e consentimento | Instalação (Teams: RSC por time; Slack-RTS: token de usuário) e vínculo usuário↔identidade quando necessário |
| 2.3 Ingestão em tempo quase real | Receptor de eventos (Graph notifications com renovação e `lifecycleNotificationUrl`; ou Slack Events) com validação de assinatura; varredura periódica de reconciliação |
| 2.4 Seleção e ciência | UX §7.4; rejeitar `private/dm/external_mixed`; grant registrado |
| 2.5 Limites | Métrica `chat_units` e retenção rolante (ex.: 90/180 dias, a decidir); não somar ao teto de 500 documentos |
| 2.6 Segurança | Cerca anti-injeção (ADR-0015, `knowledge/untrusted.py`) aplicada a mensagens; excluir remetentes externos; PII: aviso e opção de omitir autor |
| 2.7 Revogação | Privatização/remoção do app/exclusão de mensagem ⇒ esconder na hora e purgar ≤ 24 h |

**Critérios de aceite:** (a) selecionar canal público sem ciência é recusado; (b) canal privado ⇒ `private_source_not_supported`; (c) edição/exclusão aparecem nas respostas em ≤ N min (N definido no spike); (d) canal que vira privado deixa de ser citado imediatamente e é purgado ≤ 24 h; (e) mensagem de convidado/externo não é indexada; (f) texto de mensagem com instruções ("ignore as regras…") não altera o comportamento (suíte `test_prompt_injection_rag.py` estendida); (g) renovação de assinatura falha ⇒ alerta e estado degradado visível; (h) tudo da Fase 1 continua verde para fontes de chat.

### Fase 3 — Privados com acesso preservado (só depois do piloto)
ACL espelhada (`source_item_acl`), vínculo de identidade, `valid_until` e fail-closed. Critério central: membro removido do canal na origem perde a leitura em ≤ janela de sincronização, e o admin **não** consegue liberar manualmente.

### Fase 4 — Extras
Segundo provedor; hierarquia por inclusão; limites por Espaço; `manager` com delegação ampliada; **WhatsApp**: upload manual de conversa exportada (8–14 dev-dias, estimativa do pane-706) e, depois, Coexistência 1:1 (20–35 dev-dias + prazo da Meta) — ambos só sobre Espaços restritos.

---

## 11. Estimativas — faixas preliminares

Unidade: dev-dias de quem conhece a base. **[ESTIMATIVA]**, sem compromisso de prazo.

| Fase | Faixa | Confiança | Principais dependências / o que move a faixa |
|---|---|---|---|
| 0 | 5–9 | Média | Disponibilidade de um tenant/workspace real e do jurídico; parecer jurídico é lead time externo |
| 1 | 18–32 | **Baixa-média** | Resultado do spike da árvore (0.2); 62 pontos de chamada; 8+ telas; testes de matriz são a parte que mais cresce |
| 2 (Teams) | 15–28 | Baixa | Aprovação/protected API (lead time externo **não medido**), comportamento em canais privados, volume de mensagens |
| 2 (Slack-RTS) | 10–20 | Baixa | **Listagem no diretório da Slack (prazo não publicado)** e GA do RTS |
| 3 | 20–40 | Baixa | Qualquer provedor; identidade e sincronização de membros |
| 4 | 10–25 por item | Baixa | Pedido real de cliente |

**MVP (Fases 0–2): 38–69 dev-dias.** Diferença para a análise anterior (36–55 incluindo Slack): aqui entram revogação de derivados, spikes e o risco contratual.

**Por que dois devs não dividem o calendário por dois [INFERÊNCIA]:**
- A Fase 1 passa por poucos arquivos grandes e compartilhados (`library/service.py` ~1.580 linhas, `knowledge/questions.py` ~2.290 linhas): o núcleo (1.2–1.3) é **serial** e de mão única.
- A UI só avança depois do contrato da API (≈ semana 2).
- O conector da Fase 2 só começa de verdade com o resolvedor e o modelo de concessão prontos; o protótipo pode correr em paralelo se a interface `SourceItem` for congelada cedo.
- Lead times externos (Slack, Microsoft, jurídico) **não encolhem com mais gente**.

Faixa de calendário **ilustrativa**: Fase 1 em 4–9 semanas (1–2 devs); Fase 2 mais 3–7 semanas, mais prazo externo que pode dominá-las. Não usar como promessa.

---

## 12. Riscos principais

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Vazamento por snapshot persistido após revogação | Alta se não tratado | Alto | §6, critério 3 da Fase 1 |
| Divergência entre caminhos de leitura (um esquece o filtro) | Média | Alto | I3; teste de propriedade; lista dos 62 pontos |
| Termos do Slack bloqueiam indexação | Alta | Alto | Não construir antes de D-1/parecer; rota RTS zero-copy |
| Permissão do Teams ampla demais (por time) | Média | Alto | Seleção de canais é nossa; só públicos no MVP; verificar privados no spike |
| Aprovação/limites da Microsoft atrasam | Média | Médio | Spike 0.3 antes de comprometer prazo |
| Injeção de prompt via mensagens de chat | Média | Alto | Cerca ADR-0015, excluir externos, ação de escrita só com aprovação humana (ADR-0020) |
| Custo/escala da árvore filtrada | Média | Médio | Spike 0.2; índices; cache de conjunto acessível com invalidação por evento |
| Confusão de vocabulário ("Espaço") | Alta | Baixo-médio | D-3 antes de qualquer tela |
| LGPD de mensagens de funcionários | Média | Alto | Parecer jurídico, retenção, omitir autor, base legal registrada |
| Saída irrevogável (e-mail/webhook) | Certa | Médio | §6: desativar automações, `restricted` por Espaço, registro |

---

## 13. Decisões e dúvidas

### Decisões recomendadas (aceitar por padrão se o usuário não objetar)

| # | Decisão | Recomendação |
|---|---|---|
| D-0 | Reabrir a decisão de 29/09 ("Slack e Teams fora de escopo") | Sim, para **ingestão** de canais públicos, com Fase 0 antes de qualquer código |
| D-1 | Postura Slack | Não indexar; avaliar RTS zero-copy ou acordo adicional; **não** usar app interno por cliente como atalho |
| D-2 | Admin da empresa lê conteúdo de qualquer Espaço? | **Não.** Pode entrar no Espaço por ação auditada e visível |
| D-3 | Nome | Manter "Espaço" para o novo conceito (vocabulário do usuário) e renomear o legado para "Fonte sincronizada"/"Pasta conectada" |
| D-4 | Compartilhamento sem cópia | Espaço referencia pastas (N:M); nada é duplicado |
| D-5 | Privados/DMs | Fora do MVP; Fase 3 só com acesso preservado |
| D-6 | WhatsApp | Fora do MVP. Se houver demanda: **primeiro upload manual** (cobre grupos; exige Espaços restritos já prontos), **depois** Coexistência 1:1 (exige Tech Provider e parecer sobre §4.7); nunca prometer "integrar grupos existentes ao vivo" |
| D-7 | Limites | Por organização no MVP; por Espaço só com regra de atribuição |

### Dúvidas realmente bloqueantes

| # | Pergunta | Bloqueia | Por quê |
|---|---|---|---|
| Q-1 | **Quais ferramentas de chat os clientes-piloto usam e quais conteúdos querem consultar** (Slack, Teams, WhatsApp — e, no WhatsApp, *grupos* ou conversas 1:1)? | Fase 2 (escolha do provedor) | Define o spike 0.3 e se a barreira é contratual (Slack), de aprovação (Teams) ou de plataforma (WhatsApp: grupos só por upload manual) |
| Q-2 | **O ArquivIO aceita a rota zero-copy do Slack (listagem no diretório, sem índice) ou quer buscar acordo com a Slack?** | Fase 2 se for Slack | Muda a arquitetura (consulta ao vivo × índice) |

Não são bloqueantes (têm padrão recomendado): D-0…D-7 acima; retenção de chat; se `manager` de Espaço existe na Fase 1.

---

## 14. Premissas e o que não foi coberto

**Premissas:** (1) o modelo de produto continua "pasta/canal compartilhado = conhecimento da empresa", só que particionado por Espaços; (2) clientes-piloto aceitam que canais privados e DMs não entrem de início; (3) dev-dias medem uma pessoa que conhece a base; (4) prazos de purga em §6 são propostas.

**Não coberto / não verificado:** `automations/triggers.py`, `report_pdf.py`, `notifications/digest.py`, `api/answer_feedback.py`, `api/clickup_tasks.py` (apenas confirmado que chamam o ponto de estrangulamento); desempenho real da árvore filtrada; nenhum teste executado (somente leitura); termos de uso do Microsoft Graph para indexação por terceiros; comportamento do RSC em canais privados/compartilhados; formulário/limites atuais de "protected APIs" do Teams (fontes oficiais e fóruns divergem); GA do Real-time Search da Slack; texto em inglês dos termos de IA da Meta; a divergência sobre a aplicação dos novos limites de `conversations.history` a instalações existentes. Nenhum aconselhamento jurídico foi dado: as leituras de termos são técnicas e precisam de confirmação do jurídico.

---

## 15. Fontes (URLs consultadas)

Slack: [API Terms of Service](https://slack.com/terms-of-service/api) · [Atualização dos termos 13/10/2025](https://docs.slack.dev/changelog/2025/10/13/api-terms-update/) · [Atualização dos termos 29/05/2025](https://docs.slack.dev/changelog/2025/05/29/tos-updates/) · [Limites para apps fora do Marketplace](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/) · [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/) · [conversations.members](https://docs.slack.dev/reference/methods/conversations.members/) · [Real-time Search API](https://docs.slack.dev/apis/web-api/real-time-search-api/) · [Diretrizes do Marketplace](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements) · [Slack Connect](https://docs.slack.dev/apis/slack-connect/) · [Eventos](https://docs.slack.dev/reference/events/) · [message.channels](https://docs.slack.dev/reference/events/message.channels/) · [Changelog api.slack.com (via busca)](https://api.slack.com/changelog/2025-05-terms-rate-limit-update-and-faq)

Microsoft: [List channel messages](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0) · [channel getAllMessages](https://learn.microsoft.com/en-us/graph/api/channel-getallmessages?view=graph-rest-1.0) · [Change notifications de mensagens](https://learn.microsoft.com/en-us/graph/teams-changenotifications-chatmessage) · [Resource-specific consent](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/rsc/resource-specific-consent) · [Teams Export APIs](https://learn.microsoft.com/en-us/microsoftteams/export-teams-content) · [Q&A: protected APIs](https://learn.microsoft.com/en-us/answers/questions/254210/why-is-the-access-request-required-for-protected-a) · [Q&A: fim da cobrança medida](https://learn.microsoft.com/en-nz/answers/questions/5828700/payment-for-teams-export-apis-getallmessages-and-g)

WhatsApp/Meta: [Groups API](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups) · [Mensageria de grupos](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/) · [Onboarding de usuários do app Business](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/) · [Termos da plataforma (PT)](https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform)

Repositório: `specs/research/whatsapp-fonte-conhecimento-2026-10-15.md` (pane-706) · `specs/research/integracoes-analise-2026-09-29.md` · `specs/plans/integracoes/00-indice.md`, `03-api-mcp-e-canais.md` · `docs/seguranca/threat-model-api-mcp-canais.md`.
