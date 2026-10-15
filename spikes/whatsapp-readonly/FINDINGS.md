# WA-POC-01 — achados locais

## WA-POC-02 — LOCAL_SETUP_FAILED depois do vínculo (base 018473d)

Registro antes da correção: `src/session.mjs` descarta a exceção de initialize
(init_error) e de onReady (setup_error), convergindo para LOCAL_SETUP_FAILED.
Em `src/live.mjs`, antes de mostrar seleção, onReady chama adapter.list →
client.getChats. O status sozinho não distingue essas origens. Os 43 testes
anteriores passam e não verificam diagnóstico dessas duas exceções.

Metadados lstat, sem ler arquivos privados: real/auth/session-readonly-poc e
web-cache existem (0700); snapshots existem (0600); run.lock/guard ausentes.
Runtime instalado: Node 24.3.0, whatsapp-web.js 1.34.7, Puppeteer 24.38.0.
Nenhum live real executado. Presença de perfil não prova validade da sessão.

Leitura estruturada somente do relatório de métricas (sem snapshot privado):
1 run, LOCAL_SETUP_FAILED; ready=1, authFailure=0, disconnected=0;
catalogChats=0, selectedChats=0, retainedMessages=0, historyMeasurements=0.
O ready foi alcançado; a listagem não confirmou catálogo. Isso estreita a
investigação para o caminho de listagem pós-ready, sem recuperar a exceção
descartada nem demonstrar qual operação interna do WhatsApp Web falhou.

Hipótese demonstrável: a perda de diagnóstico nasce nos catches que descartam
o erro. Reproduzir com initialize/getChats rejeitando e verificar diagnóstico
de etapa + classificação fechada, sem mensagem/stack/payload bruto. Isso corrige
a observabilidade, não comprova correção da falha da integração real.

Hipótese externa, NÃO confirmada para esta conta: getChats da 1.34.7 serializa
metadados e lastMessage e pode falhar por mudanças internas do WhatsApp Web.
Fonte primária: https://github.com/wwebjs/whatsapp-web.js/issues/201845.
Também há corrida de exposeFunctionIfAbsent (check → exposeFunction) em reload;
sem exceção real, nenhuma dessas hipóteses autoriza patch na dependência.

Verificação WA-POC-02: `npm test`, exit 0, **54/54 pass, 0 fail**. Regressões
confirmam distinção initialize/onReady/getChats, ausência de payloads/paths nos
diagnósticos, recusa de novo vínculo, deadline inclusive no getChats e sentinelas
de auth/cache/biblioteca intactas em pastas sintéticas. O hook real de LocalAuth
foi testado sem initialize/browser. Sem afirmação de correção da integração real.

## Revisão h-si, base 0de870b — investigação antes da correção

- F1 MÉDIA: `Engine.select` apaga `history`/`observations`; CLI esvazia selected
  ao reiniciar e chama select após confirmação. Perde evidência e pode reatribuir
  aliases ao trocar a ordem. Hipótese: separar gate de ingestão, preservar
  medições com run/seleção e manter aliases estáveis corrige na origem.
- F2 MÉDIA: timer literal de 30 min inclui setup e impede roteiro/estabilidade.
  Hipótese: duração validada/configurável e protocolo entre runs preservados.
- F3 BAIXA: ignore não cobre nomes reais de snapshot, auth, cache e lock.
- F4 BAIXA: lock usa wx sem distinguir PID morto; write usa tmp fixo sem
  recuperação; constructor escreve antes do lock. Hipótese: serializar aquisição
  e recuperação, recusar PID vivo/incerto e limpar só temporários conhecidos
  depois da posse exclusiva. Nunca remover lock ativo para tentar novamente.
- F5 BAIXA: testes cobrem componentes e CLI non-TTY, não orquestração live.
  Extrair runner injetável mantendo os gates de produção e testar com fakes.

### Verificação h-si após correções

F1–F5 corrigidos nesta rodada: `npm test` **43/43 pass, 0 fail, exit 0**;
comandos e contagens fresh em [RESULTS.md](RESULTS.md) e
[evidence/tests.json](evidence/tests.json).

- F1: gate de ingestão separado da seleção persistida; medições cumulativas com
  run/seleção, aliases estáveis e migração legada. Reprodução original vermelha
  (`0 !== 1`); regressões de vazio/reordenação/restart/proveniência verdes.
- F2: duração 1–120 min, padrão 60; deadline e validação de argumentos testados;
  protocolo de duas execuções de 90 min preservando evidência no README.
- F3: os 6 caminhos de defesa foram confirmados por `git check-ignore`, exit 0.
- F4: PID morto recuperado sob guard exclusivo, sem tocar em PID vivo/incerto;
  recuperação concorrente: 6 processos, 1 escritor. Só tmp conhecido e regular é
  limpo sob posse do lock. Guard órfão falha fechado e requer manutenção exclusiva
  manual; não se tenta reapagar guard automaticamente, para evitar corridas.
- F5: runner live injetável testado junto a session/adapter/engine/store reais,
  sem cliente WhatsApp real. Gates, restart/cancelamento, exclusão, abort e timer.

Dívida F-03 mantida: `npm audit --json` fresh exit 1, **9 high, 0 critical**.
Revisão h-si localizou a cadeia fora do caminho live; compatibilidade de upgrade
não foi comprovada. Nenhum override de Puppeteer e nenhum lockfile modificado.
Ensaio humano e viabilidade real continuam pendentes.

- F-01: revogação pode carregar ID do envelope diferente do ID da mensagem original.
  Origem: whatsapp-web.js 1.34.7 `src/Client.js`, `onChangeMessageTypeEvent` usa
  `protocolMessageKey` para corrigir identidade do original quando disponível.
  Reproduzido em teste do adapter com envelope diferente; tombstone no ID errado
  deixaria texto na biblioteca. Correção: preferir protocolo para revogações;
  testar também ausência de `revoked_msg`.
- F-02: doctor inicialmente não encontrou Chrome 146.0.7680.31. Causa reproduzida:
  instalação intencional com `--ignore-scripts` não baixa Chromium. Resolver com
  CLI local do Puppeteer `browsers install chrome`; doctor só abre `about:blank`.
- F-03: npm audit apontou 9 dependências classificadas high (nenhuma critical),
  incluindo cadeia Puppeteer → extract-zip/basic-ftp. Não executar downgrade
  automático sugerido por `npm audit fix --force`; muda a biblioteca testada.
  Registrar como dívida e bloqueio para promover a produção, não omitir.
- F-04: refetch inicialmente deduplicava qualquer ID já conhecido e descartava
  tipo `revoked`, portanto não reconciliava edição/exclusão offline disponível no
  histórico. Dois testes vermelhos reproduziram. Corrigir usando revisão local
  no início da busca (histórico só atualiza linhas sem evento mais novo durante a
  busca) e processando marcadores revoked. Ausência na janela nunca prova exclusão.
- F-05: revisão do ciclo identificou setup humano pendente sobrevivendo a uma
  desconexão, e erro no callback de persistência sendo tratado como parada normal.
  Testes específicos reproduzem ambos. Usar AbortSignal para cancelar perguntas
  antigas e status terminal de erro para persistência; sem conteúdo bruto em log.

## WA-POC-03 — registro antes da correção (base 77669c1)

Evidência humana recebida: session_profile/make_client reached; initialize started;
authenticated/ready reached; list_chats failed com tipo unknown, kind
OPAQUE_WEB_ERROR, frames Client.getChats/ExecutionContext.evaluate; setup_callback
failed e LOCAL_SETUP_FAILED. Demonstra a fronteira, não a causa interna.

Fonte instalada 1.34.7: Client.getChats → WWebJS.getChats → Chat.getModelsArray →
Promise.all(getChatModel). Cada modelo passa por chat.serialize(), metadados
de grupo/update e eventual Msg.get/getMessagesById(lastReceivedKey._serialized).
getChatById também usa getChatModel; trocar só a listagem deixaria esse acoplamento
na entrada do histórico. Chat.fetchMessages usa getChat(getAsModel:false).

Hipótese local testável: o catálogo mínimo é indevidamente acoplado à serialização
integral/última mensagem; uma falha nessas operações bloqueia todas as escolhas.
Reproduzir com LoadUtils/Client/Chat reais e modelos sintéticos, incluindo chave
de mensagem apenas $1 → getMessagesById([undefined]) → DataError e serialize que
lança. Corrigir o caminho da POC, sem afirmar qual desses casos ocorreu na conta
pessoal e sem patch amplo de dependência.

Verificação WA-POC-03: regressão source-backed vermelha 0/7 → verde 7/7;
suite final 65/65, 0 fail, exit 0. Chromium about:blank com validação nativa de
chave IndexedDB confirma falha do getChats original, lista mínima e histórico
sem serialização de chat. CDP recria DataError como DOMException no Node;
classificação dentro da página preserva a classe sem texto bruto. Probes novos
separam capacidade, enumeração e projeção e não testam serializer integral.
Fontes/diff main fixado em UPSTREAM.md; registros em evidence/catalog-repair.json.
A correção remove o acoplamento reproduzido da POC; a etapa exata da conta real
permanece não demonstrada e compatibilidade de mensagens/eventos não é presumida.
