# Spike 0.2 — biblioteca com muitos itens (o limite de 500 documentos ativos)

Data: 2026-10-19 · Escopo: **somente medição e leitura; nenhum código de produção foi alterado, o limite continua 500, nada foi commitado.**
Pergunta do dono: *até onde dá para subir `ACTIVE_DOCUMENT_LIMIT = 500` (`backend/app/audit_usage/service.py:15`) e o que quebra?* — inclui o custo de **filtrar biblioteca e busca pgvector por um conjunto de pastas permitidas** (Espaços por pessoa; contexto em `specs/research/comunicacao-espacos-viabilidade-2026-10-15.md`, spike 0.2).

Convenções: **[MEDIDO]** = número produzido por script deste spike (arquivo em `results/`); **[CÓDIGO]** = fato lido em `path:line`; **[INFERÊNCIA]** = dedução minha; **[NÃO MEDIDO]** = dito explicitamente na §9.

---

## 1. Resposta em uma tela

| Pergunta | Resposta |
|---|---|
| **Quanto dá para subir hoje, mudando só configuração?** | **~3.000 documentos ativos por organização** [MEDIDO em 3k]. Pergunta com escopo "toda a organização" = 1,8 s (sem contar OpenAI), `@`-menção 80–190 ms, RSS 261 MB na carga do escopo (≈ +180 MB). Nada quebra. Mas é preciso mexer em **três** constantes, não uma (§5, achado A1). |
| **Onde começa a doer sem refatorar?** | **~10.000**: pergunta org-scope 6,7 s (26 s na primeira, a frio), menção 0,3–0,66 s **por tecla**, ~700 MB de RAM por pergunta. **50.000 é inutilizável**: 42 s, **2,2 GB**, menção ~1,6–2 s. |
| **Teto duro (quebra, não degrada)** | **65.535 parâmetros num statement** (psycopg): a consulta lexical repete a lista de IDs (`questions.py:1404-1430`) → falha com **>32.767 documentos no escopo + menção** (ou >65.535 sem menção). Medido: `OperationalError: number of parameters must be between 0 and 65535` (`results/sql_50k.log`, linhas `doc-in 2x33000`). |
| **Novo limite viável** | **Passo 1 — já: 3.000** (só configuração). **Passo 2 — depois de ~8 correções de código (§7): 10.000.** **Passo 3 — 25.000 só com busca vetorial por índice (ANN) validada com embeddings reais.** **Não passar de ~50.000/organização** sem particionar chunks por Espaço/organização. |
| **O filtro por pastas permitidas é caro?** | **Não é o filtro; é o que se varre.** Resolver a subárvore visível custa 5–50 ms (CTE recursiva) mesmo com 25 mil arquivos visíveis; filtrar a busca custa ≈ nº de chunks visíveis × ~0,03 ms (exato) — 4 ms para 0,2% dos docs, 23 ms para 2%, 0,5 s para 10%, 3,5 s para 50% de 50k docs. Detalhe e armadilhas (join mata o índice ANN) na §6. |
| **Maior risco escondido** | `MONTHLY_LIMITS["embedding_tokens"] = 1.000.000/mês` (`audit_usage/service.py:16`): com chunks de ~1.000 caracteres (`_estimated_tokens = len/4`, `questions.py:2279`) são ~4.000 chunks ≈ **800 docs de 5 chunks por mês**. Subir só o limite de documentos faz a **indexação falhar** (`UsageLimitExceeded`) antes de chegar em 3.000. |

---

## 2. Como foi medido (e o que isto NÃO é)

- Bancos sintéticos `spike_ls_{1k,3k,10k,50k}` no Postgres de dev (docker `pgvector/pgvector:pg16`, pgvector **0.8.6**, `shared_buffers=128MB`, `work_mem=4MB`, **sem tuning**, VM Docker com 11,7 GB). O banco `document_intelligence` nunca foi tocado.
- Tamanhos (arquivos / nós / docs ativos / chunks / espaços): **1k** 1.000 / 1.042 / 1.007 / 4.988 / 10 · **3k** 3.000 / 3.122 / 3.047 / 15.179 / 20 · **10k** 10.000 / 10.402 / 10.195 / 50.765 / 40 · **50k** 50.000 / 52.002 / 50.827 / 254.729 / 100. ~5 chunks/doc de ~1.000 caracteres, embeddings de 1.536 dims em **`embedding` (JSON) e `embedding_vec` (vector)** como a app grava. Árvore: raiz `source` → espaços → pastas até profundidade 5 (~25 arquivos/pasta, tamanhos Pareto), 5% dos arquivos indexados também num 2º espaço (sobreposição), 1% `failed`, 2% `removed`. (`seed.py`, `results/meta_*.json`)
- HTTP: `fastapi.testclient` **em processo** — inclui roteamento, auth, SQL, ORM e JSON; **não** inclui rede/TLS/Cloud Run. Mediana de 5 execuções (3 nas perguntas) após 1 aquecimento. **OpenAI/LLM são stubs** (zero rede): some o tempo real do provedor por cima.
- Máquina: Mac, 10 cores, 16 GB, Postgres em Docker Desktop → **os absolutos de produção (Cloud SQL, rede) serão outros; vale a forma da curva, a contagem de statements/linhas e a memória.**
- Defeitos conhecidos do próprio spike (não afetam as conclusões): (1) a pasta plana "Inbox" só recebe arquivos do espaço 0, então tem 100/250/500 arquivos em 1k/10k/50k (o rótulo `~N` impresso pelo bench está errado nas escalas grandes); o caso "pasta plana com 5.000 arquivos, OFFSET fundo" foi refeito à parte em `bench_sql.py` §tree. (2) A 1ª versão dos benchmarks de busca textual usava termos que não existem no vocabulário sintético (0 resultados) — refeitos com termos reais (`api_*_noask.json`, `sql_*.json`). (3) O `seed.py` de 50k falhou no `VACUUM` por **`/dev/shm` de 64 MB do container** (não por falta de disco) — corrigido no spike (`SET max_parallel_maintenance_workers = 0`) e refeito.

---

## 3. Tempos por escala (endpoints) [MEDIDO]

Mediana em ms, `results/api_{1k,10k,50k}_noask.json` e `api_3k.json`. "stmts" e "KiB" são do 50k.

| Endpoint | 1k | 3k | 10k | 50k | stmts@50k | KiB@50k |
|---|---|---|---|---|---|---|
| `GET /library (roots)` | 5 | 7 | 27 | 12 | 6 | 0.3 |
| `GET children(source root) page1/100` | 6 | 10 | 26 | 16 | 9 | 29.7 |
| `GET children(source root) last page` | 5 | 8 | 10 | 14 | 8 | 0.1 |
| `GET children(workspace root 0)` | 4 | 11 | 11 | 16 | 7 | 1.2 |
| `GET children(Inbox ~N files) pK/100` | 10 | 16 | 15 | 27 | 7 | 73.2 |
| `GET children(Inbox) pK/100 (deep offset)` | 8 | 6 | 8 | 7 | 6 | 0.1 |
| `GET /library/search 'ra' (very common)` | 7 | 16 | 13 | 46 | 6 | 15.0 |
| `GET /library/search '0000042' (rare)` | 7 | 9 | 15 | 49 | 6 | 0.9 |
| `GET /library/question-contexts` | 6 | 8 | 13 | 29 | 4 | 23.8 |
| `GET /library/mention-candidates q='' ` | 33 | 193 | 342 | 1605 | 7 | 6.0 |
| `GET /library/mention-candidates q='doc'` | 35 | 82 | 303 | 1500 | 7 | 6.0 |
| `GET /library/sync-status` | 14 | 18 | 21 | 52 | 10 | 0.4 |
| `GET /library/syncs` | 4 | 6 | 6 | 7 | 4 | 7.2 |
| `GET /library/sync-history` | 6 | 12 | 10 | 9 | 5 | 56.3 |
| `GET /workspace-folders` | 4 | 7 | 6 | 12 | 5 | 27.6 |
| `GET /workspace-folders/{big}/documents (unpaged)` | 6 | 6 | 8 | 14 | 6 | 95.4 |
| `GET /workspace-folders/{mid}/documents (unpaged)` | 5 | 7 | 7 | 10 | 6 | 95.4 |
| `GET /organizations/{id}/usage` | 4 | 4 | 5 | 10 | 5 | 0.4 |
| `POST /workspace-folders/{big}/search (rare term)` | 18 | 11 | 17 | 11 | 6 | 2.5 |
| `POST /workspace-folders/{big}/search (2 common terms)` | 26 | 21 | 36 | 46 | 6 | 10.1 |
| `POST /workspace-folders/{big}/search (2 common, page 5)` | 18 | 23 | 29 | 54 | 6 | 10.1 |
| `POST single-folder question` (1 espaço) | 82 | 178 | 170 | 282 | 15 | 0,1 |
| **`POST org-scope question` (todos os espaços)** | **417** | **1.779** | **6.726** | **42.353** | **224** | 0,3 |

Pontos que a tabela esconde:

- **O custo de uma pergunta depende do nº de chunks no escopo, não do tamanho da biblioteca**: a pergunta de 1 espaço fica em 82→282 ms mesmo com 50k docs na organização; a de escopo "organização" cresce ~linear em chunks (84 µs/chunk em 1k → 132 µs em 10k → 166 µs em 50k). É isso que Espaços/pastas resolvem *se* a pergunta passar a ser feita sobre um escopo menor.
- Pergunta org-scope a frio (1ª execução): 26,6 s em 10k e 82 s em 50k (cache de páginas vazio).
- **Pico de RAM do processo numa pergunta org-scope em 50k: 2,19 GB** (`/usr/bin/time -l`, `results/bench_api_50k.log`); ≈ 8,6 KB por chunk (inclui ~250 MB de processo-base). Em 10k, só a carga do escopo já leva o processo a 697 MB (`sql_10k.json`).
- N+1: a pergunta org-scope executa **44 / 64 / 104 / 224 statements** em 1k/3k/10k/50k, sendo **o mesmo `SELECT … FROM memberships` repetido 13 / 23 / 43 / 103 vezes** (= nº de espaços + 3) — `questions.py:1137-1142` chama `WorkspaceService.require_member_access` (`workspaces/service.py:34-39`, 2 queries) **uma vez por pasta**.
- `GET /organizations/{id}/usage` (contagem de documentos ativos) fica em 4–10 ms: o `count(*)` usa *index-only scan* em `ix_documents_organization_folder_status` (9,4 ms, 50.827 linhas, `Heap Fetches: 0`). **Contar não é problema.**

---

## 4. Recuperação (pgvector / FTS) por tamanho do escopo [MEDIDO]

Mesmo escopo "primeiros *k* espaços", cache aquecido, sem índice ANN (estado atual do produto). `results/sql_{1k,3k,10k,50k}.json`.

| Chunks no escopo | Carga ORM `scoped_rows` (`questions.py:1209`) | `PgVectorSimilarity.scores` (todos os chunks, `similarity.py:30`) | top-100 **em SQL** (exato) | RAM Python da carga |
|---|---|---|---|---|
| 5 mil (1k) | 565 ms | 316 ms | 30 ms | 22 MB heap / RSS 126 MB |
| 15 mil (3k) | 1,2 s | 300 ms | 99 ms | 66 MB / RSS 261 MB |
| 51 mil (10k) | 3,7 s | 2,0 s | 146–454 ms | 223 MB / RSS 697 MB |
| 127 mil (50k, metade) | 9,9 s | 5,4 s | 3,8 s | 558 MB / RSS 1,4 GB |
| 255 mil (50k, tudo) | **21,1 s** | **10,0 s** | **6,8 s** | **1,1 GB / RSS 1,85 GB** |

- A app faz as **duas** primeiras colunas em toda pergunta: carrega *todos* os chunks do escopo (`Document` + `DocumentChunk` com `text` e `search_text`, embeddings *deferidos*) **e** pede ao Postgres o score de *todos* eles, para só então ordenar em Python e ficar com 100 (`questions.py:1392-1401`). Fazer o top-100 dentro do SQL (`ORDER BY embedding_vec <=> q LIMIT 100`) já é ~5× mais barato com 255 mil chunks e 12–38× com 51 mil, e **não usa memória Python** — sem nenhum índice novo.
- Custo do exato ≈ **0,027 ms por chunk varrido** (6,8 s / 255 mil). Escopo pequeno é barato independente da biblioteca: 1 espaço (2,5 mil chunks) = 18 ms em 50k.
- FTS (`retrieval.py:75`, GIN `ix_document_chunks_search_vector`): termo raro 2–5 ms em qualquer escala. Termo **muito comum** ranqueia todos os matches: 0,4 s (50k chunks) → 11 s (255k) no pior caso sintético (vocabulário Zipf; texto real tende a ser menos extremo — [INFERÊNCIA]). A busca por espaço (`POST /workspace-folders/{id}/search`) ficou em 11–54 ms porque o escopo é 1 espaço.

### 4.1 Índice ANN (HNSW) — o que mede e o que NÃO dá para concluir

| | 10k (50,8 mil chunks) | 50k (254,7 mil chunks) |
|---|---|---|
| Build `CREATE INDEX … USING hnsw (embedding_vec vector_cosine_ops)` | **52,6 s**, 416 MB | **16 min 26 s**, **1.990 MB** (com `maintenance_work_mem=4GB`; com 1 GB ficou ~73% em 9+ min e foi cancelado) |
| Top-100 com índice + `hnsw.iterative_scan=relaxed_order`, filtro por `workspace_folder_id` | 5–22 ms | 7–32 ms (1 espaço: 11 ms) |
| Recall@100 vs exato | 0,98–1,0 | **0,77–1,0** (`ef_search=100`) |
| Recall@10 por `ef_search` (40→400), escopo todo | 0,76 → 1,0 | **0,42 → 0,78** |

- **Armadilha de correção silenciosa [MEDIDO]:** com o `ef_search` padrão (40) e `LIMIT 100`, a consulta com filtro devolveu **7, 12, 28 ou 40 linhas em vez de 100** (`sql_*_hnsw*.log`, linhas `topk-sql … chunk-only filter`). Sem `hnsw.iterative_scan` (pgvector ≥ 0.8, aqui 0.8.6) o filtro é pós-aplicado e **trunca o resultado sem erro**.
- **Não dá para certificar recall com este dataset.** Meus embeddings são "centroide de tópico + 50% de ruído isotrópico" — próximos de uniformes em alta dimensão, o pior caso para grafos HNSW. Recall 0,4–0,8 no 50k é um *artefato provável* dos dados sintéticos; **embeddings reais do `text-embedding-3-small` quase certamente se comportam melhor, mas isso é [INFERÊNCIA] e precisa ser medido com os documentos do cliente antes de adotar ANN.** Latências de ANN medidas aqui (8–600 ms, muito variáveis) também ficam sujeitas a esse viés.
- **Pressão de cache [MEDIDO]:** com o índice de 2 GB residente na VM de 11,7 GB, as consultas *exatas* do 50k ficaram 1,6× a 8× mais lentas (carga 34 s vs 21 s; `scores` 82 s vs 10 s; `sql_50k_hnsw2.log` vs `sql_50k.log`): tabela (5,1 GB) + índice (2,0 GB) não cabem no cache de páginas. Em produção o Postgres precisa de RAM ≥ tabela quente + índice (§7, M7).
- Tamanho em disco: **1,0 GB (10k docs), 5,1 GB (50k docs)** ≈ 100 KB/doc, sem o HNSW. A coluna JSON legada `embedding` (~9,8 KB/chunk) duplica `embedding_vec` (~6,1 KB/chunk) e responde por ~52% dos bytes das colunas de conteúdo dos chunks (JSON 9,8 KB de 18,9 KB) (`pg_column_size` no 10k).

---

## 5. Gargalos e achados, com `path:line`

Severidade = efeito ao subir o limite. **Ordenado do pior para o menor.**

### Bloqueadores de memória/tempo da pergunta
- **B1 — carrega todos os chunks do escopo em Python.** `backend/app/knowledge/questions.py:1209-1223` (`scoped_rows = list(session.execute(select(Document, DocumentChunk)…))`) + `:1224` `_deduplicate_indexed_copies` (`:1608`). 21 s e 1,1 GB heap com 255 mil chunks; ~85 µs e ~4,4 KB por chunk. É o que faz a org-scope virar 42 s / 2,2 GB. *Correção:* top-K em SQL, hidratar só os ~100 candidatos.
- **B2 — score de todos os chunks, ordenação em Python.** `backend/app/knowledge/similarity.py:30-39` (`PgVectorSimilarity.scores` sem `ORDER BY/LIMIT`, devolve um `dict` de 255 mil entradas) e `questions.py:1392-1401` (`sorted(...)[:MAX_SEMANTIC_CANDIDATES]`, `MAX=100`). 10 s em 255 mil. *Correção:* `ORDER BY <=> LIMIT K` (já medido: 6,8 s exato sem índice; ms com ANN).
- **B3 — N+1 por pasta.** `questions.py:1137-1142` (+ `workspaces/service.py:34-39`): `require_member_access` (2 SELECTs) por pasta + `folder_is_queryable`; 103 repetições no 50k. *Correção:* uma verificação de membership e uma query `WHERE id = ANY(...)`.
- **B4 — IN com milhares de parâmetros → teto de 65.535.** `questions.py:1177/1196/1413` (`Document.id.in_(document_ids)` das menções) e `:1419` (`Document.id.in_({document.id for … in scoped_rows})` na consulta lexical, que repete a lista). Medido: 30 mil binds = 307 ms contra 63 ms de `= ANY(array)`; 2×33.000 binds **falha**. *Correção:* `= ANY(:ids)` / tabela temporária / filtro por subquery; remover a lista de ids da consulta lexical (`:1404-1430` já filtra por `workspace_folder_id`).
- **B5 — lexical `ILIKE '%termo%'` sem índice** sobre todos os candidatos (`questions.py:1404-1430`, `.limit(MAX_LEXICAL_CANDIDATES)` só corta o resultado). Hoje cai em varredura do escopo; com GIN já existente (`search_vector`) poderia usar FTS. [CÓDIGO; custo isolado não medido]

### Árvore da biblioteca / menções
- **T1 — `mention_candidates` percorre a organização inteira em Python.** `backend/app/library/service.py:1073-1122` (+ `_selection_nodes` `:985-991`, `_node_path` `:1034`): carrega todos os nós (ORM), monta o caminho completo de *cada* nó e filtra por substring. **0,04 s (1k) → 0,19 (3k) → 0,34 (10k) → 1,6–2,0 s (50k)**, e o frontend chama a cada tecla após `@` (debounce 180 ms, `frontend/app/mention-composer.tsx:44-50`); cada chamada prende uma conexão (pool `5+5`, `core/database.py:18-19`) e ~1 core. *Correção:* busca no banco (índice `pg_trgm` em `lower(name)`) + `LIMIT`, caminho só dos 20 resultados.
- **T2 — `_selection_nodes` em todo caminho "catálogo".** `library/service.py:985` é chamado por `authorized_catalog` (`:1002`, "rebuild … for every tool invocation", docstring em `:1000`), `resolve_question_selection` (`:1124`), `authorize_mentions` (`:1158`), `node_paths` (`:1062`) e todos os `catalog_*` (`:561-644`) — i.e. **a cada chamada de ferramenta do agente e do MCP/API pública**. 7 ms (1k) → 17 → 145 → **666 ms** (52 mil nós); `authorized_catalog` 15 → 34 → 178 → 560–620 ms. `_descends_from`/`_node_path` são O(profundidade) por nó, e `resolve_question_selection` ainda faz O(N·profundidade) por menção de pasta (`:1141-1150`, `_descends_from` por arquivo × menção).
- **T3 — `indexed_documents_under` anda a árvore nível a nível carregando ORM.** `library/service.py:256-284` + `documents_for_nodes` (`:363-422`, `Document.external_file_id.in_({…todos os arquivos…})`): 47 ms (1k) → 294 ms (10k) → **1,75–2,0 s (50k)**; a mesma contagem por **CTE recursiva** leva 1 → 10 → 60 ms. Também esbarra no teto de 65.535 binds numa pasta com >65 mil arquivos [CÓDIGO]. Usado por reprocessar/remover da biblioteca (`api/library.py:246`, `:284`).
- **T4 — lookup de documentos de uma página é O(nº de espaços).** `library/service.py:375-412`: a consulta junta `workspace_folders` e filtra `Document.external_file_id IN (…)`; o único índice com `external_file_id` é `(workspace_folder_id, external_file_id)` (`knowledge/models.py:66`), então o plano é *nested loop* sobre **todos** os espaços (38 ms para 3 ids com 100 espaços; `EXPLAIN` em `spike_ls_50k`). *Correção:* guardar `source_id` em `documents` ou índice `(organization_id, external_file_id)`.
- **T5 — busca por nome da biblioteca = *seq scan*.** `library/service.py:542-559`: `lower(name) LIKE '%q%'` + `count(*)` sobre subquery: 203 ms só no banco para um termo que casa 40% dos 52 mil nós (`EXPLAIN ANALYZE`); HTTP 46–49 ms (a 1ª página corta cedo, o total não). Falta índice `pg_trgm` GIN em `lower(name)`.
- **T6 — listagem de filhos está OK.** `children` (`:230`) usa `ix_library_nodes_organization_parent` + `ORDER BY kind, name, id OFFSET`: pasta plana de **5.000 arquivos** (criada em transação e descartada): página 1/25/50 = **16 / 22 / 21 ms** no 50k. Paginação com `OFFSET` é aceitável até dezenas de milhares de filhos por pasta; `PAGE_SIZE_MAX = 100` (`library/service.py:25`).

### Endpoints sem paginação / payload
- **P1 — `GET /workspace-folders/{id}/documents` devolve todos os documentos do espaço.** `backend/app/api/ingestion.py:120-141` → `ingestion/service.py:247-262`: 95 KB para 500 docs (≈190 B/doc, 14 ms); **um único espaço com 50 mil docs = ~9,5 MB de JSON e 50 mil objetos ORM** [extrapolação linear — não medido nessa escala]. *Correção:* paginar como `/library/nodes/{id}/children`.
- **P2 — `GET /library/question-contexts` e `/workspace-folders` devolvem 1 item por espaço, sem paginação** (`library/service.py:911-964`, `api/ingestion`): 24 KB e 28 KB com 100 espaços, 29–40 ms; crescem com o nº de *espaços*, não de documentos. `GET /library/sync-status` (`:774`, **polling** em `frontend/app/sync-status.tsx:33`) faz 10 statements e 2 `EXISTS` sobre chunks por espaço: 14 → 18 → 21 → **52–90 ms** (50k). `GET /library/sync-history` fixa em 56 KB (já limitado). [MEDIDO]
- **P3 — `catalog_inventory`** (`library/service.py:580-627`) lê **todas** as linhas de `documents` da organização (`select … from documents join workspace_folders`, sem filtro por escopo) e monta conjuntos em Python antes de aplicar `limit=500`. [CÓDIGO; não medido isoladamente — é a mesma ordem de custo de T2 + 1 query de N linhas]

### Ingestão e limites
- **A1 — o limite existe em dois lugares e há dois relógios.** `audit_usage/service.py:15` (barra de uso `usage_summary`, `:93`) e `core/config.py:47` `active_document_limit` (bloqueio real, `ingestion/service.py:1009`, que cai em `500` literal quando `settings` é `None`). Mudar só um deixa UI e bloqueio inconsistentes. Os testes importam a constante (`tests/unit/test_ingestion_service.py:265-312`, `tests/api/test_usage_api.py:26`).
- **A2 — `embedding_tokens` mensal de 1.000.000** (`audit_usage/service.py:16`) bloqueia a indexação em ~800 docs/mês (conta acima). Também `processed_bytes` 2 GB/mês, `questions` 1.000/mês, `ocr_pages` 2.000/mês — **todas globais por organização, não por plano** (já notado no spec de Espaços §2).
- **A3 — `reconcile` custa ~8 ms e 4 statements por documento, linear** [MEDIDO, `ingest.json`: 14 → 7,8 → 7,9 → 8,4 → 7,5 ms/doc para 500 → 8.000 docs; 8.000 docs = 60 s]. Extrapolado: 50k docs ≈ **6–7 min só de banco** (fora extração, OCR e chamadas de embedding, que dominam). Os statements repetidos por doc: `_document_for` (`ingestion/service.py:876`, 1 SELECT/doc, inclusive para os inalterados), `_require_active_document_capacity` (`:996-1010`: `SELECT organizations … FOR UPDATE` + `count(*)` por documento *novo* ou reativado) e `UsageService.check_and_record` (`audit_usage/service.py:54-76`: `SELECT … FOR UPDATE` em `usage_records` + flush por documento).
- **A4 — o lock de capacidade serializa a organização.** O `FOR UPDATE` em `organizations` (`ingestion/service.py:1001-1004`) é segurado até o commit da transação do job; com sincronizações grandes e várias pastas em paralelo, os jobs da mesma organização se enfileiram nesse lock. [CÓDIGO; contenção não medida — o bench é single-thread]
- **A5 — embedding em memória.** `questions.py:918-943` (`embed_chunks`) guarda cada vetor como lista Python de 1.536 floats = **49.416 bytes** [MEDIDO com `tracemalloc`], e `embed_workspace` (`:893-916`) carrega **todos** os chunks pendentes do escopo de uma vez quando chamado sem `external_file_ids` (`ingestion/tasks.py:835`). Primeira sincronização de um espaço com 20 mil docs (~100 mil chunks) ≈ **4,9 GB só de vetores** [cálculo a partir do número medido]. O caminho em lotes de documentos (`tasks.py:778`) está bem; o caminho de escopo inteiro precisa do mesmo lote.
- **A6 — nenhum `statement_timeout`/limite de memória no caminho do request** [grep em `backend/app`, `docker-compose.yml`]: o único `memory:` do compose é o do sidecar OCR. Dimensionamento do Cloud Run/Cloud SQL de produção **não está no repositório** → ver §9.

### Índices
Existentes (`\d` em `spike_ls_10k`): `document_chunks` — `(organization_id, workspace_folder_id)`, `document_id`, `(document_id, position)` único, **GIN `search_vector`**; `documents` — `(organization_id, workspace_folder_id, index_status)`, `(workspace_folder_id, external_file_id)` único; `library_nodes` — `(organization_id, parent_id)`, `parent_id`, `source_id`, `(source_id, external_id)` único.

| Falta | Para quê | Evidência |
|---|---|---|
| **Índice ANN em `document_chunks.embedding_vec`** (HNSW, `vector_cosine_ops`) | top-K sem varrer o escopo | §4.1; hoje 0,027 ms/chunk varrido |
| `pg_trgm` GIN em `lower(library_nodes.name)` (e no caminho/nome de arquivo) | busca por nome e `@`-menção | T1, T5 (203 ms *seq scan* no 52k) |
| `documents (organization_id, external_file_id)` ou `source_id` em `documents` | lookup por arquivo sem varrer espaços | T4 (nested loop × nº de espaços) |
| `document_chunks (document_id)` já existe; faltaria um índice parcial `WHERE embedding_vec IS NOT NULL` só se o JSON legado for removido | simplificar `coalesce(embedding_vec, cast(embedding))` de `similarity.py:25-27` | `PgVectorSimilarity` hoje precisa do JSON para chunks sem backfill |
| (opcional) coluna de acesso denormalizada em `document_chunks` (`space_id`/`access_group`) | filtro ANN por Espaço sem join | §6 — o join com `documents`/`library_nodes` derrota o índice ANN |

---

## 6. Filtrar por um conjunto de pastas permitidas [MEDIDO, `bench_filter.py`, 50k, aquecido]

Modelo: a pessoa enxerga os arquivos abaixo de *K* pastas escolhidas ao acaso e disjuntas (fragmentado como numa permissão real): 0,2% / 2% / 10% / 50% dos 50.000 arquivos = 103 / 1.006 / 5.116 / 25.064 arquivos visíveis (7 / 14 / 68 / 422 pastas-raiz).

| Visível | Resolver subárvore (CTE recursiva) | Ancestrais (breadcrumb) | Mesma subárvore andando em Python (como `indexed_documents_under`) | IDs de docs visíveis (CTE+join) | Top-100 vetorial, `document_id = ANY(ids)` **exato** | idem com **índice ANN** | FTS (termo médio) |
|---|---|---|---|---|---|---|---|
| 0,2% | 20 ms | 1,5 ms | 2,4 ms | 26 ms | **4 ms** | 5,5 ms | 2,6 ms |
| 2% | 25 ms | 1,5 ms | 3,5 ms | 25 ms | **23 ms** | 92 ms | 9 ms |
| 10% | 28 ms | 5,7 ms | 72 ms | 77 ms | **542 ms** | 259 ms | 88 ms |
| 50% | 48 ms | 7,3 ms | 360 ms | 183 ms | **3,6 s** | 3,3 s | 427 ms |

E, quando o conjunto permitido é uma **união de escopos de sync inteiros** (`workspace_folder_id = ANY(...)`, que já está denormalizado nos chunks):

| Escopos | Exato (varredura) | Com ANN (iterative scan) |
|---|---|---|
| 1 (1% dos chunks) | 13 ms | 17 ms |
| 2 | 24 ms | 38 ms |
| 10 (10%) | 290 ms | **8 ms** |
| 50 (50%) | 2,2–8,8 s | **18 ms** |

Conclusões:

1. **O filtro em si é barato; o que custa é varrer os chunks visíveis (~0,03 ms/chunk) e carregá-los.** Resolver quem pode ver o quê leva dezenas de ms em SQL; fazê-lo em Python (como `library/service.py` faz hoje) chega a 360 ms e 1,7–2 s em `indexed_documents_under`.
2. **Para um Espaço pequeno (≤ ~2% da biblioteca) a busca exata filtrada é rápida** (≤ 25 ms) — e pode ser *mais barata* que antes porque varre menos.
3. **Armadilha:** a consulta **em um SQL só com `JOIN` de `library_nodes`/`documents` por baixo do `ORDER BY … <=> … LIMIT`** (variante (a) no script) **derrota o índice ANN** — 0,4 → **15 s** (50%) — e, sem cuidado, o `LIMIT` retorna menos linhas. Faça em dois passos (ids visíveis → `= ANY`) ou, melhor, denormalize o identificador de acesso no chunk.
4. **Recomendação de desenho para Espaços:** (i) resolver visibilidade por **CTE recursiva (ou tabela de fechamento/`ltree`) e cache por pessoa invalidado por evento** — não por varredura em Python; (ii) filtrar o chunk por **`workspace_folder_id` (união de escopos)** quando o Espaço for composto de escopos inteiros e por **`document_id = ANY`** quando for uma pasta dentro de um escopo; (iii) só denormalizar `access_group` no chunk se for necessário ANN com filtro de pasta fina.
5. Não medido aqui: custo de **invalidar/recalcular** a visibilidade quando um arquivo muda de pasta no Drive (o spec de Espaços trata isso como evento) e a **listagem filtrada** (`children` com `id IN visible`) — só a resolução da subárvore foi medida (§9).

---

## 7. Recomendação

**Novo limite:** passar em três degraus, cada um condicionado ao que foi medido.

| Degrau | Limite/org | Condição | Esperado (medido/derivado) |
|---|---|---|---|
| **0 — configuração** | **3.000** | `ACTIVE_DOCUMENT_LIMIT` **e** `active_document_limit` (A1) + `MONTHLY_LIMITS["embedding_tokens"]` ×10 e `processed_bytes` (A2) | org-scope 1,8 s, menção 80–190 ms, RSS 261 MB (≈ +180 MB)/pergunta [MEDIDO em 3k] |
| **1 — correções M1–M8** | **10.000** | M1–M8 abaixo | org-scope < 1 s sobre top-K em SQL (6,8 s exato sobre 255 mil chunks ⇒ ≈ 0,15–0,4 s sobre 50 mil); menção < 100 ms; sem N+1 [DERIVADO dos mesmos medidos] |
| **2 — ANN + RAM** | **25.000** | M9–M10 e validação de recall com embeddings reais | top-K em ms; build do índice ~16 min em 255 mil chunks |
| — | **≥ 50.000** | **Não recomendado** sem partição (por organização/Espaço), RAM de Postgres ≥ tabela+índice (~7 GB aqui) e revisão do pipeline de ingestão | teto de 65.535 binds; 5 GB de banco por organização |

**Mudanças necessárias** (nenhuma foi feita; ordem de custo/benefício):

| # | Mudança | Onde | Resolve |
|---|---|---|---|
| M1 | Top-K no SQL e hidratar só os candidatos; apagar `scoped_rows`/`scores` globais | `questions.py:1169-1224,1392-1401`, `similarity.py:30` | B1, B2 (−85% do tempo e toda a RAM) |
| M2 | Uma verificação de membership por pergunta, `WHERE id = ANY(folder_ids)` | `questions.py:1137-1142`, `workspaces/service.py:34` | B3 (224 → ~20 statements) |
| M3 | Trocar `IN (milhares de binds)` por `= ANY(:ids)`/subquery e tirar a lista da consulta lexical | `questions.py:1177,1196,1413,1419`; `library/service.py:363-412` | B4 (teto 65.535) |
| M4 | `@`-menção no banco: `pg_trgm` GIN em `lower(name)` + `LIMIT`; caminho só dos 20 resultados | `library/service.py:1073-1122` + migração | T1 (2 s → ms), T5 |
| M5 | Substituir `_selection_nodes` + `_descends_from` por CTE recursiva (ou `ltree`/tabela de fechamento); cache por pessoa | `library/service.py:985,1002,1124,1158,256` | T2, T3 (e é a base do filtro de Espaços, §6) |
| M6 | Índice `documents(organization_id, external_file_id)` (ou `source_id` em `documents`) | `knowledge/models.py:66` | T4 |
| M7 | Paginar `GET /workspace-folders/{id}/documents` (e `/workspace-folders`, `/library/question-contexts` quando houver muitos espaços) | `api/ingestion.py:120`, `library/service.py:911` | P1, P2 |
| M8 | Unificar o limite (um lugar só, vindo de `Settings`) e escalar `MONTHLY_LIMITS` por plano | `audit_usage/service.py:15-16`, `core/config.py:47` | A1, A2 |
| M9 | Índice HNSW + `hnsw.iterative_scan`, `ef_search ≥ K`, `maintenance_work_mem ≥ 4 GB` no build; **validar recall com embeddings reais** | migração + `similarity.py` | §4.1 |
| M10 | Embeddar em lotes também no caminho de escopo inteiro; remover a coluna JSON `embedding` após o *cutover* para `embedding_vec` (≈ −50% dos bytes de conteúdo dos chunks) | `ingestion/tasks.py:835`, `questions.py:918` | A5, tamanho em disco |

(Estimativa de esforço — [ESTIMATIVA], confiança baixa: M1–M3 ≈ 3–5 dev-dias com testes; M4–M6 ≈ 3–4; M7–M8 ≈ 1–2; M9–M10 ≈ 3–5 + validação de recall.)

---

## 8. Evidências (comandos, saídas, arquivos)

Tudo roda com `spikes/library-scale/run.sh <script>` (usa `backend/.venv` + `numpy` em `.pydeps/`, que está no `.gitignore`).

| Etapa | Comando | Resultado |
|---|---|---|
| seed 50k (refeito) | `./run.sh seed.py --label 50k --files 50000 --workspaces 100 --chunks-per-doc 5` | exit 0, 446 s → `results/meta_50k.json` (1ª tentativa falhou no `VACUUM`: `DiskFull … /PostgreSQL.…` — `/dev/shm` 64 MB; log antigo sobrescrito) |
| seed 3k | `./run.sh seed.py --label 3k --files 3000 --workspaces 20 --chunks-per-doc 5` | exit 0, 46,9 s → `meta_3k.json` |
| API 10k / 50k (+ perguntas) | `./run.sh bench_api.py --label 10k --runs 5` ; `/usr/bin/time -l ./run.sh bench_api.py --label 50k --runs 5` | exit 0; `api_10k.json`, `api_50k.json`; 50k: 240 s, **RSS máx 2.190.524.416 B** (`bench_api_50k.log`) |
| API 3k | `./run.sh bench_api.py --label 3k --runs 5` | exit 0 → `api_3k.json` |
| API sem perguntas (termos reais) | `./run.sh bench_api.py --label {1k,10k,50k} --runs 5 --skip-ask` | exit 0 → `api_*_noask.json` |
| SQL/pgvector por tamanho de escopo | `./run.sh bench_sql.py --label {1k,3k,10k,50k}` | exit 0 → `sql_*.json` |
| HNSW | `./run.sh bench_sql.py --label {10k,50k} --hnsw` ; build 50k via `psql` com `maintenance_work_mem=4GB` | exit 0 → `sql_*_hnsw*.json`; build 50k 986,5 s (`hnsw50k_build.log`), 1.990 MB |
| Recall × `ef_search` | `./run.sh bench_ann.py --label {10k,50k}` | exit 0 → `ann_*.json` |
| Filtro por pastas | `./run.sh bench_filter.py --label 10k --warm --runs 4` ; `… 50k --warm --runs 3` | exit 0 → `filter_10k.json`, `filter_50k.json` (execução a frio: `results/filter_50k.log`) |
| Ingestão | `./run.sh bench_ingest.py --steps 500,500,1000,2000,4000` | exit 0 → `ingest.json` |
| `EXPLAIN (ANALYZE)` do `count(*)`, busca por nome, lookup de documentos, filhos | `psql … -f /tmp/_q.sql` em `spike_ls_50k` | `Index Only Scan` 9,4 ms; `Seq Scan library_nodes` 203 ms; `Nested Loop` 38 ms; `Index Scan` 2,6 ms |

Cadeias auxiliares: `chain.sh`, `chain2.sh`, `chain3.sh` (benchmarks sequenciais com log em `results/*.log`, ignorados pelo git). **Git:** `git check-ignore -v` confirma `.pydeps/`, `__pycache__/`, `results/*.log` e `results/*.npy` ignorados; o diretório `spikes/library-scale/` está **não rastreado, sem commit**. Código de produção intocado.

---

## 9. O que NÃO foi medido (e por quê)

1. **Produção real**: Cloud Run/Cloud SQL, rede, TLS, tamanho de instância e limites de memória do serviço de API — não estão no repositório (só o `memory: 6g` do sidecar OCR em `docker-compose.yml`). Os GB/s e ms absolutos são de um Mac com Docker Desktop.
2. **Concorrência**: todos os benchmarks são sequenciais (1 usuário). Não medi N usuários digitando `@`, nem 2 perguntas org-scope simultâneas (2×2,2 GB), nem contenção do `FOR UPDATE` de capacidade (A4). O pool é `5+5` (`core/database.py:18-19`).
3. **OpenAI/LLM e embeddings reais**: stubs. Tempo de `text-embedding-3-small` e do modelo de resposta ficam de fora; **recall do ANN com embeddings reais** não pôde ser medido (os sintéticos são o pior caso para HNSW — §4.1).
4. **Extração/OCR e API do Drive** (download, Docling, limites de cota): fora do escopo do spike; a ingestão medida é só `reconcile()` (`bench_ingest.py`), até 8.000 docs (50k extrapolado, não executado). O primeiro `embed_workspace` de escopo inteiro (A5) é conta, não execução.
5. **Caminhos de escrita da biblioteca** lidos mas não medidos: `project_successful_sync` (`library/service.py:1219`), `prune_orphan_file_nodes` (`:1348`), `remove_folder_catalog` (`:286`), `filter_excluded_content` (`:478`, carrega todos os nós da fonte por sincronização), `manual_sync.py`. São O(nós) por sincronização; vale medir antes do degrau 1.
6. **Pergunta com `@`-menção de pasta grande ponta a ponta** (HTTP): medi só as peças (resolver subárvore, `IN` com N binds, teto de 65.535). Também não medi os endpoints do agente/MCP (`catalog_*`) por HTTP — só `_selection_nodes`/`authorized_catalog` no nível de serviço.
7. **Listagem filtrada por visibilidade** (`children` restrito a `id IN visível`) e **custo de invalidar o cache de visibilidade** quando o Drive move arquivos: só a resolução da subárvore foi medida (§6).
8. **Frontend**: renderização de listas grandes na UI (a árvore já pagina 100 por vez; não testei virtualização).
9. **Escalas**: parei em 50k arquivos / 255 mil chunks. Não executei 100k (o teto de 65.535 binds já impede a pergunta org-scope).

---

## 10. Reproduzir

```
cd spikes/library-scale
# uma vez: uv pip install --python backend/.venv/bin/python --target spikes/library-scale/.pydeps numpy
./run.sh seed.py --label 10k --files 10000 --workspaces 40 --chunks-per-doc 5   # cria spike_ls_10k a partir do template migrado
./run.sh bench_api.py --label 10k --runs 5                                      # endpoints HTTP + perguntas (stubs)
./run.sh bench_sql.py --label 10k [--hnsw]                                      # recuperação por tamanho de escopo
./run.sh bench_filter.py --label 10k --warm                                     # filtro por conjunto de pastas
./run.sh bench_ann.py --label 10k                                               # recall × ef_search (precisa do índice)
./run.sh bench_ingest.py --steps 500,500,1000,2000,4000                         # reconcile() sintético
```
Bancos `spike_ls_*` ficam no Postgres de dev (`docker exec document-ai-postgres-1 psql -U document_intelligence -c '\l'`); podem ser apagados (`DROP DATABASE spike_ls_50k;`) — somam ~9 GB (50k = 7,1 GB com o índice HNSW; 10k = 1,4 GB). Os de 10k e 50k têm o índice `ix_spike_hnsw` criado.
