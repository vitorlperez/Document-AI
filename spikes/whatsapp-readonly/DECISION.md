# WA-POC-01 — escolha de cliente

Consulta: 15/10/2026. Escopo: conversas existentes por dispositivo não oficial,
conforme decisão expressa do usuário, apenas para a POC.

**Escolha: whatsapp-web.js 1.34.7**, retornada por `npm view`, fixada no lockfile.
Menor caminho para observar WhatsApp Web real, selecionar chats antes da busca e
medir eventos pedidos. Escolha de engenharia, sem benchmark/teste de conta.

Executa Web via Puppeteer. Oferece `getChats`, `getChatById`, `message_create`
(inclusive mensagens próprias), `message_edit`, `message_revoke_everyone` e
`message_revoke_me`. Evento documentado não garante entrega offline.
[Introdução](https://wwebjs.dev/guide/),
[Client/eventos](https://docs.wwebjs.dev/Client.html).

`Chat.fetchMessages({limit})` carrega mensagens anteriores disponíveis e retorna
janela ordenada; pode parar antes do limite. Usa internamente
`WAWebChatLoadMessages.loadEarlierMsgs`, que pode mudar. Não é cursor de backup
completo. Cada busca reporta quantidade, alcance etário e duração, `complete:false`.
[Contrato Chat](https://docs.wwebjs.dev/Chat.html),
[código 1.34.7](https://raw.githubusercontent.com/pedroslopez/whatsapp-web.js/v1.34.7/src/structures/Chat.js).

LocalAuth restaura perfil local, escolhido em vez de RemoteAuth. Perfil tem acesso
à conta inteira; seleção não restringe dispositivo. QR só no browser local.
[Guia de autenticação](https://wwebjs.dev/guide/creating-your-bot/authentication.html),
[LocalAuth 1.34.7](https://github.com/pedroslopez/whatsapp-web.js/blob/v1.34.7/src/authStrategies/LocalAuth.js).

**Baileys: avaliação documental, não executado.** `npm view` retornou
`@whiskeysockets/baileys@7.0.0-rc14`, Node >=20. Usa WebSocket sem Chromium; README
avisa mudanças incompatíveis na v7 e documenta QR/sessão/`syncFullHistory`. Flag
não prova entrega de todo histórico. Dispensar browser é vantagem plausível para
serviço, sem medição de CPU/memória/estabilidade nesta análise.
[README primário](https://raw.githubusercontent.com/WhiskeySockets/Baileys/master/README.md).

Contrato oferece `messaging-history.set`, `connection.update`, `creds.update`,
`messages.upsert/update/delete`; `groupFetchAllParticipating` lista grupos.
Implementar exigiria armazenamento de estado/chats e normalização dessas
atualizações. Possível em princípio, fora deste ensaio para não misturar clientes.
Fontes `master` são mutáveis: descrevem API consultada, não validam runtime rc14.
[Eventos](https://raw.githubusercontent.com/WhiskeySockets/Baileys/master/src/Types/Events.ts),
[grupos](https://raw.githubusercontent.com/WhiskeySockets/Baileys/master/src/Socket/groups.ts),
[exemplo](https://raw.githubusercontent.com/WhiskeySockets/Baileys/master/Example/example.ts).

Ambos não oficiais, sujeitos a quebra/bloqueio. whatsapp-web.js explicitamente
não garante ausência de bloqueio; leitura não elimina risco e não há SLA oficial.
[Aviso do projeto](https://wwebjs.dev/guide/).

Árvore instalada: **9 high, 0 critical** no audit (exit 1), cadeia Puppeteer →
extract-zip/basic-ftp. Não aplicado downgrade automático do audit. Não promover
essa árvore a produção sem reavaliar dependências e repetir ensaio. A árvore do
Baileys não foi instalada/auditada: não há comparação de segurança entre árvores.

Integração futura requer consentimento/retenção e acesso por pessoa antes de
expor mensagens no ArquivIO. Contexto lido, sem alterar as notas:
`specs/research/whatsapp-fonte-conhecimento-2026-10-15.md` e
`specs/research/comunicacao-espacos-viabilidade-2026-10-15.md`.
