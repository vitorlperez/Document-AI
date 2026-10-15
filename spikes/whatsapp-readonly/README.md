# WhatsApp → biblioteca local do ArquivIO: POC somente leitura

**Implementação e validação simulada entregues; integração com conta real NÃO
validada.** Nenhuma conta vinculada, nenhum envio e nenhuma gravação no ArquivIO.

Programa independente com whatsapp-web.js **1.34.7** fixado no lockfile, Node **22+**.
A biblioteca local demonstra documentos por conversa/dia UTC com blocos, autoria
pseudonimizada, horário e proveniência. Não cria embeddings nem chama LLM.
`arquivio-poc://` é referência da POC, não permalink WhatsApp ou rota do produto.

## Executar sem conta

Na raiz do workspace:

```sh
cd spikes/whatsapp-readonly
npm ci --ignore-scripts
npm test
npm run demo
npm run report
```

Testes não requerem Chromium, rede ou credenciais. Fixtures são inventados.
`demo` sobrescreve apenas a execução simulada. Resultado esperado: 2 conversas
selecionadas, 2 mensagens retidas, 1 tombstone e 2 documentos. Texto apagado,
duplicata, texto anterior à edição e conversa de controle não selecionada não
aparecem na biblioteca final.

Para verificar separadamente o ambiente do cliente:

```sh
./node_modules/.bin/puppeteer browsers install chrome
npm run doctor
```

O instalador baixa Chrome pelo Puppeteer já instalado. `doctor` importa o cliente,
abre **somente about:blank** e fecha o browser. Não acessa WhatsApp. Testes e doctor
podem rodar sem desktop; o fluxo real exige interface gráfica. Não desative o
sandbox do Chromium.

## Etapa humana pendente: vínculo e escolha das conversas

Use terminal local sem gravação, capturas de tela ou CI. Haverá nomes privados no
terminal e um QR de autenticação no navegador. **Não cole QR, nomes, números nem
conteúdo em chats, relatórios ou issues.**

```sh
npm run live -- --consent
```

1. Exige TTY e `--consent`, explica os efeitos e pede **VINCULAR**. Sem a frase
   exata, nem cliente nem perfil de sessão são abertos.
2. Abre Chrome/WhatsApp Web local. No telefone: **Aparelhos conectados → Conectar
   aparelho**; escaneie conscientemente. QR não é impresso nem salvo pelo código
   da POC. Sessão existente é reutilizada após consentimento, sem exigir novo QR.
3. Lista os chats/grupos retornados por `getChats`. Digite índices separados por
   vírgula (`2,5`). Não há wildcard, seleção automática ou retomada silenciosa da
   seleção anterior. Seleção inválida/vazia cancela sem ingerir.
4. Confirme **SINCRONIZAR**. Só então retém texto e busca histórico das conversas
   escolhidas, inicialmente 200 mensagens/conversa. Aliases `chat-1`, `chat-2`
   seguem a ordem da seleção; nomes aparecem somente no terminal local.
5. Durante a execução, use estes comandos:

```text
stats
history 500
history 2000
check listing pass
check selection pass
check history fail
check new pass
check edit pass
check delete pass
check reconnect pass
check restart pass
check logout pass
quit
```

`history N` aceita 1–5000 e consulta só selecionados. `check` registra uma
**declaração humana** (`pass`/`fail`), separada dos contadores; nunca certifica
integração. Após encerrar, `npm run report -- --real` imprime métricas sem texto,
nomes ou IDs. Durante execução use `stats`: lock impede outro processo de ler o
snapshot simultaneamente. Encerra após 30 minutos; nova execução exige novamente
consentimento e seleção.

Para medir eventos, use conversas de teste com participantes cientes: outra pessoa
pode enviar/editar/apagar textos sintéticos manualmente no próprio WhatsApp. A POC
não oferece envio, reações, marcação como lido, alteração de grupos ou download de
mídia. Não use o composer/chats na janela Chrome da POC. Ainda é uma sessão Web
completa: há tráfego de vínculo/sync/protocolo e podem ocorrer efeitos de presença
ou cache do cliente. WhatsApp não impõe um escopo de permissão read-only aqui.

## Armazenamento e desligamento

Padrão: `~/.local/share/arquivio-whatsapp-poc/{simulated,real}/`.
Alternativa: `ARQUIVIO_WA_POC_HOME=/caminho/absoluto/dedicado`, fora de qualquer git.
Recusa repositório atual (inclusive via symlink), outro git, pasta não dedicada e
redirecionamento de auth/cache por symlink.

- `auth/`: perfil LocalAuth/Chromium, **credencial equivalente a dispositivo
  vinculado**. Pode cachear dados de **toda a conta**, incluindo conversas não
  selecionadas. A seleção limita a biblioteca, não o protocolo/cache do browser.
  Esta consequência é explicada antes de VINCULAR.
- `library.private.json`: estado e documentos na mesma substituição atômica.
  Contém texto privado e IDs internos de seleção; não compartilhe. Edição substitui
  texto antigo; exclusão observada remove texto/autor e deixa tombstone. Não há
  journal de eventos brutos ou export de conteúdo para o git.
- `report.json`: contagens, aliases, limites/alcance etário do histórico, duração
  das buscas, conexão e checks humanos. Não contém texto/telefone/nome. Mesmo
  contagens e horários de execução podem ser dados empresariais.
- Diretórios 0700, arquivos da POC 0600, `umask 077` herdado pelo cliente. Não há
  criptografia extra em repouso, envio cloud ou backup implementado pela POC.

`quit`/Ctrl+C fecham o browser preservando sessão. Para desligar definitivamente,
**remova o dispositivo no WhatsApp do telefone**, depois apague a pasta `real/`.
Apagar arquivos sozinho não comprova revogação no servidor. Não promete apagar
cache/backups do SO ou do telefone. Se crash deixar `run.lock`, confirme que o PID
ali contido não está executando antes de remover somente esse arquivo. Remova
`.tmp` remanescente só com processo parado; contém dados privados e o runner falha
com segurança em vez de sobrescrevê-lo.

## Critérios e protocolo de sucesso real

Por cenário: **pendente / passou / falhou**, com ambiente e duração observados,
sem copiar conteúdo. Hoje todos os cenários reais estão **pendentes**.

1. **Listagem/seleção:** 1 grupo, 1 individual e 1 conversa de controle não
   selecionada. Compare com telefone. `catalog` conta tipos, mas só o que a sessão
   oferece; não prova catálogo completo. Conteúdo do controle deve estar ausente
   da biblioteca da POC.
2. **Histórico:** anote no telefone a idade de mensagens de referência (7/30/90
   dias), sem textos. Busque 200/500/2000; registre `requested`, `returned`,
   `newlyRetained` (inclui linhas atualizadas), `oldestAgeDays`, `spanDays`,
   `durationMs`, `ok`. Confira referências manualmente. Sucesso = medir alcance e
   divergências; histórico insuficiente é resultado válido do ensaio. Retornar
   menos que o pedido não prova término do histórico.
3. **Novas:** participante envia manualmente 10 textos sintéticos no grupo e 10
   no individual, mais 2 no controle. Em até 10 s/evento (cronômetro do operador),
   20 aparecem uma vez, 0 do controle. Compare baseline de `events.new`; contagem
   de inserções não é automaticamente contagem de entregas novas do servidor.
4. **Edição:** edite 3 textos. Dentro de 10 s após receber evento, só texto novo
   nos documentos/snapshot. Repita 1 edição com POC offline e refaça `history`;
   registre separadamente se o cliente devolveu a atualização.
5. **Exclusão:** apague para todos 3 textos e para mim 1. Dentro de 10 s após
   evento recebido, 0 textos correspondentes e tombstones presentes. Repita
   offline e registre falha se não chegar marcador. Ausência em fetch **jamais**
   significa exclusão. Sem promessa de purga offline completa.
6. **Reconexão:** desligue/religue rede local por ~5 s. Se o Web client se recuperar
   internamente sem emitir evento, `disconnected` pode continuar zero. Exigir nova
   mensagem visível em até 60 s após restauração, sem duplicata. Se emitir evento,
   runner destrói cliente, reutiliza LocalAuth e tenta em 1/2/4 s, até 3 tentativas
   totais por execução. Após ready, refaz janela de 200/selecionado. Isso não prova
   recuperação completa do intervalo offline.
7. **Restart/revogação:** `quit` → reiniciar com consentimento → selecionar de
   novo → verificar sessão, tombstones e dedup. Revogue dispositivo no telefone:
   sem loop de reautenticação; pode retornar `AUTH_REQUIRED` ou falha local.
   Reinício deliberado depois deve pedir QR.
8. **Estabilidade:** observar 30 min e repetir após restart, contando falhas e
   retries. Não demonstra SLA ou estabilidade por dias/semanas. Mudanças futuras
   de WhatsApp Web exigem repetir o ensaio.

**Conclusão de viabilidade:** pipeline local demonstrado; integração real
inconclusiva. Só avançar investigação se seleção, novos, edições/exclusões online
e reconexão/restart passarem com conta real e o cliente aceitar alcance histórico
medido. Se eventos offline não puderem ser reconciliados, não atende espelhamento
confiável. **Não promover a produção**: faltam ensaio real, solução de acesso por
pessoa e avaliação das dependências/estabilidade da rota não oficial.

## Limites deliberados

Texto `chat` até 64 mil caracteres/mensagem, 50 mil linhas retidas (limites
defensivos, não benchmark). Sem anexos/áudio/OCR, status, broadcasts/canais,
notificações, view-once ou mensagens marcadas temporárias. Histórico disponível
ao dispositivo não garante backup inteiro/período fixo. Chats não retornados,
equivalência PN/LID, comunidades, remoção/saída de grupo e troca de conta não foram
validados. Não reutilize a mesma pasta para outra conta: desligue e limpe antes.
A seleção não é ACL e não concede acesso a ninguém no ArquivIO.

Refetch corrige textos/marcadores devolvidos. Revisão local impede resultado de
busca iniciado antes de edição ao vivo de sobrescrevê-la; não cria ordem causal
global. Tombstones impedem ressurreição, mas exclusões nunca recebidas são lacuna.
Cada mudança regrava snapshot completo; não mede escala empresarial. Blocos têm
`untrusted:true`, mas nenhum modelo é chamado: não valida a cerca anti-injeção do
produto. Biblioteca local demonstra materialização, não integração com RAG real.

Veja [DECISION.md](DECISION.md), [RESULTS.md](RESULTS.md), [FINDINGS.md](FINDINGS.md).
Módulos: core (normalização/materialização), connector (leitura/eventos), session
(ciclo/retry), store (persistência), cli (consentimento e operação).
