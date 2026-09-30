# ADR-0011: Formatos e OCR

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

TXT/Markdown, CSV/XLSX, PPTX, Sheets/Slides e OCR de PDF entram no MVP. Imagens soltas, legados e planilhas complexas continuam excluídos. Docling sidecar é o default condicionado ao spike F0.3; API externa exige consentimento por organização e DPA. Manter teto de 500 documentos configurável e orçamento estimado de 2.000 páginas OCR/org/mês; truncar com aviso citável, rejeitar acima do teto de bytes.

## Limitações de formatos e resultado do spike

- XLSX usa openpyxl 3.1.5 em modo read-only/data-only. Abas ocultas são ignoradas, mas linhas e colunas ocultas são incluídas; fórmulas sem cache ficam vazias, sem calcular valores.
- TXT/CSV aceitam UTF-8-sig, UTF-16 com BOM e cp1252. CSV/XLSX carregam cabeçalhos por linha; PPTX preserva número/título e rotula notas do orador. Macros, tabelas dinâmicas, gráficos e imagens não são interpretados.
- F0.3 executou Docling Serve CPU v1.35.0 em Docker ARM64 limitado a 1 CPU: p95 amostral 8,103 s/pág (3 documentos quentes), pico RSS 1.821.304 KiB. A imagem base carece de português no Tesseract: F4 exige imagem derivada com `por.traineddata`. PDF protegido/corrompido pode retornar HTTP 200 com `status="failure"`; validar o corpo.
- Sidecar permanece candidato; medir no Railway/Oracle e validar CER/recall antes do rollout. Evidência e contrato por página: `specs/research/ocr-spike-2026-09.md`.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
