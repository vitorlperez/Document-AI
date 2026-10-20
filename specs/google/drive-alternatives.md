# Google Drive sem CASA (ou com CASA mais barato): todas as alternativas reais

Data: 2026-10-13 · Pesquisa somente leitura (nenhum código, prd ou ADR alterado; sem commit) · Âncoras de código valem para o `HEAD` `a0a4b03`.
Pergunta do dono: *"Não temos nenhuma outra opção?"* Contexto: [PoC B7.0](drive-file-poc-result.md) provou que `drive.file` + Picker **não** libera filhos de pasta; hoje o escopo é `drive.readonly` (restrito → verificação + CASA anual), em `backend/app/integrations/google_drive.py:26`.

## 0. Resumo para leigo (1 minuto)

- **Sim, há saídas, mas nenhuma é "de graça e igual ao que temos hoje".** Cada uma troca *custo/prazo do Google* por *mais trabalho do cliente* ou por *um risco de política que o Google não deixa escrito*.
- **Não há isenção oficial de CASA para quem vende o app a vários clientes.** As isenções são: uso pessoal, desenvolvimento/teste, só dados do próprio serviço, uso interno de **uma** organização Workspace, e "instalação em todo o domínio" (essa última **dispensa só a verificação de marca**; o próprio Google diz que app com escopo restrito continua exigindo verificação) — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
- **A alternativa mais promissora para poucos clientes B2B agora é a conta de serviço (service account):** o cliente compartilha a pasta com um e-mail do ArquivIO, como compartilharia com uma pessoa. Não existe tela de consentimento nem OAuth do usuário, então **nenhum mecanismo de verificação/CASA do Google é acionado**. Mas o Google **não escreve em lugar nenhum** que isso é permitido ou isento — é zona cinzenta por silêncio, não por aprovação. Vale um e-mail ao suporte do Google e um PoC de 1–2 dias.
- **Ponte realista enquanto isso:** publicar o app *sem* verificação (aviso "app não verificado", teto de 100 usuários novos, vitalício) é viável para um piloto com poucos clientes, porque quem autoriza é o admin da organização (1 pessoa por cliente). Isso queima cota irreversível, mas tira o limite de 7 dias do modo *Testing*.
- **Descartadas (não resolvem):** Marketplace/instalação em todo o domínio como "atalho" de CASA, modelo híbrido (CASA continua), `drive.file` com pasta criada pelo app (a documentação é muda e o PoC sugere que não), Takeout/Vault como ingestão contínua.

## 1. Fatos oficiais que sustentam tudo (com fonte)

| Fato | Fonte |
|---|---|
| `drive.file` é **não sensível**; `drive`, `drive.readonly`, `drive.metadata(.readonly)` são **restritos** | [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) |
| `drive.file` = arquivos que o usuário **abre com o app** ou **compartilha via Picker**; a página **não menciona pastas nem filhos** | mesma página |
| Quem acessa dados restritos "de ou através de um servidor de terceiros" precisa de avaliação de segurança (CASA) e **reavaliar a cada 12 meses** | [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) |
| CASA é "baseada em risco, em camadas, conforme número de usuários, escopos e outros sinais"; "todos os apps devem ser revalidados todo ano" e o nível exigido "pode aumentar" | [Security Assessment (Google Cloud Help)](https://support.google.com/cloud/answer/13465431?hl=en) |
| Isenções de verificação: uso pessoal, dev/teste/staging, **só dados do próprio serviço**, **uso interno** (projeto pertence à organização + tela de consentimento *Internal*), **instalação em todo o domínio** (dispensa só *brand verification*) | [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) |
| Modo *Testing*: até 100 test users, autorização expira em 7 dias, refresh token também expira | [Google Cloud Help: publishing status](https://support.google.com/cloud/answer/15549945) |
| App não verificado em produção: teto de **100 novos usuários no total**, que "não pode ser resetado", e aviso de app não verificado | mesma página |
| Política "Limited Use" é descrita para quem "solicita acesso a dados de usuário do Google" via framework de autenticação/autorização (OAuth); **não menciona** service accounts nem arquivos compartilhados | [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy) |

## 2. Alternativa 1 — Conta de serviço (service account) lendo pastas compartilhadas

**Como funciona (leigo):** em vez de pedir "permissão para ler seu Drive inteiro", o ArquivIO tem um "usuário-robô" com e-mail próprio (`algo@projeto.iam.gserviceaccount.com`). O cliente abre a pasta no Drive, clica em **Compartilhar**, digita esse e-mail com papel **Leitor** e pronto. O robô só enxerga o que foi compartilhado com ele. Para o cliente, o risco percebido é *menor* que o do OAuth: ele escolhe a pasta e mais nada é exposto.

**Como funciona (técnico):** o backend assina um JWT com a chave da SA e troca por access token (`urn:ietf:params:oauth:grant-type:jwt-bearer`); sem refresh token, sem expiração de 7 dias, sem `prompt=consent`. As mesmas chamadas `files.list`/`changes.list`/`files.get`/`files.export` funcionam sobre o que foi compartilhado. A página oficial de service account descreve a SA como conta "que pertence ao seu app", usada tipicamente para dados do próprio app, e acesso a dados de usuário só via delegação de domínio — [Using OAuth 2.0 for Server to Server Applications](https://developers.google.com/identity/protocols/oauth2/service-account). **Ela não documenta** "compartilhar arquivo com o e-mail da SA"; a prática é descrita por terceiros (ex.: [Nexla](https://docs.nexla.com/user-guides/connectors/google_drive_api/google_drive_api_data_source), [Mastra](https://mastra.ai/integrations/file-storage/google-drive)) e confirmada por mim só via esses guias — **precisa de PoC** (ver §9).

**Impacto na UX:** conectar deixa de ser "botão Google → tela de consentimento" e vira "copie este e-mail → compartilhe a pasta → cole o link/ID da pasta no ArquivIO" (ou o ArquivIO detecta sozinho as pastas compartilhadas com o robô). Fricção maior no primeiro passo, mas **sem reautorização semanal e sem aviso de app não verificado**. Em Workspace, o admin pode bloquear compartilhamento com pessoas de fora do domínio ([Manage external sharing](https://knowledge.workspace.google.com/kb/how-to-enable-external-users-to-upload-files-to-a-shared-folder-000006409)) — clientes com política restritiva precisarão liberar uma exceção.

**Elimina CASA/verificação?**
- **Não há mecanismo de verificação acionado:** não existe cliente OAuth do usuário, tela de consentimento nem escopo restrito *solicitado a um usuário*; o processo de verificação e o CASA são descritos para "apps que solicitam escopos" via OAuth ([Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)). A isenção literal "service account que acessa só **os próprios dados**" **não** cabe aqui (os dados são do cliente) e eu **não afirmo** que ela se aplica.
- **O que o Google não diz:** nenhuma página oficial consultada afirma que "SA + pasta compartilhada manualmente" está isento nem que está proibido. A Limited Use Policy é redigida para acesso via OAuth e silencia sobre SA ([User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)). **Classificação: zona cinzenta por silêncio, risco de política baixo-a-moderado, não de bloqueio técnico.** Mitigação barata: abrir pergunta formal no Google Workspace/Cloud Support e guardar a resposta; mesmo assim cumprir na prática os princípios Limited Use (já é o que o produto faz).
- **CASA de cortesia:** vendors relatam que clientes enterprise às vezes pedem de qualquer forma auditoria/SOC 2 — isso independe do Google.

**Limites e regras técnicas (fonte):**
- **Cota:** a cota é por projeto Cloud (1.000.000 unidades/min por projeto; 325.000 por usuário por projeto), e "chamadas feitas por uma service account são consideradas como uma única conta" — [Usage limits](https://developers.google.com/workspace/drive/api/guides/limits). Consequência: **todos os clientes juntos dividem o teto "por usuário" de uma única SA**. Mitigações: uma SA por cliente ou por lote de clientes, backoff (já existe em `backend/app/integrations/http.py:20-110`).
- **Armazenamento:** "service accounts não têm cota de armazenamento e não podem ser donas de arquivos" — [Resolve errors](https://developers.google.com/workspace/drive/api/guides/handle-errors). Para o ArquivIO (somente leitura) é irrelevante; só importaria se um dia quiséssemos *escrever* no Drive.
- **Shared Drives:** a SA precisa ser adicionada como membro do drive compartilhado (e, segundo guias de terceiros, o drive precisa permitir que leitores baixem) — [Nexla](https://docs.nexla.com/user-guides/connectors/google_drive_api/google_drive_api_data_source). `supportsAllDrives=true` já está nas chamadas (`integrations/google_drive.py:252,265,286-287,404-405`).
- **Contas Gmail pessoais:** funciona igual (qualquer conta compartilha pasta com qualquer e-mail). Hipótese a validar no PoC.
- **Segurança:** a chave JSON da SA vira o segredo mais valioso do ArquivIO (acesso a todas as pastas de todos os clientes). Guardar cifrada/KMS, rotacionar, e ideal usar uma SA por cliente (blast radius menor). Isso entra no escopo de qualquer auditoria futura.

**Esforço de engenharia (estimativa 4–7 dias de código + testes, sem contar PoC):**
| O que muda | Onde |
|---|---|
| Novo provider `google_drive_sa` (ou modo no existente) com assinatura JWT e cache de token curto | novo `backend/app/integrations/google_drive_sa.py`; reutilizar `RemoteHttp` (`integrations/http.py`) e as chamadas de listagem/export de `GoogleDriveOAuthClient` (`integrations/google_drive.py:230-456`), trocando só a obtenção de credencial (hoje `refresh_access_token`, `:192`) |
| Registro do provider | `backend/app/integrations/registry.py:233-237` (`_factories`) e `:246` (ramo `google_drive`) |
| Fluxo de conexão sem OAuth: guardar `folder_id`/e-mail do robô; rota "validar acesso" (`files.get` na pasta) em vez de `/oauth/start`+`/callback` | `backend/app/api/integrations.py:428-482` (rotas OAuth atuais) → nova rota; modelo `DataSource` em `integrations/models.py:20-42` |
| Seleção de pasta: `list_folders` (`:230-247`, query `mimeType=folder and trashed=false`) já devolve **apenas o que a SA enxerga** = só as pastas compartilhadas — quase sem mudança | `integrations/google_drive.py:230` |
| Sync incremental: `changes.list` + `startPageToken` (`:249-307`) deve funcionar para a SA sobre itens compartilhados; **validar no PoC** (mudanças em itens compartilhados indiretamente) | `integrations/google_drive.py:249-307`, `ingestion/google_drive.py:64-230` |
| Refresh/reauth vira desnecessário no modo SA; tratar "pasta deixou de ser compartilhada" (403/404 → `reauth_required`) | `ingestion/google_drive.py:346-402`, `ingestion/tasks.py:698-710` |
| UI de conexão (instruções + copiar e-mail) | `frontend/` (tela de integrações) |

**Riscos:** (a) zona cinzenta de política (acima); (b) cota única por SA; (c) fricção de onboarding e dependência de o cliente não "des-compartilhar"; (d) chave da SA é segredo crítico; (e) admin Workspace pode bloquear compartilhamento externo; (f) novos arquivos criados fora da pasta compartilhada não aparecem (por design — é o que o cliente quer).

### 2.1 Variante 1b — "usuário-robô" real (conta Google do ArquivIO) em vez de service account
Cliente compartilha a pasta com `sync@arquivio.com.br` (usuário normal de um Workspace do ArquivIO) e o backend usa OAuth **desse** usuário, de um projeto *Internal*. Vantagens: aparece como "pessoa" no Drive, funciona se o cliente exige "compartilhe com um usuário e não com um robô". Desvantagens: precisa de licença Workspace, o refresh token pode ser revogado/expirar por inatividade, **e a isenção "uso interno" fala de apps usados "apenas por pessoas na sua organização"**, o que de novo é uma leitura estendida, não um caso previsto ([Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)). Mesmo risco de zona cinzenta, mais manutenção que a SA. **Não recomendo**, salvo se um cliente exigir.

## 3. Alternativa 2 — Instalação em todo o domínio (Marketplace) / delegação de domínio (domain-wide delegation)

**O que a documentação diz (decisivo):**
- A isenção "instalação em todo o domínio" dispensa **somente a verificação de marca (*brand verification*)**; o texto continua: "se o app usa escopos restritos ou sensíveis, a verificação do app é necessária" — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification). A página **não** diz que a avaliação de segurança (CASA) é dispensada nesse caso, e a mesma página exige a avaliação para todo app que acessa dados restritos por servidor de terceiros.
- O Marketplace: "se seu app usa escopos sensíveis ou restritos, ele deve passar pela revisão de verificação OAuth", "a listagem não pode ser aprovada até a verificação OAuth ser concluída" e "se usa escopos restritos, pode precisar também de avaliação de segurança" — [Configure OAuth (Marketplace)](https://developers.google.com/workspace/marketplace/configure-oauth-consent-screen). Isenção só vale para app **interno** da organização (consentimento *Internal*).
- App **privado** do Marketplace fica disponível imediatamente só "para todos na sua organização Workspace" (sem revisão do Google), e a visibilidade, uma vez definida, **não muda** — [Publish your Drive app](https://developers.google.com/drive/api/guides/publish) (via busca; use apenas para entender que privado = só o domínio do desenvolvedor). **Um app privado do ArquivIO não pode ser instalado nos domínios dos clientes**, então não serve.

**Delegação de domínio (domain-wide delegation, DwD) com service account:** o *super admin* do Workspace do cliente cadastra o ID de cliente da nossa SA e os escopos no Admin console; o backend passa a "se passar" por qualquer usuário do domínio, com os mesmos direitos do usuário — [Server to Server](https://developers.google.com/identity/protocols/oauth2/service-account). O Google descreve isso como o administrador conceder "a aplicativos de terceiros e internos acesso aos dados dos seus usuários" ([Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)).
- Vantagem: **o admin autoriza uma vez para o domínio todo**, sem 20 pessoas clicando no consentimento; ótima UX B2B para Workspace.
- Desvantagem: dá ao ArquivIO acesso a **todos os Drives de todos os usuários do domínio** — muito mais amplo que `drive.readonly` de um usuário; admins de TI desconfiam. Fonte secundária relata que usar DwD pode fazer o Google exigir **CASA Tier 3** (mais caro) — [Nango](https://nango.dev/docs/api-integrations/google-shared/google-security-review) (anedótico, ver caveat deles). Nenhuma fonte oficial confirma ou desmente.
- **Só Workspace:** a delegação é descrita para domínios Google Workspace ([Server to Server](https://developers.google.com/identity/protocols/oauth2/service-account)); **clientes com Gmail pessoal não têm admin** e ficam sem esse caminho. Para eles, só a Alternativa 1 (compartilhar pasta com a SA) ou OAuth normal.

**Elimina CASA?** **Não, nas fontes oficiais lidas.** Risco extra de ser pior (Tier 3, segundo fonte secundária).
**Esforço:** parecido com a Alternativa 1 (a mesma SA, mas com `sub=<usuário>` no JWT e um fluxo de onboarding de admin) + cadastro no Admin console do cliente; 5–8 dias. **Não recomendado agora.**

## 4. Alternativa 3 — Ficar em `drive.file` e contornar a limitação

O PoC já provou: pasta escolhida no Picker libera **só a pasta**, não filhos/netos, nem arquivos novos (0 de 5 arquivos, 0 de 2 subpastas; `changes.list` só mostrou a própria pasta) — [`drive-file-poc-result.md`](drive-file-poc-result.md). Variantes:

| Variante | Como funciona | Funciona? | Fonte / status |
|---|---|---|---|
| **3a. Picker multiselect de arquivos** | Usuário marca N arquivos no Picker; cada um fica legível; a concessão **persiste entre tokens** | Sim para arquivos individuais; **não** expande pastas | PoC `drive-file-poc-result.md` (a)/Resultados; [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) ("shares with an app via Picker") |
| **3b. Re-seleção periódica** | Lembrar o cliente de reabrir o Picker a cada novo lote | Funciona tecnicamente; **produto muito pior** (sem "acompanha arquivos novos") | PoC; sem automação possível |
| **3c. "Pasta ArquivIO" criada pelo app** | O app cria a pasta; o usuário solta arquivos dentro | **Provavelmente não.** No PoC, em pasta *escolhida* só apareceu o arquivo **criado pelo app** (controle positivo); arquivos que o usuário colocou continuaram invisíveis. **A documentação oficial é muda sobre isso** (a página de escopos não trata de pastas). Em pasta *criada pelo app* **não foi testado** | Fonte oficial: nenhuma. **Precisa de PoC de ~30 min** (criar pasta pelo app, soltar arquivo pela UI do Drive, `files.list`). Previsão: não aparece. |
| **3d. `drive.install` / "Abrir com ArquivIO"** | O app aparece no menu "Abrir com" do Drive; o escopo `drive.install` é não sensível e dá a opção de o app aparecer nesse menu; o usuário abre arquivo(s) e o app ganha acesso por arquivo | Mesma granularidade por arquivo; **sem evidência de que abrir uma pasta libere os filhos** | [Choose scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) (descrição do `drive.install`); comportamento com pasta: não documentado, precisa PoC |

**Elimina CASA?** Sim (`drive.file` e `drive.install` são não sensíveis, só exigem verificação básica de marca), **mas muda o produto** para "o cliente escolhe arquivos", sem pasta recursiva nem captação automática — o oposto da proposta do ArquivIO. **Só serviria como um segundo modo ("avulso")**, não como substituto.
**Esforço:** Picker no frontend + troca de `list_folders`/`list_folder_files` por `files.get` por ID (`integrations/google_drive.py:230,262,309`) e remoção de `changes()` (`:277`) para esse modo: 5–8 dias. Não recomendado como substituto.

## 5. Alternativa 4 — Modelo híbrido: `drive.file` por padrão + `drive.readonly` só para quem precisar

**Ainda exige CASA?** **Sim**, no momento em que o escopo restrito aparece no app público. O que determina a exigência é o app/projeto solicitar escopo restrito para usuários fora do modo *Testing/interno* ([Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)); não importa se a maioria dos usuários nunca o concede. O que o híbrido muda: o custo fica "reservado" para poucos clientes, mas **o ArquivIO tem de passar pela verificação e pelo CASA do mesmo jeito**, só que exige manter dois fluxos. O teto de 100 usuários não verificados também permaneceria como único atalho ([publishing status](https://support.google.com/cloud/answer/15549945)).

**Truque de "dois projetos Cloud"** (um só com `drive.file`, outro só com `drive.readonly` em *Testing* para os poucos clientes que precisam): **não recomendo.** *Testing* é descrito pelo Google como fase de desenvolvimento/teste e limita a 100 test users com token expirando em 7 dias ([publishing status](https://support.google.com/cloud/answer/15549945)); usar para clientes pagantes contraria a finalidade e pode ser lido como contorno. Se for assumir risco, é melhor assumir o do app não verificado (§8), que o Google prevê explicitamente.

## 6. Alternativa 5 — Ingestão fora da API do Google

| Opção | Como funciona | Viável? | Fonte |
|---|---|---|---|
| **Upload direto** (arrastar arquivos / ZIP / pasta pelo navegador) | O cliente envia os arquivos ao ArquivIO. Nenhuma API do Google envolvida | **Sim, 100% sob nosso controle, zero risco de política.** Não acompanha arquivos novos sozinho; bom como *fallback* e para clientes que não querem dar acesso | Não há endpoint de upload hoje: busca por `upload` em `backend/app/api/` e `ingestion/` não encontrou rota de arquivo (só webhooks/automações e sync por provider). Novo provider "arquivos enviados" atrás de `SourceProvider` (`integrations/base.py:19-34`), registro em `registry.py:233` |
| **Cliente de sincronização (agente desktop/CLI)** | Um agente leve no computador/servidor do cliente observa uma pasta local e envia para o ArquivIO | Funciona e "acompanha arquivos novos" com autenticação por chave nossa. Esforço grande (instalador, atualização, suporte a macOS/Windows/Linux) | — (decisão de produto) |
| **Google Drive for desktop + agente** | O cliente instala o app oficial do Google que espelha o Drive em disco; nosso agente lê a pasta local | Mac/Windows apenas; **o Google não oferece cliente oficial para Linux** (fonte de terceiros) | [Expandrive: Drive client for Linux](https://expandrive.com/google-drive-for-linux) (fonte de terceiros, comercial); sem fonte oficial lida |
| **Pasta de e-mail** (encaminhar anexos para `docs@cliente.arquivio...`) | Cada cliente recebe um endereço; anexos viram documentos | Viável (SES/Mailgun inbound). Útil para fluxos de "mandar PDF e perguntar" | — |
| **Google Takeout (agendado)** | Exporta Drive em arquivo zip para Drive/Dropbox/OneDrive/Box ou link de e-mail; agendamento = a cada 2 meses por 1 ano | **Não serve como sync contínuo** (latência de meses, ZIP gigante, só a própria conta); o próprio Google avisa que mudanças recentes podem faltar | [Export your Google data](https://support.google.com/accounts/answer/3024190) |
| **Google Vault (export)** | Admin exporta dados de Drive por busca; exports vivem 15 dias; exige licença Vault para admin e usuários | **Não é integração contínua**; funciona como carga inicial pontual para clientes Business Plus/Enterprise | [Google Vault overview](https://knowledge.workspace.google.com/vault/getting-started/vault-overview) (via resultados de busca); licença exigida confirmada em [Vault support](https://support.google.com/a/answer/2462365?hl=en) |

**Recomendação aqui:** *upload direto* (e depois pasta de e-mail) como **segundo conector sem Google**, barato e que protege o produto de qualquer decisão do Google. Takeout/Vault ficam como "carga inicial manual" para um cliente específico.

## 7. Alternativa 6 — Uso interno, Testing e "internal por organização"

| Modo | O que permite | Serve para vender a clientes? | Fonte |
|---|---|---|---|
| **Testing** | Até 100 test users; autorização e refresh token expiram em **7 dias** | Só piloto muito curto; o cliente reconecta toda semana. O código já lida com isso (`ingestion/tasks.py:698-710`, `integrations/google_drive.py:204-210` → `reauth_required`) | [publishing status](https://support.google.com/cloud/answer/15549945) |
| **Internal** (tela de consentimento *Internal*) | Só usuários da própria organização Workspace dona do projeto; isento de verificação | **Não** (clientes são outras organizações) | [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) (isenção "uso interno": projeto da organização + tipo *Internal*) |
| **In production sem verificação** | Aviso de "app não verificado"; **teto de 100 novos usuários no total, vitalício**, não reseta; refresh token deixa de expirar em 7 dias (limite de 7 dias é descrito para o modo *Testing*) | **Sim, como ponte** para poucos clientes, porque quem concede é o **admin da organização** (1 usuário por cliente — `require_admin` em `integrations/google_drive.py:549`) | [publishing status](https://support.google.com/cloud/answer/15549945) |

**Pegadinhas da ponte "não verificado":** (1) queima cota irreversível (100 admins no total); (2) admins Workspace podem bloquear apps não configurados/não verificados ("Users might be blocked from activating unverified apps that you don't trust") e o padrão do Google é permitir apps de terceiros, mas o admin pode trocar — [Control which apps access Workspace data](https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data); (3) o aviso assusta cliente grande; (4) não substitui o plano de verificação, só compra tempo.

## 8. Quanto custa, de fato, o CASA (para decidir se vale fugir)

Google não publica preço do laboratório. Fonte secundária de agosto/2025 lista: TAC Security **US$ 540–720**, Netsentries ~US$ 700, Prescient US$ 3.000+; prazos de 5–20 dias para o CASA e "4–6 semanas" de janela publicada pelo Google para restritos; renovação anual mais rápida — [Nango: Google security review](https://nango.dev/docs/api-integrations/google-shared/google-security-review) (**fonte de terceiros, não do Google**). Isso é **bem menor** que o "US$ 5–10 mil/ano" da ADR-0017, que ficou como estimativa pessimista sem cotação. O Google diz só que a exigência é baseada em risco e que o nível pode subir com a base de usuários ([Security Assessment](https://support.google.com/cloud/answer/13465431?hl=en)). Conclusão: **antes de gastar semanas migrando arquitetura para fugir do CASA, cotar o lab** (US$ 540–720 + scans que o time já planejou, `google-drive-deploy-review.md` §2 item 12) pode ser mais barato que reescrever o conector. O esforço de engenharia e o risco de zona cinzenta das alternativas valem mais que ~US$ 700/ano, se esse for o preço real.

## 9. Comparação rápida

| # | Alternativa | Elimina CASA? | Mantém "pasta recursiva + novos arquivos"? | Esforço eng. | Risco principal |
|---|---|---|---|---|---|
| 1 | **Service account + pasta compartilhada** | Sem mecanismo de verificação acionado; **não há isenção escrita** | Sim (pasta compartilhada = recursiva) | 4–7 dias | Zona cinzenta de política; cota única por SA; UX de compartilhar |
| 1b | Usuário-robô Workspace | Idem, interpretação estendida de "interno" | Sim | 3–5 dias | Zona cinzenta + token do usuário-robô |
| 2 | Domain-wide delegation / Marketplace | **Não** (verificação do escopo restrito continua); Tier 3 relatado | Sim | 5–8 dias | Pode ficar mais caro; só Workspace |
| 3a/b | `drive.file` multiselect/re-seleção | Sim | **Não** | 5–8 dias | Quebra a promessa do produto |
| 3c/d | Pasta do app / Abrir com | Sim | Provavelmente **não** (PoC 30 min) | 1 dia de PoC | Hipótese provavelmente falsa |
| 4 | Híbrido | **Não** | Sim | 5+ dias | Dois fluxos e CASA igual |
| 5 | Upload / e-mail / agente desktop | N/A (sem Google) | Upload: não automático; agente: sim | Upload 3–5 dias; e-mail 3 dias; agente semanas | Produto/suporte |
| 6 | Testing / não verificado / Internal | Não elimina; **adia** | Sim | ~0 | Teto 100 vitalício; 7 dias no Testing |
| — | **Fazer o CASA (cotar lab)** | Cumpre | Sim | Itens já planejados | Prazo 4–8 semanas |

## 10. Recomendação priorizada (poucos clientes B2B agora)

1. **Hoje (sem código):** cotar 2–3 laboratórios CASA por escrito (TAC, Netsentries etc.) — se os números de agosto/2025 ainda valem, o CASA anual custa centenas de dólares, não milhares, e o gargalo é prazo, não dinheiro. Começar as etapas do `google-drive-deploy-review.md` §2 que dependem só do dono (Search Console, marca, vídeo). *Isto continua sendo o caminho principal.*
2. **Em paralelo, PoC de 1–2 dias da Alternativa 1 (service account)** com uma pasta compartilhada (conta Gmail e conta Workspace, incluindo Shared Drive) e uma pergunta formal ao suporte do Google ("é permitido ler pastas que o cliente compartilha com a conta de serviço do nosso produto, sem OAuth?"). Se a resposta do Google for "sim/neutra" e o `changes.list` funcionar para itens compartilhados, vira um **segundo modo de conexão** (não substitui o OAuth), ideal para clientes que desconfiam de dar `drive.readonly` e para quem tem política de compartilhamento mais rígida.
3. **Ponte para o piloto:** publicar *In production* sem verificação (aviso + teto 100 novos usuários) em vez de *Testing* se houver >1 cliente real; ou ficar em Testing só para demos. Registrar a cota gasta.
4. **Construir o upload direto** (novo provider) como conector sem Google: protege o produto de rejeição do Google e atende cliente que não quer integração.
5. **Não fazer agora:** Marketplace/DwD (não elimina CASA e pode piorar), híbrido (CASA igual), `drive.file` como substituto (quebra o produto), "dois projetos" para esconder escopo restrito, Takeout/Vault como sync.

**O que precisaria de PoC / confirmação externa:**
| Item | O que provar | Tempo |
|---|---|---|
| SA lendo pasta compartilhada | `files.list`, `files.export`, `files.get alt=media` e **`changes.list`** funcionam para itens novos criados por outro usuário dentro da pasta compartilhada; pasta de conta Gmail e de Workspace; Shared Drive com a SA como membro | 1 dia |
| SA e cotas | Medir unidades consumidas num sync real e simular N clientes | 0,5 dia |
| Política do Google | Resposta escrita do suporte sobre "SA + pasta compartilhada manualmente" e Limited Use | espera externa (dias) |
| Pasta criada pelo app (3c) | Arquivos soltos pela UI do Drive numa pasta criada pelo app ficam visíveis a `drive.file`? (previsão: não) | 30 min |
| "Abrir com" (3d) | Abrir pasta pelo menu libera filhos? (previsão: não) | 0,5 dia |
| Tier do CASA | Qual nível o lab/Google atribui (a ADR-0017 assume Tier 2; não confirmado por fonte oficial) | com a cotação |

## 11. Não coberto / limites

- Não testei nada contra a API do Google nesta pesquisa; a viabilidade da SA (`changes.list`, Shared Drives, Gmail pessoal) vem de documentação oficial genérica + guias de terceiros, não de execução.
- Preços e prazos do CASA são de fonte de terceiros (Nango, agosto/2025) e podem estar desatualizados. O "Tier 3 para DwD" é anedótico na mesma fonte.
- Páginas oficiais do Google lidas via resumo automático de página (parte do texto foi sintetizada); as citações literais aparecem entre aspas; onde só havia resumo, escrevi como paráfrase.
- Não li o texto integral da ADR-0017 (arquivo `docs/adr/` não localizado nesta árvore) — o conteúdo vem do `google-drive-deploy-review.md`.
- Observação de código: desde o review, `GoogleConnectionService._before_disconnect` já faz `POST https://oauth2.googleapis.com/revoke` (`backend/app/integrations/google_drive.py:514-532`) e o callback já trata `access_denied` (`api/integrations.py:477`) — itens B2/#7 do review estão feitos, não são mais lacunas.
- Nada alterado em código, prd, PRD/ADR; sem commit.

## Fontes

- [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [Security Assessment (Google Cloud Help)](https://support.google.com/cloud/answer/13465431?hl=en)
- [Google Cloud Help: publishing status](https://support.google.com/cloud/answer/15549945)
- [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
- [Using OAuth 2.0 for Server to Server Applications](https://developers.google.com/identity/protocols/oauth2/service-account)
- [Configure OAuth (Workspace Marketplace)](https://developers.google.com/workspace/marketplace/configure-oauth-consent-screen)
- [Publish your Drive app](https://developers.google.com/drive/api/guides/publish)
- [Drive API usage limits](https://developers.google.com/workspace/drive/api/guides/limits)
- [Drive API: Resolve errors](https://developers.google.com/workspace/drive/api/guides/handle-errors)
- [Control which apps access Workspace data](https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data)
- [Manage external sharing](https://knowledge.workspace.google.com/kb/how-to-enable-external-users-to-upload-files-to-a-shared-folder-000006409)
- [Export your Google data (Takeout)](https://support.google.com/accounts/answer/3024190)
- [Google Vault overview](https://knowledge.workspace.google.com/vault/getting-started/vault-overview) · [Vault licenses](https://support.google.com/a/answer/2462365?hl=en)
- [Nango: Google security review](https://nango.dev/docs/api-integrations/google-shared/google-security-review) (terceiro)
- [Nexla: Google Drive API source](https://docs.nexla.com/user-guides/connectors/google_drive_api/google_drive_api_data_source) · [Mastra: Google Drive](https://mastra.ai/integrations/file-storage/google-drive) (terceiros, compartilhar pasta com a service account)
- [Expandrive: Drive client for Linux](https://expandrive.com/google-drive-for-linux) (terceiro)
