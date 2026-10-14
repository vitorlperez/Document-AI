# M58 — Google Drive e-mail-robô: contrato backend

Todas as rotas exigem sessão autenticada e `organization_id` (query UUID), com papel Owner/Admin. Disponíveis somente com `GOOGLE_DRIVE_SA_ENABLED=true` e organização permitida por `GOOGLE_SA_ALLOWED_ORGS` (vazio = todas). Nenhum segredo retorna à UI. OAuth continua no provider `google_drive`.

Erros: `{"detail":{"code":"not_shared"}}`. Status e corpo idênticos para ID inexistente e sem acesso. Codes: `disabled` (404), `not_shared` (404, também fonte/vínculo de outro tenant e link público), `invalid_folder_link` (422), `not_a_folder` (422), `pool_empty` (503), `robot_unavailable` (503), `rate_limited` (429), `forbidden` (403), `invalid_scope` (422). Falhas transitórias remotas: `provider_unavailable` (503).

- `POST /data-sources/google-sa/enable`: sem body. 200 `{"source_id":"uuid","robot_email":"robot@project.iam.gserviceaccount.com","share_role":"reader"}`. Idempotente por organização; pool pré-criado, robô nunca reciclado.
- `GET /data-sources/google-sa/{source_id}/inbox`: 200 `{"folders":[{"id":"drive-id","name":"Contratos","shared_by_email":"user@example.com","shared_at":"ISO8601","linked":false}]}`. Lista somente compartilhamentos explícitos. Limite de polling por organização.
- `POST /data-sources/google-sa/{source_id}/folders/verify`: body `{"url_or_id":"https://drive.google.com/drive/folders/drive-id"}`. 200 `{"code":"ok","folder_id":"drive-id","name":"Contratos","shared_by_email":"user@example.com","shared_at":"ISO8601","file_count":12,"blocked_download_count":0}`. `code` pode ser `download_blocked_partial`. Faz files.get antes da listagem, exige compartilhamento explícito na pasta ou ancestral (até 10 saltos), ignora atalhos. Não cria vínculo.
- `POST /data-sources/google-sa/{source_id}/folders`: body `{"folder_id":"drive-id"}`. Revalida acesso. 200 `{"link_id":"uuid","workspace_folder_id":"uuid","folder_id":"drive-id","status":"verified"}`. Idempotente; cria vínculo explícito e seleção kind=folder. Biblioteca pode pedir sync pela rota atual.
- `DELETE /data-sources/google-sa/{source_id}/folders/{link_id}?purge=false`: 200 `{"link_id":"uuid","status":"purge_scheduled","purge_after":"ISO8601"}`. Oculta imediatamente; apaga após 14 dias. Com purge=true: status=removed, purge_after=null.
- `POST /data-sources/google-sa/{source_id}/recheck`: sem body. 200 `{"links":[{"link_id":"uuid","status":"verified","purge_after":null}]}`. Primeiro sinal de revogação: suspect e conteúdo oculto imediatamente; segunda checagem após >=1h: access_lost, retenção 14 dias desde ocultação. Recompartilhamento restaura e zera cursor.
- `DELETE /data-sources/{source_id}?organization_id=uuid`: resposta existente. Para SA aposenta definitivamente o robô, oculta vínculos e agenda expurgo; não reutiliza identidade.

`GET /data-sources/{source_id}/scope-catalog`: para SA lista apenas pastas vinculadas verified; root_files e all_accessible indisponíveis no MVP. `POST /data-sources/{source_id}/scope` aceita exclusivamente kind=folder já verificado/vinculado à organização. `uniform_access_confirmed=true` obrigatório conforme contrato existente.

Configuração: `GOOGLE_SA_KEY_ENCRYPTION_KEY` Fernet dedicado; `GOOGLE_SA_ALLOWED_ORGS` UUIDs separados por vírgula; `GOOGLE_SA_DOWNLOAD_WORKERS` default 3. Shared Drives/Workspace/grupos permanecem sem validação real; MVP exige sharedWithMeTime.
