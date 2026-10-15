# WhatsApp → biblioteca local do ArquivIO: POC somente leitura

**Implementação e validação simulada entregues; integração com conta real NÃO
validada.** O usuário reportou vínculo humano bem-sucedido seguido de
LOCAL_SETUP_FAILED antes da seleção. Nenhum envio nem gravação no ArquivIO.

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

## Diagnosticar LOCAL_SETUP_FAILED preservando a sessão vinculada

A conta pessoal já autorizada pode ser usada; conta de teste é opcional.
Não apague auth/cache, não troque de conta e não faça outro vínculo para tentar
corrigir este status. Ele antes ocultava tanto erro em `initialize()` quanto
erro no callback de `ready` (incluindo `getChats()`). A exceção original da
execução antiga não foi guardada e não pode ser reconstruída pelo status.

Feche outras instâncias da POC. No mesmo terminal e com a mesma pasta de dados:

```sh
cd /Users/vitorperez/Documents/Document-AI/spikes/whatsapp-readonly
npm run diagnose
```

Este comando reutiliza **somente o perfil existente**, sem pedir VINCULAR ou
SINCRONIZAR. Faz uma tentativa até `getChats()` e fecha o browser, com limite de
três minutos. Não mostra nomes, não oferece seleção, não busca histórico, não
envia mensagens e não lê/regrava a biblioteca privada nem o relatório anterior.
Não apaga auth/cache; bloqueia a limpeza LocalAuth no logout. O Chromium pode
atualizar seu próprio perfil/cache durante a conexão. A biblioteca WhatsApp
serializa objetos de chats internamente em `getChats()` (inclusive lastMessage);
a POC descarta o retorno sem inspecionar nomes/IDs/textos. Não abra chats ou use
o composer na janela de diagnóstico.

Se precisar de autenticação, encerra com `AUTH_REQUIRED`, sem iniciar novo
vínculo. Perfil ausente/inseguro dá `EXISTING_SESSION_REQUIRED` antes de abrir o
cliente. Não reconecta automaticamente. `DIAGNOSIS_TIMEOUT` indica que atingiu
o limite; Ctrl+C encerra com `DIAGNOSIS_INTERRUPTED`.

Compartilhe **somente as linhas `SETUP_DIAGNOSTIC {...}` e o status final**.
Elas usam vocabulário fechado: etapas, classe/código conhecido, classificação e
nomes fixos de funções. Não imprimem mensagem/stack bruto, paths, payloads de
auth/QR ou dados de chats. Exemplo sintético:

```text
SETUP_DIAGNOSTIC {"stage":"list_chats","event":"failed","error":{"type":"Error","kind":"OPAQUE_WEB_ERROR","code":"unknown","frames":["Client.getChats"]}}
LOCAL_SETUP_FAILED
```

`OPAQUE_WEB_ERROR` classifica o erro `r`/`r: r`, sem atribuir causa. Uma falha
`BINDING_ALREADY_EXISTS` em initialize aponta outra fronteira. Há relatos
primários de incompatibilidade em
[getChats na 1.34.7](https://github.com/wwebjs/whatsapp-web.js/issues/201845), mas
isso ainda não foi comprovado nesta conta; nenhum patch especulativo, pin de
WhatsApp Web, upgrade ou exclusão de cache foi aplicado.

`SETUP_DIAGNOSED` (exit 0) comprova apenas que inicialização + getChats terminaram
naquela tentativa. Não valida catálogo completo, ingestão, eventos ou estabilidade.
Outros resultados retornam exit 1. O modo live normal também emite diagnósticos
de etapa, mas exibe nomes na seleção: não compartilhe seu terminal inteiro.

## Etapa humana pendente: vínculo e escolha das conversas

Use terminal local sem gravação, capturas de tela ou CI. Haverá nomes privados no
terminal e um QR de autenticação no navegador. **Não cole QR, nomes, números nem
conteúdo em chats, relatórios ou issues.**

```sh
npm run live -- --consent --duration-minutes 90
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
   são atribuídos na primeira escolha e permanecem estáveis na mesma pasta,
   inclusive ao reordenar/reselecionar; nomes aparecem somente no terminal local.
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
snapshot simultaneamente. `--duration-minutes N` aceita inteiro **1–120**, padrão
**60 minutos**. O timer inicia antes de criar o cliente e inclui QR/seleção; ao
atingir o limite, encerra com `RUNTIME_LIMIT` e persiste evidências. Valores
inválidos/repetidos são recusados antes de abrir cliente ou armazenamento. Use
90 minutos por execução para acomodar roteiro e 30 minutos de estabilidade;
se necessário, até 120. Nova execução exige novamente consentimento, escolha e
SINCRONIZAR. A seleção persistida nunca autoriza ingestão ao reiniciar.

### Preservar evidência entre execuções do ensaio

Use **a mesma conta autorizada e a mesma pasta dedicada** em ambas as execuções.
Uma conta de teste é opcional, não é requisito para a conta pessoal autorizada.
Não apague `real/`, não copie snapshots para o git, não use `demo` como evidência
real e não troque de conta na mesma pasta. Para explicitar a pasta, antes do live:

```sh
export ARQUIVIO_WA_POC_HOME="$HOME/.local/share/arquivio-whatsapp-poc"
```

1. Na primeira execução, faça cenários 1–6, registre `check` conforme observado
   e observe 30 min após sincronização. Anote contadores de baseline via `stats`
   para comparar deltas, pois eventos/conexão são cumulativos da pasta.
2. Encerre com `quit`. Opcionalmente guarde métricas locais fora do git, com o
   comando abaixo. É um relatório de contagens, não cópia do conteúdo privado.
3. Execute novamente o live de 90 min na mesma pasta. Antes da nova confirmação,
   textos/tombstones/evidências anteriores são preservados, mas eventos e buscas
   de conteúdo não são ingeridos. Cancele a seleção para verificar esse gate;
   depois abra outra execução, escolha conscientemente e confirme para continuar.
4. Confira dedup/tombstones, registre `check restart pass/fail` e observe outros
   30 min. Só então teste revogação no telefone e gere o relatório final.

```sh
umask 077
node src/cli.mjs report --real > "$ARQUIVIO_WA_POC_HOME/real/metrics-run-1.json"
```

Altere apenas o sufixo para `metrics-final.json` ao concluir. O snapshot canônico
contém todos os `runs` e `selections`; `history`/`observations` recebem `runId` e
`selectionId`, sem truncamento silencioso em 100 buscas. Selecionar novamente ou
cancelar não apaga essas medições. Materialização ainda remove mensagens de
conversas explicitamente desmarcadas. Evidência legada recebe proveniência
`legacy`: não é possível reconstruir runs que o código anterior não registrou.
Checks continuam sendo declarações humanas. Relatório após crash é calculado do
snapshot atômico confirmado; gravações ainda em `.tmp` não são promovidas.

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
cache/backups do SO ou do telefone.

Após crash, a próxima aquisição do lock verifica o PID com sinal 0. Se o processo
não existe (`ESRCH`), recupera `run.lock`; PID vivo/reutilizado, falta de permissão
ou estado incerto bloqueiam com `ALREADY_RUNNING`. PID inválido/vazio bloqueia com
`LOCK_OWNER_UNKNOWN`. **Nunca remova o lock de processo ativo**. Depois da posse
exclusiva, descarta só `.arquivio-wa-poc.tmp`, `library.private.json.tmp` e
`report.json.tmp` regulares, preservando o último snapshot confirmado e arquivos
não reconhecidos. Symlinks são recusados. O live informa `RECOVERED_LOCAL_RUN`.

`run.lock.guard` serializa aquisição/recuperação para impedir dois recuperadores
de apagarem o lock recém-criado de um terceiro processo. `LOCK_RECOVERY_BUSY`
indica aquisição concorrente (repita depois) ou crash durante essa curta seção.
**Esse guard nunca é removido automaticamente**, mesmo com PID morto: reapagar
um guard criaria outra corrida. Recuperação manual excepcional: feche todas as
POCs, impeça novas execuções durante a manutenção e confirme que os PIDs de
`run.lock` e `run.lock.guard` não existem. Só com exclusividade humana confirmada,
remova o guard órfão e, se PID inválido exigir, o lock inválido. Se não conseguir
confirmar a exclusividade, preserve ambos. Depois repita o comando normal; ele
recuperará lock morto e temporários. Não apague a biblioteca ou auth para resolver
contenção. A recuperação não promete durabilidade de dados ainda não confirmados
nem proteção contra edição manual concorrente dos arquivos de lock.

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
(ciclo/retry), store (persistência), live (gates/operação com dependências
injetáveis nos testes), cli (entrada e diagnóstico seguro).

Revisão h-si F1–F5: evidência fresh em [RESULTS.md](RESULTS.md) e
[FINDINGS.md](FINDINGS.md). Nenhum override de Puppeteer foi aplicado: os 9 high
do audit continuam dívida documentada. A revisão os localizou fora do caminho
live ensaiado; isso não prova compatibilidade de upgrade nem libera produção.
