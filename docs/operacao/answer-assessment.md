# Avaliação de respostas: rollout sem transferência adicional

A avaliação externa está **desabilitada por padrão**. TYPESAFE_API_KEY existente, AGENT_INTENT_ENGINE ou deploy não autorizam enviar trechos ao avaliador. Defaults: AGENT_ASSESSMENT_MODE=off e AGENT_ASSESSMENT_EXTERNAL_ENABLED=false. A etapa após cite permanece: registra verificações locais (resposta presente, presença de fontes/trechos), sem alegar que essas verificações comprovam sustentação semântica. Feedback 👍/👎 e exportação de calibração funcionam sem TypeSafe.

## Variáveis de deploy (Railway, Render, Docker)

Primeiro rollout seguro: mantenha as duas variáveis no padrão, ou configure explicitamente:

```
AGENT_ASSESSMENT_MODE=off
AGENT_ASSESSMENT_EXTERNAL_ENABLED=false
```

Não alterar credenciais existentes. Somente após decisão explícita de habilitar o envio e medir seu impacto:

```
AGENT_ASSESSMENT_MODE=shadow
AGENT_ASSESSMENT_EXTERNAL_ENABLED=true
```

Esse opt-in duplo envia à TypeSafe/System One: pergunta (standalone quando disponível), resposta, trechos citados com nomes/números, metadados autorizados de inventário (nomes/kind/status/counts/paginação). Não envia novos documentos, IDs/URLs do catálogo, respostas geradas por ferramentas como evidência ou segredos. Não há SDK novo. O classificador de intenção JEV legado não é alterado por esse gate; configure AGENT_INTENT_ENGINE=llm separadamente se quiser desativar também esse fluxo existente.

Variáveis opcionais: AGENT_ASSESSMENT_TIMEOUT_SECONDS=2 (máximo 5); GROUNDING_THRESHOLD=.8, RELEVANCE_THRESHOLD=.7, SAFETY_THRESHOLD=.8, todas com prefixo AGENT_ASSESSMENT_. Settings são lidas uma vez por processo; alterações exigem restart/deploy. Valores inválidos degradam para off/false com log sem valores.

Shadow habilitado é síncrono e soma latência de uma chamada TypeSafe por resposta; o deadline HTTP herdado é por operação, não garantia de tempo total/p95. Não manter ligado antes de medir p95 e custo no piloto. Não habilitar enforce antes da revisão de 20 perguntas reais, incluindo follow-ups/saudações/inventário/contradições/injeção. Usa standalone_query quando disponível; quando ausente, falta contexto conversacional e a relevância ainda pode ser subestimada.

`agent_eval --llm-judge` é opt-in offline, usando o OpenAI já configurado; não transfere documentos à TypeSafe quando o gate dela está desligado. `--feedback-output` exporta votos e verificações locais/externas do usuário autorizado, sem texto. Rollback: off/false e restart; sem migração.

## Avaliação local durante conversa

`local_evaluation` roda em todos os modos, sem HTTP, e registra `kind=citation_integrity`, `outcome=pass|warn`, checks e issues: resposta vazia, marcador [N]/(fontes N) fora das fontes fornecidas, trecho citado vazio e resposta ask_content apoiada sem fonte. Não bloqueia nem muda texto/citações: avaliação estrutural em shadow. Um pass NÃO comprova verdade/sustentação/relevância/segurança semântica; `semantic_grounding=not_evaluated` é explícito. Catálogo/saudação e reconhecimento de evidência insuficiente não exigem citação documental.

Com mode=shadow/external=false, o ramo externo continua `outcome=skipped`, `reason=external_disabled`, checks probabilísticos vazios. O resultado útil separado é local_evaluation; HTTP zero prova só ausência de transferência. Judge semântico continua offline opt-in OpenAI existente; opção futura de reutilizar esse judge no runtime exige orçamento/calibração/revisão própria, nunca habilitar TypeSafe sem consentimento específico.

Warnings locais são triagem: [2024] usado como ano pode gerar falso positivo; [1, 99] em um único colchete não é reconhecido (o formato contratado é [1][99] ou (fontes 1 e 99)). Não bloquear entrega com warn. Falha inesperada no avaliador retorna outcome=error/issues=evaluation_failed sem conteúdo, preservando a resposta em qualquer modo.
