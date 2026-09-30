# ADR-0015: Cerca anti prompt injection

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

F6 é dona única do corpus injection_cases.json, untrusted.py e presentation.py. Fontes são dados não confiáveis cercados por nonce; títulos e caracteres invisíveis são neutralizados. Guard de saída reutiliza sanitização existente e cobre imagens Markdown. Nenhum canal recebe bypass de tenant ou instruções presentes em documentos.

## Implementação F6

Corpus único com 14 vetores, incluindo os seis do plano 03. `untrusted.py` exporta `fence_sources`, `strip_invisible`, `safe_label`, `sanitize_label` e `UNTRUSTED_NOTICE`. Nonce de 64 bits por chamada; enquadramento forjado e ocorrências do nonce no conteúdo são neutralizados, incluindo nomes/metadados. ZWJ emoji e ZWJ/ZWNJ linguísticos são preservados.

A guarda única em `presentation.py` deriva da sanitização HTTP existente. O parser de Markdown consome parênteses balanceados e remove imagens inteiras; mantém rótulos de links e citações durante a validação. `GeneratedAnswer` e `QuestionResult` protegem todos os consumidores do serviço, com log `answer_links_stripped` apenas de contagem. Aliases HTTP preservam chamadas internas. L-7 limpa chunks JSON de resumo; L-8 sanitiza nomes no fallback.

Rollback: `SOURCE_FENCING_ENABLED=false` somente para os dois prompts textuais. Avaliação viva manual com três repetições por caso; não é CI e a ausência de relatório aprovado impede declarar o gate de release cumprido. A cerca não garante fidelidade semântica nem substitui escopo/ACL.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
