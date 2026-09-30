# ADR-0015: Cerca anti prompt injection

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

F6 é dona única do corpus injection_cases.json, untrusted.py e presentation.py. Fontes são dados não confiáveis cercados por nonce; títulos e caracteres invisíveis são neutralizados. Guard de saída reutiliza sanitização existente e cobre imagens Markdown. Nenhum canal recebe bypass de tenant ou instruções presentes em documentos.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
