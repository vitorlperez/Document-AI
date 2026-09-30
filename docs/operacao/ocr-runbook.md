# Runbook: OCR em camadas (F4)

Camadas: texto do PDF (pypdf) → `docling-serve` (sidecar HTTP) → API de nuvem (fallback, **desligado**).
Sem `OCR_ENGINE`, o comportamento é o de sempre: PDF escaneado fica sem texto (`empty_extracted_text`).

## Habilitar / desabilitar
| Variável | Padrão | Efeito |
|---|---|---|
| `OCR_ENGINE` | `none` | `docling_serve` liga o sidecar; exige `DOCLING_SERVE_URL` |
| `DOCLING_SERVE_URL` / `DOCLING_SERVE_VERSION` | — / `v1.35.0-pt1` | endpoint privado; a versão entra na chave do cache |
| `OCR_MAX_PAGES_PER_JOB` | 200 | teto de páginas por job de sync (por instância de provider) |
| `OCR_JOB_DEADLINE_SECONDS` | 600 | metade do lease de 20 min do job |
| `OCR_LANGUAGES` | `por,eng` | idiomas do Tesseract no Docling |
| `OCR_CLOUD_FALLBACK_ENABLED` / `OCR_CLOUD_DPA_APPROVED` | `false` | fallback por API: sem vendor aprovado, permanece inativo |

Rollback: `OCR_ENGINE=none`. Documentos já indexados permanecem; os `failed` voltam ao comportamento anterior.
Local: `DOCLING_SERVE_IMAGE=<tag pinada> docker compose --profile ocr up -d docling worker`.

## Dimensionamento (medido na F0.3, amostral)
- ~8,1 s/página em 1 CPU (quente), pico de RSS ≈ 1,8 GB; o limite do compose é 6 GB. **Medir no host alvo** antes de produção.
- Railway: serviço `docling` **sem domínio público**, rede privada; `worker` segue `--concurrency=1`. Render free não hospeda o sidecar. Oracle ARM: exige imagem ARM64.

## Regras de produto
- Só páginas sem texto (< 25 caracteres) são enviadas; PDF é reconhecido se ≥ 30 % das páginas estão vazias.
- Mais de 60 páginas a reconhecer num documento → `ocr_document_too_large` (terminal, não reprocessa).
- Orçamento por job estourado → `ocr_budget_exceeded`; o agendador ignora a janela de frescor da pasta e continua no próximo ciclo. Teto mensal: `ocr_pages` = 2.000/org.
- `file_encrypted`, `file_too_large`, `ocr_document_too_large` não entram em `force_file_ids`.
- Cache `extraction_cache` por organização/motor/versão/hash; retenção de 90 dias (tarefa beat diária `purge_extraction_cache`); apagado com a organização.

## Alertas sugeridos
Fila de documentos `ocr_budget_exceeded` > N; latência p95 do OCR; falhas `ocr_failed` > 5 %.

## Avaliação PT-BR
`python -m scripts.make_ocr_corpus` gera os PDFs escaneados sintéticos (Pillow) e
`python -m scripts.ocr_eval --engine docling_serve --url … --corpus tests/fixtures/ocr_pt --report scripts/reports/ocr-eval-<data>.json`
mede CER/WER/`accent_recall`. Limiares: CER ≤ 3 % (limpos) / ≤ 8 % (degradados), `accent_recall` ≥ 0,97. Pendente: rodar contra o serviço real (depende de host).
