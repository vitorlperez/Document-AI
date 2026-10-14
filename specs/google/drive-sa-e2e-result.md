# M58 — resultado do teste E2E local do e-mail-robô (14/10/2026)

Ambiente: stack docker local (`migrate api worker beat frontend`), org First Org, flags `GOOGLE_DRIVE_SA_ENABLED=true` e `NEXT_PUBLIC_DRIVE_SHARE_ENABLED=1` somente no `.env` local (ignorado pelo git), `GOOGLE_SA_KEY_ENCRYPTION_KEY` Fernet gerada localmente. Robô real `arq-poc-a` (projeto arquivio-drive-poc) importado cifrado para o pool local; nenhum robô novo no GCP. Nenhum compartilhamento do Drive foi alterado. Screenshots: `/private/tmp/claude-501/drive-sa-e2e/`.

## Veredito: parcial — fluxo até a primeira sincronização funciona com o Drive real; indexação e chat bloqueados por chave OpenAI local inválida

## Passo a passo

| # | Passo | Resultado | Evidência |
|---|---|---|---|
| 1 | Integrações → Google Drive → modal de método | OK (após correção B1) | `02-modal-metodo.png` |
| 2 | Passo 1: e-mail do robô exibido | OK (`arq-poc-a@…`) | `03-passo1-email-robo.png` (inbox vazio simulado só para capturar o passo 1; com o inbox real o passo 1 avança sozinho) |
| 3 | Inbox real detecta `poc-main` (+4 pastas do PoC) | OK, `GET /inbox` 200 | `04-passo2-inbox-detecta-poc-main.png` |
| 4 | Verificar `poc-main` | OK: 14 arquivos, download liberado (~20 s) | `05-passo3-verificacao.png` |
| 5 | Escolher o que sincronizar (vínculo + seleção) | OK após B2; `POST /folders` 200, catálogo mostra `poc-main` | `06-catalogo-escopo.png` |
| 6 | Sync dispara no worker e o robô lista/baixa arquivos reais do Drive | OK (`files.get`/`files.list` pelo worker) | logs do worker |
| 7 | Indexação | **FALHA ambiental**: `embedding_failed` — `POST api.openai.com/v1/embeddings` → 401 (chave do `.env` local inválida; confirmado com `GET /v1/models` 401) | logs do worker |
| 8 | Documentos na Biblioteca / pergunta no chat citando arquivo | **Não verificado** (depende de 7) | — |
| 9 | `poc-link-public` colada como link | Recusada: 404 `not_shared`, checklist “falhou” em “consegue abrir a pasta” | `09-poc-link-public-recusada.png` |
| 10 | Link inválido | Mensagem PT-BR + exemplo (após B3) | `08-link-invalido.png` |

## Alinhamento ao contrato final (frontend)
- `state()` agora usa `GET /data-sources/google-sa/{id}/folders` → `{folders:[{link_id,…}]}` (sem fallback para inbox); `id` do card = `link_id`; vínculos `removed` ocultos; `suspect` exibido como acesso removido; sem “contando arquivos” (o backend não expõe `file_count` na listagem).
- `DELETE` já usava `link_id`; erros `unauthenticated`/`forbidden`/`invalid_request` ganharam mensagens PT-BR.
- Após `POST /folders` o frontend inicia a primeira sync (`POST /library/workspaces/{workspace_folder_id}/reprocess`, melhor esforço).
- Estado de acesso por pasta na Biblioteca: o backend não expunha; adicionado `access_state` (`access_lost` para suspect/access_lost, `purge_scheduled`) e `purge_after` nos nós de pasta de `/library/nodes/{id}/children` (teste novo, red→green).

## Bugs encontrados
- **B1 (frontend)** com uma fonte OAuth Google já existente (mesmo `reauth_required`), clicar no card chamava `connect(id)` e o modo e-mail-robô ficava inalcançável. Corrigido: com a flag ligada o modal de método sempre abre; “Entrar com a conta Google” reconecta a fonte existente.
- **B2 (backend, 500)** `POST /folders`: `source.status="connected"` não era flushado e `select_scope` relia a fonte (sessão real usa `autoflush=False`; os testes usavam autoflush) → `GoogleAccessDenied` não tratado. Corrigido com `flush()`; teste de regressão com sessão sem autoflush (red→green).
- **B3 (frontend)** `<input type="url">` mostrava o balão nativo “Please enter a URL.” no lugar da mensagem PT-BR. Corrigido com `noValidate`.
- **B4 (UX, não corrigido)** `verify` e `link` levam ~20 s cada (reverificação completa com amostra de download); o link repete a verificação. Sugestão: reaproveitar resultado recente ou reduzir a amostra.
- `enable` é chamado 2× ao abrir a tela (card + modal); inofensivo (idempotente).

## Pendências
1. Fornecer `OPENAI_API_KEY` válida no `.env` local e repetir passos 7–8 (sync completa, documentos na Biblioteca, pergunta citando arquivo de `poc-main`, badge “acesso removido” da Biblioteca sem teste visual).
2. Configuração local nova: `docker-compose.yml` repassa `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` (vazio por padrão).
