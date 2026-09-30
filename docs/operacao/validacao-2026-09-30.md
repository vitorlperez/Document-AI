# Validação de infraestrutura — 2026-09-30

Branch `feat/integracoes`, worktree `/Users/vitorperez/Documents/Document-AI-integracoes`, macOS Darwin 24.5.0 ARM64. O relatório não contém credenciais. A validação usou os arquivos de teste sintéticos do projeto.

## iCloud

- `defaults read com.apple.bird optimize-storage`: antes `1`; depois de `defaults write com.apple.bird optimize-storage -bool false` e `killall bird`, `0` (exit 0). `bird` voltou a ficar ativo. A sincronização de Mesa/Documentos não foi alterada.
- Contagem por `ls -lOR <repo> | grep -c dataless`: repo principal `0 → 0`; worktree `28 → 0`.
- Materialização: leitura recursiva de todos os arquivos regulares dos dois repositórios, incluindo `.git` e `backend/.venv`, com `find <repo> -type f -print0 | xargs -0 -n 128 cat >/dev/null` (exit 0). A contagem final permaneceu `0` nos dois diretórios.
- O ajuste do macOS foi respeitado; não é necessária ação manual em Ajustes do Sistema.

## PostgreSQL real

- Docker Engine `28.1.1`; Docker Compose `v2.35.1`. O container `pgvector/pgvector:pg16` foi descartável, isolado na porta local `55432`, sem volume persistente; removido após os testes.
- `backend/.env` está ausente; não há host de banco remoto configurado nesse arquivo.
- Contra esse banco descartável: `alembic upgrade head` (exit 0), `alembic downgrade base` (exit 0), `alembic upgrade head` novamente (exit 0). Cabeça única: `20260930_0025 (head)` (exit 0).
- `backend/.venv/bin/python -m pytest -q -m postgres tests/integration`: `13 passed` (exit 0; repetido no fluxo CI local).

## Docling e OCR PT-BR

- Serviço iniciado pelo Compose: `DOCLING_SERVE_IMAGE=quay.io/docling-project/docling-serve-cpu:v1.35.0 docker compose --profile ocr up -d docling` (exit 0). Digest observado: `sha256:79e5fcd19ab227ed36323fa5fa31820d14d53efc4f073417ba37be7931c7af0a`; `/health` respondeu HTTP 200.
- A imagem base não inclui `por.traineddata`. Para este ensaio, o modelo português foi copiado apenas para o container descartável: `tessdata_fast` SHA-256 `c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb` e, na segunda rodada, `tessdata_best` SHA-256 `711de9dbb8052067bd42f16b9119967f30bada80d57e2ef24f65d09f531adb04`. A imagem publicada permanece sem essa customização.
- Avaliação real com `tessdata_fast`: 12 documentos, exit 0, 90,00 s. Repetida com `tessdata_best`: 12 documentos, exit 0, 61,34 s. O script imprime métricas, mas não retorna erro quando os limiares de aceite não são atingidos.

| PDF | CER (best) | WER (best) | Recall de acentos (best) |
|---|---:|---:|---:|
| 01 | 0,000 | 0,000 | 1,000 |
| 02 | 0,011 | 0,000 | 1,000 |
| 03 | 0,011 | 0,000 | 1,000 |
| 04 | 0,000 | 0,000 | 1,000 |
| 05 | 0,027 | 0,067 | 0,950 |
| 06 | 0,028 | 0,049 | 1,000 |
| 07 | 0,018 | 0,019 | 0,968 |
| 08 | 0,031 | 0,114 | 1,000 |
| 09 | 0,716 | 0,706 | 1,000 |
| 10 | 0,017 | 0,000 | 1,000 |
| 11 | 0,000 | 0,000 | 1,000 |
| 12 | 0,000 | 0,000 | 1,000 |

- Limiares definidos no plano F4: CER dos PDFs limpos 01/05/10 ≤ 0,03; degradados 02/03/04/08 ≤ 0,08; WER limpos ≤ 0,06; recall de acentos ≥ 0,97. CER dos grupos passou. O PDF 05 ficou abaixo no WER (0,067) e recall (0,950); o PDF 07 ficou em 0,968 no recall. `tessdata_best` não corrigiu o caractere `ü` do caso 05. Assim, o aceite de acentos permanece parcial.
- O CER alto do PDF 09 é da avaliação isolada do motor, que força OCR das três páginas. No fluxo real de extração, as páginas digitais foram preservadas e somente a página escaneada foi enviada ao motor: três blocos iguais ao gabarito, flags `(False, True, False)` (exit 0).
- PDF 06: comparação literal de células com `tessdata_best` encontrou `35/36` (recall `0,972`, acima de 0,90).
- Fluxo completo com `tests/fixtures/ocr_pt/pdf/01.pdf`: PDF de uma página e zero caracteres nativos; extração produziu os 261 caracteres exatamente iguais ao gabarito, com `ocr=True` (exit 0; 4,42 s).
- Memória na rodada `tessdata_best`: maior amostra de `docker stats` em 23 amostras foi `1321 MiB`; `/proc/1/status` registrou `VmHWM 1.907.096 kB` e `VmRSS 1.672.304 kB`; `/sys/fs/cgroup/memory.peak` registrou `1.620.029.440` bytes. As métricas de RSS e cgroup diferem e ficam registradas como observações distintas. O processo foi limitado pelo Compose a 6 GiB.
- Gates de rollout que exigem três syncs em staging não foram exercitados neste host.

## CI local

`act` não está instalado; os comandos do workflow `.github/workflows/ci.yml` foram executados localmente. `graphify 0.9.72` já está instalado, e o workflow CI já existe.

| Comando/etapa | Resultado |
|---|---|
| `.venv/bin/python -m pip install -e '.[dev]'` | exit 0 |
| Ruff com a lista de exclusões de `.github/workflows/ci.yml` | exit 0 — All checks passed |
| `.venv/bin/python -m pytest -q tests/unit tests/api` | exit 0 — 823 passed, 3 avisos de depreciação |
| `.venv/bin/python scripts/export_openapi.py --check` | exit 0 — OpenAPI confere |
| `.venv/bin/python -m alembic upgrade head` | exit 0 |
| `.venv/bin/python -m pytest -q -m postgres tests/integration` | exit 0 — 13 passed |
| `alembic heads` + verificação de cabeça única | exit 0 — `20260930_0025 (head)` |
| `npm run install:ci` | exit 0 — 871 pacotes |
| `npm run lint` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0 — Build complete |

O workflow fixa Node 22; o ambiente local usou Node `v24.3.0` e npm `11.4.2`. Os comandos passaram nessa versão local. `act` não foi executado.

## Resultado e pendências

- iCloud, migrações e CI local passaram. Os testes unitários/API e PostgreSQL passaram; Docling respondeu e os dois fluxos de extração ao vivo passaram.
- O gate de qualidade de OCR não está totalmente aprovado: faltam 0,02 de recall e o WER do PDF 05 excede o alvo; o PDF 07 fica 0,002 abaixo do recall. A informação necessária para fechar é decidir como tratar `ü` (caractere não usual em PT-BR no corpus) no limiar global e autorizar/definir a próxima ação para o recall do PDF 07. Nenhum limiar ou gabarito foi alterado.
- (Resolvido no adendo abaixo) A imagem Docling validada requer uma variante pinada que inclua o modelo português; o modelo foi instalado somente no container efêmero. Os três syncs de staging continuam pendentes de um ambiente de staging com fonte e PDFs de teste.
- Graphify e CI já estavam disponíveis; não foi necessário instalar ou criar esses artefatos. Nenhum arquivo de código foi alterado.

## Adendo — imagem Docling pinada e limiar de acentos (2026-09-30)

**Imagem.** `infra/docling/Dockerfile`: `FROM quay.io/docling-project/docling-serve-cpu:v1.35.0@sha256:79e5fcd19ab227ed36323fa5fa31820d14d53efc4f073417ba37be7931c7af0a` + `por.traineddata` de `tessdata_best` 4.1.0 (SHA-256 `711de9dbb8052067bd42f16b9119967f30bada80d57e2ef24f65d09f531adb04`, verificado por `ADD --checksum`). Build local `arquivio-docling:v1.35.0-pt1`, ID `sha256:da43f8e5b20705ee7cd1e381990d8facb847720c6e2bee569789c45976bd0a22`; `tesseract --list-langs` → `eng, osd, por`. O ID é local: o digest de registry só existe após publicar a imagem. `docker-compose.yml` passa a construir/usar essa imagem (`DOCLING_SERVE_IMAGE` continua como override).

**best vs fast.** Mesma suíte, imagens idênticas salvo o modelo. `best` e `fast` empatam em 10 dos 12 PDFs. PDF 06 (tabela): `best` CER 0,028 / recall 1,000; `fast` CER 0,052 / recall 0,500. PDF 08: `fast` melhor (CER 0,019 vs 0,031; WER 0,045 vs 0,114), ambos dentro de 0,08. Escolhido `best`: o gate é recall de acentos e o `fast` perde a tabela.

**Decisão do piloto.** `ü`/`Ü` não entram mais no `accent_recall` (trema abolido em PT-BR pelo Acordo Ortográfico). Implementado em `backend/scripts/ocr_eval.py` (`ABOLISHED_ACCENTS`) com teste `test_accent_recall_ignores_trema_abolished_by_the_orthographic_agreement` (vermelho antes, verde depois). Limiar 0,97 mantido para os demais acentos; gabaritos intactos.

**Reavaliação com a imagem nova** (`backend/scripts/reports/ocr-eval-2026-09-30.json`, 12 documentos, exit 0):

| PDF | CER | WER | Recall de acentos |
|---|---:|---:|---:|
| 01 | 0,000 | 0,000 | 1,000 |
| 02 | 0,011 | 0,000 | 1,000 |
| 03 | 0,011 | 0,000 | 1,000 |
| 04 | 0,000 | 0,000 | 1,000 |
| 05 | 0,027 | 0,067 | 1,000 |
| 06 | 0,028 | 0,049 | 1,000 |
| 07 | 0,018 | 0,019 | 1,000 |
| 08 | 0,031 | 0,114 | 1,000 |
| 09 | 0,716 | 0,706 | 1,000 |
| 10 | 0,017 | 0,000 | 1,000 |
| 11 | 0,000 | 0,000 | 1,000 |
| 12 | 0,000 | 0,000 | 1,000 |

- Recall de acentos ≥ 0,97 em todos os PDFs; o PDF 07 (antes 0,968) agora fecha em 1,000 sem ajuste de DPI/psm: o único caractere que falhava era `ü` (lido como `U`).
- Ressalva aceita: WER do PDF 05 = 0,067 (> 0,06 dos limpos). A única palavra errada é `ü` → `U`, em um texto de 15 palavras; o gabarito não foi alterado e o WER não tem verificação automática no script. Dentro do escopo da decisão do piloto, fica aceito com ressalva. PDF 09 segue como descrito acima (avaliação força OCR em páginas digitais; fluxo real preserva o texto nativo).
