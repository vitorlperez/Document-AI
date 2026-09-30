# agent-contextual-followups

Owner: pane-228, local main. Scope: intent.py, agent.py, questions.py, dedicated regressions/eval/report. User's library feature files are excluded.

## Reproduction before fix

Local Docker API at 1b7de66. User asks “Em quais empresas o Vitor trabalhou e quando?” then “Qual foi o último emprego?” without attaching anything. Persisted second decision: list_files/library, plan_rejected fallback, invalid_generation_output, zero citations.

Independent replay of persisted first turn: ask_content/library, classifier emitted query “Qual foi o último emprego de Vitor?” but parse_intent discards query for retrieve_evidence. Embedding receives raw “Qual foi o último emprego?”. Classifier history is truncated at 500 characters, removing Allstacks. Score filter selects only BANCO DE PERGUNTAS - ENTREVISTA RH.pdf (0.53887), not resume candidates (0.39481 or less). Real generation returns Insufficient evidence.; invalid-output handling discards consulted citations. Refusal text: agent.py:_honest_insufficient (line 795 before change). Logs confirm one candidate and invalid generation, rather than a direct zero-score-candidate refusal.

Hypothesis: missing autonomous retrieval query and contextual source targeting make the generic question retrieve the wrong document; score filtering amplifies the omission, and invalid generation erases the consulted sources. Fix the classifier contract and evidence handling, without query word lists or special cases.

## Entrega local

Concluído e validado: classificador com pergunta autônoma, histórico completo e esforço low com prazo limitado; pergunta autônoma usada pelo embedding e síntese; leitura autorizada dos arquivos herdados; candidatos de score baixo enviados ao modelo; abstenção preserva fontes/links. Seleção atual e chunks completos/adjacentes permanecem cobertos.

Mini eval real: recall 1/4→4/4; fatos 3/9→9/9. Replay real depois: Allstacks com fonte vinculada nos quatro follow-ups. A falha antiga depende da classificação: replay adicional antes com nova primeira resposta escolheu corretamente o alvo histórico e também respondeu Allstacks.

Pytest completo isolado HEAD+fix: 459 passed, zero skipped, exit 0. Árvore compartilhada: 464 passed, 1 failed fora do escopo na expectativa de FK da nova feature manual_sync_runs; chamador avisado. Rebuild api/worker necessário; sem push. Evidências detalhadas: backend/scripts/reports/followup-retrieval.md e relatórios JSON próximos.
