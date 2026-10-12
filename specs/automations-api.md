# Automações — contrato da API interna (MVP)

Status: **contrato v1** (backend em implementação; este arquivo é a fonte de verdade para o frontend).
Autenticação, CSRF/Origin e erros seguem as demais APIs internas autenticadas do app (cookie de sessão,
`organization_id` no caminho). Não é parte da API pública `/v1`.

Todas as datas são ISO-8601 UTC (`2026-10-12T11:00:00Z`). Todos os ids são UUID em string.

## Conceitos

Uma **automação** roda uma pergunta (`prompt`) sobre um conjunto de pastas (`scope`) e entrega a resposta com
citações aos destinatários, no sino (notificações) e opcionalmente por e-mail. Cada disparo gera uma
**execução** (`run`) com o resultado salvo em JSON; o PDF é gerado sob demanda a partir desse resultado.

- **Permissão de execução = permissão do criador** (`created_by_user_id`), nunca Owner/Admin. Se o criador
  perder acesso a uma pasta do escopo, a execução termina com `status = "error"`, `error_code = "creator_access_lost"`.
- **Gatilhos**: `schedule` (diário/semanal/mensal, em fuso configurável) ou `folder_changed` (quando um sync
  indexa mudanças em alguma pasta do escopo).
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
  "scope": {"workspace_folder_ids": ["…", "…"]},
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
- `scope.workspace_folder_ids`: 1–20 ids de pasta de trabalho (`/workspace-folders`, os mesmos ids usados nas
  perguntas). O criador precisa ter acesso a todas.
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
  "scope": {"workspace_folder_ids": ["…"]}, "prompt": "…",
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
| 403 | `owner or admin required` | Tentou notificar outro usuário sendo membro comum |
| 404 | `automation not found` | Id inexistente, de outra organização, ou sem permissão de ver |
| 404 | `run not found` / `run_has_no_result` | Execução inexistente / sem resposta para PDF |
| 409 | `automation_limit_reached` | Organização já tem 20 automações |
| 422 | `scope_not_allowed` | Alguma pasta não existe ou o criador não tem acesso |
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
- `folder_changed`: depois de cada sync concluído, se alguma pasta do escopo teve documentos indexados/modificados
  desde a última execução, a automação roda uma vez por conjunto de mudanças (sem duplicar se o sync repetir).
