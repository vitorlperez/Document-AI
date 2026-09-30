# Threat model: API, MCP e canais

## Ativos e atores
Ativos: chunks, nomes, URLs de origem, chaves de API, tokens OAuth e dados isolados por tenant. Atores: membro legítimo, membro desativado, autor de documento malicioso, cliente MCP malicioso, workspace Slack mal configurado e atacante de rede.

## Fronteiras de confiança
Banco → serviços: queries filtradas pela organização. Serviços → OpenAI: documentos são dados não confiáveis. Serviços → cliente MCP/LLM: trechos podem conter instruções hostis. Serviços → Slack: identidade externa não implica associação à organização.

## Invariantes
| ID | Garantia | Evidência |
|---|---|---|
| I-1 | Escopo derivado da credencial no servidor; o modelo não escolhe tenant ou membro. | `backend/tests/unit/test_scope_invariant.py::test_classifier_schema_cannot_carry_scope`; `test_scoped_access.py` |
| I-2 | Recuperação somente leitura; nenhuma tool recebe URL ou faz HTTP arbitrário. | `test_scope_invariant.py`; MCP B3 pendente |
| I-3 | Documentos rotulados não confiáveis e sem caracteres invisíveis nos prompts. | `backend/tests/unit/test_untrusted_fencing.py`; `test_injection_eval.py` |
| I-4 | Links da resposta derivados de texto são removidos; citações usam source_url do banco. | `backend/tests/unit/test_presentation.py` |
| I-5 | Chamadas autenticadas auditadas sem conteúdo. | `backend/tests/unit/test_access_audit.py::test_records_hash_and_length_but_never_the_query_text` |
| I-6 | Revogação, expiração e desativação do membro falham fechadas. | `backend/tests/unit/test_principal.py::test_every_failure_is_the_same_invalid_credential` |

## STRIDE por canal
| Canal | Ameaça | Mitigação e teste |
|---|---|---|
| API | Spoofing / elevação por chave revogada | hash SHA-256, comparação constante, membro ativo (`test_principal.py`) |
| API | Tampering / vazamento de outro tenant | ScopedAccess, 404 uniforme (`test_public_v1.py`) |
| API | Repudiation | metadados e hash da consulta (`test_access_audit.py`) |
| API | DoS | Redis por chave e organização, 503 quando indisponível (`test_ratelimit.py`, `test_public_v1.py`) |
| MCP | Confused deputy / token passthrough | audiência obrigatória e vínculo servidor; validação B1/B3 pendente |
| MCP | Injection / exfiltração | somente leitura, aviso não confiável, openWorldHint=false; B3 pendente |
| Slack/Teams | Spoofing / divulgação em canais externos | vínculo explícito e respostas efêmeras; fora de escopo |

## Riscos residuais e revisão
O LLM do cliente pode obedecer instruções nos trechos de search/fetch. Somente leitura, rótulos, openWorldHint=false e aprovação do usuário reduzem o impacto, sem garantir obediência do modelo. Links de origem confiáveis dependem dos conectores. Auditoria falha com log e continua se o banco estiver indisponível. Ranking pode ser manipulado dentro do tenant.

> Execução: canais Slack/Teams excluídos pelo dono; MCP será validado na Fase B. Revisão independente deste documento permanece pendente para o piloto; os testes citados da Fase A são adicionados durante a execução.
