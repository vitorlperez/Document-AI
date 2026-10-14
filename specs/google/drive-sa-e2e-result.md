# M58 — resultado do teste E2E local do e-mail-robô (14/10/2026)

Ambiente: stack docker local (`migrate api worker beat frontend`), org First Org, flags `GOOGLE_DRIVE_SA_ENABLED=true` e `NEXT_PUBLIC_DRIVE_SHARE_ENABLED=1` somente no `.env` local (ignorado pelo git), `GOOGLE_SA_KEY_ENCRYPTION_KEY` Fernet gerada localmente. Robô real `arq-poc-a` (projeto arquivio-drive-poc) importado cifrado para o pool local; nenhum robô novo no GCP. Nenhum compartilhamento do Drive foi alterado. Screenshots: `/private/tmp/claude-501/drive-sa-e2e/`.

## Veredito: ponta a ponta OK com o Drive real (2ª rodada, com OPENAI_API_KEY válida)

## Passo a passo

| # | Passo | Resultado | Evidência |
|---|---|---|---|
| 1 | Integrações → Google Drive → modal de método | OK (após correção B1) | `02-modal-metodo.png` |
| 2 | Passo 1: e-mail do robô exibido | OK (`arq-poc-a@…`) | `03-passo1-email-robo.png` (inbox vazio simulado só para capturar o passo 1; com o inbox real o passo 1 avança sozinho) |
| 3 | Inbox real detecta `poc-main` (+4 pastas do PoC) | OK, `GET /inbox` 200 | `04-passo2-inbox-detecta-poc-main.png` |
| 4 | Verificar `poc-main` | OK: 14 arquivos, download liberado (~20 s) | `05-passo3-verificacao.png` |
| 5 | Escolher o que sincronizar (vínculo + seleção) | OK após B2; `POST /folders` 200, catálogo mostra `poc-main` | `06-catalogo-escopo.png` |
| 6 | Sync dispara no worker e o robô lista/baixa arquivos reais do Drive | OK (`files.get`/`files.list` pelo worker) | logs do worker |
| 7 | Indexação (1ª rodada: `embedding_failed`, chave OpenAI local inválida → 401; 2ª rodada com chave nova) | OK: job `ready`, 14/14 documentos `indexed` | `10-card-conectado.png` |
| 8a | Biblioteca: fonte “Google Drive (pasta compartilhada)” → `poc-main` com 14 arquivos “Indexado” | OK (após B5) | `11-biblioteca-fonte.png`, `12-biblioteca-poc-main.png` |
| 8b | Chat: “O que diz o arquivo raiz-2.txt? Qual o código entre colchetes?” | OK (após B6): resposta com o código `[b0c9ae620d7f830a]` e fonte `raiz-2.txt · Google Drive (pasta compartilhada)` | `14-chat-resposta-cita-arquivo.png` |
| 8c | Badge de acesso removido na Biblioteca e no card (simulado desvinculando pelo ArquivIO via `DELETE …/folders/{link_id}`; compartilhamento do Drive intocado) | OK: “Acesso removido · apagando em 14 dias”, botão “Apagar agora”; re-vínculo restaurou `verified` | `15-biblioteca-acesso-removido.png`, `16-card-acesso-removido.png` |
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
- **B5 (backend+frontend)** raiz da Biblioteca aparecia como “Google Drive Sa” (nome gerado de `provider.title()`) e com ícone genérico. Corrigido: nome “Google Drive (pasta compartilhada)”, ícone Google e rótulo no seletor do chat.
- **B6 (backend)** chat com “Todas as ferramentas” falhava com “provider is invalid”: `google_drive_sa` não estava em `SELECTABLE_PROVIDERS`. Corrigido com teste (red→green).
- `enable` é chamado 2× ao abrir a tela (card + modal); inofensivo (idempotente).

## Pendências
1. B4 (latência ~20 s de verify/link).
2. Configuração local nova: `docker-compose.yml` repassa `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` (vazio por padrão). Revogação real pelo dono (suspect → access_lost) não foi exercitada (sem mexer nos compartilhamentos); coberta só por testes de backend.
