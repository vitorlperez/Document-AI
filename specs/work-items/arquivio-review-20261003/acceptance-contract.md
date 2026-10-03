# Contrato de aceite — lote 1 RAG / memória após revogação

Data: 2026-10-03. Decisor: dono do produto, instrução explícita recebida nesta rodada.
Baseline: `a43dbdd09ae1673adc088b84a4a56b5ea8665f5f`, árvore compartilhada suja.
Implementação produtiva ainda não autorizada **a este worker**; esta entrega é contrato + testes RED.

## Decisão aprovada e limite

Quando um documento citado não estiver autorizado no escopo **atual** (remoção de catálogo ou
acesso negado), a resposta anterior inteira que o utilizou fica fora do contexto enviado à IA.
Não basta retirar nome, marcador ou somente a frase do documento negado. A nova resposta é
reconstruída somente a partir de fontes atualmente autorizadas; retorna evidência insuficiente
quando necessário. Isso vale antes da classificação/planner e da síntese, inclusive metadados de
referências que poderiam revelar nomes fora do escopo. A mesma identidade/principal continua no request.

Desindexação exige recuperar evidência atual, sem reciclar texto documental antigo. Uma falha
de índice não é nova ACL: nomes de arquivos **ainda autorizados** podem participar do aviso honesto.
Histórico mostrado/armazenado permanece intacto, com conteúdo, contexto, resposta e citações originais.
Não editar APIs de histórico, registros passados, retenção, memberships, ACL ou credenciais.

Fonte `DataSource.status=disconnected/reauth_required` com pasta consultável e índice retido segue
ADR-0007. Ela não equivale a nó removido, pasta inadmitida ou membership desativada. Os três estados
da fonte têm controles positivos. A negação coletiva de referências de inventário fora da pasta
permanece fail-closed; excluir memória antes da IA não transforma uma negação em autorização parcial.

## Critérios Given / When / Then

| ID | Dado / Quando | Então e evidência automatizada |
| --- | --- | --- |
| A1 | Mesma org/principal, resposta anterior citando A+B; nó B removido; reorganizar | Excluir a resposta inteira do planner/history e de previous_answer; reconstruir de A; resultado cita A, link de A, texto atual de A. Famílias `test_policy_classifier*`, `test_policy_synthesis*`, `test_policy_answer*`. |
| A2 | Ambos os nós removidos; ainda existem linhas residuais do índice | Não voltar a uma busca geral que recupere esses documentos. Nenhum payload de geração/citação usa A/B; evidência insuficiente sem fonte. `test_current_citations*` e `test_policy_answer*[node_removed_total]`. |
| A3 | B desindexado após listagem real, ou seleção atual explicitamente restrita a A | Eliminar resposta contaminada inteira, usar apenas A e não citar/reenviar B. A desindexação usa referências persistidas da ferramenta real, sem algoritmo fake de filtro. |
| A4 | Pasta deixa de ser consultável, provider sai da seleção ou membership é desativada entre turnos | A negação atual é permitida/preservada. Mesmo se ela acontecer depois, classificador não pode ter recebido texto derivado negado. Apenas `SyncAccessDenied`, `GoogleAccessDenied` e `ValueError("mention is unavailable")` nos cenários delimitados são negações esperadas. |
| A5 | Referência de inventário de outra pasta, mesmo tenant; mention de outro tenant | Serviço nega a referência/mention. Nenhuma síntese ou resposta documental do outro tenant. `test_cross_folder_inventory_reference_denied_in_same_org`, `test_cross_org_mention_denied_without_content`. |
| A6 | Fontes continuam autorizadas, inclusive fonte desconectada ou reauth_required com índice retido | Continuidade mantém previous_answer e histórico autorizados. Três variantes de `test_authorized_continuity_and_adr0007_retained_index`. |
| A7 | Memória excluída do contexto depois de remoção parcial/total ou desindexação | Mesma conversa, usuário e org; dados armazenados iguais após recarregar do banco sintético. `test_history_is_preserved_after_context_exclusion`. |
| B1 | Arquivos A+B foram listados; B continua autorizado, mas index_status=failed; resumir lista | Resposta pode usar A e citar somente A, mas avisa honestamente que 1 arquivo ficou sem conteúdo indexado. Aviso admite quantidade segura ou nome de B autorizado + motivo. `test_coverage_listed_unindexed_file_requires_honest_warning`. |
| B2 | B listado foi removido do catálogo | Não vazar seu nome em payload da IA ou erro. Preservar a negação coletiva existente; nenhuma ampliação/redução de ACL. `test_unavailable_listed_name_not_disclosed_to_ai_or_error`. |

A1–A4 e A7 materializam a **política humana agora aprovada**; A2/A5/A6 e proteção de nomes
também exercem isolamento já exigido por Spec 001 §6 F4/§7 e ADR-0007. B1 é a omissão já
incompatível com o requisito de cobertura parcial/evidência honesta (Spec 001 §6 F4 e §7 Qualidade),
não depende de inventar política de revogação. B2 não autoriza usar nomes negados para explicar a omissão.

## Harness e oráculo

Único arquivo novo: `backend/tests/unit/test_agent_revocation_review.py`. Usa serviços reais
`AgentService`, `ConversationService`, `LibraryService`, SQLite em memória e helpers de fixture existentes.
`RecordingAI` devolve intenção fixa/vetores fixos e ecoa previous_answer quando recebido, tornando
o vazamento observável. Sem previous_answer, ecoa a evidência que o serviço realmente forneceu.
O fake não resolve alvos, autoriza, filtra memória ou reproduz algoritmo produtivo.
Capturamos classify_intent, synthesize_answer, answer/evidence e resultado final. Bloqueio HTTP
em httpx denuncia chamada externa como violação de harness; nenhum provedor real é instanciado.

`OLD-WHOLE-ANSWER` só aparece no texto anterior, nunca nas evidências atuais, e verifica exclusão
da resposta **inteira**, inclusive sua parte anteriormente autorizada. `BETA-SYNTHETIC-DENIED`
é texto totalmente fictício e verifica conteúdo derivado negado. UUIDs sintéticos variam, mas
as decisões, mensagens de assert e conjuntos esperados são determinísticos; não há relógio, sleeps,
credential, DB real, conectores, juiz pago ou comparação por ranking instável.

Casos negativos não prometem segurança global, semântica de LLM real, suporte Postgres concorrente,
validação HTTP/browser ou auditoria completa de MCP/cache/logs.

## Gate de integração

`ai-engineer` implementa somente `backend/app/knowledge/agent.py`, sem alterar o contrato de ACL
dos serviços nem enfraquecer os testes para obter verde. Revalidar proveniência antes de formar
contexto de IA, separar memória de targets atuais e impedir fallback geral quando o conjunto histórico
autorizado ficou vazio. Preservar os erros existentes de referências listadas fora do escopo.
Propagar omissão de índice como aviso honesto com metadados autorizados.

Reviewer independente inspeciona diff contra baseline + edits prévios, executa novamente os 30 casos,
as suítes focadas (e as adicionais do dossiê), lint/check e verifica cada critério. Deve ver RED neste
HEAD sem patch e GREEN com patch; nesta rodada somente RED foi solicitado e comprovado.
O gate final continua fechado até essa implementação e validação independente. Documentar política
durável em spec/ADR é responsabilidade da integração futura, não desta rodada. Graphify update
somente depois do lote integrado e da liberação de writers concorrentes.

## Decisão P2 (2026-10-03)

**Decisão do dono: manter o comportamento atual.** Um @mention atual disjunto das fontes citadas pela
resposta anterior preserva o histórico (resposta anterior, nomes listados e mensagens do planner).

Justificativa: a fonte antiga continua autorizada ao principal; trocar o foco para outro arquivo ou pasta
não é revogação de acesso, logo não há vazamento de ACL. O que o @mention faz é redirecionar o alvo
(`_resolve_targets` mantém as mentions como autoridade), e a síntese continua só com evidência da seleção
atual. Coberto por `test_current_selection_overrides_history_in_vitor_conversation`
(`backend/tests/unit/test_document_agent.py`), que segue verde e não deve ser alterado.

Limite que permanece (A3, `scope_restricted`): quando a seleção atual cobre **parte** do que a resposta
citou, a resposta inteira é excluída, porque o restante vazaria para um escopo mais estreito. Revogação real
(nó removido, pasta/provider/membership negados, índice retirado) exclui sempre, inclusive com pasta irmã
ainda consultável na mesma fonte (teste de regressão
`backend/tests/unit/test_agent_revocation_sibling_folder.py`).
