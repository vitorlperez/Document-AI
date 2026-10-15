# WA-POC-01 — achados locais

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
