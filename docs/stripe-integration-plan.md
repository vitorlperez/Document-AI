# Plano de integração com o Stripe

- **Status:** implementado e validado contra o SDK real `stripe` 16.0.1 (2026-10-28). Falta o E2E no sandbox (WP9): a rede do ambiente de desenvolvimento nega `api.stripe.com`.
- **Decisão:** ADR-0023 (`specs/adr/ADR-0023-stripe-billing-provider.md`), que emenda o ADR-0022.
- **Contexto de produto e contrato de API:** `docs/contas-pessoal-empresa.md` (§5 e §14).
- **Deploy:** `docs/deployment/railway-production.md` (variáveis e endpoint de webhook).

O Stripe entra como mais um adaptador da porta `BillingProvider`. Resolvedor de entitlements, tabelas (`subscriptions`, `billing_events`) e contrato de API não mudam, exceto pela rota de faturas e por dois tipos de evento novos.

## 1. Arquitetura

- **Customer ↔ organização.** Customer com `metadata.organization_id` e `preferred_locales=['pt-BR']` ↔ `organizations.billing_customer_id`, `billing_provider="stripe"`.
- **Subscription ↔ linha `subscriptions`** (`external_subscription_id`). Os status do Stripe coincidem com `SUBSCRIPTION_STATUSES`.
- **Catálogo.** Um Product por plano, dois Prices (mensal/anual) com `metadata` `plan_key`, `interval`, `account_type`; `lookup_key` = `{plan}_{monthly|yearly}`. `app/entitlements/catalog.py` continua a fonte de verdade.
- **Assentos.** Planos de empresa usam **um único Price escalonado (`graduated`)** com `quantity = assentos`:
  - faixa 1: `up_to = included_seats`, `flat_amount = preço base`, `unit_amount = 0`;
  - faixa 2: `up_to = inf`, `unit_amount = assento extra`;
  - anual = 10× o mensal.

  Planos pessoais: preço fixo, `quantity = 1`. O app continua impondo `max_seats`; troca de plano e de assentos **não** passa pelo Customer Portal.
- **Resolução da org**: Customer → `billing_customer_id`; fallback `metadata.organization_id`.
- **Plano**: `price.metadata.plan_key` (fallback `product.metadata`), **nunca** `lookup_key`.

## 2. Mapeamento de webhooks

Assinatura verificada com `client.construct_event(corpo_bruto, Stripe-Signature, secret)`. A assinatura é re-buscada com `expand` de `items.data.price.product` e `discounts.promotion_code`. `occurred_at = event.created`; `id = event.id` (chave no *ledger* `billing_events`: `stripe:evt_…`). Rota: `POST /webhooks/billing/stripe`.

| Evento Stripe | `BillingEvent.type` |
|---|---|
| `checkout.session.completed` / `checkout.session.async_payment_succeeded` / `checkout.session.async_payment_failed` | `subscription.upserted` (re-busca `session.subscription`; `incomplete` não concede nada) |
| `customer.subscription.created` / `updated` / `paused` / `resumed` | `subscription.upserted` |
| `customer.subscription.deleted` | `subscription.canceled` |
| `invoice.paid` | `payment.succeeded` |
| `invoice.payment_failed` | `payment.failed` |
| `invoice.payment_action_required` | `subscription.upserted` |
| `charge.dispute.created`, `charge.refunded`, `radar.early_fraud_warning.created` | `risk.flagged` (log + alerta para staff, sem mudança de acesso) |
| `mandate.updated` (Pix Automático) | `subscription.upserted` via re-busca, se resolvível (payment method → Customer → assinatura); senão `risk.flagged` |
| qualquer outro | `ignored` (200, registrado no *ledger*) |

Campos que mudaram de lugar na versão pinada: `current_period_end` vem de `items.data[0]`; fatura → assinatura via `invoice.parent.subscription_details.subscription`. Erro de assinatura ⇒ `WebhookRejected` (400); erro de API do Stripe ⇒ propaga 5xx para o Stripe repetir.

## 3. Faturas

- Faturas automáticas da assinatura.
- Customer Portal v1: histórico de faturas, atualizar forma de pagamento, cancelar ao fim do período (e atualizar CNPJ). A configuração é criada pelo script de catálogo; se não for a padrão da conta, informe o `bpc_…` em `STRIPE_PORTAL_CONFIGURATION_ID`.
- `GET /organizations/{id}/billing/invoices` — **somente owner** (demais membros `403`) → lista de até 12 faturas recentes com `id, number, status, total` (centavos), `currency, created` (ISO 8601 UTC), `hosted_invoice_url, invoice_pdf`; `[]` antes do primeiro checkout; `501 billing_not_configured` sem provedor.
- **Nunca** `automatic_tax`: o Stripe Tax **não é suportado para contas BR**. A NFS-e é emitida fora do Stripe (ver §6).
- **URLs de retorno** (não existe rota `/app/billing`; `_billing_page_url` em `backend/app/api/billing.py`): sucesso do Checkout `{public_app_url}/companies/{org_id}/admin?checkout=success`, cancelamento `…/admin?checkout=canceled`, retorno do Portal `…/admin?billing=portal`.

## 4. Nomes fixos

`backend/app/core/config.py`:

| Setting | Variável de ambiente | Observação |
|---|---|---|
| `billing_provider` | `BILLING_PROVIDER` | `"none"` (padrão) ou `"stripe"` |
| `stripe_api_key: SecretStr \| None` | `STRIPE_API_KEY` | obrigatória com `stripe`; preferir chave restrita `rk_` |
| `stripe_webhook_secret: SecretStr \| None` | `STRIPE_WEBHOOK_SECRET` | obrigatória com `stripe` |
| `stripe_api_version: str` | `STRIPE_API_VERSION` | padrão `2026-09-30.endive` |
| `stripe_checkout_integration_id: str` | `STRIPE_CHECKOUT_INTEGRATION_ID` | rótulo fixo (ex.: `arquivio_checkout_…`) |
| `stripe_portal_configuration_id: str \| None` | `STRIPE_PORTAL_CONFIGURATION_ID` | opcional; `bpc_…` do Customer Portal (vazio = padrão da conta) |
| `stripe_pix_enabled: bool = False` | `STRIPE_PIX_ENABLED` | liga `mandate_options` de Pix no Checkout; manter `false` (ver §6) |
| `trial_days` | `TRIAL_DAYS` | já existia |
| — | `STRIPE_CATALOG_API_KEY` | só o script de sincronização de catálogo |

Outros nomes: `EVENT_RISK_FLAGGED = "risk.flagged"` e `EVENT_IGNORED = "ignored"` em `backend/app/billing/provider.py`; `build_provider(name, settings=None)` importa `app.billing.stripe_provider.StripeBillingProvider` de forma tardia; módulo de catálogo `backend/app/billing/stripe_catalog.py` (sem importar `stripe`) com `ProductSpec`, `PriceSpec`, `desired_products()`, `desired_price(plan_key, interval)`, `lookup_key(plan_key, interval)`, `plan_from_price(price)`.

## 5. Pacotes de trabalho

| WP | Escopo | Testes |
|---|---|---|
| WP1 | Dependência `stripe>=16,<17` + settings; validador: `billing_provider="stripe"` exige as duas chaves; em produção recusa chaves de teste e avisa sobre `sk_` (preferir `rk_`). Segredos fora do `repr`; padrão `none` sobe. | `tests/unit/test_stripe_config.py` |
| WP2 | `stripe_catalog.py` + `backend/scripts/stripe_sync_catalog.py` (`--dry-run` padrão, `--apply`; IDs estáveis como `arquivio_business_team`; `prices.list(lookup_keys=…)`; diferença ⇒ Price novo com `transfer_lookup_key=True`, nunca editar; cria/atualiza a configuração do Customer Portal com `subscription_update` desligado). | `tests/unit/test_stripe_catalog.py`: total das faixas == `seat_price_cents` para todo plano/intervalo/assentos 1..`max_seats`; segunda execução sem escritas; mudança de preço cria Price novo e transfere o `lookup_key` |
| WP3 | `StripeBillingProvider(settings, client=None)`: checkout (Customer sob demanda com idempotency key `org-{id}-customer`; `mode=subscription`; `line_items=[{price, quantity: seats}]`; `client_reference_id`; `subscription_data.metadata`; `locale=pt-BR`; identificador de integração; `discounts` **ou** `allow_promotion_codes`; **sem** `payment_method_types`), portal, `change_plan` (`always_invoice` no upgrade, `create_prorations` no downgrade, `error_if_incomplete`, idempotency key; falha antes de escrita local), `cancel`. | `tests/unit/test_stripe_provider.py` |
| WP4 | `parse_webhook` conforme §2. | `tests/unit/test_stripe_webhooks.py` (payloads assinados localmente) |
| WP5 | Constantes em `provider.py` + `build_provider(name, settings=None)`; `service.py` trata `risk.flagged`/`ignored` (gravados, sem mudança de acesso, sem 400); fallback de org por `billing_customer_id`; `app/main.py` passa as settings de runtime. | estender `tests/api/test_account_types_api.py` |
| WP6 | Rota já existe; adicionar `stripe-signature` em `FORWARDED_REQUEST_HEADERS` (`frontend/app/api/proxy-headers.mjs`). | teste de API com payload assinado e cliente *fake* |
| WP7 | Faturas + frontend: `success_url {public_app_url}/companies/{org_id}/admin?checkout=success` (cancelamento `?checkout=canceled`, retorno do Portal `?billing=portal`; não há rota `/app/billing`); `GET …/billing/invoices` (somente owner; `list_invoices` no provedor; `NoBillingProvider` ⇒ 501); `plan-ui.tsx`: botão do portal também para donos de conta pessoal, poll curto de `GET …/billing` ao voltar do Checkout, lista de faturas. | `frontend/tests/plan-model.test.mjs` |
| WP8 | Documentação: ADR-0023, `docs/contas-pessoal-empresa.md`, `docs/deployment/railway-production.md`, `.env.example`, `.env.production.example`, este plano. | — |
| WP9 | E2E no sandbox com `stripe listen` / `stripe trigger` — executado pelo usuário, depois das chaves. | — |

Regra geral dos testes: nenhuma chamada de rede ao Stripe. Os testes de unidade usam um *fake*; `tests/unit/test_stripe_sdk_contract.py` usa o `StripeClient` real com HTTP gravado e valida os parâmetros contra os `TypedDict` do SDK (e contra o `stripe-mock`, se estiver em `STRIPE_MOCK_URL`; `go install github.com/stripe/stripe-mock@latest` e `stripe-mock -http-port 12111`).

## 6. Brasil: impostos, NFS-e, CPF/CNPJ, Boleto e Pix

Situação da conta sandbox (2026-10-27): BR/BRL, `livemode=false`, sem Products/Prices/configuração de Portal/endpoints de webhook; **Boleto e Pix indisponíveis** (capacidades não ativas).

- **Stripe Tax não é suportado para contas BR** ⇒ o código nunca envia `automatic_tax`.
- **NFS-e** é emitida fora do Stripe, por um provedor a escolher (eNotas, NFE.io ou Focus NFe). Gancho futuro: ao aplicar `payment.succeeded` (`invoice.paid`), buscar a fatura com `GET /v1/invoices/{id}` e enviar tomador, valor e descrição ao emissor.
- **CPF/CNPJ**: no Checkout de empresa, `tax_id_collection` fica ligado em melhor esforço (nunca obrigatório) com `billing_address_collection=required`, mas o Checkout provavelmente **não** coleta `br_cpf`/`br_cnpj`. Coletar no app (antes do Checkout, gravando no Customer) é decisão do dono — necessária se a NFS-e precisar do documento do tomador.
- **Checkout**: `subscription_data.billing_mode={type: flexible}` explícito; sem `ui_mode` (página hospedada padrão); `seats ≥ 1` validado no adaptador.
- **Boleto**: solicitar a capacidade no Dashboard e, nas configurações de cobrança/faturas, habilitar o envio do **link hospedado** da fatura. `checkout.session.async_payment_succeeded/failed` já são tratados. O Boleto volta pelo `hosted_voucher_url` (não pelo `success_url`); enquanto a assinatura está `incomplete` a UI mostra "pagamento pendente".
- **Pix Automático** (atrás de `STRIPE_PIX_ENABLED`, padrão `false`): o Checkout envia `payment_method_options.pix.mandate_options = {amount: max_charge_cents (custo de um ciclo em max_seats), amount_type: maximum, currency: brl, payment_schedule: monthly|yearly, reference: "Arquivio <plan_key>"}`. Sem isso o Stripe usaria o teto padrão de **R$ 400**. Troca de plano acima do teto (ou de anual para mensal) ⇒ `409 pix_mandate_reauth_required`, exigindo novo mandato. `mandate.updated` é tratado (§2). Ressalvas:
  - a documentação do Stripe diz que o Pix Automático **não está disponível para empresas domiciliadas no Brasil** — a conta do Arquivio é BR, então o Pix recorrente provavelmente fica indisponível; `STRIPE_PIX_ENABLED` permanece `false` (decisão do dono);
  - o teto do Business Scale anual (R$ 40.190) excede o limite padrão por pagamento Pix (~USD 3.000).

Códigos de erro novos do adaptador: `invalid_seats` (422), `invalid_promotion_code` (422), `subscription_required` (409), `pix_mandate_reauth_required` (409), `payment_failed` (402), `plan_unavailable` (503).

## 7. Ops checklist para go-live (sandbox → produção)

Executar primeiro no sandbox (chaves `rk_test_…`) e repetir em produção (chaves `rk_live_…`). Nunca colar valores de chaves em docs, tickets ou logs.

**Catálogo e Portal**
- [ ] Criar uma chave restrita de catálogo (escrita em Products, Prices e Customer Portal) e exportá-la como `STRIPE_CATALOG_API_KEY` só na sessão que roda o script.
- [ ] Em `backend/`: `python -m scripts.stripe_sync_catalog` (dry-run, padrão) e revisar as escritas planejadas; depois `python -m scripts.stripe_sync_catalog --apply` (com chave live, o script exige também `--confirm-live`). Rodar de novo deve dar zero escritas.
- [ ] Customer Portal: se o script avisar que a configuração criada não é a padrão da conta, torná-la padrão no Dashboard **ou** definir `STRIPE_PORTAL_CONFIGURATION_ID=<bpc_…>` na API.

**Webhook**
- [ ] Criar o endpoint em `https://<domínio público da API>/webhooks/billing/stripe` com `api_version` **`2026-09-30.endive`**, assinando exatamente estes eventos (mapeamento em `backend/app/billing/stripe_provider.py`):
  - `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`
  - `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.paused`, `customer.subscription.resumed`, `customer.subscription.deleted`
  - `invoice.paid`, `invoice.payment_failed`, `invoice.payment_action_required`
  - `charge.dispute.created`, `charge.refunded`, `radar.early_fraud_warning.created`
  - `mandate.updated`
- [ ] Copiar o segredo `whsec_…` para `STRIPE_WEBHOOK_SECRET` (um endpoint e um segredo por ambiente).

**Cobrança e recuperação de pagamento (Dashboard → Billing)**
- [ ] **Smart Retries** ligado; calendário de retentativas conforme a decisão do dono.
- [ ] **E-mails de falha de pagamento** ao cliente ligados (e de ação necessária/3DS).
- [ ] **Atualizador automático de cartões** (card updater) ligado.
- [ ] **Estado final após esgotar as retentativas**: marcar a assinatura como `unpaid` (padrão proposto; mantém recuperável pela fatura hospedada/Portal) — ou cancelar, conforme decisão do dono.

**Métodos de pagamento**
- [ ] Cartão via métodos de pagamento dinâmicos (o código nunca envia `payment_method_types`).
- [ ] Boleto (se decidido): solicitar a capacidade e habilitar o envio do link hospedado da fatura; testar o fluxo "pagamento pendente".
- [ ] Pix: **somente** depois de confirmada a disponibilidade do Pix Automático para a conta BR e verificado o caminho de código com `STRIPE_PIX_ENABLED=true` no sandbox; até lá, `STRIPE_PIX_ENABLED=false`.

**Variáveis da API (Railway)**
- [ ] `BILLING_PROVIDER=stripe`, `STRIPE_API_KEY` (restrita de runtime), `STRIPE_WEBHOOK_SECRET`; opcionais `STRIPE_API_VERSION`, `STRIPE_CHECKOUT_INTEGRATION_ID`, `STRIPE_PORTAL_CONFIGURATION_ID`, `STRIPE_PIX_ENABLED`. Em produção chaves de teste são recusadas.

**Testes**
- [ ] Ambiente local de testes: em `backend/`, `pip install -e ".[dev]"` (instala `stripe` e as dependências de teste) e rodar `pytest`.
- [ ] Ponta a ponta no sandbox: `stripe listen --forward-to localhost:8000/webhooks/billing/stripe` (use o `whsec_…` impresso pelo CLI como `STRIPE_WEBHOOK_SECRET` local) e `stripe trigger <evento>` (ex.: `checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`). O CLI entrega o payload na versão padrão da conta; como o adaptador re-busca os objetos com o cliente pinado, isso só afeta o payload bruto.
- [ ] Checkout real no sandbox para cada plano (incluindo o Price escalonado com `quantity`), Portal, troca de plano e cancelamento; conferir o retorno em `/companies/{org_id}/admin?checkout=success`.
- [ ] Pix no sandbox (se aplicável): CPF de teste `000.000.000-00`.

## 8. Riscos

- Latência da re-busca no webhook (uma chamada ao Stripe por evento).
- Eventos no mesmo segundo: comparação estrita (`<`) com `last_event_at` é suficiente.
- `change_plan` precisa falhar **antes** de qualquer escrita local.
- Duas chaves restritas nas Variables da Railway (runtime e sincronização de catálogo).

## 9. Decisões do dono (checklist)

Os itens marcados **[provisório]** já têm um padrão adotado na implementação e precisam só de confirmação; os demais estão em aberto.

- [ ] **Provedor de NFS-e** — escolher entre **eNotas**, **NFE.io** ou **Focus NFe** (com o contador); o Stripe não emite nota fiscal brasileira. Integração futura no `payment.succeeded` (§6).
- [ ] **Coleta de CPF/CNPJ no app** — o Checkout provavelmente não coleta `br_cpf`/`br_cnpj`; decidir se o app coleta antes do Checkout (necessário para NFS-e com tomador identificado).
- [ ] **Boleto/Pix no lançamento** — [provisório] só cartão via métodos dinâmicos (código nunca envia `payment_method_types`). Boleto exige solicitar a capacidade; Pix Automático provavelmente indisponível para conta BR (`STRIPE_PIX_ENABLED=false`).
- [ ] **Política de retentativas e carência** — calendário de Smart Retries, estado final após as retentativas (`unpaid` proposto vs. cancelar) e carência de 7 dias em `past_due`.
- [x] **Seletor de plano para contas pessoais** — implementado (Básico/Pro, mensal/anual, 1 assento, mesmo fluxo de checkout). Troca de plano com assinatura viva vai pelo Portal; sem UI de cancelamento/troca no app e sem campo de código promocional.
- [ ] **Comportamento do trial** — [provisório] assinar durante o trial local cobra imediatamente (sem `trial_end` no Stripe); alternativa: preservar os dias restantes como `trial_end`.
- [ ] **Abordagem fiscal** — `automatic_tax` nunca (Stripe Tax não suporta BR); no Checkout de empresa, `tax_id_collection` em melhor esforço e `billing_address_collection=required`.
- [ ] **Webhook pelo domínio da API vs. pelo proxy do frontend** — [provisório] direto no domínio público da API; `stripe-signature` também na lista de cabeçalhos do proxy como salvaguarda.
- [x] **Modelo escalonado confirmado no sandbox** (2026-10-28): Checkout aceita Price `graduated` com `quantity` (7 assentos ⇒ R$ 397); não precisa do *fallback*.
- [ ] **Achados da revisão de segurança ainda abertos** — ver ADR-0023 (índice único de customer, `FOR UPDATE` no webhook, limite de corpo/taxa na rota do webhook, Portal sempre com configuração própria em produção, 502 para erros do SDK, chave de catálogo obrigatória com `--apply`).
- [x] **Sandbox, confirmado via conector MCP (2026-10-28)** — `discount.coupon` não existe; é `discount.source.coupon` (ID, expandir com `discounts.source.coupon`); o expand `discounts.promotion_code` é aceito. Detalhes no ADR-0023.
- [ ] **Sandbox, ainda aberto (precisa de navegador/rede)** — campo CNPJ no formulário hospedado para endereço BR; entrega de webhooks com `stripe listen`/`stripe trigger`; falha de pagamento até `unpaid`/somente leitura; cancelamento no fim do período; `charge.dispute.created`.
