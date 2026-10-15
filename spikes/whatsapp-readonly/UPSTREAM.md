# WA-POC-03 — listagem mínima, comparação primária em 15/10/2026

Base local: `77669c1`; whatsapp-web.js fixada **1.34.7**, sem upgrade, patch em
node_modules, pin de WhatsApp Web ou mudança no lockfile.

## Evidência e precisão

O diagnóstico humano alcançou authenticated/ready e falhou em Client.getChats /
ExecutionContext.evaluate com OPAQUE_WEB_ERROR (`r`/`r: r`). Isso confirma a
fronteira da falha. **Não demonstra rename de chave, falha em serialize,
metadados ou enumeração na conta pessoal.** Nenhum live/diagnose real executado
pelo agente; nenhum perfil/auth/cache/conteúdo pessoal foi aberto.

O código instalado permite reproduzir localmente um defeito de acoplamento:
seleção de conversas precisa de três campos, mas depende de todo getChatModel.
Uma falha em qualquer modelo impede a escolha de todas as conversas.

## Fontes primárias consultadas e comparação

- [Documentação Client 1.34.7](https://docs.wwebjs.dev/Client.html#getChats):
  getChats devolve instâncias Chat; pupPage é a página Puppeteer do cliente.
- [Client.js v1.34.7](https://github.com/wwebjs/whatsapp-web.js/blob/v1.34.7/src/Client.js#L1668):
  avaliação de WWebJS.getChats seguida de ChatFactory. getChatById também
  materializa via getChatModel.
- [Utils.js v1.34.7](https://github.com/wwebjs/whatsapp-web.js/blob/v1.34.7/src/util/Injected/Utils.js#L920):
  enumera Chat.getModelsArray; Promise.all sobre getChatModel; serialize,
  atualização de metadados de grupo e resolução/serialização de lastMessage.
  lastReceivedKey._serialized ausente pode chegar como undefined a Msg.get e
  getMessagesById. SHA-256 instalado igual ao tag:
  `0d0f88565f481dbfeb9493b04b24033a2cb60f5fd2fd0e84e543b461d98878fe`.
- [Chat.fetchMessages v1.34.7](https://github.com/wwebjs/whatsapp-web.js/blob/v1.34.7/src/structures/Chat.js):
  usa getChat com getAsModel:false, lê mensagens e getMessageModel; não precisa
  de getChatModel nem metadados serializados do grupo.
- [Issue 201845](https://github.com/wwebjs/whatsapp-web.js/issues/201845):
  relatos com a mesma fronteira/sintoma e relatos distintos de serialize e
  chave de mensagem. São evidências de outros ambientes, não prova desta conta.
- [PR 201850](https://github.com/wwebjs/whatsapp-web.js/pull/201850):
  consultada aberta, não merged; propõe fallback de chave, tolerância de
  metadados e omissão de chats com erro. Não aplicada: devolver catálogo
  incompleto silenciosamente ocultaria conversas da escolha.
- [201852](https://github.com/wwebjs/whatsapp-web.js/issues/201852): o endereço
  /pull/201852 redireciona para uma **issue**, não é uma PR merged verificável.
- [main consultado, commit 064a3d5a5a3dce1281a6a12740b5a7051339d154](https://github.com/wwebjs/whatsapp-web.js/blob/064a3d5a5a3dce1281a6a12740b5a7051339d154/src/util/Injected/Utils.js#L995):
  já aceita _serialized ou $1 e guarda ausência da chave da última mensagem;
  também normaliza ID de mensagem. Ainda chama chat.serialize e metadados e
  usa Promise.all. SHA-256 Utils.js:
  `cff56e15b20d81671341815cb097e4fe325885b7551cc7e9b04e4dc108e6088c`.
  [Release mais recente consultada](https://github.com/wwebjs/whatsapp-web.js/releases/latest):
  v1.34.7. Não se assumiu que main já esteja publicado no npm.

## Correção e reprodução

`src/web-reader.mjs` implementa o contrato local readOnly do cliente. A listagem
usa a mesma coleção da 1.34.7, mas projeta só ID/título/tipo. Não chama serialize,
getChatModel, metadados ou última mensagem. Grupo deriva do sufixo @g.us; sem
dependência da propriedade crua isGroup. Chats @c.us/@lid são individuais;
broadcasts/canais ficam fora do escopo existente. IDs ausentes e getters que
falham interrompem o catálogo com etapa explícita; nenhum chat quebrado é omitido.

Para histórico, um Chat contendo só ID chama fetchMessages original, depois dos
mesmos gates de seleção e confirmação. Isso remove a segunda passagem pelo
serializador de chat que getChatById faria antes da busca. Não muda envio,
serialização de mensagens, tratamento de eventos ou normalização PN/LID.

`test/web-listing.test.mjs` carrega LoadUtils/Client/Chat **instalados**, sem
copiar sua implementação, e os executa com modelos sintéticos em VM. Reproduz:
1. lastReceivedKey com só $1: getMessagesById([undefined]) lança; antigo catálogo
   inteiro falha, novo catálogo completo da coleção sintética funciona.
2. chat.serialize lança: getChats e getChatById falham, seleção e fetchMessages
   da POC funcionam sem invocar o serializador de chat.
3. capacidade/enumeração/projeção, IDs inválidos, getters hostis, classes de erro,
   grupos sem isGroup, catálogo vazio e fluxo live totalmente sintético com gates.

`node test/browser-catalog.mjs` confirma avaliação e transporte reais em
Chromium/CDP, apenas about:blank, requests bloqueados e perfil temporário.
O caminho de chave ausente usa validação nativa `IDBKeyRange.only(undefined)`
para produzir DataError, sem abrir banco nem acessar o IndexedDB da conta.
Também demonstra que Puppeteer pode recriar DataError como DOMException no Node;
os probes classificam dentro da página antes da transferência, sem texto bruto.
O resultado contém somente enums; diagnose nem lê títulos nem devolve IDs/chats.

## Limitações e próxima tentativa

A causa exata interna da conta permanece desconhecida. A correção é do caminho
de leitura da POC, baseada no acoplamento reproduzido; não se afirma conserto
geral de whatsapp-web.js. Se a própria enumeração ou um campo mínimo falhar,
o novo caminho ainda falhará, agora com etapa/classe específicas. Coleção em
memória não garante todas as conversas da conta ou histórico completo.

Diagnose testa capacidade, enumeração e IDs mínimos, **não** serializadores
integrais nem títulos. Sucesso não valida histórico/eventos. Travamento de
evaluate pode impedir o retorno dos probes internos; deadline continua vigente.
O histórico/eventos mantém serializers da 1.34.7 e pode revelar outras
incompatibilidades, inclusive IDs de mensagens. Não se aplica patch preventivo.

Auth/cache não são apagados; o hook de logout preserva o perfil em live e
diagnose. Isso não restaura autenticação revogada no servidor. Testes usam
sentinelas em pastas sintéticas, sem inspeção do perfil pessoal.

Próximo passo único, humano, na pasta do spike:
`npm run live -- --consent --duration-minutes 90`.
A sessão existente é reutilizada. Se houver novo erro, compartilhar somente
SETUP_DIAGNOSTIC e status; nomes e conteúdo ficam no terminal local.
