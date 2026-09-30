# Cerca anti prompt-injection do RAG

Documentos, nomes e metadados são dados não confiáveis. O ataque combina dados privados, conteúdo hostil e um canal de saída (a “lethal trifecta”). O modelo pode ser persuadido: delimitação não substitui autorização.

Camadas: limpeza na extração (controles invisíveis e runs DOCX ocultos), fontes delimitadas por nonce novo a cada chamada, instrução explícita para tratar fontes como dados, ferramentas somente leitura e guarda única de saída em `knowledge/presentation.py`. Os resultados `GeneratedAnswer` e `QuestionResult` aplicam a guarda antes de sair do serviço. URLs confiáveis continuam somente nas citações vindas do banco. Marcadores `[N]` são preservados durante a validação; a apresentação HTTP mantém a lógica anterior de remoção de marcadores residuais.

`SOURCE_FENCING_ENABLED=true` é o default. Desligar a flag restaura somente o enquadramento antigo em `answer`/`synthesize_answer`, sem desligar a guarda de saída. Prompts JSON de resumo mantêm sua estrutura e limpam os trechos com `strip_invisible`; o resumo por arquivo também limpa cada chunk (L-7). O fallback de insuficiência sanitiza nomes (L-8).

O corpus único é `backend/tests/fixtures/injection_cases.json`, incluindo os seis vetores do plano 03. Adicione `{id, file_name, excerpt, canary?}` e rode `test_untrusted_fencing.py`, `test_presentation.py` e a suíte completa. Os testes capturam o prompt sem rede; não provam que o modelo real resistirá a persuasão semântica.

Avaliação manual: `cd backend && PYTHONPATH=. .venv/bin/python scripts/injection_eval.py`, com `OPENAI_API_KEY` no ambiente. Cada caso com canário é executado três vezes; o relatório contém apenas indicadores, sem documentos, respostas ou credenciais. Inspeciona saída bruta antes da guarda e saída protegida; qualquer canário ou link bruto falha o gate de release. Nunca executar em CI.

Limites: a cerca não impede distorção semântica dentro do escopo, não implementa ACL por arquivo (item S), não remove texto legitimamente visível que contenha instruções e preserva notas PPTX rotuladas. Linhas/colunas XLSX ocultas no modo read-only continuam sendo a limitação documentada no ADR-0011.

Regra para planos 02/03: nenhuma ferramenta de escrita/envio no mesmo turno que lê conteúdo ingerido. MCP e `/v1` consomem os módulos compartilhados; não criam corpora ou sanitizadores paralelos. Sem Slack/Teams nesta entrega.
