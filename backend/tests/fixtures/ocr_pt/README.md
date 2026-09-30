Corpus PT-BR sintético (sem dado de cliente) para a avaliação de OCR.
`docling_serve_response.json`: resposta real anonimizada do docling-serve (F0.3).
`pdf/`, `truth/`, `questions.json`: gerados por `python -m scripts.make_ocr_corpus`; `truth/*.txt` separa páginas com form feed.
Limiares e uso: `docs/operacao/ocr-runbook.md`.
