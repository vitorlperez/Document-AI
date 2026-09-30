# ADR-0011: Formatos e OCR

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

TXT/Markdown, CSV/XLSX, PPTX, Sheets/Slides e OCR de PDF entram no MVP. Imagens soltas, legados e planilhas complexas continuam excluídos. Docling sidecar é o default condicionado ao spike F0.3; API externa exige consentimento por organização e DPA. Manter teto de 500 documentos configurável e orçamento estimado de 2.000 páginas OCR/org/mês; truncar com aviso citável, rejeitar acima do teto de bytes.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
