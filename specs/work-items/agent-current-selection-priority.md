# Seleção atual prevalece sobre alvos do histórico

Status: corrigido e validado localmente; a API em execução requer rebuild.

## Sintoma e reprodução

Conversa local `dfe6d21c-00c0-4482-a70c-0fc80d2d9f33`, última mensagem
às 2026-09-29 19:50:49 UTC: “E dentro dessa pasta, o que temos de informacao
sobre o Vitor?”. O contexto persistido inclui a menção de pasta
`cafa63fd-986a-40b1-ab45-d838f5bf4307` (Test Document-AI).
As três perguntas anteriores são as do transcript fornecido pelo usuário.

O serviço Docker é `api`; `docker compose logs backend --since 30m` retorna
“no such service”. Os logs equivalentes de `api` e o transcript persistido
confirmam `list_files_with_summaries`, `previous_answer_files`, decidido por LLM,
tool `summarize_inventory`, sem fallback na última mensagem. Request
`019b476a-b60a-488a-98d7-bd1822a006e4`: classificador 2073 ms, síntese 18719 ms,
HTTP 200 em 20902 ms. O timeout pertence à terceira pergunta, que teve
`plan_rejected` e resposta extrativa preservando fontes (fb8003f).

Reprodução sem escrita no banco, executando AgentService no container existente
com os seis registros de histórico, providers e menção originais e decisão LLM
mockada igual à persistida: recupera Vitor_Perez_Resume_Revised.pdf, Escopo MPS e
Escopo de MPS, sem consultar a pasta escolhida. O classificador recebe as quatro
últimas mensagens (500 caracteres cada), contagens de menções e os nomes dessa
lista antiga. A síntese recebe pergunta atual, intenção, catálogo e trechos dos
três arquivos antigos; não recebe o histórico nem a pasta em separado.
`_previous_listed_files` conserva o último inventário não vazio (segunda resposta),
por isso os alvos nem sequer são as citações da terceira resposta.

## Causa raiz e hipótese

O prompt ordena alvos anteriores antes de `mentioned`; `parse_intent` normaliza
somente `library`/`previous_turn_files`; `_resolve_targets` retorna alvos anteriores
antes de testar as menções. Assim uma decisão LLM válida substitui a seleção
explícita. Hipótese: priorizar menções no contrato, na normalização e na resolução
impede esse conflito independentemente da formulação da pergunta.

Regra autorizada: seleção atual de pasta/arquivo prevalece; sem seleção nova,
o seguimento por arquivos citados de e983721 continua válido. Nenhuma regra lexical,
migração, alteração de catálogo ou mudança de frontend é necessária.

## Limite dos dados locais

O usuário informou um único Profile.pdf, mas o catálogo local tem dois filhos
indexados nessa pasta: Profile.pdf (5 chunks) e A Gravidade do pecado de impuresa
(35 chunks). A regressão automatizada deve cobrir a pasta com só Profile.pdf;
a reprodução contra o banco real deve respeitar os dois filhos existentes.
Nenhum dado de catálogo será alterado para forçar o cenário informado.

## Correção e evidência

- Prompt: `mentioned` é o primeiro alvo, e alvos históricos só são elegíveis sem
  anexos atuais. Normalização: qualquer alvo válido do classificador vira
  `mentioned` quando há seleção; os ordinais históricos são descartados. Resolução:
  retorna as menções antes de consultar os alvos históricos. A autorização dos
  tools permanece intacta e nenhuma lista de palavras foi adicionada.
- Regressão com as três perguntas anteriores, inventário antigo e timeout na
  terceira resposta: pasta com só Profile.pdf ou seleção direta do arquivo,
  classificador mockado tentando `previous_answer_files` ou `previous_ordinals`.
  Valida histórico enviado, catálogo/trechos da síntese, fontes com URLs,
  marcadores numéricos, referências e ausência de fallback.
- Vermelho antes da correção: `cd backend && ./.venv/bin/pytest -q --tb=short
  tests/unit/test_document_agent.py -k current_selection` → exit 1, 4 failed,
  todos por manter o alvo histórico em vez de `mentioned`.
- Verde: `cd backend && ./.venv/bin/pytest -q tests/unit/test_document_agent.py
  tests/unit/test_agent_flow.py` → exit 0, 57 passed. Inclui o seguimento de e983721,
  citações preservadas no timeout de fb8003f e o contrato de apresentação existente.
- Completo: `cd backend && ./.venv/bin/pytest -q` → exit 0, 430 passed,
  8 skipped e 4 warnings de depreciação. Os testes Postgres de integração opt-in
  continuam skipped neste comando; a reprodução real abaixo usa o Postgres Docker.
- Ruff dos dois arquivos de implementação e dois de testes → exit 0.
- `git diff --check` → exit 0.
- `.tools/graphify/bin/graphify update .` → exit 0, 3828 nós, 10438 arestas.
  Arquivos do grafo permanecem fora do commit.
- Replay contra o banco local com código corrigido e mesma decisão mockada →
  exit 0: `mentioned`, `list_library_children`, catálogo somente dos dois filhos
  existentes da pasta, sem os três arquivos antigos.
- Replay adicional com LLM real no container `api`, código corrigido carregado
  somente na memória de um processo isolado, histórico/providers/menção originais,
  sem persistência ou reinício → exit 0: o LLM escolheu
  `list_files_with_summaries / mentioned`; síntese recebeu somente os dois filhos
  da pasta, resposta descreveu Profile.pdf e citou ambos. Não houve fallback.
  Esse teste verifica o fluxo de serviço e o provedor real, não a UI/rota HTTP.

## Aplicação e limites

Nenhum frontend foi alterado: tsc/eslint não se aplicam. Nenhuma migração, push,
limpeza de banco ou parada da stack. fb8003f, 7d3df7e e e983721 continuam ancestrais.
Para a API atender novas mensagens com o fix, reconstruir a imagem backend e
recriar apenas `api`: `docker compose up -d --build --no-deps api`.
O worker compartilha essa imagem, mas o código modificado é do fluxo de perguntas
da API; não exige reinício do worker para corrigir as respostas.

O conteúdo já salvo na conversa não é reescrito. A divergência de dois arquivos
no catálogo em vez do único arquivo informado permanece registrada, sem alteração
de dados. A escolha de apresentação do LLM e a seleção histórica de inventário
quando não há nova menção permanecem com o contrato existente.
