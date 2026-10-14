# M58 — evidência backend F1–F3

Implementação em 14/10/2026. Contrato publicado antes do código (`f97acf2`); F1 `b3e5cb3`; F2 `dc746b0`. F3 inclui operação offline, verificação PostgreSQL e endurecimento de retenção/autenticação. Sem push, deploy, alteração em frontend ou provisionamento IAM real.

Cabeça Alembic conferida antes da implementação: `20261013_0031`. Nova migração: `20261014_0032`, down_revision=`20261013_0031`; também testada em PostgreSQL real descartável. Tabelas: google_sa_projects, google_sa_identities, drive_folder_links; coluna DataSource.sa_identity_id e índice único por org/provider. Trigger impede reciclagem e alteração de organização após atribuição. last_reconciled_at permite snapshot diário sem modifiedTime.

Prova final (cwd=backend):

```sh
.venv/bin/pytest tests/unit/test_google_drive_sa.py tests/unit/test_google_drive_sa_service.py tests/unit/test_google_drive_connection.py tests/unit/test_google_drive_ingestion.py tests/api/test_google_integrations.py tests/api/test_google_drive_sa_api.py tests/unit/test_ingestion_tasks.py tests/unit/test_ingestion_scheduler.py tests/unit/test_registry_context.py tests/unit/test_provider_keyring.py tests/unit/test_migration_sql.py tests/api/test_document_view_api.py tests/api/test_route_authorization.py tests/unit/test_drive_sa_pool.py -q --tb=short
```

Saída: `185 passed, 2 warnings in 8.49s`, exit 0. Warnings preexistentes de Starlette/AnyIO e configuração Alembic. Inclui toda a suíte google_drive OAuth solicitada (connection, ingestion, integrations API), autorização, visualização de documentos, scheduler e cifras.

PostgreSQL: `TEST_DATABASE_URL=<banco descartável> .venv/bin/pytest tests/integration/test_drive_sa_postgres.py -q --tb=short` → `1 passed in 2.57s`, exit 0. Verifica upgrade/downgrade, coluna de reconciliação, duas organizações simultâneas recebendo robôs distintos, duas chamadas simultâneas na mesma organização recebendo o mesmo robô, trigger contra reassignment e retorno ao pool. Banco temporário criado e removido separadamente; nenhum banco da aplicação migrado.

Ruff nos arquivos Python alterados/adicionados: `All checks passed!`, exit 0. `docker compose config --quiet`: exit 0. `git diff --check`: exit 0. `graphify update .`: exit 0, AST-only; 10111 nós/29501 arestas na última execução. Saída graphify-out permaneceu fora dos commits. PDF extraction do Graphify opcional indisponível na primeira execução; extração AST concluída.

TDD: testes novos antes do respectivo módulo/rota/script; falhas iniciais verificadas. Regressões com red→green explícito: URL legado /a/dominio/drive, chave privada inválida vira RobotUnavailable, autenticação com code estável, retenção não estendida por unlink, expurgo de união preserva outro vínculo. Isolamento de dois tenants testado em API/serviço e concorrência PostgreSQL.

Os 8 ajustes da PoC:

1. removed da raiz interrompe descoberta antes de qualquer retorno destrutivo; raiz GET inacessível marca suspect e oculta imediatamente, chunks preservados; segunda falha >=1h confirma access_lost.
2. Sem campo permissions; escopo JWT drive.readonly; backend aceita leitura independentemente do papel Reader/Commenter/Editor. Textos da UI ficam com o pane frontend.
3. cannotExportFile em ITEM_FORBIDDEN_REASONS; capabilities.canDownload nas listagens/feed SA; item bloqueado não baixado; exportSizeLimitExceeded tenta text/plain, MIME de extração acompanha fallback.
4. Verify exige files.get bem-sucedido antes de qualquer files.list; erros id inexistente/sem acesso iguais (404/not_shared).
5. Compartilhamento explícito comprovado subindo parents, máximo 10 saltos; público bloqueado; atalhos não seguidos.
6. changes.list + escopo de seleção; snapshot diário e reconciliação por alterações de ancestralidade; nenhuma consulta por modifiedTime.
7. Token source confere access_token, assina iat=agora−30s/exp<=1h, cache local thread-safe; workers configuráveis 1–3; falha do robô = provider_error, nunca reauth_required.
8. Script IAM offline com throttle 3/min, advisory lock por projeto, chave cifrada dedicada, quota registrada e alerta pool<10. Exceção orgpolicy e ausência de armazenamento documentadas.

Retenção: suspect oculta documentos e evidências imediatamente; confirmação + notificação Owner/Admin após >=1h. Purge após 14 dias do primeiro sinal, não estendido por unlink; opcional purge=true. Recuperação checada antes de purge; reativa e zera cursores. União conservadoramente oculta enquanto houver vínculo inválido; purge remove somente documentos da raiz revogada. OCR SA sem cache persistente para não reter texto órfão por 90 dias. Publicação de cada batch/finalização trava e revalida vínculos contra unlink concorrente.

Novas envs runtime: GOOGLE_DRIVE_SA_ENABLED=false, GOOGLE_SA_KEY_ENCRYPTION_KEY, GOOGLE_SA_KEY_ENCRYPTION_PREVIOUS_KEYS, GOOGLE_SA_ALLOWED_ORGS, GOOGLE_SA_DOWNLOAD_WORKERS=3. Configuração/documentação e forwarding no ambiente Docker backend; nenhuma credencial IAM no runtime. DRIVE_SA_POOL_IAM_TOKEN é opcional apenas para script offline (alternativa: gcloud auth).

Pendências externas: provisionar pool real e configurar envs/flag, exceção IAM de projeto quando necessária; excluir chaves IAM dos robôs aposentados via comando offline retire-keys (runtime apaga imediatamente a cifra local); validar Google Workspace/Shared Drives/alias/grupos e política CASA. Identidade aposentada continua permanente, enable retorna robot_retired até intervenção operacional. Nenhum teste de rede live executado em contas Google do cliente.

Arquivos principais: backend/app/integrations/{google_drive_sa.py,google_drive_sa_service.py,google_sa_models.py,registry.py,models.py,google_drive.py}; backend/app/api/{drive_sa.py,integrations.py,evidence.py}; backend/app/ingestion/{google_drive.py,tasks.py}; backend/app/core/config.py; backend/app/main.py; backend/alembic/env.py e versions/20261014_0032_drive_service_accounts.py; scripts/drive_sa_pool.py; testes google_drive_sa/API/serviço/pool/PostgreSQL e atualização do teste da cabeça Alembic; .env.example e docker-compose.yml; contrato e operações nesta pasta.

skills: inline [oc-builder, oc-stamp].
