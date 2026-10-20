# WhatsApp como FONTE de conhecimento do ArquivIO — viabilidade com fontes oficiais

Data da pesquisa: 2026-10-15 · Base de código: `main` @ `b51fa01` (working tree com alterações não commitadas alheias a esta nota) · Escopo: pesquisa somente leitura + inspeção do repositório; **nada foi implementado**.

Convenção: **[OFICIAL]** = lido em página da Meta/WhatsApp nesta sessão; **[PROJETO]** = README/aviso do próprio projeto de terceiros; **[REPO]** = verificado no código (`path:linha`); **[INFERÊNCIA]** = dedução minha; **[NÃO CONFIRMADO]** = as fontes lidas não dizem. Citações externas seguem `[Título](URL)`.

**Método e limites da evidência.** As páginas da Meta (`developers.facebook.com`) foram lidas em texto bruto (HTML → texto, locale `en_US`), não só por resumo de buscador; as citações literais abaixo vêm desse texto. O Help Center do WhatsApp (`faq.whatsapp.com`) é renderizado por JavaScript e **não pôde ser lido diretamente** (só o título veio); o que digo sobre a exportação manual vem de trechos do próprio artigo exibidos por buscador e está marcado como tal. O changelog da Meta traz entradas datadas até 20/10/2026 (posteriores à data desta sessão, 15/10/2026); tratei a data como informada pela página, sem poder reconciliá-la.

---

## 1. Conclusão (leia isto primeiro)

A pesquisa anterior (pane-705) dizia, sem ler documentação, que seria impossível. **Não é impossível, mas o escopo "o usuário escolhe chats/grupos/conversas existentes" só é parcialmente atendido por vias oficiais:**

| O que o usuário quer | Oficial direto (Meta) | Veredito |
|---|---|---|
| **Conversas 1:1 de um número WhatsApp Business app** (histórico) | **Sim, via Coexistência**: até 180 dias de histórico + mensagens novas em tempo real | Viável, com requisitos pesados (§4) |
| **Conversas 1:1 futuras** de um número já na Cloud API | Sim (webhook `messages`) | Viável |
| **Grupos já existentes** (criados no app) | **A documentação lida diz que não**: Coexistência — *"Group chats will not be synchronized"*; histórico — *"Messages that are part of a group chat will not be included"*; Groups API — *"not available for WhatsApp Business app phone numbers"* | **Não suportado oficialmente** |
| **Grupos criados via API** (novos, ≤ 8 pessoas, só por convite) | Sim, mensagens futuras via webhook | Existe, mas **não** é "integrar grupos existentes"; produto diferente |
| **Histórico de grupos** | Nenhuma fonte oficial lida oferece | **Não confirmado / não oferecido** |
| **Conta WhatsApp pessoal** (WhatsApp Messenger) | Nenhuma API oficial descrita nas páginas lidas | **Não confirmado**; fora de todas as vias oficiais |
| **Exportação manual** (`.txt`/`.zip`) | Oficial no app, por chat, sem API | Viável, é a única via que cobre **grupos existentes** e **contas pessoais** com suporte oficial do lado do WhatsApp; **o ArquivIO hoje não tem upload** (§7) |
| **Conectores por QR não oficiais** (Baileys, whatsapp-web.js, etc.) | Os próprios projetos avisam que não são oficiais; os termos do WhatsApp proíbem acesso automatizado não autorizado | Não recomendado para produto B2B (§6.3) |

**Caminho recomendado (juízo meu, com base nas evidências):** (1) **importação manual `.txt`/`.zip`** como primeira entrega — cobre grupos e contas pessoais, não depende de aprovação da Meta, mas exige criar o caminho de upload que não existe; (2) **Coexistência + Embedded Signup** como segunda fase para empresas que usam WhatsApp Business app (1:1, tempo real), assumindo que o ArquivIO vire **Tech Provider** (não precisa de BSP — §5); (3) **não** prometer "integrar grupos existentes" ao vivo.

---

## 2. O que as fontes oficiais DEMONSTRAM

### 2.1 Coexistência (Business app + Cloud API no mesmo número)

Fonte principal: [Onboard WhatsApp Business app users (Coexistence)](https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users).

- É um modo do Embedded Signup que permite onboarding *"using their existing WhatsApp Business app account and phone number"*; depois disso o cliente continua mandando mensagens 1:1 pelo app e *"WhatsApp keeps messaging history between both apps in sync"*.
- **Não é QR.** O fluxo descrito pede que a empresa digite o número do app, receba um código de verificação, toque em **Connect to the Business Platform**, depois **Confirm** para *"share their chat history with you"* e cole o código. (Isto distingue Coexistência de conectores por QR/dispositivo vinculado.)
- Tabela de recursos oficial: chats individuais — *"All chat messages in the most recent 6 months can be synchronized"* e mensagens enviadas/recebidas são espelhadas entre Cloud API e app; contatos — sincronizáveis; **grupos — "Not supported. Group chats will not be synchronized."**; canais, listas de transmissão, chamadas, mensagens temporárias, "ver uma vez" e localização ao vivo — não suportados na Cloud API.
- Webhooks a assinar: `history`, `smb_app_state_sync` (contatos), `smb_message_echoes` (mensagens enviadas pela empresa no app/dispositivos vinculados após o onboarding) e `account_update`.
- Mensagens recebidas de clientes depois do onboarding chegam no webhook `messages` normal ([Webhook components](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components): `messages[].from`, `id`, `timestamp`, `type`, `text.body`, `contacts[].profile.name`, `wa_id`).
- Verificação de que o número está nos dois mundos: campos `is_on_biz_app` e `platform_type` no ID do número de telefone.

### 2.2 Sincronização/importação de histórico

Fontes: [history webhook](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/reference/history) e a página de Coexistência acima.

- Cobre *"all messages sent or received within 180 days of the time when the business was onboarded"*; **"Messages that are part of a group chat will not be included."**
- Fases: 0 = dia 0–1; 1 = dia 1–90; 2 = dia 90–180; blocos (`chunk_order`, `phase`, `progress` 0–100); um único webhook pode descrever *"thousands of messages"* (capturar primeiro, processar depois).
- Mídia: o histórico traz `media_placeholder`; IDs de mídia só vêm *"for media messages sent within 14 days of onboarding"*.
- Cada mensagem traz `from`, `id`, `timestamp` (do dispositivo), `type`, conteúdo e `history_context.status`; `to` só aparece em ecos de mensagens enviadas pela empresa.
- **Janela única:** *"you have 24 hours to synchronize their messaging history, otherwise they must be offboarded"* e cada passo de sync (`smb_app_data` com `smb_app_state_sync` e com `history`) *"You can only perform this step once"*; refazer exige offboarding e novo Embedded Signup.
- **Consentimento do cliente:** se a empresa não compartilhar o histórico, chega um webhook `history` com erro `2593109`.

### 2.3 Groups API (Cloud API)

Fontes: [Groups API](https://developers.facebook.com/docs/whatsapp/cloud-api/groups) (atualizada em 16/06/2026 segundo a página), [Get started](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/getting-started), [Group messaging](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/groups-messaging), [Group management reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/reference), [FAQ](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/faq).

- Propósito literal: *"enables you to programmatically create groups for messaging and collaboration"*; *"Groups are an invite-only experience where participants join using a group invite link you send them."*; *"Since you cannot manually add participants to the group, simply send a message with your invite link"*.
- Limites: máx. **8 participantes**; **1** negócio Cloud API por grupo; até 10.000 grupos por número; tipos suportados: texto, mídia e templates; não suportados: chamadas, mensagens temporárias, "ver uma vez", autenticação, comércio, interativas; **editar/apagar mensagem não suportado**.
- Elegibilidade: *"open to all businesses with an Official Business Account (OBA)"*; **"Groups are not available for WhatsApp Business app phone numbers and phone numbers onboarded to Multi-solution Conversations."** Pré-requisito do guia: o número está em uso com a Cloud API *"(not the WhatsApp Business app)"*. Disponível em todos os países onde a Cloud API está disponível (FAQ).
- Receber mensagens de grupo: o webhook `messages` traz `group_id` e `from` = participante que enviou (exemplo oficial em [Group messaging](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/groups-messaging), seção "Receive group messages"); tipo não suportado vem como `unsupported` (código 130501). Webhooks de metadados: `group_lifecycle_update`, `group_participants_update`, `group_settings_update`, `group_status_update`.
- Preço: *"per-message pricing"* (página de preços dos grupos: não analisada em detalhe — **lacuna**).

### 2.4 Exportação manual (lado WhatsApp)

Fonte: [How to export your chat history](https://faq.whatsapp.com/1180414079177245/?cms_platform=android) — **conteúdo não legível diretamente (JavaScript)**; os pontos abaixo vêm de trechos do artigo exibidos por buscador:
- Passos: abrir o chat individual ou de grupo → Mais opções → Mais → **Exportar conversa** → *Sem mídia* / *Incluir mídia*.
- O histórico exportado é um **arquivo de texto**; *"can't be re-imported because it's a text file and not a backup file"*; com mídia, só a mídia mais recente vai em anexo.
- **[NÃO CONFIRMADO em fonte oficial lida]:** limite de 10.000 mensagens (com mídia) / 40.000 (sem mídia) apareceu num artigo antigo e localizado; o artigo atual não o repete. O formato `.zip` com `_chat.txt` aparece só em fontes secundárias (guia comercial de conversão para PDF). Tratar como a ser validado com exportações reais em Android e iOS.
- É ação **por chat, manual**, feita pelo dono do aparelho; não há exportação em lote.

---

## 3. O que as fontes oficiais NÃO confirmam (não é prova de impossibilidade nem de possibilidade)

1. **Entrar numa conta pessoal via API oficial.** Nenhuma página lida descreve API para o WhatsApp pessoal. Coexistência exige explicitamente o *WhatsApp Business app* (versão ≥ 2.24.17).
2. **Adicionar o número da Cloud API a um grupo *existente*.** A documentação de grupos só descreve grupos *criados pela API*, entrada por convite e `group_participants_add` com `reason: invite_link`. Não encontrei frase proibindo nem permitindo um grupo pré-existente; **a ausência não vale como autorização**. Além disso, grupos não existem para números do Business app (inclui Coexistência).
3. **Histórico de grupos por qualquer via oficial** — nenhuma lida.
4. **Seleção parcial de chats no momento do onboarding.** O consentimento é sobre *compartilhar o histórico* (sim/não); a documentação lida não descreve escolher conversas individuais. O filtro "só estes chats" teria que ser feito pelo ArquivIO **depois** de receber os dados **[INFERÊNCIA]** — com implicações de minimização de dados (LGPD) a avaliar.
5. **Disponibilidade da Coexistência no Brasil.** A página principal não lista países. O changelog registra extensões país a país (Índia em 05/05/2025; Nigéria e África do Sul em 15/04/2026); **não encontrei confirmação explícita para o Brasil** nas páginas lidas. Validar antes de prometer (§8).
6. **Adequação do ArquivIO às políticas de IA da Meta** — ver §6.4: não há evidência para afirmar conformidade.
7. **Modelo de conta novo (setembro/2026).** O changelog descreve um novo modelo de contas do WhatsApp (fase 1 a partir de 23/09/2026, todas as empresas até meados de outubro de 2026) e o Embedded Signup v5 (20/10/2026) com onboarding de Business app ligado por padrão. Os detalhes de Coexistência podem mudar; a página de versões que li ainda diz que a última é a v4.
8. **Identificadores de usuário (BSUID).** O changelog descreve IDs de usuário com escopo de negócio e eventos quando o telefone não pode ser compartilhado. Isso afeta **autoria**: o remetente pode não ser sempre o número de telefone. Impacto exato **não confirmado**.

---

## 4. Requisitos e limites (resumo para o plano)

**Coexistência / Embedded Signup** (páginas citadas em §2):
- O ArquivIO precisa ser **Solution Partner ou Tech Provider** (*"You must already be a Solution Partner or Tech Provider"*) e usar Embedded Signup com *session logging*.
- Cliente: **WhatsApp Business app ≥ 2.24.17**; mantê-lo aberto durante a sincronização; o número passa a ter throughput fixo de **20 mps**.
- Onboard + sync de contatos e histórico **dentro de 24 h**, cada passo **uma vez**.
- Após o onboarding, todos os dispositivos vinculados (*companion*) são desvinculados e o cliente precisa revincular; Windows e WearOS não são suportados como companion; mensagens vindas de companion não suportado **não geram webhook** `messages`.
- Preço: mensagens enviadas pelo app continuam grátis; mensagens pela Cloud API seguem a tabela de preços. **Para uma fonte de conhecimento que só lê, não há envio — impacto de custo por mensagem seria nulo [INFERÊNCIA]**, mas cobrança por conta/portfólio e cartão de crédito do cliente são exigidos pelo guia de Tech Provider (*"Your onboarded clients must add a credit card"*).
- Cliente desconectando no app dispara `account_update` `PARTNER_REMOVED`; inatividade do app principal (~14 dias) ou do companion (~30 dias) também desconecta.

**Tech Provider** ([Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)):
- App Meta com caso de uso WhatsApp + portfólio de negócios; **verificação do negócio**; **App Review** com acesso avançado a `whatsapp_business_messaging` e `whatsapp_business_management`; dois vídeos (envio de mensagem e criação de template). Há opção *"Onboard without a partner"*.

**Groups API:** OBA, número Cloud API puro, 8 participantes, convite obrigatório (ver §2.3).

**Datas de depreciação:** Embedded Signup v2/v3 deixam de existir em 15/10/2026 (data de hoje) — implementar direto na versão vigente (v4/v5 conforme o changelog).

---

## 5. Direto versus BSP

Evidência oficial: o guia de Tech Provider diz que um Tech Provider *"can independently provide all WhatsApp messaging services to clients who you have onboarded, or you can work with a Solution Partner"*, e oferece *"Onboard without a partner"*. **BSP não é obrigatório [OFICIAL].** O que é obrigatório é o ArquivIO **ser** Tech Provider (ou Solution Partner) para usar o Embedded Signup de Coexistência. Empresas que **usam a própria conta** diretamente (sem plataforma de terceiro) podem usar a Cloud API, mas a **Coexistência para um SaaS multi-tenant** passa por Tech Provider. Tempo de aprovação do App Review: um resultado de busca cita "cerca de 24 h" como média; **não confirmei** na página oficial lida — tratar como lacuna. A verificação de negócio é o item de maior latência provável **[INFERÊNCIA]**.

---

## 6. Alternativas além da Coexistência

### 6.1 Importação manual de `.txt`/`.zip`
- Cobre **conta pessoal, Business app, grupos e 1:1**, sem aprovação da Meta e sem custo de API. Custos: ação manual, por chat, **sem sync contínuo**, qualidade de dados depende do formato exportado (varia por idioma/OS — **precisa de amostras reais**), mídia limitada, sem re-importação oficial.
- O exportador do WhatsApp é função do próprio app/usuário; o uso é do arquivo que o usuário já tem. Pontos de LGPD (consentimento dos participantes do grupo, retenção) precisam de avaliação jurídica **[lacuna]**.

### 6.2 Cloud API pura (número só da API) como "caixa de entrada"
- Mensagens 1:1 futuras para um número dedicado + grupos criados via API. Serve para um fluxo novo ("encaminhe para este número / convide o bot ao grupo"), **não** para histórico existente.

### 6.3 Conectores por QR/dispositivo vinculado **não oficiais**
- Verificação: [whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) avisa — *"WhatsApp does not allow bots or unofficial clients on their platform, so this shouldn't be considered totally safe. Also it is not guaranteed you will not be blocked by using this method."* Seu exemplo exibe um QR para login. [Baileys](https://github.com/WhiskeySockets/Baileys) afirma *"not affiliated, associated, authorized, endorsed by, or in any way officially connected with WhatsApp"* e *"We discourage any stalkerware, bulk or automated messaging usage."*
- [Termos de Serviço do WhatsApp](https://www.whatsapp.com/legal/terms-of-service): proíbem acessar *"directly, indirectly, through automated or other means"* de modo não autorizado, criar contas por meios automatizados, coletar informação de usuários de modo não autorizado e criar software/API que funcione "substancialmente igual" aos serviços. A página não cita "clientes não oficiais" nem scraping de forma explícita; a ligação com os conectores é **interpretação** minha.
- **Distinção importante:** QR de conector não oficial ≠ Coexistência (§2.1: fluxo oficial usa código e botões no app, sem QR). Não tratei todo QR como não oficial.
- Conclusão: risco de bloqueio do número do cliente, risco legal e de reputação para um produto B2B de conhecimento corporativo. **Não recomendado como caminho de produto.** Existe tecnicamente (que é o motivo de a pesquisa anterior, provavelmente, ter olhado para isso), mas não é "oficial".

### 6.4 Bot de perguntas (secundário) e políticas de IA
- Termos vigentes ([Meta Terms for WhatsApp Business Platform](https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform), última atualização informada 23/09/2026, §4.7): provedores de IA/ML (*"large language models, generative AI platforms, general-purpose AI assistants, or similar"*) são restringidos quando a IA é a oferta principal; também não podem usar os dados da plataforma para treinar/melhorar sistemas, nem para criar perfis de usuários individuais (§4.1(a)). Resumo de página oficial de preços: [AI Providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers) — vigência 15/01/2026 e cobrança em mercados onde a Meta é obrigada por lei a permitir (Brasil: cobrança de service messages com taxas publicadas).
- **O que eu NÃO posso afirmar:** que um bot do ArquivIO (Q&A sobre documentos da empresa) *está* ou *não está* dentro das regras. Depende de a Meta considerá-lo "AI Provider" cuja oferta principal é IA; o texto diz que a Meta decide. Não há evidência atual lida que isente o caso. **Tratar como risco aberto e perguntar à Meta / jurídico antes de investir em bot.** Ingestão (ler conversas) e bot (responder no WhatsApp) são riscos separados; a ingestão não envolve enviar mensagens.
- Alternativa que evita a questão: perguntas ao ArquivIO continuam pelo app/API/MCP/Slack já existentes (`backend/app/access/models.py` já prevê canais `slack|teams`), e o WhatsApp fica só como **fonte**.

---

## 7. Repositório: caminho de upload e encaixe (inspeção; nada implementado)

Consultas `graphify query/explain` seguiram o `AGENTS.md`; leitura confirmatória no código.

### 7.1 Não existe upload hoje
- `rg -i "upload|UploadFile|multipart"` em `backend/app` e `backend/pyproject.toml`: **sem ocorrências**. Em `frontend`, só `frontend/components/ui/attachment.tsx` (componente de UI, sem rota de upload). O spec 001 lista *"upload de arquivos"* fora do escopo (`specs/001-mvp-document-intelligence.md:58`).
- Fontes atuais são conectores com credencial: `SELECTABLE_PROVIDERS = {"google_drive","google_drive_sa","notion","onedrive","clickup"}` (`backend/app/api/ingestion.py:57`), contrato `SourceProvider.discover(...)` (`backend/app/integrations/base.py:19-30`); registry em `backend/app/integrations/registry.py` (SharePoint existe em `integrations/sharepoint.py`).
- **Conclusão:** "importar `.txt`/`.zip`" é um **recurso novo** (endpoint multipart, armazenamento/stream, nova "fonte local"), não uma extensão trivial de algo existente.

### 7.2 O que se reaproveita
- **Extração de texto:** `EXTRACTORS` já tem `"text/plain": text.text_plain_blocks` (`backend/app/ingestion/extraction/__init__.py:34`; separa por linha em branco, `text.py:61`); `decode_text` trata UTF-8/UTF-16/cp1252 (`text.py:44`). Extensão `.txt` mapeada em `mime.py:12`. **Mas** um chat do WhatsApp **não tem linhas em branco entre mensagens** — o split por parágrafo não respeita mensagens; precisaria de um **parser próprio** (linha com data/hora/autor).
- **Proteção contra zip bomb:** `guard_zip` (`limits.py:78`, razão máx. 200×, 200 MB descomprimido) e `MAX_FILE_BYTES` 100 MB (`limits.py:20`) — reaproveitáveis para um `.zip` de exportação (mas hoje `guard_zip` só é chamado para DOCX em `extract_blocks`; um `.zip` genérico exigiria abrir o `_chat.txt` e a mídia com limites).
- **Pipeline de indexação:** `DiscoveredDocument` (`ingestion/service.py:46`: `external_file_id`, `name`, `mime_type`, `source_url`, `modified_at`, `text`, `blocks`) → `IngestionService` (`:126`) → `_upsert_indexed` (`:919`), com chunking, embeddings, `DocumentChunk(page_number)`.
- **API pública/MCP já cita documentos** (`backend/app/api/public_v1.py`, `backend/app/mcp_server/`), então perguntas sobre o conteúdo do chat funcionam por fora sem criar bot no WhatsApp.

### 7.3 Deduplicação
- Hoje: `Document` único por `(workspace_folder_id, external_file_id)` (`backend/app/knowledge/models.py:66`) e `content_hash = sha256(text)` por documento (`models.py:37`; `service.py:924,951`): se o hash e `processing_version` batem, **não reindexa** (`service.py:947-958`). **Não há dedup entre documentos diferentes** (mesmo texto em dois `external_file_id` vira dois documentos) nem **dedup por mensagem**.
- Para chats: uma re-exportação do **mesmo chat** em outra data (arquivo maior com sobreposição) mudaria o hash e reindexaria o documento inteiro se o `external_file_id` for estável (ex.: ID do chat); com ID por arquivo, duplicaria. **Decisão de modelagem necessária:** identificar o chat (hash do nome/participantes) e deduplicar por mensagem (hash de `timestamp+autor+texto`) — **[INFERÊNCIA]** e **sem suporte atual** no modelo.

### 7.4 Autoria, data e citações internas
- `ExtractedBlock` guarda `text`, `page_number`, `section_path`, `ocr` (`backend/app/ingestion/blocks.py`). Não há campo de **autor** nem **timestamp por bloco**; `rg "author|sender"` em `backend/app/knowledge` e `backend/app/ingestion` não retornou nada. O documento só tem `modified_at` (`models.py:38`).
- Citações expostas: `title`, `url` (= `source_url`), `page_number`, `modified_at` (`backend/app/knowledge/retrieval.py:96-98,133-134`; `presentation.py:48-49`).
- **Para chats**, a citação útil seria "mensagem de *Fulano*, 12/03/2026 14:05, no grupo X". Opções sem mudar o schema: um documento por chat-dia (ou por semana) com `section_path` = "Grupo X › 12/03/2026" e o autor **dentro do texto do bloco** (cada linha "[14:05] Fulano: …") — o autor fica pesquisável/citável, mas não filtrável. Mudar o schema (campos de autor/hora por chunk) seria um custo adicional.
- `source_url` é `NOT NULL` com até 2048 caracteres (`models.py:36`): um upload local precisa de um esquema interno (ex.: `arquivio://uploads/...`) e a UI de abertura do arquivo original (`document_view.py`, `file-viewer.tsx`) precisaria suportá-lo — **[INFERÊNCIA]**, não verifiquei esses arquivos em detalhe.

### 7.5 Acesso por Espaços e limites
- Todo `Document` pertence a um `WorkspaceFolder` (Espaço) (`models.py:30`), que exige uma `DataSource` (`workspaces/models.py:18`; `DataSource.provider` é string livre de 40 caracteres e `encrypted_credentials` é *nullable*, `integrations/models.py:24-25`) → uma fonte "upload" sem credenciais cabe sem migração radical **[INFERÊNCIA]**.
- Controle de acesso: **não há ACL por espaço**; o Espaço exige `uniform_access_confirmed` — todos os membros podem ver tudo (`workspaces/service.py:78-80`); a nota anterior (`integracoes-analise-2026-09-29.md`) já classifica "ACL por arquivo/canal" como pré-requisito para Slack/WhatsApp. Chat de WhatsApp é **conteúdo de pessoas** (clientes, colegas); sem permissões por Espaço, um chat importado ficaria visível a todos da organização. **Este é o principal bloqueio de produto para o WhatsApp, maior que o técnico.** (O plano geral de "níveis/Workspaces" do pane-704 é onde isso deve ser resolvido.)
- Limites que um chat estoura: **500 documentos ativos por organização** (`audit_usage/service.py:15`), `MAX_DOCUMENT_CHARS = 600_000` e `MAX_CHUNKS_PER_DOCUMENT = 2_000` (`limits.py:23-24`) — um grupo ativo de 2 anos não cabe em um documento; precisa de fatiamento (por período) e provavelmente de uma política de limite própria.

---

## 8. Estimativas preliminares ([ESTIMATIVA], dias-pessoa, sem lead time externo; baixa confiança)

| Entrega | Escopo | Esforço | Observações |
|---|---|---|---|
| **A. Importação manual `.txt`/`.zip`** (MVP) | endpoint de upload + validação/limites, fonte "upload", parser de chat (formatos PT/EN, Android/iOS, mensagens multilinha, mensagens de sistema), fatiamento em documentos, dedup por chat/mensagem, citação com autor/data no texto, UI de upload + escolha do Espaço, testes | **8–14 d** | Depende de amostras reais; sem dependência da Meta. Pré-requisito de produto: permissão por Espaço antes de liberar |
| **B. Coexistência (1:1)** | virar Tech Provider (verificação + App Review), Embedded Signup + sessão, endpoint de webhooks (assinatura/validação, idempotência, fila), `smb_app_data` + ingestão de `history`/`messages`/`smb_message_echoes`, mapeamento número→thread→documento/dia, filtro por conversa escolhida, offboarding/`account_update`, painel de status, testes | **20–35 d** + lead time externo (verificação do negócio, App Review, cartão de crédito dos clientes, validação em Brasil) | Janela de 24 h e sync único exigem robustez; não cobre grupos |
| **C. Grupos criados via API** | OBA (verificação), Groups API, convites por template, webhooks `group_*`, ingestão de `messages` com `group_id` | **10–18 d** + OBA | Utilidade baixa para "integrar grupos existentes" |
| **D. Conector QR não oficial** | — | 5–10 d técnicos | **Não recomendado** (risco de bloqueio/legal) |
| **E. Bot de perguntas no WhatsApp** | — | 8–15 d | **Bloqueado por decisão de política (§6.4)**; secundário |

Ordem sugerida: **A** → (decisão de permissões por Espaço) → **B**. C/D/E só com decisão explícita.

---

## 9. Lacunas e como fechá-las

| Lacuna | Como fechar |
|---|---|
| Help Center do WhatsApp (exportação) não legível; formato `.zip`/`_chat.txt`, limites de mensagens, localização do texto | Exportar chats reais (1:1 e grupo; Android e iOS; PT/EN; com e sem mídia) e anexar fixtures; ler o artigo no navegador |
| Coexistência no **Brasil** | Teste real com um número Business app BR numa conta de teste; consultar a lista atual de países |
| Prazos e critérios de verificação de negócio / App Review | Abrir o fluxo no App Dashboard; falar com o suporte da Meta |
| ArquivIO como "AI Provider" sob §4.7 | Pergunta formal à Meta e revisão jurídica; só depois de decidir bot |
| LGPD (bases legais, consentimento de terceiros em grupos, retenção, operador/controlador) | Parecer jurídico; desenho de minimização (descartar conversas não escolhidas antes de gravar) |
| Preço de mensagens em grupos; custos de sub-contas | Ler página de preços de grupos (fonte `…/groups/pricing`, baixada mas não analisada) |
| BSUID e impacto na autoria | Ler a documentação de IDs de usuário e testar payloads em sandbox |
| Mudanças do novo modelo de contas / ES v5 | Reler a documentação quando for implementar; fixar versão |
| Página de preços de IA e termos pelo domínio `whatsapp.com/legal/business-solution-terms` redireciona para `facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform`; texto lido em PT-BR via resumo automático | Reler o §4.7 e §4.1 em texto integral antes de decisões jurídicas |

Observação sobre método: um subconjunto das páginas (Termos, Help Center) foi lido por ferramenta de resumo, não texto bruto; as citações literais de Termos vêm desse resumo e devem ser conferidas.

---

## 10. Fontes (oficiais e de projeto)

- [Onboard WhatsApp Business app users (Coexistence)](https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users)
- [Webhook: history](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/reference/history)
- [Webhook: smb_message_echoes](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/smb_message_echoes)
- [Webhooks — componentes (messages)](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components)
- [Groups API](https://developers.facebook.com/docs/whatsapp/cloud-api/groups) · [Get started](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/getting-started) · [Group messaging](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/groups-messaging) · [Group management reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/reference) · [FAQ](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/faq) · [Webhooks for Groups](https://developers.facebook.com/docs/whatsapp/cloud-api/groups/webhooks)
- [Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)
- [Embedded Signup — versions](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/versions)
- [WhatsApp changelog](https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog)
- [Pricing — AI Providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers)
- [Meta Terms for WhatsApp Business Platform](https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform)
- [WhatsApp Terms of Service](https://www.whatsapp.com/legal/terms-of-service)
- [How to export your chat history](https://faq.whatsapp.com/1180414079177245/?cms_platform=android) (conteúdo não legível diretamente)
- [whatsapp-web.js (README)](https://github.com/pedroslopez/whatsapp-web.js) · [Baileys (README)](https://github.com/WhiskeySockets/Baileys) — projetos de terceiros, citados apenas por seus avisos.
