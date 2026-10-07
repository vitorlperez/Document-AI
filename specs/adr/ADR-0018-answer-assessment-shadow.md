# ADR-0018 - Avaliação de resposta em shadow

Status: aprovado no pedido de 2026-10-07; implementação sujeita à validação independente.

O fluxo AgentService tem uma etapa fixa assess após cite e antes de finish. Reutiliza o cliente HTTP TypeSafe System One existente, `jev-1.13.0`, sem SDK novo. A aplicação combina três probabilidades Noul (grounded, relevant, safe) com limiares locais versionados. Esses valores não comprovam autorização nem qualidade absoluta: autorização permanece nos serviços locais. Estado inclui só a pergunta atual, resposta, trechos citados e resultados das ferramentas já autorizadas; nunca busca documentos adicionais. Entradas são explicitamente tratadas como dados não confiáveis.

Padrão `AGENT_ASSESSMENT_MODE=shadow` preserva resposta e citações, inclusive em erro/timeout/credencial ausente. Off desliga chamadas. Enforce é opt-in, nunca habilitado nesta entrega; recusa ou erro produz answer null, confidence insufficient_evidence e retrieval_status assessment_reject/assessment_unavailable. Sem retry/regeneração. Antes de enforce, medir falsos positivos, latência e qualidade em dataset revisado do piloto (spec 001 exige revisão de 20 perguntas), inclusive inventário, saudação, follow-up, documentos contraditórios e prompt injection.

Configuração isolada em AssessmentSettings (pydantic-settings já instalado), lê .env/process env: AGENT_ASSESSMENT_MODE, TIMEOUT_SECONDS (padrão 2, máximo 5), GROUNDING_THRESHOLD (.8), RELEVANCE_THRESHOLD (.7), SAFETY_THRESHOLD (.8). Todos com prefixo AGENT_ASSESSMENT_. Credencial/modelo vêm das settings existentes TYPESAFE_API_KEY/AGENT_JEV_MODEL. A chamada usa o menor deadline entre o restante do agente e o timeout de assessment. O timeout HTTP por operação herdado não é garantia de p95. Estado >24.000 bytes é marcado unavailable, sem truncamento que criaria aprovação parcial.

Metadados seguros de decisão e limiares persistem no resolved_context.assessment da mensagem existente. Logs têm somente status e duração. Evidência: probe real em APIs TypeSafe/OpenAI com duas respostas sintéticas; não representa benchmark em corpus real de cliente nem calibração estatística.

`agent_eval --llm-judge [--judge-model ...]` usa OpenAI existente apenas offline, com scores grounding/relevance/completeness. Reusa factory do runtime (corrige omissão de JEV no avaliador anterior). Julga antes do rollback; erro do judge é registrado pelo tipo, sem texto de fornecedor. `--feedback-output` exporta IDs/votos/assessment do usuário autenticado no escopo, sem conteúdo.

PUT /organizations/{org}/conversations/{conversation}/messages/{message}/feedback aceita up/down; valida associação ativa, organização, dono da conversa e role assistant, substitui o voto no JSON context sob lock do pai, sem migração. Conteúdo e response permanecem imutáveis. O voto não altera limiares automaticamente. A UI recarrega o transcript persistido após uma resposta para vincular controles a IDs canônicos; adiciona uma leitura de histórico por pergunta. Se essa leitura falhar, mantém a resposta e não oferece voto até restauração bem-sucedida.

Reversão: MODE=off desliga avaliação externa; nenhum dado exige migração. A feature não altera conectores ClickUp nem configuração Railway. Rollout remoto e calibração por tráfego do piloto ficam com o responsável pela operação após revisão independente.
