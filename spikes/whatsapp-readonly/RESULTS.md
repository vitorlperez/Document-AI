# WA-POC-01 — resultado de 15/10/2026

**Conclusão: POC isolada executável entregue; pipeline local validado por simulação.
Viabilidade com conta WhatsApp real inconclusiva. Nenhuma conexão real realizada.**
Skills: inline [oc-builder, oc-blackbox, oc-stamp].

## Evidência executada

Ambiente observado: macOS arm64, Node v24.3.0, npm 11.4.2,
whatsapp-web.js 1.34.7, Puppeteer 24.38.0, Chrome 146.0.7680.31.

- `npm ci --ignore-scripts`: exit 0; 193 pacotes instalados, 194 auditados.
- `npm test`: **30 testes, 30 pass, 0 fail**, exit 0. Inclui normalização,
  seleção, descarte de controle, dedup, histórico, texto editado antes/durante
  busca, tombstones, revogação com ID de protocolo, reinício de estado, exclusão
  no snapshot em disco, relatório sem conteúdo/IDs, permissões 0700/0600, locks,
  diretórios/symlinks, gate de TTY/consentimento, retry/timeout, cancelamento de
  setup humano e falha de persistência. Clientes em testes são **fakes locais**.
- `npm run demo`: exit 0; 2 conversas sintéticas, 2 mensagens retidas, 1 tombstone,
  2 documentos; `validation:simulated`, `realIntegrationValidated:false`.
- `npm run report`: exit 0; snapshot simulado relido e mesmas contagens.
- `./node_modules/.bin/puppeteer browsers install chrome`: exit 0; browser local
  instalado no cache do Puppeteer, fora do git.
- `npm run doctor`: exit 0; import do cliente e launch Chromium confirmados;
  abriu só `about:blank`, `whatsappConnected:false`.
- `npm audit --json`: **exit 1**, 9 high, 0 critical. É um check com ressalva,
  não uma suíte verde de segurança. Detalhes abaixo.
- `graphify query "WhatsApp POC isolated integration source knowledge ingestion library read only"`:
  exit 0 antes de investigar o código; contexto complementado pelas duas notas
  de pesquisa solicitadas e pelos spikes vizinhos.
- `graphify update .`: exit 0 depois das mudanças de código (AST, sem LLM).
  Os arquivos graphify já estavam alterados ao iniciar; atualização preservada
  no workspace, fora do commit desta POC para não incluir alterações alheias.

Testes foram escritos e vistos falhar antes de implementar módulos. Regressões
específicas F-01/F-04/F-05 foram reproduzidas vermelhas, depois verdes; detalhes em
[FINDINGS.md](FINDINGS.md). Não foi executada suíte do produto: nenhum código do
backend/frontend ou controle de acesso foi alterado.

## O que isto prova e o que permanece pendente

**Simulado:** eventos com o formato documentado percorrem adapter → filtro de
seleção → estado → biblioteca privada → relatório. Dados de controle não são
retidos. Replays não duplicam, exclusões observadas purgam texto e não ressuscitam;
reconexão do controlador é limitada e reutiliza o mesmo engine.

**Ambiente local real, sem conta:** módulo instalado importa; Chromium inicia e
encerra. Isso não prova compatibilidade com a versão WhatsApp Web que a conta
receberá, nem que a injeção de eventos funcionará após QR.

**Pendente real:** QR/sessão, catálogo e seleção de chats/grupos reais, alcance
histórico por conversa, novas mensagens, eventos de edição/exclusão, recuperação
de rede, persistência/revogação da sessão e estabilidade. Nenhuma quantidade de
histórico real ou taxa de sucesso é inferida a partir dos fixtures.

Etapa exata: em terminal privado local, executar
`cd spikes/whatsapp-readonly && npm run live -- --consent`; ler avisos; digitar
VINCULAR; vincular no telefone; escolher índices; confirmar SINCRONIZAR. O roteiro
de oito cenários e tempos de aceite está em [README.md](README.md). A conta nunca
foi escolhida pelo agente. Não foi iniciada sessão real para "esperar o QR".

O ambiente instrui pedir a etapa humana por `overclock_clarify`. Na descoberta
de ferramentas deste pane, nem esse método nem ToolSearch foram expostos. Essa
falha de wiring impede abrir o formulário aqui; não é autorização presumida nem
impedimento ao runner já preparado. O chamador precisa disponibilizar a ferramenta
ou conduzir o vínculo conscientemente pelo procedimento local documentado.

## Dependências e limitações materiais

Audit classificou 9 pacotes como high: whatsapp-web.js, puppeteer, puppeteer-core,
@puppeteer/browsers, extract-zip, proxy-agent, pac-proxy-agent, get-uri e basic-ftp.
Não equivale a nove vulnerabilidades independentes: várias são propagação da
mesma cadeia. A versão instalada trouxe extract-zip 2.0.1 e basic-ftp 5.3.1.
O audit sugeriu downgrade de whatsapp-web.js; não foi aplicado automaticamente.
Fontes primárias dos alertas:
[extract-zip: symlink traversal](https://github.com/advisories/GHSA-jmr9-qjv8-65gv),
[extract-zip: arbitrary writes](https://github.com/advisories/GHSA-7pqw-9j4j-h8q3),
[basic-ftp: parsing DoS](https://github.com/advisories/GHSA-c475-qrg2-pj4r).

Não há promessa de histórico completo. A biblioteca depende de janela/estado
disponível no dispositivo, IDs PN/LID podem divergir, e exclusão offline sem evento
ou marcador não é recuperável por simples ausência no histórico. O perfil Web
pode cachear conta inteira: seleção protege só a biblioteca da POC. Credenciais e
textos ficam localmente fora do git, sem criptografia adicional da POC.

**Decisão de viabilidade atual:** continuar apenas como experimento condicionado
ao ensaio real e à aceitação do alcance histórico observado. Não promover a
produção. Sem acesso por pessoa, dependências reavaliadas e evidência de eventos
reais, não é uma integração empresarial validada. Baileys foi comparado por fontes
primárias em [DECISION.md](DECISION.md), sem benchmark ou runtime de conta.
