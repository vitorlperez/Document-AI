# Evidência F6 — 2026-09-30

Skills: inline [oc-builder, oc-stamp]. Branch: feat/integracoes. Sem push.

Prefixo de validação: `cd backend && PYTHONPYCACHEPREFIX=/tmp/f6-pycache PYTHONPATH=/tmp/f6-test-bootstrap .venv/bin/python -S -m pytest`. A cópia temporária reproduz as 75 versões instaladas no `.venv` e evita imports dataless do iCloud. O `-S` impede que metadados de pacotes no iCloud voltem a entrar pela descoberta de plugins.

- Vermelho da cerca: `-q tests/unit/test_untrusted_fencing.py --tb=no`: **31 failed**, exit **1**.
- Vermelho da apresentação: `-q tests/unit/test_presentation.py`: módulo ausente, exit **2**. Teste posterior do guard no serviço: **1 failed, 3 passed**, exit **1** antes do fix.
- Novos testes independentes: `-q tests/unit/test_untrusted_fencing.py tests/unit/test_presentation.py tests/unit/test_injection_eval.py -k 'not insufficient_fallback'`: **37 passed, 1 deselected**, exit **0**.
- Regressão disponível: os três arquivos anteriores + `tests/unit/test_semantic_questions.py -k 'not insufficient_fallback and not external_file_ids_from_distinct_sources and not broad_scope_empty_context'`: **83 passed, 3 deselected**, exit **0**. Os três excluídos precisam dos imports da extração/F4; não foram declarados verdes.
- Suíte completa `-q`: **43 erros de coleta**, exit **2**, incluindo `ExtractedBlock` ausente em `ingestion/blocks.py`, exports ausentes em `extraction/__init__.py` e `extraction.cache` ainda ausente. Arquivos da área F4, fora do limite de edição desta pane. `cat` e `brctl download` (relativos e absolutos) não materializaram esses arquivos.
- Ruff nos arquivos F6: **All checks passed**, exit **0**. `git diff --check` no pathspec F6: exit **0**.
- `graphify update .` depois do commit dos testes: exit **0**, 4913 nodes / 13726 edges; atualização final depois do commit de implementação também requerida.

Entregue: corpus único (14 casos, seis IDs do plano 03), cerca/nonce/Unicode, rollback default true, JSON de resumos limpo (L-7), sanitização do fallback (L-8), extração do módulo de apresentação com aliases HTTP, imagens/links com parser balanceado, guarda nos objetos de resultado antes de validar citações, log só da contagem, eval manual que inspeciona saída bruta e protegida e ADR-0015.

Pendente: T6.4 (`strip_invisible` em sanitize_blocks + DOCX w:vanish), teste L-8 em runtime, invariante read-only em runtime e regressão API/agente completa depois que F4 recuperar os imports. O teste T6.4 está entregue; a implementação deve ser feita pela dona da F4 para respeitar o GATE. Nenhum arquivo extraction/*, blocks.py, OCR ou migração 0021 foi editado nesta pane.

Gate vivo: `injection_eval.py` manual não executado (42 chamadas reais para este corpus, com três repetições), por economia de tokens. Não declarar F6/release aprovado até obter zero vazamentos e suíte completa verde.

Desvio de commit: config.py contém OCR concorrente. O índice temporário inclui apenas source_fencing_enabled reconstruído sobre HEAD, junto do pathspec exclusivo F6; commit-tree/update-ref atômico preserva o working tree OCR e demais mudanças concorrentes.

## Avaliação viva (gate F6) — 2026-09-30

Comando: `cd backend && OPENAI_API_KEY=*** PYTHONPATH=. .venv/bin/python scripts/injection_eval.py` (gpt-5-mini, 14 casos × 3 repetições). Resultado: **42 runs, 0 failures**, exit **0** — nenhum vazamento de canário nem de link (saída bruta e protegida). Relatório: `backend/scripts/reports/injection-eval-2026-09-30.json`. Isto fecha o "Gate vivo" acima; a suíte completa verde continua exigida no fim da missão.
