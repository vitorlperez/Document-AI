# Consolidação entre documentos — 2026-09-30

## Causa observada

A conversa anexada começa com “A síntese automática ficou indisponível”, seguida de
passagens integrais por arquivo. Esse texto vem do fallback Python do QuestionService;
o LLM não escreveu cards e o prompt de 7d3df7e não participa dessa montagem.
O classificador real retornou ask_content/library; o esquema nem possui intenção
“por arquivo”. O classificador pode devolver none/search_library como ferramenta,
mas o agente normaliza para retrieve_evidence conforme o contrato de ask_content.

`docker compose logs backend --since 60m` não funciona neste checkout: não há serviço
backend. `docker compose logs api --since 60m` foi capturado antes de outra atividade
recriar a API. Os eventos do request b5bb9b00-9c05-41d8-8560-67045c0d04d7 mostram:
classificador 6251,51 ms; embeddings 964,03 ms; geração read_timeout 12899,05 ms;
provider_unavailable_extractive_fallback. Evidência exata filtrada em
`content-consolidation-logs.json`; log completo local em
`/tmp/document-ai-synthesis-api-before.log`.

O fluxo de conteúdo usa OpenAIQuestionProvider.answer, não synthesize_answer. Ambos
foram corrigidos para evitar divergência futura. Antes, o modelo factual recebia
o catálogo geral de oito blocos, incluindo abertura obrigatória e cards, além de
fontes longas separadas por nomes de arquivos e raciocínio padrão. A ampliação
correta do contexto tornou especialmente prejudicial o fallback que despejava
quatro passagens completas.

## Correção

- Contexto rotulado como pool entre documentos; agrupamento de passagens idênticas
  por conteúdo, com marcadores e fences originais. Nenhum chunk é cortado/removido.
- Prompt factual próprio: informação pedida primeiro, lista/tabela compacta,
  cobertura de todos os itens mesmo nos trechos posteriores, sem introdução/recap,
  sem seções por arquivo exceto pedido explícito, divergência relevante uma vez.
- Uma fonte suficiente por fato repetido, incluindo versões/traduções. Fontes
  adicionais permanecem para fatos complementares ou divergências. Alias
  determinístico só para passagens literalmente iguais, nunca por nome do currículo.
- Raciocínio low para a geração factual dentro do mesmo orçamento de 25 segundos.
- Repetições de índices válidos do LLM são normalizadas; índices desconhecidos
  continuam rejeitados. Links continuam vindo da evidência autorizada, fora do LLM.
- Timeout retorna aviso curto e as fontes consultadas com links, sem reproduzir
  documentos inteiros como se fossem a resposta factual.

## Replay real pareado

Pergunta: **Em quais empresas o Vitor trabalhou e quando?**
Classificador, embeddings e geração reais; sem histórico/menções, Google Drive.
Transações de uso revertidas. Código posterior executado por PYTHONPATH isolado,
sem alterar o processo da API. As 28 passagens e seus hashes são idênticos:
**55.675 caracteres de evidência em ambos**, mesmo orçamento de 64.000.

| Medida | Antes | Depois |
|---|---:|---:|
| Caracteres da resposta, sem bloco de fontes da UI | 17.603 | 289 |
| Tempo total | 25,85 s | 12,52 s |
| Empresas respondidas em síntese factual | 0 (fallback extrativo) | 4 |
| Passagens de evidência | 28 | 28 |
| Fonte da síntese factual | indisponível | Profile.pdf, link preservado |

Antes: “A síntese automática ficou indisponível. Estes são trechos indexados
relevantes, sem interpretação adicional:” e quatro passagens integrais por arquivo.
O corpo completo, com prompt efetivamente enviado, foi preservado no host em
`/tmp/document-ai-consolidation-before.json`.

Resposta final efetiva do serviço:

```text
Wasion International — jan-2021 a ago-2021 (fonte 1)
Cloudiabot (Cloudia Bot) — set-2021 a jan-2023 (fonte 1)
Estoca — fev-2023 a jun-2025 (registro indica término em jun-2025 em algumas versões) (fonte 1)
Allstacks — jun-2025 a Present/Agora (registro indica início em jun-2025) (fonte 1)
```

Os marcadores raw do LLM usam [7], remapeados para fonte 1 da lista vinculada ao
Profile.pdf; o frontend renderiza o botão [1]. O termo Present/Agora é o período
registrado, sem recalcular duração ou afirmar atualização na data de hoje.
O prompt e resposta JSON reais posteriores estão no host em
`/tmp/document-ai-consolidation-after-concise.json`. O relatório versionado
`content-consolidation-replay.json` inclui instruções reais completas, decisão,
modelo, esforço, métricas, nomes/hashes das passagens e resposta raw/final; omite
excertos privados e URLs. A redução medida é **98,36%**, mantendo quatro empresas.

Replays intermediários mostraram (1) índices repetidos rejeitados pela validação
e (2) resposta curta que omitia Allstacks. Ambos foram investigados antes de
ajustar o contrato: normalização dos índices e prompt factual próprio. A medição
é uma amostra, não uma garantia estatística de cobertura/concisão de todo o corpus.

## Validação e aplicação

Regressões com LLM mockado verificam os dois prompts reais, passagens longas
integrais, quatro empresas no perfil, citações/links, equivalência sem eliminar
datas divergentes, índices repetidos válidos, rejeição de índices inexistentes,
resumo explícito por arquivo preservado e timeout curto com fontes.

Comando completo: `cd backend && TEST_DATABASE_URL=<PostgreSQL descartável local>
.venv/bin/pytest -q`. O banco document_ai_consolidation_test é separado do banco
da aplicação. Resultado final fresco: **845 passed, zero skipped, zero failures,
exit 0, quatro avisos de depreciação, 71,15 segundos**. Log completo no host:
`/tmp/document-ai-consolidation-pytest-final.log`. O banco descartável foi removido
depois da suíte. As primeiras regressões novas falharam antes do fix: 4 failed,
3 passed; depois há oito casos novos verdes no conjunto completo.

Ruff nos cinco arquivos Python alterados: exit 0, All checks passed.
`docker compose config --quiet`: exit 0. `git diff --check`: exit 0.
`graphify update .`: exit 0, AST atualizado; nenhum arquivo graphify entra no commit.

Este worker não derrubou/recriou a stack nem fez push. Outra atividade recriou
api/worker/docling durante um replay (exec 137); a avaliação foi repetida e suas
capturas preservadas no host. O SHA do questions.py da API instalada difere do
código final: é necessário rebuild da imagem backend e recriação de api/worker.
Nenhuma migração ou rebuild de frontend é necessário para esta correção.
Os seis commits exigidos permanecem ancestrais. Alterações frontend existentes
foram mantidas; commits de outros workers continuaram chegando à main compartilhada.
