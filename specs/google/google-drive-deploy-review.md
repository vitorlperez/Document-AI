# Google Drive: o que falta para publicar o app OAuth e se a conexão está bem desenhada

Data: 2026-10-13 · Investigação somente leitura (nada alterado em código nem em prd) · Âncoras de código valem para o `HEAD` `e85e411`; as âncoras antigas de `docs/integracoes/google-oauth-verificacao-checklist.md` (ex.: `:25`) deslocaram uma linha — hoje o escopo está em `backend/app/integrations/google_drive.py:26`.

## 0. Resumo para leigo (30 segundos)

- **"Deploy no Google" não é hospedar o sistema no Google.** O Arquivio continua no Railway. O que o Google exige é *publicar o app de login* (a "tela de consentimento" que aparece quando o cliente clica em "Conectar Google Drive") e *ser aprovado por eles*.
- **Hoje a conexão funciona, mas só para um grupo pequeno.** Enquanto o app estiver em modo *Testing*, o Google derruba a autorização a cada 7 dias e aceita no máximo 100 usuários de teste. Para clientes reais é preciso sair desse modo.
- **O motivo da burocracia é o escopo pedido.** O Arquivio pede `drive.readonly` ("ler e baixar tudo do Drive"). O Google classifica isso como **restrito**, o nível mais rigoroso: exige verificação do app **e** uma auditoria de segurança paga (CASA), renovada todo ano.
- **O código está bem feito** (tokens cifrados, renovação automática, sync incremental, tratamento de limite de uso), mas tem **4 lacunas que o Google/auditor vão cobrar**: não revoga o token ao desconectar, a política de privacidade não tem a declaração "Limited Use", o callback não trata o usuário que clica em "Cancelar", e o app lê o Drive inteiro mesmo quando o cliente só escolhe uma pasta.
- **Recomendação:** manter a decisão da ADR-0017 (CASA com `drive.readonly`) e começar *agora* as etapas que dependem só de você (marca, política, vídeo, cotação do laboratório), porque o prazo total é 4–8 semanas e vem majoritariamente de fila externa.

## 1. O que o código pede de fato

| Item | Evidência | Observação |
|---|---|---|
| Escopo único: `https://www.googleapis.com/auth/drive.readonly` | `backend/app/integrations/google_drive.py:26`, usado em `:537` | **Restrito.** Não pede `openid`/`email`: o e-mail da conta vem de `drive/v3/about` (`:219-228`) |
| `access_type=offline` + `prompt=consent` | `integrations/google_drive.py:168-169` | Garante refresh token em toda conexão; força a tela de consentimento sempre (inclusive na reconexão) |
| `state` de uso único ligado ao usuário/sessão | `integrations/google_drive.py:536`, `integrations/oauth_base.py` (`_new_state`/`_consume_state`) | Boa proteção CSRF |
| Rotas OAuth | `backend/app/api/integrations.py:428-482` (`/data-sources/google/oauth/start` e `/callback`) | Callback exige `code` e `state` obrigatórios (`:459-460`) |
| Redirect URI de prd (valor não secreto) | `railway variables` (serviço API, produção): `GOOGLE_OAUTH_REDIRECT_URI` = `https://www.arquivio.com.br/api/data-sources/google/oauth/callback` | Tem que estar **idêntico** nos "Authorized redirect URIs" do cliente OAuth no Google Cloud |
| Variáveis no Railway (só nomes) | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_TOKEN_ENCRYPTION_KEY` — todas presentes | Também existem `PUBLIC_APP_URL=https://www.arquivio.com.br` e `WORKOS_REDIRECT_URI` no mesmo domínio |
| Páginas públicas | `https://www.arquivio.com.br/`, `/privacidade`, `/termos` → HTTP 200 (curl em 13/10) e `https://api.arquivio.com.br/health/ready` → 200 | Em 28/09 estavam 404 em `*.up.railway.app` (`docs/integracoes/acoes-humanas-externas.md`, item 1): o domínio próprio já resolveu isso |

**Não verificável daqui (precisa do console do Google Cloud, conta do dono):** o status de publicação atual (Testing/Production), a lista de test users, se o domínio `arquivio.com.br` já está em "Authorized domains"/Search Console, quais redirect URIs estão cadastrados, e se o logo/branding já foi verificado.

## 2. Checklist concreto do que falta (Parte 1)

Regras oficiais confirmadas nesta sessão:
- Escopos de Drive: `drive.file` = não sensível; `drive.readonly`, `drive.metadata.readonly`, `drive` = **restritos** — [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
- Todo app que pede dados restritos e acessa dados "de ou através de um servidor de terceiros" precisa de avaliação de segurança por avaliadores credenciados pelo Google; reavaliação **a cada 12 meses** após a data da Letter of Assessment (LOA); isenções só para uso pessoal, dev/teste/staging, dados do próprio serviço, uso interno de uma organização Workspace e instalação em todo o domínio — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification). O Arquivio guarda texto/vetores em servidor próprio para organizações de terceiros, então **não se enquadra em nenhuma isenção** (mesma conclusão da ADR-0017).
- Em *Testing*: até 100 test users; autorizações e refresh tokens expiram em 7 dias (exceto escopos de perfil básico). Apps não verificados: teto de 100 usuários novos **durante toda a vida do projeto**, que não reseta — [Google Cloud Help: publishing status](https://support.google.com/cloud/answer/15549945).
- Pré-requisitos de submissão: domínio verificado no Search Console, branding verificado e publicado, escopos declarados, política de privacidade **no mesmo domínio da home** e linkada na tela de consentimento, vídeo de demonstração em inglês mostrando o fluxo OAuth com o client ID na barra de endereços (YouTube "não listado"), justificativa de "por que escopos menores não bastam", e declaração Limited Use — mesma página de [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

| # | Etapa | Quem | Esforço / prazo estimado | Custo | Estado hoje |
|---|---|---|---|---|---|
| 1 | Domínio próprio no ar (`www`/`api`) | dono | feito | já pago | **OK** (200 em prd) |
| 2 | Verificar `arquivio.com.br` no Google Search Console e pôr em *Authorized domains* | dono (conta dona do projeto Cloud) | ~30 min + propagação DNS (min–horas) | grátis | **A confirmar no console** |
| 3 | Projeto Cloud de prd, *User type = External*, e-mails de suporte/desenvolvedor monitorados; adicionar um 2º dono/editor (o Google avisa a renovação por e-mail) | dono | 1 h | grátis | A confirmar |
| 4 | Branding: nome "Arquivio" idêntico ao produto, logo 120×120, URLs home/privacidade/termos no domínio verificado → *Verify Branding* + *Publish branding* | dono | 1–2 h para preencher; análise do Google ~2–3 dias úteis (`docs/integracoes/acoes-humanas-externas.md`, item 3) | grátis | Pendente |
| 5 | **Política de privacidade com Limited Use** (hoje 0 ocorrências de "Limited Use" em `frontend/app/privacidade/page.tsx`; seção 4 está nas linhas 14) e coerente com o que o app faz (revogação/expurgo, ver §3.5); revisão jurídica (LGPD, OpenAI como subprocessador) | eng. 0,5 dia + jurídico | 3–7 dias (fila do jurídico) | honorários jurídicos (a definir pelo dono) | Rascunho em `docs/legal/google-politica-privacidade-rascunho.md`, **não publicado** |
| 6 | **Implementar B2**: revogar o token no Google ao desconectar (`POST https://oauth2.googleapis.com/revoke`) e opção de expurgo do índice. Hoje `disconnect` só zera credenciais e marca `disconnected` (`backend/app/integrations/oauth_base.py:109-135`); não há nenhuma chamada a `/revoke` no backend (grep) | eng. | 1–2 dias com testes | — | **Não feito** (adiado na ADR-0017) |
| 7 | Tratar `error=access_denied` no callback (hoje `code` e `state` são obrigatórios → 422 em vez de mensagem amigável: `api/integrations.py:459-460`) | eng. | 2–3 h | — | Não feito |
| 8 | Declarar o escopo `drive.readonly` em *Add or remove scopes* + justificativa ("por que não `drive.file`": ADR-0017) | dono + eng. | 2 h | — | Texto-base na ADR |
| 9 | Vídeo de demonstração em prd (conectar → consentimento com client ID visível → escolher pastas → sync → pergunta com citação → desconectar/revogar) | dono + eng. | 0,5 dia | — | Pendente (depende de #5–#7 para a parte "revogar") |
| 10 | Teste com conta Google sem relação com o projeto, janela anônima, incluindo revogação em `myaccount.google.com/permissions` | eng. | 1–2 h | — | Pendente |
| 11 | Cotar 2–3 laboratórios CASA por escrito e fixar o teto (ADR-0017 cita provisoriamente US$ 5–10 mil/ano; fontes divergem muito) | dono | 1 semana de e-mails | **US$ 0,5–10 mil por rodada/ano, sem cotação firme** (fonte secundária: vendor guides falam em "quatro dígitos" e 4–8 semanas — [Nango: Google security review](https://nango.dev/docs/api-integrations/google-shared/google-security-review)) | Pendente (itens 4 e 9 de `acoes-humanas-externas.md`) |
| 12 | Scans exigidos pelo lab: `pip-audit`, `npm audit --omit=dev`, SAST (semgrep/bandit), DAST (OWASP ZAP) contra staging; arquivar relatórios em `docs/seguranca/` | eng. | 2–4 dias (inclui corrigir achados) | grátis (ferramentas OSS) | Checklist B4 todo desmarcado em `docs/integracoes/google-oauth-verificacao-checklist.md:38-45` |
| 13 | Submeter a verificação do escopo restrito no *Verification Center* (exige branding publicado) e responder o time de OAuth review | dono | 1 dia para submeter; respostas em ciclos de dias | grátis | Pendente |
| 14 | CASA (Tier 2 é o usual para apps SaaS; a ADR-0017 assume Tier 2 — o tier final é definido pelo Google/lab, **não confirmei em fonte oficial**): contratar lab, enviar scans, corrigir achados, receber a **LOA**; enviá-la ao Google | dono + eng. | 4–8 semanas no total (fonte secundária, mesma da linha 11) | taxa do lab | Pendente |
| 15 | Mudar o app para *In production*; sumir o aviso "não verificado" e o teto de 100 usuários | dono | minutos após aprovação | — | Pendente |
| 16 | Renovação anual: lembrete 90 dias antes do vencimento da LOA e dono nomeado | dono | recorrente | repetição da taxa do lab | Pendente |

**Caminho crítico estimado:** etapas 2–4 (1 semana) em paralelo com 5–7 e 12 (1–2 semanas de engenharia) → 11/13 → CASA (4–8 semanas). **Total realista: 6–10 semanas até aprovação**, com custo externo dominado pelo laboratório CASA e renovação anual. Cada semana de atraso na cotação (item 11) empurra tudo.

**Ponte enquanto isso (decisão do dono, ADR-0017 ainda em aberto):** (a) manter *Testing* com reconexão semanal (até 100 test users; o código já trata a expiração como `reauth_required`: `backend/app/ingestion/tasks.py:698-710`, `integrations/google_drive.py:204-210`), ou (b) publicar sem verificação, aceitando o aviso "app não verificado" e o teto vitalício de 100 usuários — [Google Cloud Help](https://support.google.com/cloud/answer/15549945). Para um piloto com poucos clientes, (a) é mais seguro porque não gasta o teto vitalício; (b) queima cotas irreversíveis.

**Sobre "hospedar no Google Cloud":** possível (Cloud Run + Cloud SQL), mas **não é necessário e não ajuda na verificação**. O Google verifica o *app OAuth* (identidade, domínio, escopos, política), não onde o servidor roda. O projeto Cloud existe só para guardar o cliente OAuth. Migrar hospedagem agora custaria semanas e risco sem encurtar um dia a aprovação; o runbook do Railway (`docs/deployment/railway-production.md`) segue válido.

## 3. A arquitetura da integração está boa para este tipo de produto? (Parte 2)

**Veredito:** a *engenharia* está acima da média para um MVP (sync incremental real, refresh seguro, backoff, tokens cifrados). O ponto fraco não é técnico, é **de escopo**: `drive.readonly` dá ao Arquivio acesso ao Drive inteiro e é o que faz o projeto cair na verificação mais cara. Dado que o produto sincroniza **pastas inteiras, recursivamente, e acompanha arquivos novos**, `drive.readonly` é hoje o único escopo que sustenta esse modelo; a alternativa barata (`drive.file` + Picker) muda o produto.

### 3.1 Escopos: `drive` × `drive.readonly` × `drive.file` + Picker

| Opção | Classificação | Cobre pasta recursiva + arquivos novos? | Impacto na verificação |
|---|---|---|---|
| `drive` | Restrito | Sim (e escreve, desnecessário) | Pior que readonly: mais permissão, mesma auditoria |
| **`drive.readonly` (atual)** | **Restrito** | **Sim** | CASA + verificação + renovação anual |
| `drive.metadata.readonly` | Restrito | Só metadados, não baixa conteúdo | Inútil: não resolve e continua restrito |
| `drive.file` + Google Picker | **Não sensível** | **Não confirmado**: a documentação diz "arquivos que o usuário abre com o app ou compartilha via Picker"; **não afirma que escolher uma pasta libera os filhos** ([Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)); minha busca também não encontrou essa garantia | Sem CASA nem verificação de escopo restrito (só verificação básica de marca) |

Pontos fortes do `drive.readonly`: some o atrito de re-escolher arquivos; `changes.list` funciona sobre o Drive todo.
Riscos: (1) auditoria anual e custo recorrente; (2) política tem que descrever que o app *pode* ler tudo mesmo escolhendo uma pasta (já está dito em `frontend/app/privacidade/page.tsx:14` e `termos/page.tsx:13`, bom); (3) `list_folders` varre **todas** as pastas da conta (`integrations/google_drive.py:230-247`, query `mimeType = 'application/vnd.google-apps.folder' and trashed = false`) mesmo sendo só para montar o seletor — o revisor do Google vai questionar o princípio do menor privilégio ("por que não `drive.file`?"), e a resposta precisa estar escrita na justificativa.
Recomendação: manter `drive.readonly`, **mas executar o PoC de 1 dia da ADR-0017 (B7.0)** — criar uma pasta, escolhê-la no Picker com `drive.file` e testar se arquivos filhos e novos aparecem em `files.list`/`changes.list`. Se o resultado for "sim", a migração muda a conta (CASA some, ~US$ 0 e semanas a menos); se "não", a decisão A fica comprovada e pode ser citada na justificativa ao Google. Custo: 1 dia, e é a única ação que pode **eliminar** o custo anual.

### 3.2 Fluxo OAuth: offline, refresh, armazenamento, revogação

Pontos fortes:
- `access_type=offline` + `prompt=consent` garante refresh token (`integrations/google_drive.py:168-169`).
- Refresh automático com margem de segurança de 2 min (`ingestion/google_drive.py:37,345-350`) e **lock de linha** (`with_for_update`, `:373-378`) que evita duas workers renovarem ao mesmo tempo e brigarem pelo token; ao receber 401, tenta renovar e repete uma vez (`:352-357`).
- `invalid_grant` vira `GoogleRefreshTokenInvalid` → `reauth_required`, e há reconexão com **outra conta** (`complete(..., reauth_source_id)`, `integrations/google_drive.py:514-548,590-614`).
- Tokens cifrados com Fernet, chave em env, suporte a chaves de reserva/rotação (`CredentialCipher`, `:458-503`, `integrations/keyring.py`); cursores de sync também cifrados (`:484-491`). Chave por provider: `docs/operacao/chaves-por-provider.md`.
- Logs sem segredos (teste `tests/unit/test_auth_log_redaction.py`).

Riscos / lacunas:
1. **Sem revogação ao desconectar** (`oauth_base.py:109-135`; nenhum `/revoke` no backend). O token continua válido no Google; a política (`privacidade/page.tsx:14`) diz honestamente que "a autorização também pode ser revogada nas configurações do provedor", mas o auditor e o Google costumam esperar revogação best-effort. Prioridade **alta**, 1–2 dias.
2. **Callback sem tratamento de cancelamento** (`api/integrations.py:459-460`: `code`/`state` obrigatórios). Se o usuário clicar em "Cancelar" na tela do Google, recebe 422 cru. Prioridade média, 2–3 h.
3. **Credencial como string `a|b|c` cifrada** (`:464-471`, `split("|", 2)` em `:476`): funciona porque tokens do Google não contêm `|`, mas é frágil; JSON seria mais robusto. Prioridade baixa.
4. **Sem `include_granted_scopes`/`login_hint`** e `prompt=consent` sempre: aceitável (um escopo só), mas a reconexão poderia usar `login_hint=<account_email>` para reduzir confusão na troca de conta. Prioridade baixa.
5. Rotação da chave Fernet é lacuna conhecida (`google-oauth-verificacao-checklist.md:44`).
6. **Limited Use ausente** na política pública (0 ocorrências em `privacidade/page.tsx`) — **bloqueio de aprovação**, não de funcionamento. A declaração obrigatória é descrita na página oficial de [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification). Também precisa constar que dados do Google vão à OpenAI como subprocessador (já mencionado em `privacidade/page.tsx:15`) e que não são usados para treinar modelos.

### 3.3 Sync: polling × Changes API × push (webhooks)

O que existe:
- **Changes API com `startPageToken`** já implementada: `start_page_token` (`integrations/google_drive.py:249-260`), `changes()` paginado com `pageSize=1000`, `includeItemsFromAllDrives`/`supportsAllDrives` (`:277-307`); cursor expirado (400/410) cai em snapshot completo (`:293-294`, `ingestion/google_drive.py:217-230`); mudança de pasta/remoção dispara reconciliação completa (`:159-165,192-209`) — correto, porque mover pasta altera a ancestralidade de todos os filhos.
- Disparo por **polling do Celery beat a cada 15 min** (`ingestion/tasks.py:61-91`, `core/config.py:133`) com cooldown de falha.
- **Push notifications não existem** no código (nenhum `changes.watch`).

Avaliação: Changes API + polling a cada 15 min é a **escolha certa** neste estágio — custa 1 chamada barata por ciclo e fecha o gap de consistência. Push só encurtaria a latência de 15 min para segundos, mas: o canal de `changes.watch` vive no máximo 1 semana, **não renova sozinho** (é preciso recriar com novo `id`), a notificação vem **vazia** (você ainda precisa chamar `changes.list`) e exige HTTPS com certificado válido — [Notifications for resource changes](https://developers.google.com/workspace/drive/api/guides/push). Ou seja, push é *adicional* ao polling, nunca substituto, e **não influencia a verificação**. Recomendação: não construir agora; se um cliente pedir "tempo real", adicionar `changes.watch` + renovação diária + manter o polling de 15 min como rede de segurança (2–3 dias de engenharia).

Ponto de atenção: um `startPageToken` **por seleção** (`ingestion/google_drive.py:78-82,145-153`) multiplica chamadas quando há muitas pastas, e o mesmo feed de mudanças (da conta toda) é lido uma vez por seleção. Uma única leitura por *fonte* e distribuição entre seleções reduziria quota. Prioridade baixa/média, depende de escala.

### 3.4 Quotas e backoff

Pontos fortes: política única `RemoteHttp` com até 5 tentativas, backoff exponencial com jitter e teto de 30 s, `Retry-After` respeitado, orçamento total de 90 s por requisição e **bloqueio compartilhado entre threads** (um 429 desacelera todos os extratores paralelos) — `backend/app/integrations/http.py:20-110`. Mapeamento específico de 403 do Google: `rateLimitExceeded`, `userRateLimitExceeded`, `sharingRateLimitExceeded` são tratados como retentáveis (`integrations/google_drive.py:99-100,124-125,128-141`); outros 403 viram `GoogleRemoteUnauthorized` (exceto os por-arquivo `ITEM_FORBIDDEN_REASONS`). Extração paralela limitada a 3 threads (`ingestion/google_drive.py:36`). Download com verificação de tamanho e MD5 (`:446-451`).
Riscos: (a) o orçamento de 90 s é por requisição; o escalonador precisa reenfileirar em `RemoteThrottled` (parece tratado, mas não percorri todo o `tasks.py`); (b) todo 403 não reconhecido vira "reauth" (`:140`), o que pode marcar uma fonte como desconectada por erro transitório de permissão em um arquivo — o tratamento por item mitiga no ingest, mas `folders()` marca a fonte inteira (`:655-668`). Prioridade média.

### 3.5 Shared drives (Drives compartilhados)

Parcialmente suportado: `supportsAllDrives` e `includeItemsFromAllDrives` em todas as chamadas de lista/mudança (`integrations/google_drive.py:252,265,286-287,404-405`), então arquivos de drives compartilhados aparecem nas listagens e mudanças da conta. **Lacunas:** não há `drives.list` nem seleção de um shared drive como raiz (a unidade de seleção é pasta/`root_files`/`all_accessible`); `changes.list` usa `spaces=drive` sem `driveId` — em contas Workspace o feed do usuário já inclui os drives dos quais ele é membro, mas **atenção a clientes cujo conteúdo está só em shared drives**: `'root' in parents` (`:354`) não os cobre. Recomendo um teste manual com uma conta Workspace antes da gravação do vídeo; ajuste só se falhar. Prioridade média.

### 3.6 Export de Google Docs/Sheets/Slides

Implementado: `GOOGLE_EXPORT_MIME = {Docs: text/plain, Sheets: XLSX, Slides: PPTX}` (`ingestion/extraction/mime.py:8`), usado em `read_file` (`integrations/google_drive.py:436-444`); visualização no chat exporta PDF (`export_pdf`, `:413-428`). Erro `exportSizeLimitExceeded` (limite de ~10 MB do `files.export`) vira `file_too_large` (`:136-137,327-328`). Pontos fortes: reaproveita os extratores XLSX/PPTX; cota por tamanho por tipo (`limits.max_file_bytes_for`, `limits.py:37-39`; teto padrão 100 MB, `:20`).
Riscos: (a) Docs exportado como `text/plain` perde tabelas e estrutura de títulos; `text/markdown` ou `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX, que o pipeline já extrai) preservaria mais estrutura — melhoria de qualidade, não de verificação; (b) arquivos Google acima de 10 MB de export não são indexados (limite do Google, não contornável pelo export); (c) a resposta inteira do export fica em memória antes de gravar em disco (`dest.write(response.content)`, `:443`) — com 3 threads e limite de memória do worker, vale monitorar. Prioridade baixa.

### 3.7 Multi-conta

Uma `DataSource` por conexão (`integrations/models.py`; só há índice único para SharePoint, `:34-42`), então **uma organização pode ter várias contas Google**; a reconexão pode trocar a conta e, ao detectar e-mail diferente, zera todos os cursores para forçar snapshot completo (`integrations/google_drive.py:591-614`); o e-mail da conta aparece na UI para o administrador entender qual conta está ligada (F-024). Ponto forte importante. Risco: não há trava contra a **mesma conta Google conectada duas vezes** na mesma organização (duplicaria a indexação); considerar índice único `(organization_id, provider, account_email)` quando `account_email` não for nulo. Prioridade baixa/média.

## 4. Recomendações priorizadas (o que muda para passar na verificação mais barato e rápido)

| Prioridade | Ação | Por quê | Esforço |
|---|---|---|---|
| **P0** (esta semana, dono) | Cotar 2–3 labs CASA, definir teto, verificar domínio no Search Console e iniciar a verificação de marca | É o caminho crítico e depende de fila externa | 1 semana, sem eng. |
| **P0** (eng.) | Rodar o **PoC de 1 dia `drive.file` + Picker** (ADR-0017 B7.0) | Única ação que pode eliminar CASA e o custo anual; ou comprova a Opção A para a justificativa | 1 dia |
| **P1** (eng.) | Implementar **revogação** (`/revoke` best-effort) + expurgo opcional ao desconectar; testes antes (TDD) | Exigido na prática pelo auditor e necessário para o vídeo/ política serem verdadeiros | 1–2 dias |
| **P1** (eng. + jurídico) | Publicar a política com **Limited Use**, subprocessadores e retenção; alinhar `termos` | Bloqueia a aprovação de marca/escopo | 0,5 dia + jurídico |
| **P1** (eng.) | Tratar `error=access_denied` no callback | UX no vídeo e no review | 2–3 h |
| **P1** (eng.) | Rodar os scans (pip-audit, npm audit, semgrep/bandit, ZAP) e arquivar | Pedido do lab; antecipar reduz rodadas pagas | 2–4 dias |
| **P2** | Teste com conta Workspace + shared drive; ajustar se faltar | Evita surpresa com cliente Workspace | 0,5–1 dia |
| **P2** | `login_hint` na reconexão; trava de conta duplicada; JSON em vez de `a|b|c` | Robustez | 0,5 dia cada |
| **P3** | Exportar Docs como DOCX/Markdown em vez de `text/plain` | Qualidade de busca | 1 dia |
| **P3** | `changes.watch` (push) com renovação diária + polling de segurança | Só se pedirem tempo real | 2–3 dias |
| **Não fazer** | Migrar hospedagem para o Google Cloud para "ajudar na verificação" | Não ajuda; só custa | — |

## 5. Não coberto / limites desta análise

- Não acessei o Google Cloud Console (status de publicação, test users, redirect URIs cadastradas, branding) — itens marcados "a confirmar".
- Não li todo `ingestion/tasks.py` (reenfileiramento em `RemoteThrottled`), nem os testes de ponta a ponta; as afirmações sobre o escalonador vêm de `tasks.py:61-110,698-710`.
- Custos e prazos do CASA vêm de fontes secundárias e da ADR-0017 (sem cotação firme); o tier exato não foi confirmado por fonte oficial.
- O comportamento de `drive.file` com pasta escolhida no Picker **não está confirmado** (nem na doc oficial lida, nem nas buscas): só um PoC resolve.
- Não alterei código, não toquei em prd (apenas `railway variables` somente leitura, mostrando só nomes e a redirect URI/URL pública, que não são segredos) e não fiz commit.

## Fontes externas

- [Choose Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) — classificação dos escopos e definição de `drive.file`.
- [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) — CASA, isenções, 12 meses, pré-requisitos, Limited Use.
- [Google Cloud Help: publishing status / verification](https://support.google.com/cloud/answer/15549945) — Testing (100 usuários, 7 dias) e teto de 100 usuários vitalício.
- [Notifications for resource changes](https://developers.google.com/workspace/drive/api/guides/push) — `changes.watch`, expiração, renovação manual, payload vazio.
- [Nango: Google security review](https://nango.dev/docs/api-integrations/google-shared/google-security-review) — fonte secundária de prazo/custo do CASA.
