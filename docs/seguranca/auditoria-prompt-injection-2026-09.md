# Auditoria anti prompt-injection — setembro 2026

| ID | Ponto verificado | Disposição |
|---|---|---|
| L-1 | questions.py: fence_sources; agent.py: sanitize_label | cerca da F6 existente; nomes tratados |
| L-2 | untrusted.py: strip_invisible e nonce | invisíveis removidos, delimitadores por chamada |
| L-3 | presentation.py: serialize_question_result | links/imagens da resposta removidos; URL somente da citação |
| L-4 | agent.py: classificador e histórico | risco residual de segunda ordem; schema fechado, fallback registrado |
| L-5 | standalone_query do classificador | ranking manipulável somente dentro do escopo servidor |
| L-6 | questions.py: previous_answer | limite de 4000 caracteres; risco residual aceito |
| L-7 | questions.py: chunks das sínteses por arquivo | strip_invisible já presente na F6; não duplicado |
| L-8 | agent.py: _honest_insufficient | sanitize_label já presente na F6; não duplicado |
| L-9 | API/MCP: trechos devolvidos ao cliente | dados não confiáveis; leitura apenas, aprovação no cliente; MCP pendente |

> Execução: reutilizados knowledge/untrusted.py e presentation.py dos commits 6a7d955/34c8a45. Sem mudanças em ingestion/extraction/blocks ou sanitize, de propriedade da pane-258. Evidência automatizada: test_scope_invariant, test_untrusted_fencing, test_injection_eval, test_presentation, test_agent_flow, test_document_agent e test_multiscope_questions_api. Revisão independente do threat model pendente.
