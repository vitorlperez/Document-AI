# ArquivIO — Google Drive "e-mail-robô" em produção: passo a passo do DONO

Para: Vitor Perez (VL PEREZ LTDA, www.arquivio.com.br, Railway) · Data: 14/10/2026 · Sem commit.
Este guia é só do que **você** (a pessoa) faz ou confere. O que o pane-687 faz (código, provisionamento sob demanda, deploy, envs) está marcado como **[pane]**.
Fontes técnicas: `drive-sa-operations.md`, `drive-service-account-design.md`, `drive-service-account-poc-result.md`, `drive-sa-e2e-result.md`, `casa-rfq.md` e o código (`backend/app/core/config.py`, `.env.example`).

## Como ler (glossário rápido)

- **Robô / service account (SA)**: uma "conta de máquina" do Google com e-mail `nome@projeto.iam.gserviceaccount.com`. O cliente compartilha a pasta com esse e-mail, como Leitor, e o ArquivIO lê só essa pasta.
- **Projeto-pool**: o projeto do Google Cloud onde os robôs moram (ex.: `arquivio-drive-prod-1`). Limite: **100 robôs por projeto** e **3 criações por minuto** (medido no PoC).
- **Provisioner**: um robô "gerente", com poder só dentro do projeto-pool, que o *worker* usa para criar um robô novo por organização.
- **Organização do Google Cloud**: o "guarda-chuva" da sua conta de empresa (criada em 12/09/2026). Ela tem uma regra de segurança ligada por padrão: **`iam.disableServiceAccountKeyCreation`** ("desativar criação de chave de conta de serviço"). Ela impede criar chaves — por isso precisamos de uma **exceção só no projeto-pool**.

> Regra de ouro: tudo que for "exceção" ou "papel temporário" é feito **no menor escopo possível** e **desfeito depois**.

---

## 0. Antes de tudo — decisões e avisos

- [ ] **(Você)** Decidir se vai com todos os clientes ou só pilotos (use `GOOGLE_SA_ALLOWED_ORGS`, seção 4.5). **Recomendado: começar só com pilotos.**
- [ ] **(Você)** Confirmar a retenção: o padrão do design é **ocultar na hora e apagar em 14 dias** após o cliente remover o compartilhamento (com botão "Apagar agora"). Os textos legais (seção 4) devem dizer isso.
- [ ] **(Você)** Ler o aviso de custo do Drive (seção 1.3): o Google anunciou que **exceder cotas passará a ser cobrado "mais tarde em 2026"**. Para o nosso volume (PoC: ~5,6% do limite no pior caso) não é preocupação, mas vale um alerta de orçamento.

---

## 1. Google Cloud

### 1.1 Entrar na conta/organização certa

1. Abra https://console.cloud.google.com/ e confira, no canto **superior esquerdo** (seletor de projeto), que está logado com **a conta que é dona da organização** (a mesma usada no PoC, e-mail do dono, não um Gmail qualquer).
2. Clique no seletor de projeto → aba **"Todos" / "All"** → você deve ver a **organização** (nome do domínio ou "No organization"). Se aparecer só projetos sem organização acima deles, **pare**: você está na conta errada ou a organização não existe (a exceção de política exige organização).
3. Para ver o **ID da organização** (vai ser útil): https://console.cloud.google.com/iam-admin/settings → campo **Organization ID**.

### 1.2 Faturamento (billing)

- **Instrução**: https://console.cloud.google.com/billing — veja se existe uma conta de faturamento e se está **ativa**.
- **O que as fontes oficiais dizem**:
  - Drive API: "All standard use of the Google Drive API is available at no additional cost" ([Usage limits](https://developers.google.com/workspace/drive/api/guides/limits)). A página **não diz** se é preciso ter conta de faturamento vinculada.
  - Criar service accounts: a [página oficial](https://docs.cloud.google.com/iam/docs/service-accounts-create) **não menciona custo** e não exige billing.
  - Quando uma API do Google é cobrada, é preciso ter billing no projeto ([APIs and billing](https://support.google.com/googleapi/answer/6158867)). Não encontrei fonte oficial que diga que Drive/IAM exijam billing.
  - **No PoC** (`arquivio-drive-poc`), o projeto, a Drive API e 2 robôs funcionaram; os resultados do PoC **não registram** se havia billing vinculado. **A conferir por você**: se o `arquivio-drive-poc` tem billing (https://console.cloud.google.com/billing/linkedaccount?project=arquivio-drive-poc). Se não tinha e funcionou, o projeto-pool também funciona sem.
- **Recomendação prática (como a cobrança por excesso de cota está planejada)**: vincule uma conta de faturamento ao projeto-pool **e** crie um alerta de orçamento (https://console.cloud.google.com/billing/budgets → **Criar orçamento** → R$ 50/mês, alertas em 50%/90%/100% enviados ao seu e-mail). Assim, se o Google passar a cobrar excesso, você é avisado antes. Sem billing, o risco é a API parar caso um dia passe a ser exigido — confirmar nos avisos que o Google prometeu com 90 dias de antecedência.

### 1.3 Criar o projeto-pool de produção

1. Abra https://console.cloud.google.com/projectcreate
2. **Project name**: `arquivio-drive-prod-1` (o *Project ID* será parecido; **anote o ID exato** — ele é o valor de `GOOGLE_SA_POOL_PROJECTS`).
3. **Organization / Location**: escolha a **sua organização** (não deixe "No organization").
4. Clique **Create** e aguarde a notificação (sino) dizer que foi criado. Selecione o projeto no seletor.

### 1.4 Habilitar as APIs (Drive e IAM)

1. Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com → confirme que o seletor mostra `arquivio-drive-prod-1` → **Enable**.
2. IAM API: https://console.cloud.google.com/apis/library/iam.googleapis.com → **Enable** (se já aparecer "API enabled", ok).
3. Para criar chaves/ver robôs pelo comando também costuma ser preciso a **Service Usage API** — normalmente já está ligada. Conferir em https://console.cloud.google.com/apis/dashboard.

### 1.5 Conceder a VOCÊ o papel temporário "Organization Policy Administrator"

> Papel `roles/orgpolicy.policyAdmin`. Só pode ser concedido **na organização**, nunca no projeto ([docs](https://docs.cloud.google.com/iam/docs/troubleshoot-org-policies)). No PoC o Google recusou no projeto.

1. Abra https://console.cloud.google.com/iam-admin/iam
2. No seletor de projeto, escolha a **organização** (não o projeto).
3. **Grant access** (Conceder acesso) → *New principals*: seu e-mail → *Role*: **Organization Policy Administrator** → **Save**.
4. Anote a hora. Você vai **remover** isso no passo 1.8.

### 1.6 Criar a exceção da política "Disable service account key creation" SÓ no projeto

1. Abra https://console.cloud.google.com/iam-admin/orgpolicies
2. Selecione o **projeto** `arquivio-drive-prod-1` no seletor (não a organização).
3. Busque "**Disable service account key creation**" (`iam.disableServiceAccountKeyCreation`) → clique no nome → **Manage policy**.
4. **Policy source** → **Override parent's policy**. Em *Rules* → **Add a rule** → *Enforcement*: **Off** → **Set policy**.
5. **Espere 1–3 minutos** (o PoC levou ~60–90 s; 2 tentativas falharam antes da 3ª).
6. Conferir: reabra a política no projeto e veja "Enforcement: Off"; e na organização continua "On".
7. Documentação do Google sobre essa regra: [Create and delete service account keys](https://docs.cloud.google.com/iam/docs/keys-create-delete) (cita que organizações criadas em/depois de 03/05/2024 já têm a regra ligada, e que isentar um projeto exige o admin de política da organização). Há uma alternativa por **tags** (também descrita lá); o PoC usou o método simples acima e funcionou.

### 1.7 Criar a SA "provisioner" com papéis mínimos (só no projeto)

1. Abra https://console.cloud.google.com/iam-admin/serviceaccounts/create (projeto `arquivio-drive-prod-1` selecionado).
2. **Name**: `arq-provisioner` → **Create and continue**. (Pode pular o passo de papéis aqui.)
3. Vá a https://console.cloud.google.com/iam-admin/iam (projeto selecionado) → **Grant access**:
   - Principal: `arq-provisioner@<projeto>.iam.gserviceaccount.com`
   - Roles: **Service Account Admin** (`roles/iam.serviceAccountAdmin`) e **Service Account Key Admin** (`roles/iam.serviceAccountKeyAdmin`).
   - **Nenhum outro papel.** Nunca Owner/Editor. Nunca na organização.
4. Conferir na aba **Principals** que a linha do provisioner tem exatamente esses 2 papéis.

### 1.8 Chave do provisioner (você OU o pane via gcloud)

Duas opções — peça ao pane-687 qual ele prefere:

- **Opção A — o pane faz via gcloud (menos manuseio de segredo por você).** Você só precisa estar logado no `gcloud` (rode `! gcloud auth login` no terminal desta sessão se pedido) e o pane cria a chave e grava direto em variável do Railway, sem arquivo em disco.
- **Opção B — você cria no console:** https://console.cloud.google.com/iam-admin/serviceaccounts → clique no `arq-provisioner` → aba **Keys** → **Add key** → **Create new key** → **JSON** → **Create**. O arquivo é baixado **uma única vez**. Transforme em base64 e cole direto na variável do Railway (seção 3), depois **apague o arquivo** do computador e da pasta Downloads (e esvazie a lixeira). Nome da env: `GOOGLE_SA_PROVISIONER_KEY_B64` (já existe em `config.py`).
- Limite do Google: **10 chaves por robô** ([docs](https://docs.cloud.google.com/iam/docs/keys-create-delete)). Faça no máximo 1 chave ativa para o provisioner; ao rotacionar, crie a nova, troque no Railway, e só então apague a antiga.

### 1.9 Remover o papel temporário

**Faça logo depois da exceção estar funcionando e do provisioner criado.**

1. https://console.cloud.google.com/iam-admin/iam → selecione a **organização**.
2. Ache seu e-mail → ícone de lápis → remova **Organization Policy Administrator** → **Save**.
3. Conferir: recarregue a lista e veja que o papel sumiu (como no PoC: "já removido, verificado").
4. Observação: a exceção no projeto **continua valendo** depois que você remove o papel. Só quem tem esse papel pode alterar a política; você o devolve se um dia precisar mudar.

### 1.10 Contatos essenciais (alertas) e cotas

- **Essential Contacts**: https://console.cloud.google.com/iam-admin/essential-contacts → selecione a **organização** → **Add contact** → seu e-mail (e um segundo e-mail de backup) → categorias: **Security, Technical, Billing, Legal, Suspension**. Isso faz o Google avisar você de incidentes de segurança, mudanças de cobrança e suspensões.
- **Cotas** (conferir 1 vez e sempre antes de crescer): https://console.cloud.google.com/iam-admin/quotas → selecione `arquivio-drive-prod-1` → filtro "**Service Account Count**" (esperado: 100) e "**Create Service Account requests**" (esperado: 3/min). Conferir também a Drive API em https://console.cloud.google.com/apis/api/drive.googleapis.com/quotas (esperado, segundo o PoC: 12.000 consultas/min por usuário e por projeto).
- **Capacidade**: com 100 robôs por projeto e 1 por organização, um projeto atende ~100 organizações (menos o provisioner). O app emite o alerta `drive_sa.pool_low` quando restam <10 livres; quando isso acontecer, **você** cria `arquivio-drive-prod-2` repetindo as seções 1.3–1.9 e o pane/engenheiro adiciona o ID em `GOOGLE_SA_POOL_PROJECTS` (separado por vírgula).
- **Alerta de orçamento**: ver 1.2.

---

## 2. Segurança das chaves

### 2.1 Onde guardar

| Segredo | Onde guardar | Nunca |
|---|---|---|
| Chave JSON do provisioner (ou o base64) | **Somente** na variável `GOOGLE_SA_PROVISIONER_KEY_B64` do Railway, nos serviços **Worker e Beat** (não no API/Frontend); marque como **Sealed** (3 pontinhos → Seal) | Git, chat, e-mail, Notion, Downloads |
| `GOOGLE_SA_KEY_ENCRYPTION_KEY` (Fernet) | Railway (API, Worker, Beat) **e** uma cópia em gerenciador de senhas (1Password/Bitwarden) | Mesma chave do OAuth/Microsoft/Notion/ClickUp (tem que ser própria) |
| Chaves dos robôs de cada org | Já ficam **cifradas no Postgres** pelo app | Arquivo em disco |

> Atenção: **perder `GOOGLE_SA_KEY_ENCRYPTION_KEY` = perder acesso a todas as chaves dos robôs** (teria que recriar tudo e pedir novo compartilhamento aos clientes). Faça a cópia no gerenciador de senhas **antes** do deploy.

### 2.2 Quem tem acesso

- [ ] **(Você)** Revisar quem tem acesso ao Railway (https://railway.com/workspace → **People** / Settings) e ao Google Cloud (https://console.cloud.google.com/iam-admin/iam). Só você (e o pane/serviço necessário). Ative **verificação em 2 etapas** (https://myaccount.google.com/security) nas contas.
- O **runtime (API)** não recebe credenciais IAM: só Worker/Beat recebem o provisioner. Confirmar isso na seção 3.

### 2.3 Revogação de emergência (do mais rápido ao mais definitivo)

1. **Desligar a flag** (segundos, reversível): Railway → serviço Backend/API, Worker e Beat → **Variables** → `GOOGLE_DRIVE_SA_ENABLED=false` → **Deploy**. Tira o modo robô de todos sem apagar dados. Para esconder a tela: `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` vazio no Frontend (exige rebuild, ver seção 3).
2. **Desativar o provisioner**: https://console.cloud.google.com/iam-admin/serviceaccounts → `arq-provisioner` → **Disable** (menu ⋮). Impede novos robôs; não afeta quem já lê.
3. **Apagar a chave do provisioner**: mesma página → aba **Keys** → lixeira na chave. Se vazou, faça isto **antes** de trocar no Railway.
4. **Desativar um robô específico** (suspeita num cliente): na lista de service accounts, ⋮ → **Disable**. A leitura dessa organização para na hora.
5. **Apagar tudo** (último recurso): https://console.cloud.google.com/iam-admin/settings → **Shut down** o projeto, ou apagar service accounts. **Irreversível** — os clientes terão que recompartilhar.
6. Se a `GOOGLE_SA_KEY_ENCRYPTION_KEY` vazou: gere outra, ponha a antiga em `GOOGLE_SA_KEY_ENCRYPTION_PREVIOUS_KEYS` (para ler o que já está cifrado) e peça ao pane para re-cifrar; depois remova a antiga.

---

## 3. Railway

> Mapa: dashboard https://railway.com/dashboard → seu projeto → clique no serviço (Backend/API, Worker, Beat, Frontend, Postgres). Docs: [Variables](https://docs.railway.com/variables).

### 3.1 Onde ver/editar variáveis

- Serviço → aba **Variables** → **New Variable** (um por vez) ou **RAW Editor** (cola várias).
- **Toda alteração vira "staged changes"** (mudanças pendentes): você precisa **revisar e clicar Deploy** para valer.
- **Sealed** (3 pontinhos → Seal) esconde o valor; use para a chave do provisioner e a Fernet.

### 3.2 Nomes das variáveis

| Variável | Onde | Status | Valor / observação |
|---|---|---|---|
| `GOOGLE_DRIVE_SA_ENABLED` | API, Worker, Beat | confirmado em `config.py`/`.env.example` | `false` por padrão; `true` liga o modo. Ligue por último |
| `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` | **Frontend** | confirmado (`frontend/app/product/drive-share-flag.ts`) | `1` liga a tela. **É variável de build**: depois de mudar, o Railway precisa **rebuildar** o Frontend (Deployments → Redeploy) — só reiniciar não basta |
| `GOOGLE_SA_KEY_ENCRYPTION_KEY` | API, Worker, Beat | confirmado | Fernet **própria**. Obrigatória se a flag estiver `true` (o app não sobe sem ela). Gere uma nova; nunca reutilize |
| `GOOGLE_SA_KEY_ENCRYPTION_PREVIOUS_KEYS` | API, Worker, Beat | confirmado | Vazia, até trocar a chave |
| `GOOGLE_SA_ALLOWED_ORGS` | API, Worker, Beat | confirmado | UUIDs das organizações separados por vírgula. **Vazia = todas**. Para pilotos: liste só os UUIDs |
| `GOOGLE_SA_DOWNLOAD_WORKERS` | Worker | confirmado | `3` (aceita 1–3) |
| `GOOGLE_SA_POOL_PROJECTS` | Worker, Beat | confirmado em `config.py`; **valor a confirmar com o pane-687** | ID(s) do(s) projeto(s)-pool, ex.: `arquivio-drive-prod-1` |
| `GOOGLE_SA_PROJECT_QUOTA` | Worker, Beat | existe em `config.py` (padrão 100) — a confirmar se precisa setar | `100` |
| `GOOGLE_SA_WARM_POOL_SIZE` | Worker, Beat | existe em `config.py` (padrão 0, máx. 20) — **a confirmar** | quantos robôs "pré-criados" manter |
| `GOOGLE_SA_CAPACITY_ALERT_BELOW` | Worker, Beat | existe em `config.py` (padrão 10) | alerta `drive_sa.pool_low` |
| `GOOGLE_SA_PROVISIONER_KEY_B64` | **só Worker/Beat** | existe em `config.py` — **a confirmar** com o pane-687 que este é o nome final | chave do provisioner, **Sealed** |

Não há (ainda) variáveis a mais confirmadas no código; **tudo que o pane-687 criar além dessa lista fica "a confirmar"** — peça a lista final dele no handoff dele.

### 3.3 Backups do Postgres ANTES da migração

As migrações novas são `20261014_0032_drive_service_accounts.py` e `20261014_0033_drive_sa_on_demand.py`. Antes do deploy:

1. [ ] Railway → projeto → serviço **Postgres** → aba **Backups** ([guia oficial](https://docs.railway.com/guides/postgres-backups-restores)).
2. [ ] Ative agendamento **Daily** (guardado 6 dias), **Weekly** (1 mês) e, se quiser, **Monthly**.
3. [ ] Clique em **Create backup** (backup manual agora) e **espere o status "completo"**. Atenção: o backup manual tem teto de 50% do tamanho do volume — se o banco for maior que isso, aumente o volume antes.
4. [ ] (Recomendado) Na mesma aba, **Enable PITR** (recuperação para qualquer minuto) e espere o primeiro backup-base terminar; sem custo extra de recurso além do armazenamento do bucket.
5. [ ] Tire uma foto/anote a hora e o nome do backup manual.
6. Para restaurar: Backups → ⋮ no backup → **Restore** → revise o "staged change" → Deploy. Aviso: restaurar apaga backups mais novos que ele.

### 3.4 Como desligar rápido (se algo der errado)

1. Serviço **Backend/API** → Variables → `GOOGLE_DRIVE_SA_ENABLED` = `false`; repita no **Worker** e no **Beat** → **Deploy**.
2. Para sumir a tela: Frontend → `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` vazio → rebuild.
3. Em caso de bug de código: serviço → aba **Deployments** → no deploy anterior bom, ⋮ → **Redeploy / Rollback**.
4. O banco **não é desfeito** por rollback de código; só por restauração de backup.

---

## 4. Legal e produto

### 4.1 Política de privacidade e termos

Páginas do app: `frontend/app/privacidade/page.tsx` e `frontend/app/termos/page.tsx` (publicadas em https://www.arquivio.com.br/privacidade e /termos). O pane pode editar o código; o **conteúdo jurídico deve ser aprovado por você** (idealmente por um advogado).

- [ ] Incluir o **modo e-mail-robô**: o cliente compartilha pastas específicas com um e-mail de serviço nosso, como **Leitor**; lemos **somente** as pastas compartilhadas; não alteramos nem apagamos arquivos no Drive do cliente.
- [ ] Incluir a **retenção ao remover o compartilhamento**: a leitura para; o conteúdo indexado é **ocultado imediatamente** e **apagado em até 14 dias** (ou "Apagar agora" a pedido). Se mudar a decisão para "apagar na hora", ajuste o texto.
- [ ] **OpenAI como subprocessador**: o texto extraído é enviado à OpenAI para gerar embeddings/respostas. Declare isso e o país de tratamento (LGPD).
- [ ] **Limited Use (opcional)**: a política "Google API Services User Data Policy / Limited Use" vale para dados obtidos via **OAuth** (escopos do Google). No modo robô o acesso é por compartilhamento direto (sem OAuth do usuário), então não é obrigatório; ainda assim, incluir uma frase de que o uso é limitado ao serviço contratado reforça a confiança e o processo CASA do OAuth ([casa-rfq.md](casa-rfq.md) já assume que a política mostre isso).
- [ ] Citar quem opera: VL PEREZ LTDA, CNPJ 61.265.563/0001-04.

### 4.2 Texto de onboarding (sugestão para a tela e e-mail)

> "Compartilhe a pasta no Google Drive com o e-mail do ArquivIO (copie na tela), escolha **Leitor** e clique em Compartilhar. Só lemos as pastas que você compartilhar. Para parar, remova o compartilhamento no Drive: o acesso para na hora e o conteúdo é apagado em até 14 dias."

- Incluir **aviso de que o Drive sugere "Editor" por padrão** (PoC): peça "Leitor" (Editor também funciona, mas Leitor basta).
- Avisar que o e-mail termina em `...gserviceaccount.com` (parece estranho, é normal) e que **pastas com "qualquer pessoa com o link" são recusadas**.
- Avisar que a primeira sincronização de ~1.000 arquivos leva ~6 min (PoC).

### 4.3 Comunicação com clientes piloto

- [ ] Enviar um e-mail curto: o que é, o passo a passo, como revogar, retenção de 14 dias, contato.
- [ ] Pedir feedback depois do primeiro uso (≤ 48 h).

### 4.4 Quem NÃO deve ser liberado agora

Clientes com **Google Workspace restritivo** (compartilhamento externo bloqueado ou só domínios permitidos): o PoC **não testou** Workspace, e a regra de "domínios permitidos" pode bloquear `gserviceaccount.com`. Para esses, use o modo OAuth atual ou espere a fase 2 (alias `@arquivio.com.br`).

### 4.5 Liberar só pilotos (`GOOGLE_SA_ALLOWED_ORGS`)

1. Descubra o UUID da organização-cliente (peça ao pane ou veja no banco/admin).
2. Railway → API, Worker e Beat → `GOOGLE_SA_ALLOWED_ORGS` = `uuid1,uuid2` → Deploy.
3. Vazia = todas as organizações. Para abrir geral, limpe a variável **depois** do piloto dar certo.

---

## 5. Teste final em produção (roteiro de clique)

Faça com uma organização piloto (a sua, de preferência) e uma pasta de teste **sua** no Drive, com 2–3 arquivos pequenos e um código fácil de reconhecer dentro de um deles.

1. [ ] Abra https://www.arquivio.com.br e entre com a org liberada.
2. [ ] **Integrações** → card **Google Drive** → deve abrir o modal de método → escolha **Compartilhar pastas** (e-mail-robô).
3. [ ] **Passo 1**: o e-mail do robô aparece (`…@arquivio-drive-prod-1.iam.gserviceaccount.com`). Clique em **Copiar e-mail**.
4. [ ] No Drive (https://drive.google.com): clique direito na pasta de teste → **Compartilhar** → cole o e-mail → escolha **Leitor** (o Drive sugere Editor) → desmarque "Notificar" → **Enviar/Compartilhar**.
5. [ ] Volte ao ArquivIO: o **Passo 2** deve detectar a pasta em segundos. Selecione-a.
6. [ ] **Verificar**: esperado ~20 s, "download liberado".
7. [ ] **Escolher o que sincronizar** → confirmar → **Sincronizar**. Espere o status ficar **Indexado** (em Biblioteca → "Google Drive (pasta compartilhada)").
8. [ ] **Chat**: pergunte "O que diz o arquivo X? Qual o código?" e confira que a resposta cita o arquivo e o código certo.
9. [ ] **Negativo**: cole um link de pasta **com "qualquer pessoa com o link"** → deve ser recusado (`not_shared`).
10. [ ] **Revogação**: no Drive, remova o compartilhamento da pasta (Compartilhar → ícone do robô → **Remover acesso**). Em até alguns minutos, a Biblioteca/card deve mostrar **"Acesso removido · apagando em 14 dias"** e o chat não deve mais citar a pasta.
11. [ ] (Opcional) Recompartilhe e veja o estado voltar a "verificado".
12. [ ] Confira no Railway → Worker → **Logs** que não há erros (`drive_sa.robot_unavailable`, `pool_cleanup_required`).

---

## 6. Limpeza do PoC

Depois que a produção passar no teste:

- [ ] **Google Cloud**: https://console.cloud.google.com/cloud-resource-manager → `arquivio-drive-poc` → **Delete** (ou, no terminal: `gcloud projects delete arquivio-drive-poc`). Isso apaga os robôs `arq-poc-a`/`arq-poc-b` e a exceção de política dele. (Há ~30 dias para desfazer.)
- [ ] **Chaves locais**: apague a pasta `~/.config/arquivio-drive-poc/` (chaves dos robôs do PoC).
- [ ] **Drive pessoal** (https://drive.google.com): remova o compartilhamento com o robô A e apague/arquive as pastas `poc-main`, `poc-notify-on`, `poc-notify-off`, `arvore-1000`, `poc-sem-download`, `fora-do-compartilhamento`.
- [ ] **ATENÇÃO — pasta `poc-link-public`**: ela está com "**Qualquer pessoa com o link**". Abra-a → Compartilhar → Acesso geral → **Restrito** (ou apague a pasta).
- [ ] **gcloud**: no terminal, `gcloud auth revoke --all` (ou `gcloud auth revoke SEU_EMAIL`) para sair; confira com `gcloud auth list`. Se não for mais usar: `brew uninstall --cask gcloud-cli` (opcional).
- [ ] **Banco local**: o robô `arq-poc-a` importado no banco/dev local pode ser apagado (dev é descartável).
- [ ] Conferir que o papel **Organization Policy Administrator** não está mais em ninguém: https://console.cloud.google.com/iam-admin/iam (organização).

---

## 7. Checklist final

**Preparação**
- [ ] (Você) Conta/organização certa conferida (1.1)
- [ ] (Você) Billing decidido + alerta de orçamento (1.2)
- [ ] (Você) Backup manual + agendado do Postgres feitos e verificados (3.3)
- [ ] (Você) Cópia da `GOOGLE_SA_KEY_ENCRYPTION_KEY` no gerenciador de senhas (2.1)

**Google Cloud**
- [ ] (Você) Projeto `arquivio-drive-prod-1` criado, ID anotado (1.3)
- [ ] (Você) Drive API e IAM API habilitadas (1.4)
- [ ] (Você) Papel Organization Policy Administrator concedido na organização (1.5)
- [ ] (Você) Exceção da política criada **só no projeto**, aguardou 1–3 min (1.6)
- [ ] (Você) SA `arq-provisioner` criada com **apenas** Service Account Admin + Service Account Key Admin no projeto (1.7)
- [ ] (Você ou pane) Chave do provisioner criada e gravada **Sealed** no Railway (Worker/Beat); arquivo local apagado (1.8)
- [ ] (Você) Papel Organization Policy Administrator **removido** (1.9)
- [ ] (Você) Essential Contacts configurados (1.10)
- [ ] (Você) Cotas conferidas: 100 robôs, 3/min (1.10)

**Railway**
- [ ] (pane) Envs criadas conforme a seção 3.2; lista final enviada a você
- [ ] (Você) Conferiu que Frontend tem `NEXT_PUBLIC_DRIVE_SHARE_ENABLED` e **rebuild** foi feito
- [ ] (Você) Conferiu que credencial do provisioner está **só** em Worker/Beat
- [ ] (pane) Migrações 0032 e 0033 aplicadas; deploy feito
- [ ] (Você) `GOOGLE_SA_ALLOWED_ORGS` com só os pilotos (4.5)
- [ ] (Você) Sabe desligar a flag (3.4)

**Legal e produto**
- [ ] (pane) Atualiza `privacidade` e `termos` (código)
- [ ] (Você) Aprova o texto jurídico (retenção 14 dias, OpenAI, robô) (4.1)
- [ ] (Você/pane) Texto de onboarding aprovado e no app (4.2)
- [ ] (Você) E-mail enviado aos pilotos (4.3)

**Teste e fechamento**
- [ ] (Você) Teste final de produção completo (seção 5), incluindo revogação
- [ ] (Você) Limpeza do PoC (seção 6), incluindo `poc-link-public`
- [ ] (Você) Plano de emergência lido (2.3)
- [ ] (Você) Lembrete de rotação da chave a cada **90 dias** (alerta `drive_sa.rotation_overdue`)
- [ ] (Você, futuro) Quando restarem <10 robôs livres (`drive_sa.pool_low`): criar `arquivio-drive-prod-2`

---

## Anexo — fontes oficiais consultadas

- [Create and delete service account keys](https://docs.cloud.google.com/iam/docs/keys-create-delete) — papel Service Account Key Admin, política de chaves, limite de 10 chaves por robô.
- [Troubleshoot organization policy errors for service accounts](https://docs.cloud.google.com/iam/docs/troubleshoot-org-policies) — Organization Policy Administrator só na organização.
- [Create service accounts](https://docs.cloud.google.com/iam/docs/service-accounts-create) — passos do console; sem menção a custo.
- [Drive API usage limits](https://developers.google.com/workspace/drive/api/guides/limits) — "no additional cost" e aviso de cobrança por excesso em 2026.
- [APIs and billing](https://support.google.com/googleapi/answer/6158867).
- [Railway: Postgres backups & restores](https://docs.railway.com/guides/postgres-backups-restores) · [Railway: Variables](https://docs.railway.com/variables).
- Não verificados em fonte oficial nesta rodada (confirmar na tela): rótulos exatos de menu no console (mudam com frequência) e se Drive/IAM exigem conta de faturamento.
