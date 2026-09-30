# Follow-ups contextuais e fontes — 2026-09-29

## Causa raiz comprovada

A conversa persistida mostra a primeira pergunta “Em quais empresas o Vitor trabalhou e quando?” respondida com quatro empresas, versões divergentes dos períodos e sete fontes vinculadas. O segundo turno “Qual foi o último emprego?” foi classificado como `list_files/library`; a execução caiu em `plan_rejected`, buscou a biblioteca e terminou em `invalid_generation_output`, com zero citações.

No replay independente do follow-up com o primeiro turno persistido, o classificador escolheu `ask_content/library` e escreveu “Qual foi o último emprego de Vitor?” em `query`. Esse campo serve apenas à busca por nome de arquivo e era descartado para `retrieve_evidence`. O embedding recebeu a pergunta crua. O histórico entregue ao classificador terminava em 500 caracteres, antes de Allstacks. As fontes históricas não foram escolhidas como alvo.

A única evidência enviada ao LLM foi `BANCO DE PERGUNTAS - ENTREVISTA RH.pdf`, score **0,53887**, 2932 caracteres; os candidatos de currículo visíveis no top-15 tiveram scores até **0,39481**, abaixo de `MIN_EVIDENCE_SCORE=0.45`. O LLM retornou `Insufficient evidence.`. Portanto a recusa observada **não foi um gate determinístico sem candidatos**: o gate eliminou os currículos, o modelo recebeu a fonte errada e abstém; o tratamento de geração inválida apagou também a fonte consultada. O texto da recusa está em `agent.py:_honest_insufficient` (linha 795 antes da alteração). Os logs `docker compose logs api --since 30m` confirmam um candidato e `provider_outcome=invalid_output`. O comando solicitado com `backend` retornou `no such service`; o serviço real é `api`.

`followup-probe-before.json` registra intenção bruta, histórico, consulta efetivamente embeddada, scores, candidatos, resultado da geração e status. Não inclui credenciais ou URLs.

## Correção na origem

- O classificador fornece `standalone_query`, pergunta factual autônoma de até 1000 caracteres, resolvendo referências por LLM. Ela chega tanto ao embedding quanto à geração, e fica em `resolved_context` para diagnóstico.
- O histórico recente mantém a resposta completa, incluindo o final. O prompt distingue entidades/fatos de arquivos e orienta follow-ups factuais a continuar as fontes citadas.
- Mantido o mecanismo `e983721`: as citações anteriores viram alvos do catálogo atual. Esses arquivos são autorizados novamente e seus chunks indexados completos são relidos como candidatos junto da busca por score. Não se confia em excerpts históricos nem se conserva acesso revogado. No catálogo disponível durante a medição, apenas `Profile.pdf` ainda tinha referência de arquivo resolvível dentre as sete fontes originais; a avaliação não inventa alvos para as demais.
- No fluxo `ask_content`, o modo `content` usa scores para ordenar, sem descartar candidatos pela barreira de 0,45. A síntese decide se sustentam a pergunta. O modo legado `relevance` continua compatível, inclusive o gate de pasta testado em `1b7de66`.
- Abstenção ou saída inválida não retorna afirmações não verificadas, mas preserva as fontes autorizadas consultadas. A resposta honesta mostra `Arquivos consultados` com os marcadores; a interface recebe as citações e seus links para `Fontes`.
- `3afc9bd` continua prevalecendo: seleção atual ganha do histórico, inclusive nas novas perguntas autônomas. `1b7de66` continua preservando chunks completos, orçamento de 64000 caracteres e mescla ordenada de adjacentes.

Não há listas de palavras por pergunta nem regra específica de empresa. O modelo continua `gpt-5-nano` no classificador e `gpt-5-mini` na geração. Experimentos com esforço `minimal` ainda confundiram fatos e inventário; `low` resolveu os alvos e as perguntas autônomas. O ensaio direto tomou 3,31 s e 5,64 s em dois follow-ups. Por isso o classificador recebe 2000 tokens de saída e timeout default de **8 s**, dentro do limite total inalterado de **25 s**. As demais chamadas não mudaram de esforço.

## Mini eval real antes/depois

Extensão do mini eval de `profile_retrieval_cases.json`, em `followup_eval_cases.json`, agora com quatro follow-ups sem nova seleção. Usa banco, embeddings e classificador reais da stack local; geração mockada captura exatamente os chunks que a síntese receberia. As perguntas de duração e cargo acrescentam uma resposta-fixture explícita identificando Allstacks, isolando a resolução de “lá” e de cargo. A primeira resposta base é a conversa persistida do usuário. Os vetores são armazenados somente em `/tmp`; todas as transações de uso são revertidas.

Recall conta o chunk 1 esperado de `Profile.pdf`. Fatos visíveis conta textos literais no contexto, não acerto de uma resposta simulada. Proveniência original de chunks é considerada após a mescla. Os cinco chunks do perfil se tornam um trecho completo de 7869 caracteres.

| Follow-up | Recall antes → depois | Fatos visíveis antes → depois |
|---|---|---|
| Qual foi o último emprego? | 0/1 → 1/1 | 0/2 → 2/2 |
| e o último? | 0/1 → 1/1 | 0/2 → 2/2 |
| quanto tempo ficou lá? | 1/1 → 1/1 | 3/3 → 3/3 |
| qual o cargo? | 0/1 → 1/1 | 0/2 → 2/2 |
| Total micro | **1/4 (25%) → 4/4 (100%)** | **3/9 (33,3%) → 9/9 (100%)** |

Os relatórios brutos são `followup-before.json` e `followup-after.json`. O hash do prompt enviado em todas as quatro chamadas depois corresponde ao hash do prompt do módulo: `e17c19b71466ad0fa6b9014a46eb63f29fd3a3f0d64a2f3012d24488cc4c027a`. O classificador é estocástico e as reescritas diferem; não é comparação com um vetor idêntico, pois a mudança é justamente reescrever. Esta amostra pequena mede cobertura deste currículo e destas referências, não qualidade geral do corpus.

## Replay com LLM real

`followup-replay.json` inclui primeira pergunta ampla gerada novamente com LLM real e oito citações vinculadas. Sem nova seleção, “Qual foi o último emprego?” retorna **Software Engineer na Allstacks; June 2025 - Present**, com `(fonte 1)` e link de `Profile.pdf`. Os outros três follow-ups também responderam com fonte vinculada: Allstacks, **8 meses conforme registrado no documento**, e **Software Engineer**. Não foi recalculado o registro `Present` em relação à data atual.

Um replay adicional **antes**, com a primeira resposta gerada novamente, teve sucesso: o classificador antigo dessa vez escolheu `ask_content/previous_answer_files` e o follow-up respondeu Allstacks com link, mesmo usando a query crua. Registro: `followup-sequence-before.json`. Isso confirma que a falha dependia da decisão do classificador; a reprodução com o primeiro turno real persistido recusou, mas não se afirma que todo replay do código anterior falha. O escopo herdado de `e983721` já funcionava quando escolhido corretamente.

O fluxo é `AgentService` completo, incluindo classificação, resolução de catálogo, embeddings, síntese e citações. A execução posterior usa cópia isolada de código no próprio container, sem alterar o processo da API ou reiniciar a stack. As respostas não foram persistidas.

## Verificação

- Regressões novas contra snapshot de `1b7de66` com imports explicitamente fixados: **6 failed, 1 passed**, exit 1. A primeira falha é a consulta crua no lugar da autônoma; a segunda é o gate impedindo a geração; quatro falhas cobrem validação do novo contrato.
- Foco no fluxo, currículo, semântica e deadlines: **129 passed**, exit 0, 4,85 s, incluindo seleção atual com pergunta autônoma.
- Suíte completa do snapshot isolado **HEAD + somente os arquivos deste fix**, PostgreSQL descartável separado: **459 passed, zero skipped**, exit 0, quatro avisos de depreciação, 24,66 s. Os arquivos do snapshot foram comparados byte a byte ao checkout atual antes da entrega.
- Suíte completa da árvore compartilhada: **464 passed, 1 failed**, zero skipped, exit 1. Falha fora do escopo em `test_foundation_migration_applies_and_reverts_on_disposable_postgres`: a feature concorrente acrescenta FK `manual_sync_runs`, mas o teste espera só `organizations` e `workspace_folders`. Não foram alterados seus arquivos; o chamador foi informado.
- Ruff nos arquivos Python deste fix: exit 0, `All checks passed!`. `git diff --check`: exit 0. `docker compose config --quiet`: exit 0.
- `.tools/graphify/bin/graphify update .`: exit 0, atualização AST sem LLM. Arquivos graphify sujos ficam fora do commit.
- `docker compose ps`: API e PostgreSQL/Redis saudáveis; frontend e worker continuam em execução.

## Repetir e aplicar

Copie `followup_eval.py` e `followup_eval_cases.json` para `/tmp` no container `api`. Antes: `docker compose exec -T api python /tmp/followup_eval.py --cases /tmp/followup_eval_cases.json --output /tmp/followup-before.json --embedding-cache /tmp/followup-embeddings.json`.

Depois, copie `backend/app` para um diretório novo `/tmp/contextual-followup-eval`, sem substituir `/app/app`. Execute com **working directory e PYTHONPATH da cópia**: `docker compose exec -T -w /tmp/contextual-followup-eval -e PYTHONPATH=/tmp/contextual-followup-eval api python /tmp/followup_eval.py --cases /tmp/followup_eval_cases.json --output /tmp/followup-after.json --embedding-cache /tmp/followup-embeddings.json`. Para replay: acrescente `--replay --fresh-sequence`. Os hashes do código e do prompt ajudam a verificar o código realmente carregado; não use `python -c` no diretório `/app` para inferir os imports de um script em `/tmp`.

Aplicação exige rebuild da imagem backend e recriação de **api e worker**. Este fix não exige frontend, migração de banco ou reindexação. A stack não foi derrubada e nenhum push foi feito. Skills: inline [oc-builder, oc-blackbox, oc-stamp].
