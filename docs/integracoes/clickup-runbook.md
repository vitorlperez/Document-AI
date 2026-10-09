# ClickUp — runbook de ativação e piloto

Decisões e limites: `specs/adr/ADR-0019-clickup-connector.md`.

## 1. Criar o app OAuth (ação humana, ~10 min)

1. No ClickUp, com um usuário que possa criar apps: **Settings → Apps → Create new app** (`https://app.clickup.com/settings/apps`).
2. Nome: o do produto. **Redirect URL:** exatamente `https://<domínio-da-API-ou-app>/api/data-sources/clickup/oauth/callback` (em Railway, o mesmo valor de `CLICKUP_OAUTH_REDIRECT_URI`; o ClickUp pode recusar HTTP sem TLS no futuro).
3. Copie **Client ID** e **Client Secret**.
4. Gere a chave de cifra do provider (terminal seguro):
   `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
5. Na **API**, defina `CLICKUP_OAUTH_CLIENT_ID`, `CLICKUP_OAUTH_CLIENT_SECRET`, `CLICKUP_OAUTH_REDIRECT_URI` e `CLICKUP_TOKEN_ENCRYPTION_KEY`. No **worker**, a chave `CLICKUP_TOKEN_ENCRYPTION_KEY` deve ser exatamente a mesma da API. Opcional: `CLICKUP_INCLUDE_CLOSED_TASKS=true`. O sync lê o access token salvo; client ID, secret e redirect URI são exigidos por `authorization_url`/`exchange_code` na API, não pelo caminho de descoberta/indexação do worker. [Autenticação ClickUp](https://developer.clickup.com/docs/authentication).
6. Na ativação inicial, publique os serviços que receberam configuração. Sem as variáveis OAuth na API, o botão "Conectar" devolve "integration unavailable" (503). Para corrigir somente uma chave divergente no worker de uma conexão existente, preserve a chave da API, aplique-a no worker sem deploy automático e faça redeploy controlado somente do worker; valide Settings, banco, Redis, Celery e a descriptografia antes de repetir o sync. Não gere outra chave nem reconecte o usuário para corrigir essa divergência.

## 2. Cota de documentos (decidir antes do piloto)

Tarefas viram um documento cada. O teto por organização é `ACTIVE_DOCUMENT_LIMIT` (padrão do código: 500, ADR-0003).

**Decisão (2026-10-07): valor inicial `ACTIVE_DOCUMENT_LIMIT=1500` na API e no Worker do Railway** (só o Worker aplica o teto de fato; a API apenas enfileira) (3× o padrão). Base da escolha, só com limites que o projeto já tem:

- `MONTHLY_LIMITS["embedding_tokens"] = 1_000_000` por organização/mês (`app/audit_usage/service.py`, constante de código, não variável de ambiente). Estimativa (não medida): uma tarefa tem 150–400 tokens (título, fatos, descrição); o orçamento é compartilhado com perguntas e com as outras fontes, e o teto de documentos conta todos os documentos indexados da organização, não só os do ClickUp; 1.500 documentos ≈ 225–600 mil tokens, ou seja, 22–60% do orçamento do mês no pior caso, sobrando margem para reindexações e perguntas.
- `processed_bytes` (2 GB/mês) não é restrição: 1.500 tarefas são poucos MB.
- Armazenamento: ~6 KB de vetor por chunk no Postgres, ou cerca de 9–15 MB para 1.500 documentos.
- Subir o limite além de ~3.000 documentos **não adianta** sem também subir `MONTHLY_LIMITS["embedding_tokens"]` (mudança de código e revisão de custo): o orçamento mensal de embeddings acaba antes.

Critério para subir: depois da primeira sincronização, `embedding_tokens` do mês abaixo de 60% e documentos ativos acima de 80% do teto → subir em degraus (1.500 → 2.500) junto com a revisão do orçamento de embeddings. Enquanto isso, orgs com mais tarefas abertas que o teto devem selecionar só os Spaces/Lists relevantes (ou, para incluir tarefas fechadas, `CLICKUP_INCLUDE_CLOSED_TASKS=true` só depois de subir o teto).

## 3. Checklist do piloto (precisa de um workspace real)

- [ ] Conectar como Owner/Admin autorizando um Workspace de teste; a tela volta com `?connected=clickup` e o card mostra o e-mail da conta.
- [ ] Gerenciar → o catálogo mostra Workspace › Space › Folder › List; criar um espaço de sincronização numa List pequena e confirmar `uniform_access_confirmed`.
- [ ] Sincronizar: a biblioteca mostra `ClickUp › Workspace › … › tarefa`; fazer uma pergunta sobre o conteúdo de uma tarefa e conferir a citação (link abre a tarefa no ClickUp).
- [ ] Editar uma tarefa no ClickUp e ressincronizar: só ela é re-lida/re-embedada; apagar uma tarefa: ela some da biblioteca e das respostas.
- [ ] Docs: criar um Doc com subpágina e confirmar que ambos aparecem no texto indexado. Se o plano não expõe Docs v3, a sincronização das tarefas deve continuar normalmente.
- [ ] Revogar o app no ClickUp (Settings → Apps) e sincronizar: a fonte vira "Reconectar" sem 500 e sem perder o que já foi indexado.
- [ ] Anotar o tempo da primeira sincronização e o uso (100 req/min no plano Business ou inferior).

## 4. Diagnóstico

| Sintoma | Causa provável |
|---|---|
| `integration unavailable` ao conectar | variáveis `CLICKUP_*` ausentes na API |
| Conectou, catálogo vazio | nenhum Workspace foi autorizado na tela do ClickUp; reconectar e marcar o Workspace |
| Sincronização "limite de documentos" | `ACTIVE_DOCUMENT_LIMIT` (seção 2) |
| Sincronização lenta/pausando | teto de 100 req/min; o `RemoteHttp` espera `Retry-After` e retoma |
| Tarefas apagadas no ClickUp continuam citáveis | uma Lista devolve 403/404 em toda sincronização (o sistema não declara remoção de tarefas enquanto alguma lista está ilegível); corrija o acesso do usuário conector à Lista ou tire-a da seleção |
| Fonte vira "Reconectar" | token revogado (401); reconectar com a mesma conta |

## 5. Chave divergente entre API e worker

Se a API abre a conexão salva e o worker falha com `credential unavailable` antes de consultar o ClickUp, compare as chaves somente em memória e registre apenas igualdade booleana. Preserve a chave que abre a conexão na API; altere somente `CLICKUP_TOKEN_ENCRYPTION_KEY` no worker. Nunca passe o valor em argumentos CLI, logs ou arquivos.

Antes do redeploy, confira filas e tarefas ativas/reservadas/agendadas. Depois do startup, comprove no container novo a descriptografia da mesma fonte. Repita no máximo um sync normal do espaço solicitado, usando o fluxo existente com bloqueio/unique index e histórico novo; não reutilize ou apague os jobs falhados, não force rebuild e não dispare o scheduler. Se aparecer outra falha, registre a causa antes de ampliar mudanças.

Caso de produção de 08/10/2026: [evidência sanitizada](../../TASK/evidence/clickup-sync-20261008-investigation.json). Os watch paths atuais de Railway cobrem `/backend/**` ou `/frontend/**`, além de `/railway.json` e `/railway.toml`; alterações somente em docs/TASK não devem redeployar serviços. Confirme o estado remoto após o push.
