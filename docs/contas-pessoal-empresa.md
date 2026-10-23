# Contas Pessoal e Empresa — modelo, planos pagos, Stripe, comps e LP

> Documento de planejamento/arquitetura. Nenhum código foi alterado.
> **Revisão 2** — decisões novas do dono incorporadas: (1) **não existe plano gratuito permanente**, só **trial** com dias limitados; (2) Pessoal tem 2 planos pagos, Empresa tem 2 planos pagos (a quantidade de membros muda entre eles); (3) cobrança via **Stripe**; (4) **contas atuais ficam como estão** (`legacy`); (5) **cupons** (Stripe) e **comps/cortesias** (override local administrativo, sem cobrança).
> Regras anteriores mantidas: conta **pessoal não adiciona membros** e tem **limites menores**; conta pessoal pode virar **empresa**.
> Valores de limite e preço são **propostas iniciais** — marcados `[A CONFIRMAR]` quando dependem de custo/decisão comercial.

---

## 0. Resumo executivo

- **O tipo de conta mora na `organizations`**, não no `users`. Toda a app já é multi-tenant por `organization_id` (`OrganizationScope`). Conta pessoal = **org de 1 pessoa com `account_type='personal'`**.
- **Upgrade pessoal→empresa = mesmo `organization_id`** (zero migração de dados): muda `account_type`, nome e o **price** da assinatura Stripe (troca de price na mesma subscription, com proration).
- **Não há plano grátis.** Toda org nova nasce em **trial de 14 dias, sem cartão, controlado localmente** (não no Stripe). Ao expirar: **somente leitura** até assinar. Detalhes em §4.
- **Catálogo de planos** (`plan_key`): `personal_basic`, `personal_pro`, `business_team`, `business_scale`; estados técnicos `personal_trial`, `business_trial`, `expired`, `legacy`. Tabela em §2.3.
- **Empacotamento recomendado para Empresa: preço base com assentos incluídos + assento extra** (modelo B, §3). Cada plano de empresa tem pool de uso fixo (documentos, perguntas…) e N assentos incluídos; assentos extras são cobrados por unidade. No Stripe = **1 Price escalonado (graduated + flat fee) por plano/intervalo, `quantity` = assentos comprados**.
- **Um único ponto de enforcement no backend**: `app/entitlements/` com `entitlements_for(org)` que aplica a **precedência `comp > assinatura Stripe > trial > legacy > expirado`**, calculada **no momento da leitura** (não depende de evento para expirar trial/comp/carência).
- **Stripe** (§5): Checkout Session (hospedado) + Customer Portal + webhook assinado e idempotente; o Stripe é a verdade do **pagamento**, a tabela local `subscriptions` é a verdade do **acesso**, atualizada só por sincronização (re-fetch) idempotente.
- **Contas fora do padrão sem cobrança** (§6): **comp** = linha em `organization_comps` (plan_key concedido + `limits_override` + validade + motivo + quem concedeu), auditada, que **ignora o Stripe**. Gerenciada por quem é `PlatformStaff` — conceito que **já existe** (`organizations/models.py:66`, `api/platform.py`, tela `/staff`). **Descontos normais** = cupons/promotion codes do Stripe.
- **Contas existentes** (§10): ficam como estão — `plan_key='legacy'`, sem limites novos, fora do Stripe, **sem backfill/migração forçada**.

---

## 1. Como funciona hoje (mapa com referências)

### 1.1 Organização, membros, roles
| Tema | Onde | Observação |
|---|---|---|
| `Organization` (sem tipo/plano) | `backend/app/organizations/models.py:17-24` | Só `name`, `onboarding_step`, `onboarding_completed_at`. **Não há `account_type`, `plan` nem limites por org.** |
| `MembershipRole` owner/admin/member | `organizations/models.py:11-14` | |
| `Membership` | `organizations/models.py:27-42` | `is_active`, `deactivated_at`. Unicidade parcial org+user ativo: `:96-102`. |
| `MembershipInvitation` | `organizations/models.py:45-63` | token hash, `expires_at`, `space_ids`. Unicidade de pendente por org+email: `:112-118`. |
| Criar org | `OrganizationService.create_organization` `organizations/service.py:43-79` | Cria org + Space "Geral" (default) + membership OWNER + SpaceMember manager + audit. **Sem checagem de quantas orgs o usuário já criou.** |
| Endpoint criar org | `POST /organizations` `api/auth.py:401-410` (`OrganizationCreateInput` `:82`) | Qualquer usuário autenticado cria quantas orgs quiser. |
| Listar orgs do usuário | `organizations_for_user` `service.py:110-118`, `GET /organizations` `auth.py:413-416` | Retorna id, name, membership_id, role — **sem tipo**. |
| Convidar | `create_invitation` `service.py:168-220` | Exige OWNER (`:174-183`), só roles admin/member (`:172`), expira 7 dias, substitui convite pendente. **Sem checagem de limite de assentos.** |
| Aceitar convite | `accept_invitation` `service.py:222-262` | Casa por e-mail canônico (`:231`); cria Membership + `enrollment.enroll_member`. **Sem checagem de assentos.** |
| Adicionar membro direto | `add_membership` `service.py:81-100` | Sem limite. |
| Mudar role / desativar | `service.py:152-166`, `:286-308` | Owner-only; owner não é alterável. |
| Endpoints de membros/convites | `api/auth.py:419-535` | `POST …/members/invitations` (`:461`), `POST /invitations/{token}/accept` (`:488`) |
| Frontend de equipe | `frontend/app/product/team-staff.tsx:31-36` | Convite/role/remover; só `owner` carrega membros (`:31`). |

### 1.2 Espaços, pastas, grants (ADR-0021)
- `Space` (`spaces/models.py:22-35`), `SpaceMember` roles member/manager (`:47+`), `SpaceFolderGrant` (`:78`), `SpaceNodeGrant` (`:110`).
- Criação de Space: `SpaceService.create_space` `spaces/service.py:130-142` (exige admin, **sem limite de quantidade**); rota `api/spaces.py:152-163`.
- Todo membro novo é matriculado no Space default ("Geral") por `spaces/enrollment`.
- Em conta pessoal o modelo de Spaces continua válido, mas a UI deve **esconder** a gestão de pessoas/grants de pessoas.

### 1.3 Billing / planos / limites
- **Não existe billing, plano, Stripe nem assentos** (busca por `stripe` em todo o repo, fora de docs/graphify, não retorna nada; `httpx` já é dependência — `backend/pyproject.toml:12`; o SDK `stripe` precisará ser adicionado).
- Limites de uso existentes são **globais por deploy**, não por org:
  - `core/config.py:49-53`: `active_document_limit=3000`, `monthly_limit_processed_bytes=12GB`, `monthly_limit_embedding_tokens=10M`, `monthly_limit_questions=1000`, `monthly_limit_ocr_pages=2000`.
  - `audit_usage/service.py:23-31` (`active_document_limit()`, `monthly_limits()`), contagem em `UsageService.check_and_record` `:67-88` (tabela `usage_records`, `audit_usage/models.py:50-57`, chave org+mês+métrica), resumo em `usage_summary` `:91-109` (`GET …/usage`, `api/usage.py:30`, UI `product/usage-panel.tsx:23`).
  - Pontos que consomem: ingestão `ingestion/service.py:618, 939, 974, 1020`; perguntas `knowledge/questions.py:931, 1039, 1118, 1233, 1484`; todos tratam `UsageLimitExceeded` (API: `api/ingestion.py:359,456`, `api/public_v1.py:277`, `api/notifications.py:101`; jobs: `ingestion/tasks.py:994`, `automations/executor.py:121`, `notifications/digest.py:45,80`, `notifications/followed.py:101`).
- Outros limites **hard-coded**: `MAX_AUTOMATIONS_PER_ORGANIZATION = 20` (`api/automations.py:45`, aplicado em `:286-292`); `max_file_bytes=100MB` (`config.py:139`); rate limits `api_org_rate_limit_per_minute=600`, `api_ask_rate_limit_per_minute=10`, `mcp_rate_limit_per_minute=60` (`config.py:141-148`); `sync_scheduler_max_concurrent_per_org=3` (`:153`); `ocr_max_pages_per_job=200` (`:35`).
- API keys: `access_admin.py:81`. MCP: `api/mcp_admin.py`. Automations/webhooks: `automations/models.py`. Integrações: `DataSource` (`integrations/models.py:20`).
- SSO: `workos_*` em `config.py:100-102` é só o provedor de login (AuthKit), **não é SSO corporativo por org**.
- Padrão de segredo/config: `Settings(BaseSettings)` com `SecretStr` (`core/config.py:1-8`) — as chaves Stripe seguem esse padrão.

### 1.4 Signup / login / onboarding
- Registro e login por senha/OAuth: `api/auth.py:209-262`, `GET /auth/login` `:288` (aceita `screen_hint`), `GET /auth/callback` `:331`.
- **Todos os caminhos terminam em `/login` no app** quando não há `return_to` de convite: `_custom_auth_result` `auth.py:186-189`; `callback` `:353-354`. `_safe_invitation_return_to` `:66-79` só aceita `/invitations/<token>`.
- O front decide o destino: `product-app.tsx:55-64` carrega `/organizations`; 1 org → entra direto (`shouldAutoEnterOrganization`, `landing-session.mjs:12`); >1 → `OrganizationPicker`; 0 → `Onboarding` "Crie sua primeira organização" (`product/auth-screens.tsx:20-21`, `POST /organizations`).
- Onboarding por org: `organizations/onboarding.py` (só OWNER). Rotas em `api/onboarding.py`.
- LP: `frontend/app/landing-page.tsx` (469 linhas), logada acessível (commit `82654be3`). **Não há seção de preços/planos nem segmentação pessoal×empresa.**
- Convite: `frontend/app/product-app.tsx:112` (`InvitationAcceptance`), cookie `document_intelligence_return_to`.

### 1.5 Staff / superadmin da plataforma (já existe)
Há um conceito de operador global **separado do tenant**, pronto para ser estendido:

| Peça | Onde |
|---|---|
| Tabela/modelo `PlatformStaff` (`user_id` único, `is_active`) | `backend/app/organizations/models.py:66-74`; migração `alembic/versions/20260911_0009_platform_staff_access.py` |
| Grants expirantes por org (`reason` ≤240, `expires_at`, `revoked_at`) — **molde para o comp** | `organizations/models.py:77-93` |
| Serviço `PlatformStaffAccessService` (`is_platform_staff`, `all_organizations`, `grant/revoke_metadata_access`, `_audit`) | `backend/app/organizations/staff_access.py:34-160` |
| Rotas `/platform/companies` e `/platform/companies/{id}/overview` (somente metadados; "deliberadamente separadas das APIs de tenant") | `backend/app/api/platform.py:15-65`; montado em `app/main.py:188` |
| Flag exposta ao front em `/auth/me` | `backend/app/api/auth.py:397` (`is_platform_staff`) |
| Tela de suporte `/staff` (só renderiza se `user.is_platform_staff`) | `frontend/app/product/team-staff.tsx:47-53`; entradas de menu `account-menu.tsx:66`, `mobile-nav.tsx:95`; tipo `types-and-api.tsx:21` |
| Auditoria | `AuditLog` (`audit_usage/models.py:21-32`: org, actor, action, target_type, target_id — **sem coluna de payload**; `actor_user_id` é NOT NULL) |

Limitações: **não há CLI/endpoint/UI para criar um `PlatformStaff`** (só testes: `tests/api/test_platform_staff_api.py:57`), não há papéis dentro do staff e `/platform` é somente leitura. O desenho do comp (§6) estende isso em vez de inventar outro mecanismo.

### 1.6 Gaps que o projeto precisa fechar
1. Nenhum conceito de tipo/plano/assinatura por org.
2. Limites globais (mesmo teto para toda org) e dispersos (config + constante + inline).
3. Convite/aceite/`add_membership` sem teto de assentos.
4. `POST /organizations` sem limite → N orgs "grátis" para contornar limites/trial.
5. Onboarding e LP assumem equipe (`auth-screens.tsx:21`).
6. Nenhuma integração de pagamento, webhook público ou tabela de assinatura.
7. Staff existe mas não consegue conceder nada (só ver metadados).

---

## 2. Modelo proposto

### 2.1 Onde mora o tipo — `organizations.account_type` + fontes de acesso
Opção A (recomendada): colunas na `organizations`. Opção B (rejeitada): `users.account_type` (quebra com usuário dono pessoal **e** membro de empresa; limites são por org).

**Colunas novas em `Organization`** (`organizations/models.py:17`):

| Coluna | Tipo | Default | Papel |
|---|---|---|---|
| `account_type` | `String(16)` + `CHECK IN ('personal','business')` | `'business'` (linhas existentes, ver §10) | Capacidades estruturais (pode ter membros?). |
| `plan_key` | `String(32)` | `'legacy'` (existentes) | **Projeção/cache** do plano efetivo — atualizada a cada mutação (webhook, comp, trial); usada em listagens, admin e métricas. **A verdade do acesso é `resolve_entitlement()` em tempo de leitura** (§2.2), porque trial/comp/carência expiram por tempo, sem evento. |
| `entitlement_source` | `String(16)` | `'legacy'` | Projeção de qual fonte venceu: `comp`/`subscription`/`trial`/`legacy`/`expired`. **Exceção:** o valor `legacy` é também *entrada* (marcador gravado pela migração e limpo na primeira assinatura); os demais valores são só projeção. |
| `trial_started_at`, `trial_ends_at` | `DateTime(tz)` nullable | `NULL` | Trial **local** (§4). `NULL` = nunca teve trial (ex.: legacy). |
| `stripe_customer_id` | `String(64)` nullable, unique | `NULL` | 1 Customer Stripe por org, criado no primeiro checkout. |
| `account_type_changed_at` | `DateTime(tz)` nullable | | Cooldown de downgrade (anti-abuso). |
| `created_by_user_id` | `Uuid` nullable FK users | | Limitar nº de orgs pessoais e de trials por usuário (§2.5). |

*(removidos em relação à revisão 1: `limits_override` na org — passa para a tabela de comps; `billing_customer_id`/`billing_subscription_id` — substituídos por `stripe_customer_id` + tabela `subscriptions`.)*

**Tabelas novas:**

| Tabela | Fase | Campos principais |
|---|---|---|
| `organization_comps` (§6.2) | F3 | `organization_id`, `plan_key`, `limits_override` JSON, `expires_at`, `reason`, `granted_by_user_id`, `revoked_at`, `revoked_by_user_id` |
| `subscriptions` (§5.4) | F6 | `organization_id`, `stripe_subscription_id` (unique), `stripe_customer_id`, `status`, `plan_key`, `interval`, `seats` (quantity), `current_period_end`, `cancel_at_period_end`, `past_due_since`, `stripe_price_id`, `discount_summary`, `updated_at` |
| `stripe_webhook_events` (§5.5) | F6 | `id` = `evt_…` (PK), `type`, `received_at`, `processed_at`, `error` |
| `platform_staff.role` (coluna) | F3 | `'support'` (default) / `'admin'` — só `admin` concede comps |

Por que `account_type` **e** `plan_key`? O tipo define **capacidades estruturais**; o plano define **tamanhos**. Dá para ter 2 planos por tipo sem mexer na lógica estrutural.

Invariantes (checadas no serviço, não no banco):
- `personal` ⇒ no máximo **1 membership ativa** (o owner) e **0 convites pendentes**; checagem transacional com `SELECT … FOR UPDATE` na org (padrão de `onboarding.py:58-75`).
- `personal` ⇒ roles só OWNER.
- Um comp para uma org só pode apontar `plan_key` cujo `account_type` do catálogo seja o da org (para mudar de tipo, faz-se o upgrade antes).

### 2.2 Ponto único de enforcement — `app/entitlements/`

```
backend/app/entitlements/
  __init__.py
  catalog.py      # PLANS: dict[plan_key, PlanDefinition] — fonte única dos valores (+ mapa price→plan)
  resolver.py     # resolve_entitlement(session, org, now) -> ResolvedEntitlement (precedência §6.3)
  service.py      # entitlements_for(session, org_id) ; require_*/usage helpers ; upgrade/downgrade
  errors.py       # EntitlementError(code, limit, used, upgrade_to) -> HTTP 402/403
```

- `Entitlements` (dataclass frozen) = `catalog[plan_key]` ⊕ `comp.limits_override` (quando a fonte é comp). Campos: `can_have_members`, `max_members`, `max_spaces`, `active_documents`, `monthly_processed_bytes`, `monthly_embedding_tokens`, `monthly_questions`, `monthly_ocr_pages`, `max_file_bytes`, `max_automations`, `max_api_keys`, `max_data_sources`, `allowed_providers`, `mcp_enabled`, `public_api_enabled`, `webhooks_enabled`, `audit_log_retention_days`, `sso_enabled`, rate limits, **`read_only: bool`** (novo, §4.3) e **`source`** (de onde veio).
- Em planos pagos pelo Stripe, `max_members = max(included_seats, subscription.seats)` — o limite de membros vem da **quantity** comprada, não só do catálogo (§3, §5.6).
- **Substituir** (não duplicar) as leituras globais:
  - `audit_usage/service.py:23-31` → `active_document_limit()`/`monthly_limits()` recebem o `Entitlements`; `Settings` vira só *fallback de dev/testes* e define o `legacy`.
  - `UsageService.check_and_record` (`:69`) lê o limite da org via `entitlements_for`.
  - `usage_summary` (`:91`) devolve também `plan_key`, `account_type`, `source`, `trial_ends_at` e limites efetivos.
  - `MAX_AUTOMATIONS_PER_ORGANIZATION` (`automations.py:45,286-292`) → `ent.max_automations`.
  - `max_file_bytes` (`config.py:139`) → `min(settings.max_file_bytes, ent.max_file_bytes)` no upload.
- **Guards** (dentro dos serviços, não nas rotas — valem também para jobs/MCP/API pública):

  | Guard | Chamado em |
  |---|---|
  | `require_writable` (bloqueia se `read_only`) | ingestão, criação de recursos, convites, automações, sync |
  | `require_can_invite` + `require_seat_available` | `create_invitation` (`service.py:168`), `accept_invitation` (`:222`, **de novo**), `add_membership` (`:81`) |
  | `require_space_quota` | `SpaceService.create_space` (`spaces/service.py:130`) |
  | `require_automation_quota` | `create_automation` (`automations.py:286`) |
  | `require_api_key_quota` / `require_feature('public_api')` | `create_key` (`access_admin.py:81`), `public_v1.py` |
  | `require_feature('mcp')` | `mcp_admin.py:67/81`, `mcp_server` |
  | `require_provider(provider)` + `require_source_quota` | ao criar `DataSource` (`integrations/*.py`, `google_drive_sa_service.py:135`) |
  | `require_org_creation_quota(user)` | `create_organization` (`service.py:43`) / `POST /organizations` (`auth.py:401`) |
- **Erro padronizado**: `EntitlementError` → HTTP **402** (plano/limite/expirado) ou **403** (tipo de conta) com corpo `{"code":"seat_limit","limit":5,"used":5,"upgrade_to":"business_scale"}`. Códigos novos: `trial_expired`, `subscription_required`, `read_only`. `UsageLimitExceeded` herda de `EntitlementError` (mesmo handler).
- **Cache**: por request (como o predicado de leitura do ADR-0021), **nunca** entre requests — upgrade/comp/webhook têm de valer na próxima requisição.

### 2.3 Catálogo de planos e limites (sem plano gratuito)
Premissas: custo variável dominante = embeddings + perguntas (LLM) + OCR + armazenamento processado. O teto "Team" reproduz os valores globais atuais (`config.py:49-53`). Tudo `[A CONFIRMAR]` contra custo real por pergunta/página. **Uso é um pool por organização** (não por assento).

| Capacidade | `personal_basic` | `personal_pro` | `business_team` | `business_scale` |
|---|---|---|---|---|
| Pode ter membros | **Não** | **Não** | Sim | Sim |
| Assentos incluídos / máximo | 1 / 1 | 1 / 1 | **5** / 15 | **20** / 100 |
| Roles | só owner | só owner | owner/admin/member | owner/admin/member |
| Documentos ativos indexados | 500 | 2.000 | 3.000 (atual) | 20.000 |
| Volume processado/mês | 2 GB | 6 GB | 12 GB (atual) | 100 GB |
| Tokens de embedding/mês | 2 M | 6 M | 10 M (atual) | 50 M |
| Perguntas/mês (pool da org) | 200 | 600 | 1.000 (atual) | 5.000 |
| Páginas OCR/mês | 400 | 1.200 | 2.000 (atual) | 10.000 |
| Tamanho máx. de arquivo | 25 MB | 50 MB | 100 MB (atual) | 100 MB |
| Espaços (Spaces) | 1 ("Geral") | 3 | 25 | 200 (soft) |
| Grants por pasta/pessoa | n/a | n/a | sim | sim |
| Fontes de dados conectadas | 2 | 5 | 10 | 30 |
| Provedores | Google Drive + upload | + OneDrive/Notion | todos | todos |
| Automações | 3 | 10 | 20 (atual) | 100 |
| Webhooks de saída | não | 2 | sim | sim |
| Chaves de API pública | 0 | 1 | 10 | 50 |
| MCP remoto | não | sim (1 conexão) | sim | sim |
| Rate limit API/min (org) | 60 | 120 | 600 (atual) | 1.200 |
| Perguntas/min (`api_ask_rate_limit_per_minute`) | 5 | 10 | 10 (atual) | 30 |
| Retenção do log de auditoria | 30 dias | 30 dias | 180 dias | 365 dias |
| Painel de auditoria / export | não | não | sim | sim |
| SSO corporativo por org | não | não | não | sim *(requer WorkOS SSO connection por org)* |
| Suporte | e-mail | e-mail | e-mail prioritário | SLA |
| **Preço-âncora mensal** `[A CONFIRMAR]` | **R$ 39** | **R$ 99** | **R$ 299** (5 assentos) | **R$ 899** (20 assentos) |
| **Assento extra/mês** `[A CONFIRMAR]` | — | — | **R$ 49** (até 15) | **R$ 39** (até 100) |
| **Anual** `[A CONFIRMAR]` | R$ 390 (2 meses grátis) | R$ 990 | R$ 2.990 + R$ 490/assento | R$ 8.990 + R$ 390/assento |

**Estados técnicos** (não vendidos — existem só no catálogo):

| `plan_key` | Quando | Limites |
|---|---|---|
| `personal_trial` | trial pessoal ativo | 300 docs, 100 perguntas (no período), 1 GB, 2 fontes, 1 Space, sem API/MCP `[A CONFIRMAR]` |
| `business_trial` | trial empresa ativo | 5 assentos, 1.000 docs, 300 perguntas (no período), 3 GB, 3 fontes, 5 Spaces `[A CONFIRMAR]` |
| `expired` | trial acabou / assinatura perdida e sem comp | `read_only=true` (§4.3) |
| `legacy` | contas existentes (§10) | exatamente os valores globais atuais de `Settings`; `can_have_members=True`, sem teto de assentos |

Notas:
- Os limites do trial são **mensais** porque `usage_records` é por mês (`audit_usage/models.py:50-57`); um trial de 14 dias pode cruzar dois meses. Mitigação: o limite de perguntas do trial é aplicado sobre a **soma dos `usage_records` desde `trial_started_at`**, não por mês-calendário.
- Limites "de teto de abuso" (ex.: 100 req/min por chave) continuam globais em `Settings` e valem como `min(plano, global)`.
- Sugestão de ladder de preço: Pessoal Pro (R$ 99) < Team (R$ 299) deixa o salto pessoal→empresa explícito. Todos os números dependem do custo por pergunta.

### 2.4 Gating na UI
- `GET /organizations` (`auth.py:413`) passa a devolver `account_type`, `plan_key`, `entitlement_source`, `trial_ends_at`, `read_only` e um bloco `entitlements` enxuto (`can_have_members`, `max_members`, flags). Tipo `Company` no front ganha esses campos.
- Hook único `useEntitlements(company)` + `<UpgradeGate feature="members">`: esconder (Equipe, Spaces avançado, Webhooks) vs. mostrar desabilitado com CTA.
- Regras de UI:
  - Pessoal: remove "Equipe" do menu e mostra card "Trabalhe com outras pessoas → Transformar em conta de empresa".
  - **Faixa de trial** no topo ("Faltam 5 dias de teste — Assinar") e **faixa de somente leitura** quando `read_only` ("Seu teste acabou. Seus arquivos estão salvos — assine para voltar a adicionar e perguntar").
  - Painel de uso (`usage-panel.tsx:23`) mostra plano, fonte e barra por métrica; em warning/exceeded, CTA de upgrade.
  - Erros 402 (`code`) → um único diálogo de upgrade/assinatura.
  - **O gating de UI é conveniência; a verdade é o backend.**
- Seletor de organização (`org-picker.tsx`, `account-menu.tsx`): badge "Pessoal" / "Empresa" (e "Teste" quando trial).

### 2.5 Anti-abuso
- `require_org_creation_quota`: no máximo **1 org pessoal ativa por usuário como dono**. Orgs empresa: sem teto técnico, mas com rate limit.
- **Trial uma vez por criador e por tipo** (`created_by_user_id`): um usuário não ganha novo trial pessoal criando outra org. Trial só começa com e-mail verificado (o fluxo atual já verifica — `auth.py:209-262`).
- Convidados em org empresa **não** consomem trial/limite pessoal deles; o uso é sempre da org do contexto.
- Upgrade pessoal→empresa durante o trial **mantém os dias restantes** (não reinicia).

---

## 3. Empacotamento da venda (recomendação)

O dono ainda não definiu como vender Empresa. Três modelos viáveis:

### 3.1 Comparativo

| | **A. Faixas fechadas** | **B. Preço base + assento extra** *(recomendado)* | **C. Por assento puro** |
|---|---|---|---|
| Ideia | `business_team` = até 10 pessoas por R$ X; `business_scale` = até 50 por R$ Y | Cada plano tem preço base com N assentos incluídos e um pool de uso; cada assento acima custa R$ Z | R$ Z × nº de pessoas; plano só muda as features/limites por pessoa |
| Prós | Mais simples de explicar e de cobrar; previsível; Stripe trivial (quantity 1) | Previsível **e** justo: sem degrau brusco; combina com custo real (uso em **pool**, não por pessoa); upgrade Team→Scale claro (mais pool/SSO/auditoria) | Modelo familiar (Slack-like); escala linear; sem "degrau" |
| Contras | **Degrau**: 11ª pessoa força saltar de plano; time de 6 paga por 10; desincentiva convidar | Mais um conceito (assentos incluídos + extras); precisa de UI de "adicionar assentos" | Custo do produto **não escala com pessoas** (escala com documentos/perguntas) ⇒ margem imprevisível; time de 2 paga pouco por um pool grande ou o pool precisa ser por assento (complexidade em `Entitlements`); "assento vazio" gera atrito |
| Stripe | 1 Product + 1 Price flat por faixa/intervalo; troca de faixa = troca de price | 1 Product por plano + **1 Price escalonado (graduated) com `flat_amount`** na 1ª faixa (assentos incluídos) e `unit_amount` nas seguintes; `quantity` = assentos; *fallback:* 2 itens (base qty 1 + assento extra) | 1 Product + 1 Price por assento/intervalo; `quantity` = assentos |
| Limites | `max_members` fixo da faixa | `max_members = quantity` comprada (≥ incluídos, ≤ teto do plano) | `max_members = quantity` |

### 3.2 Recomendação: **modelo B**
- **Por quê**: (1) o custo do Arquivio é dominado por uso (embeddings/perguntas/OCR), que o plano limita em **pool**; assento é só um multiplicador de receita e de acesso. (2) Previsibilidade para o comprador (preço-base conhecido) sem o degrau do modelo A. (3) Resolve o que o dono pediu — "o que muda nos planos de empresa inclui a quantidade de membros": cada plano tem assentos **incluídos** e **máximo** diferentes. (4) O argumento de upgrade Team→Scale fica honesto: passou de 15 pessoas **ou** precisa de mais pool/SSO/auditoria.
- **Exemplo**: Team R$ 299 inclui 5; 8 pessoas = 299 + 3 × 49 = **R$ 446/mês**. Scale R$ 899 inclui 20.
- **Pessoal** não usa assentos: dois planos flat (`personal_basic`, `personal_pro`), `quantity = 1`.
- **Regra de upgrade automático sugerido** na UI: ao tentar passar de 15 assentos no Team, oferecer Scale (comparando o total).
- **Alternativa se o dono quiser simplicidade máxima no lançamento**: começar com o modelo A (2 faixas fechadas) e migrar para B depois — custo da mudança é criar novos Prices e mover assinaturas; mas expõe o degrau. Não recomendado.
- Anual com desconto (≈ 2 meses grátis) `[A CONFIRMAR]`; lançar mensal+anual desde o início custa só mais 4 Prices.

---

## 4. Trial (único "grátis")

### 4.1 Decisão proposta
| Ponto | Proposta | Racional |
|---|---|---|
| Duração | **14 dias** `[A CONFIRMAR: 7 ou 14]` | Produto de documentos precisa de tempo para conectar fontes e indexar (sync + OCR); 7 dias é curto para empresa; 14 é padrão B2B. |
| Cartão | **Não exigir** | Menor fricção, funil de PLG; volume baixo e B2B toleram trial sem cartão; o custo de abuso é contido por limites do trial e "1 trial por criador". Revisar se a conversão ficar baixa ou o abuso alto (§4.4). |
| Onde vive | **Local** (`organizations.trial_*`), **não** no Stripe | Ver §4.2. |
| Início | Na **criação da org** (`create_organization`), com e-mail verificado | `personal_trial` ou `business_trial` conforme `account_type`. |
| Lembretes | D-3, D-1 e D0 por e-mail (job; módulo `notifications/` já tem digest) | |
| Upgrade durante trial | pessoal→empresa mantém os dias restantes | anti-abuso |

### 4.2 Trial local vs. trial no Stripe
| | Local (recomendado) | Stripe (`trial_period_days`) |
|---|---|---|
| Fricção | Zero: o usuário entra e usa | Passa pelo Checkout antes de ver valor (cartão, ou `payment_method_collection='if_required'` + `trial_settings.end_behavior.missing_payment_method`) |
| Complexidade | Trial = 2 colunas + regra no resolver | Subscription Stripe existe desde o dia 0; precisa tratar `customer.subscription.trial_will_end` e fim sem método de pagamento |
| Conversão/cobrança | No fim, Checkout normal (sem `trial`) | Cobra automaticamente no fim (conversão maior **com** cartão) |
| Abuso | Controlado por regras próprias | Cartão atua como barreira |
| Quando escolher | Lançamento | Se a conversão sem cartão ficar abaixo do esperado, testar trial-com-cartão como experimento |

### 4.3 O que acontece ao expirar: **somente leitura**
Estado `expired` (`read_only=true`), vale para trial vencido, assinatura cancelada/não paga (após carência) e comp vencido, quando não há outra fonte:

| Permitido | Bloqueado (`402 read_only`/`trial_expired`) |
|---|---|
| Entrar, navegar na biblioteca, abrir/baixar documentos, buscar | Novos uploads e ingestão |
| Ver painel de uso e **billing** (assinar, trocar plano, portal) | Perguntas ao LLM (têm custo) — `[A CONFIRMAR: liberar 5 perguntas/mês de cortesia?]` |
| Exportar dados | Convidar/aceitar convites, criar Spaces/automações/chaves |
| Remover membros (para reduzir) | Sync agendado (pausa com `status='paused_plan'`) e jobs de automação |

- **Nada é apagado.** Retenção pós-expiração: manter dados por no mínimo **90 dias** `[A CONFIRMAR]`, com e-mails avisando antes de qualquer limpeza (a limpeza em si é decisão futura, fora do escopo).
- Reativação: ao assinar (Checkout) ou receber um comp, `read_only` cai na próxima requisição; syncs pausados voltam.

### 4.4 Anti-abuso do trial
1 trial por `created_by_user_id` e por tipo; limites menores que o plano de entrada; sem API/MCP no trial pessoal; rate limit na criação de org. Sinal a monitorar: orgs `expired` com mesmo usuário/domínio recorrente.

---

## 5. Cobrança via Stripe

Moeda **BRL** (todos os Prices em `brl`, valores em centavos: R$ 299,00 ⇒ `unit_amount=29900`). Conta Stripe do Brasil.

### 5.1 Catálogo no Stripe (Products/Prices)
Um script idempotente `backend/scripts/stripe_sync_catalog.py` cria/atualiza o catálogo a partir de `entitlements/catalog.py` (fonte única), em **test mode** primeiro.

| Product | Prices (BRL) | `lookup_key` |
|---|---|---|
| Arquivio Pessoal Básico | mensal R$ 39 · anual R$ 390 | `personal_basic_monthly` · `personal_basic_yearly` |
| Arquivio Pessoal Pro | mensal R$ 99 · anual R$ 990 | `personal_pro_monthly` · `personal_pro_yearly` |
| Arquivio Empresa Team | graduated: 1ª faixa `up_to=5` `flat_amount=29900`; depois `unit_amount=4900` (`up_to='inf'`; teto de 15 imposto pelo app) · anual ×10 | `business_team_monthly` · `business_team_yearly` |
| Arquivio Empresa Scale | graduated: `up_to=20` `flat_amount=89900`; depois `unit_amount=3900` · anual ×10 | `business_scale_monthly` · `business_scale_yearly` |

- **`metadata.plan_key` e `metadata.account_type` em Product e em cada Price** (e `included_seats` nos de empresa).
- **Derivação do plano**: usar `price.metadata.plan_key` (fallback `product.metadata.plan_key`), **não** o `lookup_key`. Motivo: ao mudar preço de lista cria-se um Price novo e se **transfere o `lookup_key`** (`transfer_lookup_key=true`); assinaturas antigas continuam no Price antigo (grandfathering) já **sem** lookup_key. O `lookup_key` serve para o app descobrir "qual Price vendo agora" (`prices.list(lookup_keys=[…])`).
- Mapa `price→plan_key` também em `catalog.py` para teste. Price desconhecido ⇒ log + alerta, **mantém o plano anterior** (nunca rebaixa em silêncio).
- Validar em modo teste que Checkout aceita Price escalonado com `quantity` definida pelo app. *Fallback:* 2 itens (base `quantity=1` + "assento extra" `quantity=n`, adicionado só quando n>0).
- Impostos/NFS-e: Stripe BR **não emite nota fiscal brasileira**; definir com o contador a emissão (integração externa ou manual) `[A CONFIRMAR]`. Para empresa, ativar `tax_id_collection` (CNPJ).

### 5.2 Checkout Session
`POST /organizations/{id}/billing/checkout` — **OWNER**, org com `account_type` coerente com o plano.
Body: `{ "plan_key": "business_team", "interval": "month", "seats": 8, "promotion_code": "LANCAMENTO20"? }`.

Cria (lazy, com idempotency key `org-{id}-customer`) o Customer (`email` do owner, `name` da org, `metadata.organization_id`, `preferred_locales=['pt-BR']`) e a Session:
- `mode='subscription'`, `line_items=[{price: <resolvido por lookup_key>, quantity: seats|1}]`
- `client_reference_id=organization_id`; `metadata.organization_id`; **`subscription_data.metadata.organization_id`** (para os eventos da subscription acharem a org)
- `locale='pt-BR'`, `payment_method_types=['card']` no lançamento (boleto/PIX: §5.9)
- **Cupom** (§6.1): `allow_promotion_codes=true` (campo "Código promocional" na página hospedada) **ou** `discounts=[{promotion_code: …}]` quando o código veio do nosso campo/URL — **não combinar os dois** (restrição do Stripe)
- `success_url=/app/billing?session_id={CHECKOUT_SESSION_ID}`, `cancel_url=/app/billing`
- Empresa: `tax_id_collection.enabled=true`, `billing_address_collection='required'`
- **A página de sucesso não concede acesso**; ela só consulta `GET …/billing` (poll curto) enquanto o webhook processa. Acesso só muda via sincronização (§5.5).

### 5.3 Customer Portal
`POST /organizations/{id}/billing/portal` — OWNER — devolve a URL da `billing_portal.Session` (`return_url` = billing).
Configuração do portal: **atualizar forma de pagamento, ver/baixar faturas, cancelar ao fim do período**. **Trocar plano e quantidade ficam no app**, não no portal, porque precisamos validar (downgrade com membros, assentos ≥ membros ativos, cooldown) antes de mexer na assinatura. Para cartões com 3DS no upgrade, usar `flow_data.type='subscription_update_confirm'` do portal como fallback.

### 5.4 Tabela local `subscriptions` e `stripe_customer_id`
`organizations.stripe_customer_id` (unique) + tabela `subscriptions` (uma linha por subscription Stripe; normalmente 1 ativa por org — índice parcial único `WHERE status IN ('active','trialing','past_due','unpaid','paused','incomplete')`):

`id`, `organization_id` (FK), `stripe_subscription_id` (unique), `stripe_customer_id`, `status`, `stripe_price_id`, `plan_key`, `interval`, `seats`, `current_period_end`, `cancel_at_period_end`, `past_due_since`, `discount_summary` (JSON enxuto p/ exibir), `last_synced_at`, `stripe_event_created` (ordenação).

### 5.5 Webhook
`POST /webhooks/stripe` — **público** (fora do `authenticated` de `main.py:188`; isentar de qualquer checagem de origem/CSRF, cf. contrato de origem do commit `12baf465` — verificar na implementação). Passos:
1. Ler o **corpo bruto** e validar `Stripe-Signature` (`stripe.Webhook.construct_event`, `STRIPE_WEBHOOK_SECRET`, tolerância padrão). Falha ⇒ 400.
2. `INSERT INTO stripe_webhook_events (id=evt_…)` — conflito ⇒ já processado ⇒ 200 (idempotência).
3. **Re-buscar o objeto atual no Stripe** (`subscriptions.retrieve(id, expand=['items.data.price','discounts'])`) em vez de confiar no payload — resolve eventos fora de ordem/duplicados. Rodar `sync_subscription(sub_id)`.
4. `recompute_entitlement(org)` (atualiza a projeção `plan_key`/`entitlement_source`), commit, marcar `processed_at`, responder 200 rápido. Erro ⇒ 5xx (Stripe repete por até 3 dias) e grava `error`.

| Evento | Ação |
|---|---|
| `checkout.session.completed` | Achar org por `client_reference_id`; gravar `stripe_customer_id` se ausente; se `payment_status='paid'` → `sync_subscription(session.subscription)`; **limpa `legacy`/trial** (primeira assinatura). Pagamento assíncrono (boleto/PIX): aguarda os dois abaixo. |
| `checkout.session.async_payment_succeeded` / `…_failed` | Sincroniza / notifica falha (métodos assíncronos). |
| `customer.subscription.created` / `updated` | `sync_subscription`: status, price→`plan_key`, `quantity`→`seats`, `current_period_end`, `cancel_at_period_end`, desconto. Se o plano mudou de pessoal→empresa, ajusta `account_type`. |
| `customer.subscription.deleted` | Marca `canceled`; sem outra fonte ⇒ `expired` (somente leitura). |
| `invoice.paid` (e `invoice.payment_succeeded`) | Limpa `past_due_since`; registra último pagamento. |
| `invoice.payment_failed` | Define `past_due_since` (se nulo); e-mail/aviso na UI. |
| `invoice.payment_action_required` | Aviso "confirme o pagamento" (3DS/boleto) com link da fatura hospedada. |
| `customer.subscription.trial_will_end` | **Não usado** (trial é local). |
| `charge.dispute.created` | Alerta interno para staff. |

### 5.6 Derivação do `plan_key` e `quantity` (assentos)
`sync_subscription` faz: `plan_key = price.metadata.plan_key`; `seats = item.quantity`; grava em `subscriptions`; o resolver usa `subscriptions` (não o payload cru). Regras:
- `max_members = clamp(seats, included_seats, plan.max_seats)`.
- **Adicionar assentos**: `POST …/billing/seats {seats}` → `subscription_items.update(quantity)` com `proration_behavior='always_invoice'` (cobra a diferença na hora) e `idempotency_key`; `seats` local atualiza por webhook (e otimisticamente).
- **Remover assentos**: só se `seats_novo ≥ membros ativos + convites pendentes`; `proration_behavior='create_prorations'` (crédito na próxima fatura).
- Quantity alterada fora do app (dashboard Stripe) abaixo do nº de membros ⇒ **não remove ninguém**; bloqueia novos convites/aceites e mostra "assentos acima do contratado" ao owner.

### 5.7 Upgrade pessoal→empresa na mesma subscription
Em `EntitlementService.upgrade_to_business(...)` (transação com `FOR UPDATE` na org):
1. Validar: owner; `account_type='personal'`; nome da empresa; plano de destino de empresa; assentos ≥ 1.
2. Se **tem subscription ativa** (Stripe): `subscriptions.update(sub_id, items=[{id: item_id, price: <price business>, quantity: seats}], proration_behavior='always_invoice', payment_behavior='error_if_incomplete', idempotency_key=…)` — o crédito do tempo não usado do plano pessoal é abatido na cobrança do novo plano. Falha de pagamento/3DS ⇒ nada muda (cai no fluxo `subscription_update_confirm` do portal).
3. Em sucesso, na **mesma transação**: `account_type='business'`, `name`, `account_type_changed_at`, linha `subscriptions`, `AuditLog organization.upgraded`. O webhook depois só confirma (idempotente). `customers.modify(name=…)` mantém o nome da empresa na fatura.
4. Se **em trial** (sem subscription): só muda tipo/nome localmente (`personal_trial`→`business_trial`, dias restantes preservados); a primeira assinatura entra pelo Checkout.
5. Se **expirado**: Checkout normal do plano de empresa.
6. O `organization_id` não muda; documentos, spaces, grants, integrações e chaves permanecem.

Downgrade empresa→pessoal (§7.3) é a troca inversa de price, com crédito proporcional (`create_prorations`), bloqueado se houver membros.

### 5.8 Trial vs. assinatura, dunning e inadimplência
- **Trial local** (§4): nenhum objeto Stripe até o Checkout.
- **Dunning**: ativar **Smart Retries** e e-mails de falha de pagamento do Stripe; configurar "após esgotar tentativas ⇒ marcar a assinatura como `unpaid`" (mantém a subscription recuperável via fatura hospedada/portal), `[A CONFIRMAR]` ajustar o calendário de retentativas.
- **Estados → acesso** (aplicado pelo resolver em tempo de leitura):

| `subscriptions.status` | Acesso |
|---|---|
| `active` / `trialing` | pleno |
| `past_due` | **pleno durante a carência** (`past_due_since + 7 dias` `[A CONFIRMAR]`) com faixa "atualize o pagamento"; depois ⇒ **somente leitura** |
| `unpaid` / `paused` | somente leitura |
| `canceled` / `incomplete_expired` | cai para a próxima fonte (trial válido? senão `expired`) |
| `incomplete` | não concede (primeiro pagamento ainda não confirmado) |
| `cancel_at_period_end=true` | pleno até `current_period_end`; depois chega `subscription.deleted` ⇒ `expired` |

- A carência é calculada comparando `now` com `past_due_since` na leitura — **não depende de cron**. Um job diário (`notifications/`) apenas envia os avisos.

### 5.9 Métodos de pagamento e configuração
- **Cartão** no lançamento. **Boleto e PIX** são opção no Stripe Brasil: dependem de elegibilidade da conta e de o método suportar **cobrança recorrente** na versão da API usada; planos anuais combinam melhor com boleto/PIX. Validar com o Stripe antes de prometer na LP `[A CONFIRMAR]`. Métodos assíncronos exigem tratar `checkout.session.async_payment_*` (já previsto).
- Novas variáveis em `Settings` (`core/config.py`): `stripe_secret_key: SecretStr`, `stripe_webhook_secret: SecretStr`, `stripe_api_version` (pinada), `billing_enabled: bool`, `trial_days=14`, `past_due_grace_days=7`. Com `billing_enabled=false` (dev/CI) o app roda sem Stripe.
- Dependência nova: pacote `stripe` (versão fixa) em `backend/pyproject.toml`.

### 5.10 Endpoints de billing (resumo)
| Rota | Quem | Função |
|---|---|---|
| `GET /organizations/{id}/billing` | membros (owner vê tudo) | plano, fonte, status, assentos, `trial_ends_at`, próxima cobrança, desconto |
| `POST …/billing/checkout` | owner | cria Checkout Session |
| `POST …/billing/portal` | owner | cria Portal Session |
| `POST …/billing/change-plan` | owner | troca de price (upgrade/downgrade) com **prévia de proration** (`invoices.create_preview`) |
| `POST …/billing/seats` | owner | altera `quantity` |
| `GET …/billing/promotion-codes/validate?code=` | owner | valida cupom e mostra o desconto antes do Checkout |
| `POST /webhooks/stripe` | Stripe | §5.5 |

---

## 6. Cupons e contas especiais

### 6.1 (a) Descontos normais: cupons Stripe
- **Coupon** (regra do desconto): `percent_off` **ou** `amount_off` (BRL, em centavos), `duration` = `once` | `repeating` (+`duration_in_months`) | `forever`, `max_redemptions`, `redeem_by`, `applies_to.products` (limitar a planos).
- **Promotion Code** (o código que o cliente digita, ex. `LANCAMENTO20`): ligado a um Coupon; `max_redemptions`, `expires_at`, `first_time_transaction`, `minimum_amount`, restrição a um customer. Gerenciar tudo no **Dashboard do Stripe** — nenhum código nosso para criar cupom.
- **Onde o cliente usa**: (1) campo na página do Checkout (`allow_promotion_codes=true`); (2) campo **"Tem um cupom?"** na nossa tela de assinatura/LP — valida via `promotion_codes.list(code=…, active=true)`, mostra o desconto e passa `discounts=[{promotion_code: id}]` no Checkout; (3) link `…?cupom=CODIGO` guardado em cookie curto (mesmo padrão do `plano=`).
- O app **mostra** o desconto vigente (`subscriptions.discount_summary`) mas não o calcula.
- **Cupom 100%** não é o instrumento para "conta de graça": a subscription continua existindo no Stripe, pode expirar e gera ruído. Use **comp** (abaixo).

### 6.2 (b) "Comp"/cortesia: override local, sem cobrança
Tabela `organization_comps` (molde: `StaffAccessGrant`, `organizations/models.py:77-93`):

| Campo | Regra |
|---|---|
| `organization_id` | FK; **no máximo 1 comp ativo por org** (índice único parcial `WHERE revoked_at IS NULL`); conceder um novo revoga o anterior na mesma transação |
| `plan_key` | qualquer chave vendável do catálogo (`business_team`, `personal_pro`…) cujo `account_type` bata com o da org |
| `limits_override` | JSON validado por schema (`extra='forbid'`, só campos de `Entitlements`; ilimitado = valor explícito `"unlimited"`) — cobre também "cliente pagante com limites negociados" |
| `expires_at` | **obrigatório por padrão**; permanente só com flag explícita (`--no-expiry`) + motivo — evita cortesia esquecida |
| `reason` | obrigatório, ≤240 (mesmo limite de `staff_access.py:108`) |
| `granted_by_user_id` | FK users `RESTRICT` |
| `revoked_at`, `revoked_by_user_id` | revogação manual |
| `created_at` | |

- **Auditoria**: cada concessão/revogação grava `AuditLog` (`comp.granted`, `comp.revoked`, `comp.extended`; `target_type='organization_comp'`, `target_id=comp.id`; ator = staff) — o **detalhe** (plano, overrides, motivo) fica na própria linha do comp, já que `audit_logs` não tem payload (`audit_usage/models.py:21-32`). Expiração por tempo não tem ator (`actor_user_id` NOT NULL) ⇒ registra em log de aplicação/job, não em `AuditLog`.
- **Ignora o Stripe**: o comp decide o acesso mesmo que exista assinatura. **Aviso:** conceder comp a uma org com assinatura ativa **não cancela a cobrança** — a ferramenta mostra o alerta "org tem assinatura ativa" e oferece, em ação separada e explícita, cancelar/reembolsar pelo Stripe.
- Extensão de trial = comp com `plan_key='business_trial'`/`'personal_trial'` e `expires_at` novo (sem mecanismo extra).

### 6.3 Precedência (resolver)
```
resolve_entitlement(org, now):
  1. comp ativo      (revoked_at IS NULL e (expires_at IS NULL ou > now))   -> source=comp,         plan=comp.plan_key ⊕ limits_override
  2. assinatura Stripe com acesso (active/trialing; past_due dentro da carência;
                     cancel_at_period_end até current_period_end)           -> source=subscription, plan=sub.plan_key, seats=sub.seats
  3. trial local     (trial_ends_at > now)                                  -> source=trial,        plan=<tipo>_trial
  4. legacy          (org.entitlement_source == 'legacy'; limpo na 1ª assinatura) -> source=legacy, plan=legacy
  5. caso contrário                                                          -> source=expired,      read_only=true
```
**comp > assinatura Stripe > trial > expirado** (o `legacy` fica entre trial e expirado e é encerrado quando a org faz a primeira assinatura voluntária). Cada passo é uma consulta indexada por `organization_id`; o resultado é cacheado só durante o request.

### 6.4 Como o admin do sistema gerencia
Reaproveita o **`PlatformStaff`** (§1.5): quem administra é um usuário global, **fora de qualquer tenant**.
- **Autorização**: `is_platform_staff` ativo **e** `platform_staff.role='admin'` (coluna nova; `support` continua só-leitura como hoje). Rotas novas no router existente `api/platform.py:15` (já montado em `main.py:188`):
  - `GET /platform/organizations/{id}/entitlement` — fonte vencedora, plano, comp, assinatura, trial, uso.
  - `POST /platform/organizations/{id}/comps` `{plan_key, limits_override?, expires_at, reason}`.
  - `DELETE /platform/organizations/{id}/comps/{comp_id}` — revogar.
  - `GET /platform/comps?expiring_within=30` — comps a vencer/permanentes.
- **Tela**: estender a tela `/staff` já existente (`frontend/app/product/team-staff.tsx:47+`; hoje lista empresas e metadados): ao abrir uma empresa, aba "Plano e cortesia" com formulário (plano, validade, motivo, overrides em campos validados) e histórico. Menu "Suporte" já existe (`account-menu.tsx:66`).
- **CLI** (primeiro, mais barato): `backend/scripts/platform_admin.py` com `grant-staff --email …` (**hoje não existe forma de criar `PlatformStaff` fora de testes**), `comp grant|revoke|list`. Camada fina sobre o mesmo `CompService`, que é quem valida e audita.
- **Segurança**: não há `ADMIN_TOKEN`/chave global; tudo passa por sessão de usuário + `PlatformStaff`. Operações de comp sempre exigem `reason`.

---

## 7. Fluxos de upgrade e downgrade

### 7.1 O que muda nos dados no upgrade pessoal→empresa
Mesma org, mesmo `organization_id`. **Nada é copiado.**

| Item | Antes (pessoal) | Depois (empresa) |
|---|---|---|
| `account_type` | `personal` | `business` |
| `plan_key` | `personal_basic`/`personal_pro`/`personal_trial` | `business_team` (ou `business_scale`) / `business_trial` |
| `name` | nome da pessoa | nome da empresa (obrigatório) |
| Dono | OWNER | continua OWNER |
| Documentos, DataSources, chunks, conversas, usage_records | | **preservados** |
| Space "Geral" | default, 1 membro | continua default; passa a receber novos membros |
| API keys / MCP / automações | | preservadas; seguem os limites do novo plano |
| Assinatura Stripe | price pessoal | **mesma subscription**, price de empresa (§5.7) |
| Auditoria | | `AuditLog organization.upgraded` |

### 7.2 Endpoint
`POST /organizations/{id}/upgrade` `{ "name": "Acme Ltda", "plan_key": "business_team", "seats": 5, "interval": "month" }` — só OWNER; idempotente; implementação em §5.7. Efeito imediato na próxima requisição.

### 7.3 Downgrade empresa→pessoal
Permitido apenas quando **todas** valem (checklist na UI): (1) 0 membros ativos além do owner; (2) 0 convites pendentes; (3) cooldown ≥ 30 dias desde `account_type_changed_at` `[A CONFIRMAR]`.
- Com assinatura: troca de price + crédito proporcional; sem assinatura: só muda o tipo (o trial restante é preservado).
- **Excedentes** (documentos, fontes, automações, Spaces acima do teto pessoal): **nunca deletar**. Leitura/busca/perguntas continuam (até o teto de perguntas); **novas** criações bloqueadas (402 `over_quota`); automações acima do teto **pausadas** (`plan_downgrade`); fontes acima do teto/provedor não permitido **pausam o sync** (`paused_plan`); Spaces extras só arquivados pelo dono. UI com "pré-visualização de impacto" (padrão de `members/{id}/impact`, `api/spaces.py:234`).
- Downgrade com membros: **bloqueado** ("remova N membros antes"); nunca remover membros automaticamente.
- Business Scale→Team segue a mesma política; excedente de assentos bloqueia novos convites/aceites e mantém os existentes até o dono desativar.

---

## 8. Signup e convites

### 8.1 Escolha do tipo (uma pergunta, default pessoal)
Hoje: Login/Registro → `/login` → `Onboarding` "Crie sua primeira organização" (`auth-screens.tsx:20-21`) → `POST /organizations`.

Novo (só tela de criação + payload):
1. Auth permanece igual (o redirect final a `/login` não muda — `auth.py:186-189, 353-354`).
2. Tela "Como você vai usar o Arquivio?" com 2 cartões, ambos informando **"Teste grátis por 14 dias, sem cartão"**:
   - **Para mim** (pré-selecionado) → `account_type='personal'`, nome sugerido `Espaço de {primeiro nome}`.
   - **Para minha empresa** → `account_type='business'`, pede nome da empresa.
3. `POST /organizations` ganha `account_type` e passa a **iniciar o trial** (`trial_ends_at = now + trial_days`, `plan_key='<tipo>_trial'`, `entitlement_source='trial'`).
4. LP/CTAs pré-selecionam via `?plano=pessoal|empresa` em cookie curto (padrão `auth.py:337-343`), sem mexer no OAuth state. Também aceita `?cupom=CODIGO` (§6.1).
5. Convidado por e-mail **não** cria org nem consome trial: `accept_invitation` entra direto na org da empresa.

### 8.2 Usuário com org pessoal + membro de empresa
Já suportado (`organizations_for_user`, `service.py:110`; picker em `product-app.tsx:114`). Mudanças: badge/agrupamento no picker; última org usada primeiro (`product/active-organization.ts`), priorizando empresa se veio de convite; **separação estrita de dados** (já garantida por `OrganizationScope`) comunicada na UI; e-mail de convite explica "Sua conta pessoal não muda" (`organizations/delivery.py`). Convidado consome **assento da empresa**, nunca os limites da conta pessoal dele.

### 8.3 Convites (regras novas)
- `create_invitation`: `personal` ⇒ `EntitlementError('personal_no_members', upgrade_to='business_team')`; `business` ⇒ `membros ativos + convites pendentes ≥ max_members` ⇒ `seat_limit` (com `upgrade_to` = comprar assento ou `business_scale`); `read_only` ⇒ `read_only`.
- `accept_invitation`: reconferir assentos e se a org ainda é business/gravável.
- Convidar e-mail que já tem conta pessoal: permitido.
- UI para pessoal: "Contas pessoais são de uma pessoa só. Transforme em conta de empresa para convidar sua equipe." + botão.

---

## 9. Landing Page

Estratégia e copy completas: **`docs/lp-pessoal-empresa.md`** (atualizado nesta revisão). Pontos que dependem deste documento:
- **Sem "Começar grátis" permanente**: CTAs viram **"Testar grátis por 14 dias"**; nota "sem cartão" só se a decisão de §4.1 for confirmada.
- Tabela de preços com **4 planos vendidos** (Pessoal Básico, Pessoal Pro, Empresa Team, Empresa Scale) + faixa de assento extra + Enterprise "sob consulta".
- **Campo/link de cupom** na assinatura (`?cupom=`) e "Tem um cupom?" no Checkout/tela de billing.
- `?plano=` e `?cupom=` repassados ao login e lidos na criação da org.

---

## 10. Contas existentes: ficam como estão (`legacy`)

**Decisão do dono: nenhuma migração forçada para planos.**

- Toda org existente recebe `plan_key='legacy'`, `entitlement_source='legacy'`, `account_type='business'` (só porque é o comportamento de hoje: pode ter membros). **Sem classificação heurística** pessoal×empresa e **sem backfill de `created_by_user_id`** — a migração de dados da revisão 1 foi **removida**.
- Catálogo `legacy` = exatamente os valores globais atuais de `Settings` (`config.py:49-53, 139-148`), `max_automations=20`, sem teto de assentos, sem `read_only`, sem trial, sem Stripe.
- UI: sem badge, sem faixas de trial/assinatura. A página de billing mostra "Conta atual (plano legado)" e oferece **assinar um plano voluntariamente** (Checkout) — ao concluir a primeira assinatura, o `legacy` é encerrado (`entitlement_source` passa a `subscription`) e a org segue os limites do plano escolhido. Se a org tiver >1 membro, só planos de empresa são oferecidos.
- Staff pode tratar casos específicos por **comp** (§6) sem tocar no `legacy`.
- **Migração Alembic** `20261022_0041_account_types.py` (down_revision `20261021_0040`): apenas `ADD COLUMN` (`account_type` default `'business'`, `plan_key` default `'legacy'`, `entitlement_source` default `'legacy'`, `trial_*`, `stripe_customer_id`, `account_type_changed_at`, `created_by_user_id`, `platform_staff.role`) + `CHECK` de `account_type`; **nenhum `UPDATE` de dados**. Padrão de arquivo: `alembic/versions/20261021_0040_space_node_grants.py`. Migrações seguintes: `0042_organization_comps` (F3) e `0043_billing_subscriptions` (F6).
- **Cuidado com os defaults**: `server_default='legacy'` cobre orgs criadas por código antigo durante o deploy; depois do deploy o código sempre passa `plan_key` explícito (trial) e os defaults são removidos numa migração seguinte — senão uma org nova mal criada herdaria `legacy` (generoso) para sempre. Teste: criar org pelo endpoint nunca resulta em `legacy`.
- Testes existentes (`seed_tenant` em `tests/access_helpers.py:28`, `seed_world` em `tests/spaces_helpers.py:45`): as orgs de fixture ficam `legacy` ⇒ **suítes atuais continuam verdes sem alteração**; novas suítes criam orgs com plano explícito.
- DB local é resetável; a migração precisa existir para staging/prod. Arquivos " 2" duplicados e gitignored quebram alembic/tsc localmente — validar em espelho limpo.

Dados que **não** mudam: documents, chunks, library_nodes, data_sources, spaces, space_*grants, usage_records, api_keys, automations, memberships.

---

## 11. Plano de implementação em fases

> Cada fase é entregável e testável sozinha. Sem estimativa de prazo (decisão do dono).

### Fase 1 — Modelo + catálogo + resolver (sem mudar comportamento)
- `backend/alembic/versions/20261022_0041_account_types.py` (§10, só `ADD COLUMN`).
- `organizations/models.py` — colunas novas (`:17-24`) e constantes de tipo.
- `backend/app/entitlements/{__init__,catalog,resolver,service,errors}.py` — catálogo com os 4 planos + `*_trial` + `expired` + `legacy`; resolver com a precedência de §6.3 (comp/subscription ainda inexistentes ⇒ ramos vazios).
- `audit_usage/service.py:23-31,67-109` — ler limites do `Entitlements` (todas as orgs `legacy` ⇒ números atuais).
- `api/auth.py:413-416` — `GET /organizations` devolve `account_type`, `plan_key`, `entitlement_source`, `entitlements`.
- `frontend/app/product/types-and-api*` — tipo `Company`.
- Testes: `tests/unit/test_entitlements.py` (catálogo, merge de overrides, **legacy == Settings**, precedência por tabela), teste de migração (upgrade/downgrade, colunas, nenhum UPDATE).
- Risco: quebrar `usage_summary` e jobs que tratam `UsageLimitExceeded` ⇒ manter assinatura compatível; `test_semantic_questions`, `test_ingestion_service`, `test_automations_api` verdes.

### Fase 2 — Tipo de conta, trial local, assentos e somente leitura
- `organizations/service.py` — `create_organization` (`:43`) grava `account_type`, `created_by_user_id`, **inicia o trial** e aplica "1 org pessoal / 1 trial por criador"; guards em `create_invitation` (`:168`), `accept_invitation` (`:222`), `add_membership` (`:81`).
- `api/auth.py:82-85,401-410` — `OrganizationCreateInput.account_type`; handler global `EntitlementError`→402/403 (`app/main.py`).
- Estado `expired`/`read_only` + `require_writable` nos caminhos de escrita; jobs pausam em vez de falhar.
- `POST /organizations/{id}/upgrade` e `…/downgrade` (sem Stripe ainda: só trial/legacy).
- Job de lembretes de trial (D-3/D-1/D0).
- Testes (`tests/api/test_auth_and_invitations.py`, `tests/api/test_invitation_people_spaces_api.py`, novo `tests/api/test_account_types_api.py`): pessoal não convida; empresa respeita assentos (membros + pendentes); aceitar com org lotada falha; trial expira ⇒ 402 `read_only` e leitura segue; upgrade preserva `organization_id`/dados/role; upgrade por não-owner ⇒ 403; idempotente; downgrade com membros ⇒ 409; 1 org pessoal e 1 trial por usuário; **criar org pelo endpoint nunca gera `legacy`**; concorrência no último assento (`FOR UPDATE`).
- Risco: corrida de assentos; fixtures legadas seguem `legacy`.

### Fase 3 — Comps e administração de staff
- `0042_organization_comps` + `platform_staff.role`; `entitlements/comps.py` (`CompService.grant/revoke/list`, validação do `limits_override`, auditoria).
- Resolver passa a honrar o ramo comp.
- `api/platform.py` — rotas de §6.4; `backend/scripts/platform_admin.py` (CLI `grant-staff`, `comp …`).
- Frontend: aba "Plano e cortesia" na tela `/staff` (`team-staff.tsx`).
- Testes: extensão de `tests/api/test_platform_staff_api.py` — staff `support` não concede (403); `admin` concede; motivo obrigatório; expiração; revogação; um comp ativo por org; comp vence assinatura/trial; `AuditLog` gravado.

### Fase 4 — Limites por plano nos recursos
- `spaces/service.py:130`, `api/automations.py:45,286-292`, `api/access_admin.py:81`, `api/mcp_admin.py:67,81` + `mcp_server/*`, `integrations/*.py` e `google_drive_sa_service.py:135`, `ingestion/service.py:1020`, upload `max_file_bytes`, `access/ratelimit.py`.
- Pausa de recursos excedentes no downgrade (`plan_downgrade`, `paused_plan`).
- Testes: um por guard + regressão de que jobs/MCP/API pública respeitam o limite da org.

### Fase 5 — Frontend: signup, trial, gating e upgrade
- `auth-screens.tsx:20-21` — tela "Como você vai usar o Arquivio?" (dois cartões, "teste grátis por 14 dias") + `account_type`.
- `product-app.tsx:108-116` — ler `plano`/`cupom`; badges no picker (`org-picker.tsx`, `account-menu.tsx`).
- `team-staff.tsx` (aba Equipe) — modo pessoal; novo `upgrade-dialog.tsx`, `use-entitlements.ts`, faixas de trial/somente leitura; `usage-panel.tsx` com plano/CTA; tratamento global de 402 em `types-and-api`.
- Testes front (`frontend/tests/*.test.mjs`, padrão `lane2-chat-motion.test.mjs`): lógica pura (`shouldShowTeam`, `trialBannerFor`, `upgradeCopyFor`).

### Fase 6 — Stripe (primeiro em test mode)
- `0043_billing_subscriptions` (`subscriptions`, `stripe_webhook_events`); dependência `stripe`; `Settings` (§5.9).
- `scripts/stripe_sync_catalog.py` (Products/Prices/lookup_keys/metadata).
- `backend/app/billing/` — `checkout.py`, `portal.py`, `sync.py` (`sync_subscription`, `recompute_entitlement`), `webhook.py`; rotas §5.10 e `POST /webhooks/stripe`.
- Frontend: página de assinatura (`product/billing.tsx`): plano atual, assentos, trocar plano com prévia de proration, portal, campo de cupom.
- Testes: assinatura de webhook inválida ⇒ 400; evento duplicado ⇒ 200 sem reprocessar; eventos fora de ordem convergem (re-fetch); `invoice.payment_failed` ⇒ carência 7 dias ⇒ somente leitura depois; `subscription.deleted` ⇒ expired; `price→plan_key` por metadata (inclusive Price sem `lookup_key`); upgrade pessoal→empresa troca price e preserva org; remover assentos < membros bloqueado; comp vence assinatura. Stripe mockado (cliente injetável) + execução manual com Stripe CLI (`stripe listen`/`trigger`) em test mode.
- Risco: dupla fonte de verdade ⇒ regra "Stripe = pagamento; `subscriptions` local = acesso; só `sync_subscription` escreve nela".

### Fase 7 — Landing page e preços
- `frontend/app/landing-page.tsx` + `/empresas` conforme `docs/lp-pessoal-empresa.md`; CTAs "Testar grátis por 14 dias"; tabela de 4 planos; cupom; `?plano=`/`?cupom=` repassados.
- Publicar **depois** de fixar catálogo e preços (F1/F6).

### Fase 8 — Go-live
- Catálogo em live mode, webhook de produção, Customer Portal configurado, e-mails de dunning, NF-e definida, conta Stripe verificada; runbook de rollback (`billing_enabled=false` mantém tudo no que já foi sincronizado).

### ADR
Registrar `specs/adr/ADR-0022-tipos-de-conta-planos-e-entitlements.md` (tipo na org, catálogo único, precedência, política de excedentes, Stripe como verdade do pagamento, comp via PlatformStaff).

---

## 12. Matriz de riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Limites ainda lidos de `Settings` em algum caminho | Plano ignorado | Busca por `monthly_limit_`/`active_document_limit`/`MAX_AUTOMATIONS` no CI; teste por caminho (API, job, MCP) |
| Corrida de assentos | Org passa do limite | `SELECT … FOR UPDATE` na org dentro do guard |
| Webhook fora de ordem/duplicado | Plano errado | Tabela de eventos (idempotência) + **re-fetch** da subscription |
| Trocar preço de lista quebra derivação | Cliente antigo vira "plano desconhecido" | Derivar de `price.metadata.plan_key`, não de `lookup_key`; Price desconhecido mantém o plano anterior |
| Comp esquecido ou eterno | Receita perdida | `expires_at` obrigatório, listagem `expiring_within`, auditoria |
| Comp sobre org que ainda paga | Cobrança dupla/confusa | Alerta na ferramenta; cancelar/reembolsar é ação explícita e separada |
| Abuso de trial (várias orgs) | Custo de LLM/OCR | 1 trial por criador/tipo, e-mail verificado, limites menores no trial |
| Somente leitura bloqueia job em andamento | Erro silencioso | Pausar com `paused_plan` e motivo visível, nunca falhar mudo |
| Downgrade apaga/trunca dados | Perda de confiança | Nunca apagar; bloquear novos e pausar |
| Org nova herdar `legacy` por default de coluna | Limites ilimitados | Remover defaults pós-deploy + teste "endpoint nunca gera legacy" |
| Gating só no front | Bypass por API | Backend é a fonte; testes de API |
| Stripe BR não emite NFS-e | Compliance | Decidir emissão com contador antes do go-live |
| PIX/boleto recorrente indisponível | Promessa errada na LP | Validar com o Stripe antes de anunciar |
| SSO prometido sem entrega | Frustração | SSO só no Scale, depois da F6 `[A CONFIRMAR]` |

---

## 13. Decisões que dependem do dono

**Já decidido (revisão 2):** sem plano grátis permanente; trial com dias limitados; 2 planos pagos Pessoal + 2 Empresa; Stripe; contas atuais ficam como estão; cupons Stripe; comps locais sem cobrança.

**Ainda pendentes:**
1. **Empacotamento Empresa**: confirmar o modelo B (base + assentos incluídos + assento extra) ou preferir A/C (§3).
2. **Valores finais** em BRL de todos os planos e do assento extra, mensal e anual (calibrar com custo real por pergunta/página OCR) — §2.3.
3. **Trial**: 7 ou 14 dias; **sem cartão** (recomendado) ou com cartão; limites do trial; liberar perguntas de cortesia após expirar?
4. **Retenção** dos dados de contas expiradas (90 dias propostos) e se algum dia há limpeza.
5. **Carência de pagamento** (7 dias propostos) e calendário de retentativas do Stripe.
6. **Nota fiscal** (NFS-e): quem emite e como.
7. **Boleto/PIX**: oferecer no lançamento ou só cartão.
8. **Papéis do staff**: quem será `admin` (concede comps) e quem fica `support`; política de comps permanentes.
9. **Cooldown e regras de downgrade** (§7.3).
10. **SSO por org**: confirmar que entra só no Scale e quando.
11. **Contas `legacy`**: nunca migrar, ou convidar a assinar com benefício (ex.: cupom) em algum momento.
12. **Enterprise** "sob consulta": existe no lançamento? canal de contato de vendas.


---

## 14. Contrato de API do backend (implementado)

> Implementação em `backend/app/entitlements/`, `backend/app/billing/`, `backend/app/api/billing.py`; decisão em `specs/adr/ADR-0022-tipos-de-conta-planos-e-entitlements.md`. **O pagamento é agnóstico de provedor e nenhum provedor está integrado** (`billing_provider="none"`): checkout/portal/troca de plano/cancelamento respondem `501 billing_not_configured`. Onde o §5 fala em Stripe, leia "provedor". Rotas reais **sem prefixo `/auth`** para `/me` e `/organizations` (o doc antigo dizia `/auth/me`).

### 14.1 Bloco de plano (em `GET /organizations`, `POST /organizations`, `GET /me → organizations[]`, upgrade/downgrade, billing)

```json
{
  "account_type": "personal | business",
  "plan_key": "personal_trial | personal_basic | personal_pro | business_trial | business_team | business_scale | legacy | expired",
  "entitlement_source": "comp | subscription | trial | legacy | expired",
  "trial_ends_at": "2026-11-06T12:00:00+00:00 | null",
  "read_only": false,
  "entitlements": {
    "can_have_members": true, "max_members": 5, "max_spaces": 5, "max_automations": 20, "max_api_keys": 3,
    "max_data_sources": 3, "mcp_enabled": true, "public_api_enabled": true, "webhooks_enabled": true,
    "audit_panel_enabled": true, "sso_enabled": false, "allowed_providers": null
  }
}
```
`null` em limite = ilimitado; `allowed_providers: null` = todos. Os campos são **resolvidos na hora da leitura** (trial/comp/carência vencem sozinhos). `GET /organizations` retorna `[{id, name, membership_id, role} + bloco]`; `GET /me` ganha `organizations: [{id, name, role} + bloco]`.

### 14.2 Rotas

| Método e rota | Quem | Corpo → resposta |
|---|---|---|
| `GET /plans` | público (sem login) | `{currency:"BRL", trial_days:14, trial_requires_card:false, billing_configured:bool, plans:[{plan_key, account_type, title, price_month_cents, price_year_cents, currency, included_seats, max_seats, extra_seat_month_cents, extra_seat_year_cents, can_have_members, limits:{…}, features:{mcp, public_api, webhooks, audit_panel, sso, providers}}]}` — 4 planos vendidos, valores em **centavos** |
| `POST /organizations` | logado | `{name, account_type?: "personal"(padrão)|"business"}` → `201 {id, membership_id, role}` + bloco de plano (inicia trial de 14 dias do tipo). `403 personal_org_limit` se já tem org pessoal. Segunda org do mesmo tipo (empresa) nasce `expired`/`read_only` (trial já usado) |
| `POST /organizations/{id}/upgrade` | owner | `{name, plan_key?:"business_team"|"business_scale", seats?:1..100, interval?:"month"|"year"}` → `200 {id, name}` + bloco. In-place, idempotente (já empresa ⇒ 200 sem mudar). Trial preservado. Com assinatura ativa chama `provider.change_plan`. `422 invalid_plan/invalid_seats`, `409 comp_type_mismatch` |
| `POST /organizations/{id}/downgrade` | owner | `{plan_key?:"personal_basic"|"personal_pro"}` → `200 {id,name,paused_automations}` + bloco. `409 downgrade_blocked` com `blockers: ["members","pending_invitations","cooldown"]` |
| `GET /organizations/{id}/billing` | membro | bloco + `{billing_configured, provider, legacy, seats_used, comp_expires_at, grace_ends_at, subscription:{status, plan_key, interval, seats, current_period_end, cancel_at_period_end, coupon_code, discount_summary}|null, account_type_changed_at}` |
| `POST …/billing/checkout` | owner | `{plan_key, interval?, seats?, promotion_code?}` → `{url}` (redirecionar). `501 billing_not_configured`; `422 invalid_plan/invalid_seats`; `409 seats_below_members` |
| `POST …/billing/portal` | owner | `{}` → `{url}`; `501` sem provedor |
| `POST …/billing/change-plan` | owner | `{plan_key, interval?, seats?}` → bloco; `409 subscription_required/invalid_seats`; `501` |
| `POST …/billing/cancel` | owner | `{}` → bloco (cancela ao fim do período); `501` |
| `POST /webhooks/billing/{provider}` | provedor (público, assinatura verificada pelo adaptador) | corpo bruto → `{status:"processed"|"duplicate"|"ignored"}`; `400` assinatura/payload inválido; `501 billing_not_configured` |
| `GET /platform/organizations/{id}/entitlement` | PlatformStaff ativo (**admin** ou **support**, somente leitura) | bloco + `{name, staff_role:"admin"|"support", effective:{…todos os limites}, projection, trial_started_at, subscription, comps:[…]}` |
| `POST /platform/organizations/{id}/comps` | admin | `{plan_key, reason(≤240), expires_at?|permanent:true, limits_override?}` → `201 comp + warning:"active_subscription"|null`. `422` (motivo vazio, sem `expires_at` nem `permanent`, plano de outro tipo, override inválido). Revoga a comp anterior |
| `PATCH /platform/organizations/{id}/comps/{comp_id}` | admin | `{expires_at}` → comp |
| `DELETE /platform/organizations/{id}/comps/{comp_id}` | admin | `204`; `404` |
| `GET /platform/comps?expiring_within=<dias>` | PlatformStaff ativo (admin ou support, somente leitura) | comps vivas (permanentes sempre; datadas dentro da janela) |

`support` (PlatformStaff sem `admin`) **lê** plano/fonte/trial/assentos/cortesias (`GET …/entitlement` e `GET /platform/comps`), mas recebe `403 not allowed` em `POST/PATCH/DELETE` de comps (só `admin`); quem não é staff recebe `403` em todas. CLI: `python scripts/platform_admin.py grant-staff --email <e-mail> [--role admin]`, `comp grant|revoke|list`.

### 14.3 Erros de plano (todos com o mesmo corpo)

`{ "detail": "<mensagem>", "code": "<code>", "limit": <int|null>, "used": <int|null>, "upgrade_to": "<plan_key>|null" }`

| `code` | HTTP | Quando |
|---|---|---|
| `personal_no_members` | 403 | convidar/aceitar/adicionar membro em conta pessoal (`upgrade_to:"business_team"`) |
| `personal_org_limit` | 403 | segunda org pessoal do mesmo dono |
| `seat_limit` | 402 | membros ativos (+ pendentes no convite) ≥ `max_members` (`upgrade_to:"business_scale"` no Team/trial) |
| `trial_expired` | 402 | escrita com trial vencido (`read_only`) |
| `read_only` | 402 | assinatura sem pagamento após carência (7 dias), `unpaid`/`paused`, ou qualquer escrita/uso em org somente leitura (inclui perguntas/OCR/embeddings no `UsageService`) |
| `space_limit`, `automation_limit` (`detail:"automation_limit_reached"`), `api_key_limit`, `data_source_limit`, `active_document_limit` | 402 | teto do plano atingido (`active_document_limit` vem como `UsageLimitExceeded`) |
| `feature_unavailable` | 402 | API pública / MCP fora do plano |
| `provider_unavailable` | 402 | conector não permitido no plano (ex.: OneDrive no Pessoal Básico) |
| `usage_limit` | **429** | pool mensal (documentos processados, tokens, perguntas, OCR) esgotado — `detail:"organization usage limit reached"`, agora também com `limit/used/upgrade_to` |
| `billing_not_configured` | 501 | qualquer rota de pagamento sem provedor |
| `downgrade_blocked` | 409 | + `blockers[]` |
| `invalid_plan`, `invalid_seats` | 422/409 | plano do tipo errado / assentos fora do intervalo ou abaixo dos membros |

**Orgs `legacy`** continuam com o contrato antigo: sem erros novos (exceto `409 automation_limit_reached`, inalterado), `max_*` = `null`. O frontend deve tratar `402`/`403` com `code` por um único diálogo de upgrade e usar `read_only` para a faixa "somente leitura". Callbacks OAuth de conectores podem devolver `402 provider_unavailable/data_source_limit` em JSON (o redirecionamento amigável é trabalho de frontend).

### 14.4 Provedor de pagamento (para quando existir)

Implementar `app.billing.provider.BillingProvider` (`create_checkout`, `open_portal`, `change_plan`, `cancel`, `parse_webhook(body, headers) → BillingEvent`) e registrar em `build_provider`; ativar com `BILLING_PROVIDER=<nome>`. `BillingEvent`: `id`, `type` (`subscription.upserted|subscription.canceled|payment.failed|payment.succeeded`), `occurred_at`, `organization_id`, `external_customer_id`, `external_subscription_id`, `plan_key`, `interval`, `seats`, `status` (`active|trialing|past_due|unpaid|paused|incomplete|incomplete_expired|canceled`), `current_period_end`, `cancel_at`, `cancel_at_period_end`, `coupon_code`, `discount_summary`. Idempotência por `<provider>:<id>`; eventos mais antigos que `subscriptions.last_event_at` são ignorados; plano desconhecido nunca rebaixa em silêncio.

### 14.5 Pendências conhecidas (fora desta entrega)

Rate limit por plano (`api_rate_limit_per_minute` existe no catálogo mas `access/ratelimit.py` ainda usa os globais); pausa de fontes de dados excedentes no downgrade; lembretes de trial por e-mail; tela de staff e frontend; `max_file_bytes` por plano no upload; suspensão do sync agendado em `read_only` (hoje o bloqueio ocorre ao indexar/consumir uso).
