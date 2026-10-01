# M27 — Lint do backend no push 4e5ac95

- Responsável: pane-294; branch: `main`; status: corrigido e validado localmente, sem push.
- Escopo: reproduzir/corrigir Ruff sem alterar comportamento; validar backend; commit local, sem push.
- Execução remota: run `36888527278`, job backend `110457940596`, etapa 6
  `Lint backend (excluding recorded legacy files)`, exit 1. Frontend passou;
  testes, contrato e migrações do backend foram pulados após o lint.
- Limitação: `gh` não estava instalado; após instalação, `gh run list` e
  `gh run view --log-failed` retornam exit 4 por ausência de autenticação.
  A API pública retorna jobs e annotations, mas o download de logs retorna 403.
  Não foi possível extrair os erros detalhados nem a versão instalada dos logs remotos.
- Reprodução: Python 3.12.14, Ruff 0.16.7 e 0.16.9, snapshot isolado `4e5ac95`:
  `ruff check .` retorna 18 erros; o comando com exclusões do workflow retorna 9.
  O working tree atual reproduz os mesmos achados, sem precisar alterar arquivos concorrentes.
- Causa: 13 blocos de imports (I001), três alocações de TemporaryFile (SIM115),
  lista de classe sem ClassVar (RUF012) e variável desempacotada não usada (RUF059).
  As exclusões de arquivos legados cobrem somente sete migrações e dois achados em
  `test_answer_blocks.py`; não cobrem os nove achados em OCR/download/extração.
- Histórico: apenas um run de main disponível na API. O snapshot anterior ao push
  `aec0e90` também falha localmente (13 achados; quatro fora das exclusões).
  `0686275` adicionou dois achados de OCR/limits e `f6f1f73` sete de download/extração;
  o snapshot deste último já reproduz os 18 achados finais. Não há evidência de runs
  anteriores falhando: histórico de código não é histórico de execução de CI.
- Hipótese comprovada: os achados de OCR/download/extração são dívida anterior ao
  onboarding/cache; a reprodução isolada reproduz a falha fora das exclusões.
- Correção proposta: organizar imports, marcar a variável descartada, declarar
  ClassVar no spy e fechar arquivos de teste com context managers. Nos dois adaptadores,
  SIM115 exige uma exceção pontual documentada: o arquivo aberto é transferido ao
  chamador; um `with` interno fecharia o stream antes da extração. O tratamento de erro
  existente já fecha o arquivo em qualquer exceção e permanece intacto.

## Erros da reprodução do comando do CI

As mensagens abaixo são da reprodução local do snapshot enviado, não dos logs remotos.
Ruff 0.16.9 é a versão mais alta publicada antes do run que satisfaz `ruff>=0.8,<1`;
essa é a resolução esperada do install do CI, mas não foi confirmada pelo log de instalação.

| Arquivo em backend | Linha original | Regra / mensagem |
| --- | --- | --- |
| `app/ingestion/extraction/limits.py` | 1 | I001 — Import block is un-sorted or un-formatted |
| `app/ingestion/google_drive.py` | 3 | I001 — Import block is un-sorted or un-formatted |
| `app/integrations/google_drive.py` | 415 | SIM115 — Use a context manager for opening files |
| `app/integrations/http.py` | 3 | I001 — Import block is un-sorted or un-formatted |
| `app/integrations/onedrive.py` | 346 | SIM115 — Use a context manager for opening files |
| `tests/unit/test_extraction_stream.py` | 3 | I001 — Import block is un-sorted or un-formatted |
| `tests/unit/test_extraction_stream.py` | 17 | SIM115 — Use a context manager for opening files |
| `tests/unit/test_ocr_pdf_layers.py` | 103 | RUF012 — Mutable default value for class attribute |
| `tests/unit/test_remote_download.py` | 171 | I001 — Import block is un-sorted or un-formatted |

Os outros nove achados de `ruff check .`, também corrigidos, eram I001 em sete
migrações (`0011`, `0012`, `0014`, `0015`, `0016`, `0017`, `0018`), I001 na linha 3
e RUF059 (`Unpacked variable document is never used`) na linha 50 de `test_answer_blocks.py`.

## Evidência final

- Ruff 0.16.9 instalado em diretório temporário separado, sem alterar a venv compartilhada.
- Snapshot isolado `4e5ac95`, comando exato com exclusões: **9 erros, exit 1** antes;
  após aplicar somente os 16 arquivos desta correção: **All checks passed!, exit 0**.
  Prova independente das alterações concorrentes no working tree.
- Working tree, `ruff check . --extend-exclude <lista do workflow>`:
  **All checks passed!, exit 0** (Ruff 0.16.9).
- Working tree, `ruff check .`: **All checks passed!, exit 0** (Ruff 0.16.9).
- `.venv/bin/python -m pytest -q tests/unit tests/api`:
  **1237 passed, 4 warnings in 42.41s, exit 0**. Avisos de depreciação em
  Starlette/AnyIO/Alembic, nenhum erro. Inclui alterações concorrentes atuais;
  estas não integram o commit de lint.
- AST dos 12 arquivos de produção/migração comparada a HEAD: idêntica após normalizar
  a ordem dos imports; comentários/noqa não alteram a AST. Nenhuma alteração de schema.
- `.venv/bin/python scripts/export_openapi.py --check`: **OpenAPI export matches /v1, exit 0**.
- `.venv/bin/alembic heads`: **20260930_0026 (head), exit 0**, um único head.
- `graphify update .`: **5925 nodes, 17287 edges, 354 communities, exit 0**.
  Artefatos gerados do grafo ficam fora do commit de lint.
- `git diff --check`: **exit 0**.
- PostgreSQL 16 + pgvector em container/banco descartável separado dos dados locais:
  `.venv/bin/alembic upgrade head`: **exit 0**;
  `.venv/bin/python -m pytest -q -m postgres tests/integration`:
  **14 passed, 1 warning in 65.01s, exit 0**. Container de teste removido após o teste.

## Arquivos corrigidos

- `backend/alembic/versions/20260912_0011_oauth_reauth_source.py`
- `backend/alembic/versions/20260913_0012_company_library.py`
- `backend/alembic/versions/20260915_0014_workos_session_logout.py`
- `backend/alembic/versions/20260923_0015_onedrive_delta_checkpoints.py`
- `backend/alembic/versions/20260923_0016_onedrive_account_binding.py`
- `backend/alembic/versions/20260928_0017_agent_conversations.py`
- `backend/alembic/versions/20260929_0018_manual_sync_runs.py`
- `backend/app/ingestion/extraction/limits.py`
- `backend/app/ingestion/google_drive.py`
- `backend/app/integrations/google_drive.py`
- `backend/app/integrations/http.py`
- `backend/app/integrations/onedrive.py`
- `backend/tests/unit/test_answer_blocks.py`
- `backend/tests/unit/test_extraction_stream.py`
- `backend/tests/unit/test_ocr_pdf_layers.py`
- `backend/tests/unit/test_remote_download.py`

skills: inline [oc-builder, oc-blackbox, oc-stamp]
