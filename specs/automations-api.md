# Automações — contrato da API interna (MVP)

Status: **contrato v1.1** (inclui catálogo de destinatários e webhooks de saída; este arquivo é a fonte de verdade para o frontend).
Autenticação, CSRF/Origin e erros seguem as demais APIs internas autenticadas do app (cookie de sessão,
`organization_id` no caminho). Não é parte da API pública `/v1`.

Todas as datas são ISO-8601 UTC (`2026-10-12T11:00:00Z`). Todos os ids são UUID em string.

## Conceitos

Uma **automação** roda uma pergunta (`prompt`) sobre um conjunto de **pastas indexadas da biblioteca, em qualquer nível da árvore** (`scope`) e entrega a resposta com
citações aos destinatários, no sino (notificações) e opcionalmente por e-mail. Cada disparo gera uma
**execução** (`run`) com o resultado salvo em JSON; o PDF é gerado sob demanda a partir desse resultado.

- **Permissão de execução = permissão do criador** (`created_by_user_id`), nunca Owner/Admin. Se o criador
  perder acesso a uma pasta do escopo, a execução termina com `status = "error"`, `error_code = "creator_access_lost"`.
- **Gatilhos**: `schedule` (diário/semanal/mensal, em fuso configurável) ou `folder_changed` (quando um sync
  indexa mudanças dentro de alguma pasta do escopo, subpastas incluídas).
- Cada execução consome **1 pergunta** da cota mensal da organização. Cota estourada => `status = "quota"`
  e aviso ao criador.
- Limite: **20 automações por organização** (constante `limit` devolvida na listagem).

## Permissões

| Ação | Quem pode |
|---|---|
| Listar | Membro: só as próprias. Owner/Admin: todas da organização |
| Criar | Qualquer membro ativo (para si) |
| Notificar **outros** usuários (`recipient_user_ids` com ids diferentes do próprio) | Somente Owner/Admin |
| Ver / editar / ligar-desligar / executar / excluir | Criador, ou Owner/Admin |
| Baixar PDF / ver execuções | Quem pode ver a automação |

Destinatário sem acesso a alguma pasta do escopo **não é bloqueado na criação**: na execução ele é ignorado
(sem notificação) e registrado em `result.skipped_recipients`. Destinatário que não é membro ativo da
organização é rejeitado na criação (`recipient_not_member`).

## Objeto `Automation`

```json
{
  "id": "…",
  "name": "Relatório semanal de contratos",
  "enabled": true,
  "trigger_kind": "schedule",
  "trigger_config": {"frequency": "weekly", "weekday": 0, "hour": 8, "timezone": "America/Sao_Paulo"},
  "scope": {"node_ids": ["…"], "folders": [{"node_id": "…", "name": "2026", "path": "Drive/Projetos/2026"}]},
  "prompt": "Resuma o que mudou nos contratos e liste pendências.",
  "template": "summary",
  "output_formats": ["email", "pdf"],
  "recipients": [{"user_id": "…", "email": "ana@empresa.com"}],
  "created_by_user_id": "…",
  "last_run_at": "2026-10-12T11:00:00Z",
  "next_run_at": "2026-10-19T11:00:00Z",
  "last_run": {"id": "…", "status": "ok", "finished_at": "2026-10-12T11:00:41Z"},
  "created_at": "2026-10-11T18:00:00Z"
}
```

Campos:

- `trigger_kind`: `"schedule"` | `"folder_changed"`.
- `trigger_config`
  - `schedule`: `frequency` `"daily"|"weekly"|"monthly"`; `hour` 0–23 (hora cheia, no `timezone`);
    `weekday` 0–6 (0 = segunda; obrigatório se `weekly`); `day` 1–28 (obrigatório se `monthly`);
    `timezone` nome IANA (padrão `"America/Sao_Paulo"`).
  - `folder_changed`: `{}` (sem parâmetros no MVP).
- `scope.node_ids`: 1–20 ids de **nós de pasta** da biblioteca (`kind = "folder"`, qualquer profundidade; os mesmos
  ids de `@menção` do chat — `GET /library`, `GET /library/nodes/{id}/children` e
  `GET /library/mention-candidates`). A automação considera os arquivos indexados da pasta **e de todas as
  subpastas**. A raiz da fonte (`kind = "source"`), arquivos e ids desconhecidos/de outra organização são rejeitados
  (`422 scope_not_allowed`), assim como pasta sem nenhum documento indexado. O criador precisa poder consultar todas.
  - Na **resposta**, `scope.folders` traz `{node_id, name, path}` (caminho completo, `Fonte/Pasta/Subpasta`) para
    exibir sem nova consulta; pasta que sumiu da biblioteca fica fora de `folders` (a UI mostra "indisponível") e a
    próxima execução termina em `scope_unavailable`.
  - **Legado (somente leitura de compatibilidade)**: automações criadas antes têm
    `scope.workspace_folder_ids` (espaço conectado inteiro) e continuam executando como antes, sem migração de
    dados; o `POST`/`PATCH` ainda aceita esse formato. Envie **exatamente um** dos dois campos (`node_ids` ou
    `workspace_folder_ids`); ambos ou nenhum => `422`. Ao editar uma automação legada na UI, escolher pastas troca o
    escopo para `node_ids`.
- `prompt`: 1–1000 caracteres.
- `template`: `"summary"` (resumo), `"table"` (a resposta pede uma tabela Markdown), `"alert"` (só avisa quando
  há algo a reportar; resposta vazia => `status = "empty"` e nenhuma notificação).
- `output_formats`: subconjunto de `["email", "pdf"]` (pode ser `[]`). O **sino é sempre notificado**.
  `"email"` envia e-mail (respeitando a preferência de cada usuário); `"pdf"` inclui o link de PDF na
  notificação (`data.pdf_path`). O download do PDF sempre funciona para qualquer execução com resultado.
- `recipients` (saída): destinatários resolvidos. Entrada usa `recipient_user_ids`. O criador é sempre incluído.
- `last_run_at`/`next_run_at`: `next_run_at` é `null` para `folder_changed` ou automação desligada.
- `last_run`: resumo da execução mais recente ou `null`.

## Objeto `AutomationRun`

```json
{
  "id": "…",
  "automation_id": "…",
  "status": "ok",
  "trigger_ref": "schedule:2026-10-12T11:00:00+00:00",
  "started_at": "…",
  "finished_at": "…",
  "documents_considered": 12,
  "questions_used": 1,
  "error_code": null,
  "result": {
    "answer": "Texto em Markdown…",
    "citations": [{"document_id": "…", "document_name": "contrato.pdf", "source_url": "https://…", "page_number": 3, "excerpt": "…"}],
    "skipped_recipients": [{"user_id": "…", "reason": "no_folder_access"}],
    "notified": 2
  },
  "pdf_available": true
}
```

- `status`: `queued` | `running` | `ok` | `empty` | `quota` | `error`.
- `trigger_ref`: `manual:<uuid>`, `schedule:<instante previsto>` ou `folder:<instante da última mudança>`.
- `error_code` (quando `status = "error"`): `creator_access_lost`, `scope_unavailable`, `ai_unavailable`, `internal_error`.
- `result` é `null` em `queued`/`running`/`quota`/`error`. Em `empty`, `answer` é `null`.
- `pdf_available` = `status == "ok"` (há resposta para renderizar).

## Rotas

Prefixo comum: `/organizations/{organization_id}`.

### `GET /automations`
Resposta `200`:
```json
{"limit": 20, "items": [Automation, …]}
```
Ordenado por `created_at` decrescente.

### `POST /automations` → `201` `Automation`
Corpo:
```json
{
  "name": "…", "trigger_kind": "schedule", "trigger_config": {…},
  "scope": {"node_ids": ["…"]}, "prompt": "…",
  "template": "summary", "output_formats": ["email"],
  "recipient_user_ids": ["…"], "enabled": true
}
```
`name` 1–160; `template` padrão `summary`; `output_formats` padrão `["email"]`; `recipient_user_ids` padrão `[]`
(só o criador); `enabled` padrão `true`.

### `GET /automations/{automation_id}` → `200` `Automation`

### `PATCH /automations/{automation_id}` → `200` `Automation`
Mesmos campos do `POST`, todos opcionais. Mudar `trigger_kind`/`trigger_config` recalcula `next_run_at`.
O escopo é validado contra o acesso do **criador** da automação.

### `GET /automation-recipients?node_ids=<id>&node_ids=<id>`
Catálogo para o seletor de destinatários. **Somente Owner/Admin** (`403 owner or admin required` para membro comum;
membro comum só pode notificar a si mesmo, então o seletor não deve ser exibido para ele).
`node_ids` (repetível, 0–20) são as pastas do escopo da automação em edição; omitido => `has_access` é `null`.
Pasta inexistente/não pasta/sem acesso do solicitante => `422 scope_not_allowed`. (`workspace_folder_ids` continua
aceito para escopo legado; não combine os dois.) Resposta `200`:
```json
{"items": [
  {"user_id": "…", "name": "ana", "email": "ana@empresa.com", "role": "member",
   "has_access": true, "is_you": false}
]}
```
- Lista só **membros ativos** da organização (inclui o próprio usuário, com `is_you = true`), ordenados por e-mail.
- `name`: o app não guarda nome de usuário; é a parte local do e-mail (antes do `@`). Mostre o e-mail como texto principal.
- `has_access`: `true` se o membro tem acesso a **todas** as pastas informadas; `false` se falta alguma;
  `null` se nenhuma pasta foi informada. Mostre aviso para `false` (ele seria ignorado na execução, ver Permissões);
  selecionar esse membro continua permitido.
- `role`: `owner` | `admin` | `member`.

### `DELETE /automations/{automation_id}` → `204`
Apaga a automação e suas execuções.

### `PUT /automations/{automation_id}/enabled` → `200` `Automation`
Corpo `{"enabled": true|false}`. Ligar uma automação `schedule` recalcula `next_run_at` a partir de agora.

### `POST /automations/{automation_id}/run` → `202`
Executa agora (assíncrono). Resposta: `AutomationRun` com `status = "queued"`. Faça polling em
`GET …/runs/{run_id}`. Não exige a automação estar ligada.

### `GET /automations/{automation_id}/runs?limit=20` → `200`
`{"items": [AutomationRun, …]}` do mais recente ao mais antigo (`limit` 1–100, padrão 20).

### `GET /automations/{automation_id}/runs/{run_id}` → `200` `AutomationRun`

### `GET /automations/{automation_id}/runs/{run_id}/pdf` → `200`
`application/pdf`, `Content-Disposition: attachment; filename="arquivio-<slug>.pdf"`, `Cache-Control: no-store`.
`404 run_has_no_result` se a execução não tem resposta.

## Erros

Formato FastAPI: `{"detail": "<codigo>"}` (validação de corpo do Pydantic devolve `422` no formato padrão
`{"detail": [{"loc": …, "msg": …}]}`).

| HTTP | `detail` | Quando |
|---|---|---|
| 403 | `not allowed` | Não é membro ativo da organização, ou não é o criador/Owner/Admin |
| 403 | `owner or admin required` | Tentou notificar outro usuário, listar o catálogo de destinatários ou gerir webhooks sendo membro comum |
| 404 | `automation not found` | Id inexistente, de outra organização, ou sem permissão de ver |
| 404 | `run not found` / `run_has_no_result` | Execução inexistente / sem resposta para PDF |
| 409 | `automation_limit_reached` | Organização já tem 20 automações |
| 422 | `scope_not_allowed` | Alguma pasta não existe, não é pasta indexada da biblioteca (arquivo, raiz da fonte, sem documentos indexados) ou o criador não tem acesso |
| 422 | `recipient_not_member` | Algum destinatário não é membro ativo |
| 422 | `invalid_trigger_config` | Combinação inválida (ex.: `weekly` sem `weekday`, fuso desconhecido) |
| 422 | `invalid_output_formats` | Valor fora de `email`/`pdf` |

## Notificações geradas (para o sino)

`kind = "automation_result"`, `title` = nome da automação, `body` = início da resposta, e `data`:
```json
{"automation_id": "…", "run_id": "…", "template": "summary", "citations": [ … ],
 "pdf_path": "/organizations/<org>/automations/<id>/runs/<run>/pdf"}
```
(`pdf_path` só quando `output_formats` contém `"pdf"`; já é o caminho relativo da rota de PDF acima.)

`kind = "automation_quota"` para o criador quando a cota mensal impediu a execução:
`data = {"automation_id": "…", "run_id": "…"}`.

`kind = "automation_failed"` para o criador quando a execução termina em `error`:
`data = {"automation_id": "…", "run_id": "…", "error_code": "…"}`.

## Comportamento dos gatilhos (para a UI explicar)

- `schedule`: um tick a cada 5 minutos executa as automações com `next_run_at <= agora`; atraso típico < 5 min.
- `folder_changed`: depois de cada sync concluído, se algum documento **dentro das pastas escolhidas (e subpastas)**
  foi indexado/modificado desde a última execução (mudanças em outras pastas do mesmo espaço não disparam), a automação roda uma vez por conjunto de mudanças (sem duplicar se o sync repetir).

## Webhooks de saída

Notificam um sistema externo (Zapier, n8n, serviço próprio) quando uma automação **termina**. Configuração por
organização; **somente Owner/Admin** (membro comum: `403 owner or admin required`). Prefixo `/organizations/{organization_id}`.

### Objeto `WebhookEndpoint`
```json
{"id": "…", "url": "https://hooks.empresa.com/arquivio", "events": ["automation.completed"],
 "enabled": true, "revoked_at": null, "created_at": "…", "created_by_user_id": "…",
 "last_delivery": {"id": "…", "status": "delivered", "attempts": 1, "created_at": "…"}}
```
`last_delivery` é `null` se nunca houve entrega. O `secret` **nunca** aparece aqui; só nas respostas de criação e
rotação (campo `secret`, exibido uma única vez; o servidor guarda apenas o hash).

### Rotas
- `GET /webhook-endpoints` → `200` `{"limit": 5, "items": [WebhookEndpoint, …]}` (inclui revogados no fim).
- `POST /webhook-endpoints` → `201` `WebhookEndpoint` + `"secret": "whsec_…"`. Corpo:
  `{"url": "https://…", "events": ["automation.completed"], "enabled": true}` (`events` padrão `["automation.completed"]`;
  `enabled` padrão `true`). Máximo 5 endpoints ativos (não revogados) por organização (`409 webhook_limit_reached`).
- `PATCH /webhook-endpoints/{id}` → `200` `WebhookEndpoint`. Campos opcionais `url`, `events`, `enabled`. Endpoint revogado: `409 webhook_revoked`.
- `POST /webhook-endpoints/{id}/rotate-secret` → `200` `WebhookEndpoint` + `secret` novo (o anterior deixa de valer na hora).
- `DELETE /webhook-endpoints/{id}` → `204`. Revoga (`revoked_at` preenchido, `enabled = false`); entregas pendentes são canceladas. Idempotente.
- `GET /webhook-endpoints/{id}/deliveries?limit=20` → `200` `{"items": [Delivery, …]}` (mais recente primeiro, 1–100).
  `Delivery`: `{"id", "event", "run_id", "status": "pending|delivered|failed", "attempts", "last_error", "last_status_code", "created_at", "delivered_at"}`.
  `last_error` é um código curto (`http_500`, `timeout`, `connection_error`, `blocked_destination`), nunca o corpo da resposta.

### Validação da URL (proteção SSRF)
Apenas `https://`, sem credenciais na URL, **somente porta 443**.
Host que seja IP literal ou que resolva (DNS) para endereço privado, loopback, link-local, multicast, reservado ou
não especificado (inclui `10/8`, `172.16/12`, `192.168/16`, `127/8`, `169.254/16`, `::1`, `fc00::/7`, `fe80::/10`, IPv4-mapeado) é recusado.
Na criação/edição: `422 invalid_webhook_url`. A checagem é **refeita a cada entrega** (resolve o DNS e conecta no IP
validado, contra DNS rebinding); falha => entrega `failed` com `last_error = "blocked_destination"` sem retentativa.
Redirecionamentos não são seguidos. Timeout de 5 s por tentativa.

### Evento `automation.completed`
Disparado quando uma execução chega a `ok`, `empty`, `quota` ou `error` (não em `queued`/`running`) para endpoints
ativos que assinam o evento. Requisição `POST` com `Content-Type: application/json`:
```json
{"id": "<delivery_id>", "event": "automation.completed", "created_at": "…", "organization_id": "…",
 "data": {"automation_id": "…", "automation_name": "…", "run_id": "…", "status": "ok",
          "error_code": null, "documents_considered": 12, "finished_at": "…",
          "answer": "Markdown… (até 4000 caracteres)", "citations": [{"document_name": "…", "source_url": "…", "page_number": 3}]}}
```
`answer` e `citations` só em `ok` (senão `null`/`[]`). Não envia `excerpt`.

Cabeçalhos: `X-Arquivio-Event`, `X-Arquivio-Delivery` (id, estável entre retentativas — use para deduplicar),
`X-Arquivio-Timestamp` (epoch em segundos) e `X-Arquivio-Signature: v1=<hex>`.
Assinatura: `HMAC-SHA256(chave, f"{timestamp}.{corpo_bruto}")` em hex, onde **chave = SHA-256 hex do secret**
(`hashlib.sha256(secret.encode()).hexdigest()`; o servidor guarda esse mesmo valor em `secret_hash`).
Recomenda-se rejeitar timestamps com mais de 5 minutos.

Retentativas: resposta 2xx = entregue. Falha de rede/timeout/5xx/429 => até 5 tentativas no total, com backoff
exponencial (30 s, 60 s, 120 s, 240 s). Outros 4xx = `failed` sem retentativa. Esgotadas as tentativas: `failed`.
