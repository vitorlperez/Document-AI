Biblioteca: modal de sincronizações e resync completo

Resultado: o painel direito saiu da Biblioteca. Ferramentas permanecem à esquerda, com ação de ressincronização por integração; arquivos/pastas ocupam o centro, com rolagem independente no desktop, busca, breadcrumbs e voltar. O botão Sincronizações abre um dialog nativo (foco contido, Escape e retorno de foco), com polling de 3 segundos, histórico manual, contagens, datas, usuário, falhas por documento e as ações/detalhes dos espaços sincronizados.

Execuções manuais de pasta, integração e espaço da Biblioteca geram ManualSyncRun persistido. Os jobs vinculados fazem descoberta completa: Google ignora o checkpoint; OneDrive enumera o snapshot; Notion ignora a data conhecida. O reconciliador força reconstrução dos documentos do escopo mesmo com hash idêntico. Pasta inclui descendentes existentes e novos informados pelo catálogo remoto. Integração abrange todos os espaços autorizados da fonte. O scheduler automático segue seu caminho incremental.

Comandos e resultados:

- `graphify query 'LibraryScreen manual resync integration folder synchronization history'`: exit 127, comando indisponível.
- Testes novos antes da implementação: `backend/.venv/bin/pytest backend/tests/api/test_company_library_api.py -q`: exit 1, 2 failed / 5 passed (ausência de histórico e resync de integração).
- `backend/.venv/bin/pytest backend/tests/unit/test_google_drive_ingestion.py backend/tests/unit/test_onedrive.py backend/tests/unit/test_notion_integration.py backend/tests/api/test_company_library_api.py -q`: exit 0, 60 passed na execução dessa etapa.
- `cd backend && .venv/bin/pytest -q`: exit 0, 459 passed / 8 skipped / 4 warnings, 24.54 s.
- Teste final reforçado com subpasta remota nova: `backend/.venv/bin/pytest backend/tests/api/test_company_library_api.py -q`: exit 0, 9 passed / 2 warnings.
- `cd frontend && npx tsc --noEmit`: exit 0, sem erros.
- `cd frontend && npm run lint`: exit 0, sem erros ou warnings do ESLint.
- `cd frontend && npm run build`: exit 0, cinco etapas do Vinext concluídas. Avisos de NO_COLOR/FORCE_COLOR e classificação estática de algumas rotas emitidos pelo framework.
- Ruff nos módulos alterados de API/library/ingestion: exit 0, All checks passed.
- `docker compose exec -T api alembic upgrade head`: exit 0. Inspeção fresh confirmou manual_sync_runs e processing_jobs.manual_run_id no PostgreSQL local.
- `curl -sf .../health/live`: exit 0, status ok após reinício da API.
- `git diff --check`: exit 0 após ajuste dos finais de arquivo dos testes.
- `graphify update .`: exit 127, comando indisponível; os artefatos graphify existentes não foram editados por este worker.

Cobertura nova: recursividade de pasta e integração, nova subpasta remota, arquivos novos/com falha, escopo/autor/status/datas/contagens persistidos, vários espaços por integração, deduplicação de arquivos sobrepostos, hash idêntico reconstruído, histórico após exclusão do espaço, falha da fila persistida e conflito com job ativo. Há testes de full snapshot nos três conectores; os testes existentes de sync incremental passam.

Navegador: Chrome nativo via cua_repl, usando a sessão local já aberta. Resync real da pasta Test Document-AI: 2/2 arquivos processados, 0 falhas; andamento e término chegaram pelo polling. Histórico confirmado após recarga; botão voltar, abertura/fechamento do dialog e Escape verificados. Com 100 itens, a lista central rolou e ferramentas/busca permaneceram fixas.

Prints (PNG):

- artifacts/library-resync/library-tools.png
- artifacts/library-resync/library-files.png
- artifacts/library-resync/library-scrolled.png
- artifacts/library-resync/sync-running.png
- artifacts/library-resync/sync-completed.png

Arquivos deste trabalho (incluem arquivos que já estavam modificados antes do worker):

- frontend/app/product-app.tsx
- frontend/app/chat-workspace.css
- backend/app/api/library.py
- backend/app/library/models.py
- backend/app/library/service.py
- backend/app/library/manual_sync.py (novo)
- backend/app/ingestion/models.py
- backend/app/ingestion/service.py
- backend/app/ingestion/tasks.py
- backend/app/ingestion/google_drive.py
- backend/app/integrations/base.py
- backend/app/integrations/registry.py
- backend/app/integrations/notion.py
- backend/app/integrations/onedrive.py
- backend/alembic/versions/20260929_0018_manual_sync_runs.py (novo)
- backend/tests/api/test_company_library_api.py
- backend/tests/unit/test_google_drive_ingestion.py
- backend/tests/unit/test_onedrive.py
- backend/tests/unit/test_notion_integration.py
- artifacts/library-resync/validation.md e os cinco PNGs

Limitações:

- Os 8 testes marcados postgres exigem TEST_DATABASE_URL descartável e foram skipped; não houve downgrade destrutivo do banco local. O upgrade real da migration foi verificado.
- Google foi validado com worker/credenciais reais; OneDrive e Notion, por testes com providers simulados. Não houve validação visual mobile.
- Para descobrir arquivos novos sem ampliar o escopo autorizado, resync de pasta enumera os espaços daquela fonte por completo; o force de reconstrução e as contagens ficam restritos à pasta/subpastas. Isso pode tornar a descoberta mais demorada em fontes grandes.
- As contagens atualizam por fase (descoberta/reconciliação), não a cada download. O histórico exibido limita-se às 100 execuções mais recentes; os registros anteriores permanecem persistidos.
- Os endpoints novos são utilizados pelas ações da Biblioteca. A tela de Integrações e o endpoint legado /workspace-folders/{id}/sync não foram reformulados nesta tarefa.
- Para conferir no navegador, arquivos específicos foram copiados aos containers api/worker/frontend e a API/worker foram reiniciados. A atualização de código nesses containers é temporária: recriar containers exige rebuild das imagens. A migration aplicada no PostgreSQL local é persistente.
- Nenhum commit ou push foi feito. Nenhum dos arquivos vedados no briefing foi editado por este worker.

skills: inline [oc-builder, oc-stamp]
