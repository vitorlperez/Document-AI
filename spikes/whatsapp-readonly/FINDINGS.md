# WA-POC-01 — achados locais

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
