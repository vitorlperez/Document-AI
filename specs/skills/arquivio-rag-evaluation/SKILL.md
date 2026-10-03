---
name: arquivio-rag-evaluation
description: Avaliar mudanças no retrieval, classificação de intenção, ferramentas, síntese e citações do Arquivio com fixtures sintéticas, baseline e orçamento de chamadas.
---

# Avaliação de RAG do Arquivio

Este pacote é fonte versionável de um playbook do projeto; sua presença aqui não significa instalação no catálogo do Overclock. O piloto pode apontar este arquivo no briefing de IA, testes ou validação.

## Escopo e fontes

Use em mudanças de comportamento da IA, comparação de modelos ou regressões de qualidade. Não introduza um framework de avaliação sem necessidade medida. Leia `docs/agent-flow.md`, o dossiê da feature e os módulos afetados localizados por Graphify.

Reaproveite `backend/tests/fixtures/semantic_evaluation.json`, `backend/tests/fixtures/injection_cases.json` e testes em `backend/tests/unit/test_semantic_questions.py`, `test_agent_flow.py`, `test_document_agent.py` e `test_injection_eval.py`. Os caminhos são relativos à raiz do repositório.

## Processo

1. Defina a hipótese e a etapa alterada: classify, execute, synthesize ou cite. Separe falha de retrieval de falha de geração. Registre baseline, dataset, configuração, versão do código e critérios no dossiê.
2. Comece com fixtures sintéticas e provedores fake. Cubra pergunta respondível, evidência insuficiente, pergunta ambígua, seguimento da conversa, referências ordinais, arquivo removido/revogado, timeout e citações inválidas conforme o comportamento tocado.
3. Para retrieval, registre documentos esperados e recuperados, recall@k e ranking quando existir ground truth. Para resposta, confira se cada afirmação verificável é sustentada pela fonte e se os marcadores apontam documentos realmente usados e autorizados. Não trate presença de marcador como prova de grounding.
4. Inclua organização e pasta adversárias. Modelo, memória de conversa e ferramenta nunca ampliam o escopo autorizado pelo request. Revalide arquivos reutilizados em turnos posteriores.
5. Rode o menor conjunto pytest aplicável a partir de `backend/`. Amplie conforme os critérios do dossiê, sem confundir mocks com avaliação do provedor real.
6. Quando a hipótese exigir modelo real, use os avaliadores existentes: `python -m app.knowledge.intent_eval --help` e `python -m app.knowledge.agent_eval --help`. O primeiro precisa de credencial de IA; o segundo também de dados e identidade autorizada. Use ambiente de teste e casos sintéticos, nunca documentos de clientes.

## Custo e resultado

Antes de uma avaliação externa, delimite número de casos, variantes, repetições e chamadas; registre o teto já autorizado. A autorização de configurar o squad não autoriza benchmarks pagos. Não rode juiz LLM em toda a suíte por padrão; utilize checks determinísticos e revisão humana onde suficientes.

Compare baseline e candidato no mesmo conjunto. Reporte qualidade por cenário, regressões, latência medida, chamadas, tokens/custo quando disponíveis e lacunas. Não estime p95 com amostra inadequada nem invente custo quando o provedor não o fornece. Falha de isolamento ou fonte não autorizada é bloqueante; o gate final pertence ao validador independente.
