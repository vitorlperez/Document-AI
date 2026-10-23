# ADR-0022: Tipos de conta (pessoal/empresa), planos e entitlements

- **Status:** Implementado no backend (2026-10-23); frontend e provedor de pagamento pendentes.
- **Data:** 2026-10-23
- **Decisor:** produto (usuário). Decisões do dono: empacotamento **modelo B** (preço base com assentos incluídos + assento extra); **trial local de 14 dias, sem cartão**, que ao expirar vira **somente leitura**; contas existentes ficam **`legacy`** (sem migração forçada); cortesia (**comp**) local gerida por `PlatformStaff` admin; **não integrar Stripe agora** — a camada de pagamento é **agnóstica de provedor**.
- **Relaciona-se com:** `docs/contas-pessoal-empresa.md` (análise e contrato de API), `docs/lp-pessoal-empresa.md`, ADR-0004 (`0004-platform-staff-access.md`), ADR-0021 (Espaços; o limite de Espaços passa a ser por plano).
- **Não substitui** nenhum ADR anterior.

## Contexto

Antes desta decisão não havia tipo de conta, plano, assinatura nem limite por organização: os tetos eram globais (`Settings.active_document_limit`, `monthly_limit_*`, `MAX_AUTOMATIONS_PER_ORGANIZATION`), qualquer pessoa criava N organizações e convites não tinham teto de assentos. O produto passa a vender dois formatos (Pessoal: uma pessoa, limites menores; Empresa: equipe) e precisa de preço e limites por plano.

## Decisões

| # | Decisão |
|---|---|
| D1 | **O tipo mora na organização** (`organizations.account_type` ∈ `personal`/`business`), não no usuário. Conta pessoal = organização de 1 pessoa. **Upgrade pessoal→empresa é in-place** (mesmo `organization_id`; nada é copiado). |
| D2 | **Catálogo único** em `app/entitlements/catalog.py`: `personal_basic` (R$ 39), `personal_pro` (R$ 99), `business_team` (R$ 299, 5 assentos incluídos, R$ 49/extra, até 15), `business_scale` (R$ 899, 20 incluídos, R$ 39/extra, até 100); anuais 10×. Valores em **centavos BRL**. Estados técnicos não vendidos: `personal_trial`, `business_trial`, `expired`, `legacy`. |
| D3 | **Resolução em tempo de leitura**, nunca dependente de job/webhook para expirar: `resolve_entitlement(org, now)` com precedência **comp > assinatura > trial > legacy > expirado**. Cache **por sessão (= request)**, invalidado em toda mutação. `organizations.plan_key`/`entitlement_source` são só **projeção** (a verdade é o resolvedor); `legacy` também é marcador de entrada, limpo pela primeira assinatura. |
| D4 | **Guards dentro dos serviços** (valem para API, jobs, MCP e API pública): `require_writable`, `require_can_invite`, `require_seat_available`, `require_space_quota`, `require_automation_quota`, `require_api_key_quota`/`require_feature`, `require_source_quota`, `require_org_creation_quota`. `UsageService` e a capacidade de documentos leem o plano da org; `Settings` é só o fallback do `legacy`. Assentos = `membros ativos + convites pendentes` (convite) ou `membros ativos` (aceite/`add_membership`), sob `SELECT … FOR UPDATE` na org. |
| D5 | **Erro padronizado** `EntitlementError`: HTTP **402** (plano/limite/somente leitura) ou **403** (tipo de conta) com corpo `{detail, code, limit, used, upgrade_to}`; `UsageLimitExceeded` é subclasse (continua **429** para o pool mensal; `read_only` é 402). |
| D6 | **Trial local** de `trial_days=14`, sem cartão, iniciado na criação da org; **um trial por criador e por tipo**; **no máximo 1 org pessoal por dono**. Ao expirar: `expired`/`read_only` (nada é apagado; leitura, billing e remoção de membros seguem). |
| D7 | **Comp** (`organization_comps`): plano de catálogo do mesmo tipo da org + `limits_override` validado (`"unlimited"` explícito), `expires_at` obrigatório salvo `permanent`, motivo ≤ 240; uma comp ativa por org; só `PlatformStaff.role='admin'`; `AuditLog` (`comp.granted/extended/revoked`). Ignora qualquer assinatura (e avisa que a cobrança não é cancelada). |
| D8 | **Cobrança agnóstica de provedor.** Porta `BillingProvider` (`create_checkout`, `open_portal`, `change_plan`, `cancel`, `parse_webhook` → `BillingEvent` normalizado), tabela genérica `subscriptions` (`provider`, `external_*`, `plan_key`, `status`, `seats`, `current_period_end`, `cancel_at`, `coupon_code`…) escrita **somente** por `BillingService.apply_event` (idempotente por `billing_events`, descarta evento mais antigo que `last_event_at`). Sem provedor configurado (`billing_provider="none"`, padrão) os endpoints devolvem **501 `billing_not_configured`**. Cupom/código promocional trafega pela interface (`promotion_code`); a regra de desconto é do provedor futuro. |
| D9 | **Downgrade** empresa→pessoal só com 0 membros além do dono, 0 convites pendentes e cooldown de 30 dias; **nunca apaga**: automações acima do teto são **desativadas**, criação nova passa a ser bloqueada. |
| D10 | **Contas existentes** ficam `business`/`legacy` (defaults da coluna; a migração não faz `UPDATE`). `legacy` = valores atuais de `Settings`, sem teto de assentos, sem somente leitura. Criar org pelo endpoint **nunca** gera `legacy`. |

## Consequências

- Todo recurso novo que consome capacidade deve passar por um guard de `app/entitlements/service.py`; não ler `Settings` para limite de org.
- Fixtures de teste que criam `Organization(...)` direto continuam `legacy` (suíte existente verde); testes que criam org via `POST /organizations` agora enviam `account_type` explícito.
- Plugar um provedor real = implementar `BillingProvider` (+ registrar em `build_provider`) e mapear seus eventos para `BillingEvent`; nenhuma mudança no resolvedor, nas tabelas ou na API.
- Pendentes: UI (gating, faixas de trial/somente leitura), limites de rate por plano, pausa de fontes de dados excedentes no downgrade (`paused_plan`), e-mails de lembrete de trial.
