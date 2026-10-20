# Google Drive por "e-mail-robô": design da solução (compartilhar pasta com o ArquivIO)

Data: 2026-10-14 · Documento de design, **somente leitura no código** (nada alterado em código/prd/ADR; sem commit) · Âncoras de código valem para o `HEAD` `a0a4b03` · Complementa [`drive-alternatives.md`](drive-alternatives.md) §2, [`drive-file-poc-result.md`](drive-file-poc-result.md), [`google-drive-deploy-review.md`](google-drive-deploy-review.md) e [`casa-rfq.md`](casa-rfq.md).

Pergunta do dono: *"a ideia de termos um e-mail de serviço onde os nossos usuários compartilham as pastas é boa. Como seria essa solução, como diferenciar as pastas de cada cliente e como deixar o processo fácil?"*

Convenção de evidência: **[doc]** = confirmado em documentação oficial citada; **[código]** = confirmado lendo o repositório (`arquivo:linha`); **[hipótese → PoC]** = plausível mas **não verificado**, entra no PoC de 1 dia (§7).

---

## 0. Resumo para leigo (1 minuto)

- **A ideia funciona assim:** o ArquivIO tem um "usuário-robô" com um e-mail próprio. O cliente abre a pasta no Google Drive, clica em **Compartilhar**, cola esse e-mail como **Leitor** e volta ao ArquivIO colando o link da pasta. O robô só enxerga o que foi compartilhado com ele. Não há tela "Entrar com Google" e nenhuma permissão sobre o Drive inteiro.
- **Como saber de quem é cada pasta?** Esta é a pergunta que decide o projeto, porque o maior risco é um cliente ver a pasta de outro. **Recomendação: um robô por empresa-cliente** (cada cliente recebe o *seu* e-mail-robô, diferente de todos os outros). Assim a pergunta "de quem é esta pasta?" some: se o robô do cliente A consegue ler, é porque o cliente A compartilhou. O robô do cliente B simplesmente **não enxerga** a pasta de A, nem que B cole o link dela. O isolamento vem do próprio Google, não de uma regra nossa que poderia ter bug.
- **Facilidade:** o ArquivIO mostra o e-mail com botão **Copiar**, abre o Drive em outra aba, fica "ouvindo" e **detecta sozinho** quando a pasta é compartilhada (ou o cliente cola o link). Em seguida mostra "✅ Acesso confirmado: 128 arquivos em 9 subpastas" ou um erro em português dizendo exatamente o que fazer.
- **Dois pontos de atenção honestos:**
  1. **Empresas Google Workspace com compartilhamento externo restrito** podem não conseguir compartilhar com o e-mail-robô: o Google diz que domínios de conta de serviço (`gserviceaccount.com`) **não podem ser adicionados à lista de domínios permitidos** ([Allow external sharing with only trusted domains](https://support.google.com/a/answer/6160020?hl=en)). A saída planejada é um **e-mail com nosso domínio** (`drive-acme@arquivio.com.br`, um Grupo Google que contém o robô) — ainda **hipótese a validar** (§1.4 e §7).
  2. **Política do Google/CASA:** o robô não aciona o consentimento OAuth, mas o Google não escreve que isso é permitido ou isento (zona cinzenta). Recomendação: manter a pergunta formal ao Google e **não desmontar o plano do CASA** até ter resposta escrita (§4).
- **Esforço:** PoC de 1 dia; MVP funcional em ~10–13 dias de engenharia; nada disso substitui o OAuth atual (fica como segundo modo atrás de feature flag).

---

## 1. Visão geral e jornada do usuário

### 1.1 Atores e peças

```
 Cliente (Admin/Owner da org)            ArquivIO                               Google
 ───────────────────────────             ───────────────────────────            ───────────────
 Tela Integrações ──habilitar──▶  atribui o robô da org  (pool)
 copia e-mail  ─────────────────────────────────────────────────▶  Drive: Compartilhar → Leitor
 cola link da pasta ──────────▶  files.get(folderId) como robô ──▶  200 / 404 / 403
                                  valida + vincula + sincroniza ◀──  files.list / changes.list
```

Quem pode configurar: **Owner/Admin** da organização, como hoje (`require_admin`, `backend/app/integrations/oauth_base.py:28-38`); membros comuns só consomem.

### 1.2 Jornada passo a passo (mockups em texto)

**Tela 0 — card "Google Drive" em Integrações** (hoje `ToolsCatalog`, `frontend/app/product/integrations-screen.tsx:113-119`, botão "Conectar" → `connect()` em `:41` que faz `window.location.assign(.../google/oauth/start)`). Com a flag ligada o botão abre um modal de método:

```
┌ Conectar Google Drive ───────────────────────────────────────────────┐
│ Como você prefere dar acesso?                                         │
│                                                                       │
│ ● Compartilhar pastas com o ArquivIO            [Recomendado]         │
│   Você escolhe as pastas e as compartilha como "Leitor".              │
│   O ArquivIO não vê mais nada do seu Drive. Funciona com Gmail        │
│   e com Google Workspace.                                             │
│                                                                       │
│ ○ Entrar com a conta Google                     (modo atual, OAuth)   │
│   Você autoriza a leitura do Drive e escolhe as pastas depois.        │
│                                                                       │
│                                   [Cancelar]  [Continuar]             │
└───────────────────────────────────────────────────────────────────────┘
```

**Tela 1 — "Passo 1 de 3: copie o e-mail do ArquivIO"**

```
┌ Compartilhar pastas com o ArquivIO ───────────────────── 1 ─ 2 ─ 3 ┐
│ Passo 1 de 3 · Compartilhe a pasta com este e-mail                  │
│                                                                      │
│  ┌────────────────────────────────────────────────┐ [ ⧉ Copiar ]    │
│  │ arq-k7m2x9qa@arquivio-drive-01.iam.gserviceac… │  ← copiado ✓    │
│  └────────────────────────────────────────────────┘                  │
│  Este e-mail é exclusivo da sua empresa. Ninguém mais o usa.         │
│                                                                      │
│  1. [ Abrir o Google Drive ↗ ]  (abre em outra aba)                  │
│  2. Clique com o botão direito na pasta → Compartilhar               │
│  3. Cole o e-mail, escolha  Leitor,  desmarque "Notificar pessoas"   │
│  4. Clique em Enviar                                                 │
│                                                                      │
│  ⏳ Aguardando você compartilhar… verificando a cada 5 s             │
│  Já compartilhou? [ Colar o link da pasta ]                          │
│  Sua empresa bloqueia compartilhamento externo? [ Ver o que fazer ]  │
└──────────────────────────────────────────────────────────────────────┘
```

- **Botão Copiar:** `navigator.clipboard.writeText` com fallback para seleção do texto; o e-mail aparece em fonte mono, *truncate* só visual (o valor copiado é completo).
- **Deep link para o Drive:** só dá para abrir `https://drive.google.com/` (o Google **não expõe** URL que abra direto a janela "Compartilhar" com e-mail pré-preenchido — [hipótese → PoC]; se existir, usar). Depois que o cliente cola o link, passamos a oferecer **"Abrir esta pasta no Drive"** = `https://drive.google.com/drive/folders/<id>` (URL oficial de pasta).
- **"Aguardando…":** enquanto a tela está aberta, o front consulta `GET .../inbox` a cada 5 s (parar em 5 min; retomar com botão). O backend lista `files.list q="sharedWithMe and mimeType='application/vnd.google-apps.folder'"` com o robô da org — `sharedWithMe` é um termo de busca oficial ([Search for files and folders](https://developers.google.com/workspace/drive/api/guides/search-files)). Como o robô é **da org**, tudo que aparece é dela.
- Passos 2–4 são o ponto onde o cliente mais trava; vale uma imagem/GIF curto de 6–8 s ao lado (conteúdo estático, sem dados).

**Tela 2 — "Passo 2 de 3: confirmar a pasta"** (aparece sozinha quando o inbox detecta, ou após colar link)

```
┌ Passo 2 de 3 · Confirmar pasta ──────────────────────────────────────┐
│ Encontramos pastas compartilhadas com o ArquivIO:                    │
│                                                                      │
│  📁 Contratos 2026        compartilhada por maria@acme.com · há 1 min │
│      [ Conectar esta pasta ]                                         │
│  📁 Financeiro            compartilhada por joao@acme.com  · há 3 min │
│      [ Conectar esta pasta ]                                         │
│                                                                      │
│ Não apareceu? Cole o link da pasta:                                  │
│  [ https://drive.google.com/drive/folders/1AbC…  ]  [ Verificar ]    │
└──────────────────────────────────────────────────────────────────────┘
```

**Tela 3 — verificação "acesso confirmado"** (checklist animado, ~2–5 s)

```
┌ Verificando acesso… ─────────────────────────────────────────────────┐
│ ✓ Link reconhecido (pasta, não arquivo)                              │
│ ✓ O ArquivIO consegue abrir a pasta  "Contratos 2026"                │
│ ✓ Permissão de leitura                                                │
│ ✓ Conteúdo pode ser baixado           (amostra de 20 arquivos)       │
│ ✓ Contagem: 128 arquivos · 9 subpastas                               │
│                                                                      │
│ ✅ Acesso confirmado                                                 │
│ Compartilhada por maria@acme.com · Seu robô: arq-k7m2x9qa@…          │
│                                                                      │
│        [ Escolher o que sincronizar ▸ ]   (abre o seletor atual)     │
└──────────────────────────────────────────────────────────────────────┘
```

"Escolher o que sincronizar" **reaproveita** o modal de escopo existente (`loadCatalog`, `integrations-screen.tsx:46` → `GET /data-sources/{id}/scope-catalog`, `api/integrations.py:604-704`), pois `list_folders` (`integrations/google_drive.py:230-247`) devolve **apenas o que o robô enxerga**; o texto "uniform access" (`uniform_access_confirmed`, `api/integrations.py:74`) permanece.

**Tela 4 — pasta conectada** (card em Integrações / Biblioteca)

```
 Google Drive · Pasta compartilhada      ● Conectado       [Gerenciar] [Desconectar]
 Robô: arq-k7m2x9qa@…  [⧉]   Pastas: Contratos 2026 (128 arquivos) · sync há 4 min
 + Adicionar outra pasta (compartilhe com o mesmo e-mail e atualize)
```

### 1.3 Estados de erro (texto exato sugerido, em PT-BR)

| Situação | Como detectamos (API) | Mensagem ao usuário | Ação oferecida |
|---|---|---|---|
| **Link inválido** (não é Drive, é arquivo, ID mal formado) | parse local (§5) | "Esse link não parece ser de uma **pasta** do Google Drive." | exemplo de link correto |
| **Pasta não compartilhada** (ou ID errado) | `files.get(folderId)` do robô → **404** `notFound`. O Drive responde 404 também para arquivo existente sem acesso [hipótese → PoC; a página [Resolve errors](https://developers.google.com/workspace/drive/api/guides/handle-errors) trata 404 como "arquivo não encontrado"]. **Não distinguimos "não existe" de "sem acesso"** (de propósito: evita enumerar IDs) | "Ainda não conseguimos abrir essa pasta. Ela precisa estar compartilhada com **{email do robô}** como Leitor." | botão Copiar e-mail; "Já compartilhei, verificar de novo"; link "Abrir esta pasta no Drive" |
| **Compartilhada, mas só como "Comentador"/outro papel** | `files.get` ok; `capabilities`/papel ≠ leitor; leitura OK → **aceitar** (papel maior que Leitor não impede ler) | (sem erro) | aviso opcional "Leitor basta" |
| **Sem permissão de download** (dono desabilitou "leitores podem baixar/copiar") | `files.get alt=media` → 403 `cannotDownloadFile`/`fileNotDownloadable` (já mapeado em `ITEM_FORBIDDEN_REASONS`, `integrations/google_drive.py:103-105`); pré-checagem lê `capabilities.canDownload` e `copyRequiresWriterPermission` ([doc](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)) na amostra | "Encontramos 37 arquivos com download bloqueado pelo proprietário. O ArquivIO não consegue ler o conteúdo deles. Peça ao dono para liberar 'Leitores podem baixar, imprimir e copiar'." | lista dos arquivos bloqueados (nome, dono); pasta é conectada mesmo assim, itens ficam `source_file_unavailable` (já existe, `ingestion/google_drive.py:329-333`) |
| **Workspace bloqueia compartilhamento externo** | **Não é detectável pela API**: o convite nunca é enviado, então o inbox fica vazio. Heurística: após 90 s sem nada no inbox → mostra aviso | "Parece que sua empresa não permite compartilhar com endereços de fora. Peça ao administrador do Google Workspace para liberar (texto pronto abaixo) ou use o modo 'Entrar com Google'." | botão **"Copiar texto para o TI"** (§1.4) e opção de alternar para OAuth |
| **Compartilhamento removido / pasta apagada depois** | no sync: `files.get(root)` 404 (ou `changes` com `removed`) confirmado em **2 checagens ≥ 1 h** (evita falso positivo) | "O acesso à pasta **Contratos 2026** foi removido. Paramos de sincronizar. Para voltar, compartilhe de novo com {email}." | status do vínculo `access_lost`; e-mail/notificação ao admin; botão "Verificar agora" e "Apagar os dados desta pasta" (§3.5) |
| **Pasta na Lixeira** | `trashed=true` | igual ao anterior com texto "foi movida para a lixeira" | idem |
| **Robô indisponível** (chave revogada/SA desativada — problema **nosso**) | token endpoint → `invalid_grant`/`invalid_client` | "Estamos com um problema técnico para acessar o Google Drive. Já fomos avisados." (**não** pede ao cliente "reconectar") | alerta para a equipe (§3.7); status interno `provider_error` |
| **Cota/limite do Google** | 403 `rateLimitExceeded` etc. | "O Google pediu para aguardarmos. Vamos tentar de novo automaticamente." | backoff existente (`integrations/http.py:20-110`) |

### 1.4 Workspace com compartilhamento externo bloqueado (o caso difícil)

Fato **[doc]**: administradores podem restringir o compartilhamento a **domínios permitidos**, e **domínios `gserviceaccount.com` não podem ser adicionados a essa lista** ([Allow external sharing with only trusted domains](https://support.google.com/a/answer/6160020?hl=en)). Se a política do cliente for "só domínios permitidos", o e-mail do robô **não funciona**; se for "bloquear todo compartilhamento externo", também não. Se a política permitir "compartilhar com qualquer pessoa/qualquer e-mail", funciona.

Consequência para o design:
1. Oferecer ao cliente um **texto pronto para o TI** ("Precisamos que o administrador permita compartilhar a pasta X com o endereço Y; o endereço só terá acesso de leitura às pastas que vocês escolherem").
2. **Fase 2 (recomendada se aparecer cliente assim):** um endereço **do nosso domínio**, p. ex. `drive-acme@arquivio.com.br`, que é um **Grupo Google** (Cloud Identity Free ou Workspace) cujo único membro é o robô daquela org. O TI do cliente só precisa **permitir o domínio `arquivio.com.br`** (domínio de empresa normal, verificável), não "todo o Google". Bônus: podemos **trocar o robô por baixo** (rotação/comprometimento da chave) sem o cliente recompartilhar nada. **[hipótese → PoC]**: (i) conta de serviço pode ser membro de grupo; (ii) pasta compartilhada com o grupo aparece em `sharedWithMe`/`changes` do robô; (iii) o allowlist do Workspace aceita endereço de grupo do nosso domínio.
3. Fallback sempre disponível: o modo OAuth atual (admin do cliente autoriza), enquanto ele existir.

---

## 2. Como diferenciar os clientes (o centro do design)

### 2.1 O problema

Se **um único** robô é compartilhado por todos os clientes, ele enxerga as pastas de todos. Ao cliente B colar um link, nada no Google diz "esta pasta é de A". Alguém tem de **vincular pasta ↔ organização** e **impedir que B reivindique a pasta de A**. O pior cenário (vazamento entre tenants) significa documentos de A respondendo perguntas de B.

### 2.2 Opções comparadas

| | (a) **1 robô global** + cliente cola link | (b) **1 robô por organização** | (c) **Grupo Google por cliente** | (d) **Detecção automática** `sharedWithMe` + e-mail de quem compartilhou |
|---|---|---|---|---|
| **Ideia** | todos compartilham com o mesmo e-mail; vínculo `org ↔ folderId` no nosso banco | cada org tem seu robô (`arq-xxxx@projeto.iam…`); o e-mail identifica a org | endereço `drive-acme@arquivio.com.br` = grupo; o robô é membro | robô global lista `sharedWithMe` e atribui a org pelo e-mail de `sharingUser` |
| **Isolamento** | **fraco**: depende de nosso código impedir B de reivindicar A | **forte**: isolamento feito pelo Google (B nunca enxerga A) | forte se grupo→robô for 1:1 por org; **sozinho (grupo com um robô global) = igual a (a)** | **fraco/incerto**: e-mail ≠ organização |
| **Reivindicação indevida** | precisa de prova de posse (§2.3) | **impossível** por construção | idem (b) | impossível "pegar" pasta alheia, mas **pastas órfãs** ficam sem dono |
| **Blast radius da chave** | **todos os clientes** | **1 cliente** | 1 cliente (se robô por org) | todos |
| **Cota da Drive API** | todos dividem o limite *por usuário* de uma única SA (a cota "325.000 por usuário/projeto" trata SA como **uma só conta**, [Usage limits](https://developers.google.com/workspace/drive/api/guides/limits)) | cada org tem seu próprio balde por usuário; só o teto do projeto (1.000.000/min) é comum | idem (b) | como (a) |
| **Feed de mudanças** | `changes.list` do robô traz mudanças de **todos** os clientes; cada org lê/filtra o feed alheio (metadados de A passam pela memória do worker de B; custo O(clientes²)) | feed **só da org** → o `discover()` atual funciona quase igual | idem (b) | como (a) |
| **UX do cliente** | 1 e-mail igual para todos (simples) mas com "prova de posse" extra | 1 e-mail por cliente (copiar/colar, sem passo extra) | e-mail "bonito" do nosso domínio; **resolve allowlist de Workspace** | zero passos de colar link, mas frágil |
| **Operação** | mínima (1 chave) | alta: provisionar/guardar N chaves; limite de contas de serviço por projeto | muito alta: Cloud Identity + Directory API + N robôs | média + fila de "órfãs" para humano |
| **Veredito** | **não recomendado em produção** | **recomendado** | **fase 2 opcional** (allowlist e troca de robô) | **só como ajuda de UX** dentro de (b) |

### 2.3 Se, mesmo assim, fosse 1 robô global (por que descartamos e como seria segura)

Caso o dono prefira (a) por simplicidade operacional, as defesas **obrigatórias** seriam:

1. **Índice único global** `folder_id` em vínculos *verificados* (um ID de pasta do Drive é globalmente único); org B recebe "esta pasta já está conectada a outra conta".
2. **Prova de posse por arquivo-desafio:** o ArquivIO gera `arquivio-verificacao-<código aleatório>`; o cliente cria um arquivo/documento com esse nome **dentro** da pasta; o robô o encontra por `files.list` — só quem **tem permissão de edição** consegue criar arquivo ali, então ler o link não basta. Atrito alto (passo extra, arquivo "sujo" na pasta do cliente).
3. **Sinal auxiliar `sharingUser`:** `files.get fields=sharingUser,sharedWithMeTime` devolve "o usuário que compartilhou o arquivo com o usuário solicitante" ([File resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)). Se o e-mail confere com um **membro ativo e verificado** da org que reivindica → verificação automática; senão → arquivo-desafio. Fraqueza: quem compartilhou pode não ser membro do ArquivIO (TI, secretária) ou usar outro e-mail.
4. **Nunca** usar `changes.list` global; um "roteador" confiável (§3.6) resolveria ancestralidade → vínculo, com testes de dois tenants.

Mesmo com tudo isso, (a) continua tendo **uma chave que abre todos os clientes** e cota única. É o tipo de risco que um laudo CASA/enterprise pergunta primeiro. Por isso a recomendação é (b).

### 2.4 Por que (c) sozinho não ajuda e (d) é só assistente

- **"sa+org@…" não existe:** *plus-addressing* é recurso de Gmail/Workspace; e-mail de conta de serviço não aceita sufixos. Um grupo `drive-acme@arquivio.com.br` é a forma de ter "um endereço por cliente" apontando para um robô.
- (c) com **um** robô global por trás volta a ser (a) (o Drive mostra só "compartilhado com o grupo X"; o robô não sabe qual grupo originou o acesso). Só faz sentido **1 grupo → 1 robô** (cliente) ou como **apelido do nosso domínio** para driblar o allowlist (§1.4). Exige domínio verificado no Cloud Identity/Workspace e Admin SDK; custo operacional não justifica antes de existir cliente com a restrição.
- (d): o e-mail de `sharingUser` é confiável (vem do Google, não é falsificável), mas **não identifica organização**: `@gmail.com` é comum a milhares de empresas; consultores compartilham para vários clientes; a pessoa que compartilha pode não ter conta no ArquivIO. Útil como **rótulo** ("compartilhada por maria@acme.com") e para auditoria, **não** como chave de decisão.

### 2.5 Recomendação final do mapeamento

> **(b) robô por organização, com vínculo explícito pasta↔org (a pasta que o cliente cola/confirma) e (d) apenas como ajudante de UX/auditoria. (c) vira fase 2 *se* aparecer cliente Workspace com allowlist. (a) fica descartado para produção.**

Regras de segurança derivadas:
- **Nunca reciclar um robô entre organizações.** Se a org A sai, o robô dela é *aposentado* (não volta para o pool): os compartilhamentos antigos no Drive do cliente A continuariam apontando para esse e-mail, e uma org nova que o recebesse herdaria o acesso. Cada robô tem 1 organização na vida (`UNIQUE` em `organization_id` + estado `retired` terminal).
- **Validar todo `folderId` colado** com regex antes de qualquer chamada. Hoje o código interpola o ID em `q` (`integrations/google_drive.py:325`, `f"'{folder_id}' in parents ..."`) porque os IDs vinham de `list_folders`; com ID digitado pelo usuário isso vira **injeção de consulta**. Obrigatório: `^[A-Za-z0-9_-]{10,128}$` e `q` montado só após validar.
- **Não seguir atalhos (shortcuts)**: `application/vnd.google-apps.shortcut` com `shortcutDetails` ([doc](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)) pode apontar para fora da pasta; ignorar (hoje já cai em "não elegível" por MIME, `ingestion/google_drive.py:312-313`); incluir teste.
- **Pasta "qualquer pessoa com o link"** é legível pelo robô sem ter sido compartilhada com ele. Aceitável (já é pública), mas rotular `verified_via="link_public"` e avisar o cliente, para não confundir com "compartilhei privadamente".
- **Mensagens iguais** para "não existe" e "sem acesso" (§1.3) — não vazar quais IDs existem.
- **Auditoria:** `AuditLog` (`backend/app/audit_usage/models.py`, usado em `oauth_base.py:131-139`) para: `drive_sa.enabled`, `drive_sa.folder_linked`, `drive_sa.folder_access_lost`, `drive_sa.folder_unlinked`, `drive_sa.key_rotated`, `drive_sa.retired` — com `actor_user_id`, `organization_id`, `folder_id` (não nome do arquivo).
- **Teste de isolamento obrigatório** em CI: duas orgs com dois robôs; B tenta vincular a pasta de A → resposta idêntica a "não compartilhada", nenhuma linha criada, nenhum conteúdo de A em respostas de B.

### 2.6 Escala: limite de robôs por projeto

- A página de cotas do IAM diz que o limite de **contas de serviço por projeto "varia conforme o projeto"** e manda consultar a cota **Service Account Count** no console; e que **cada conta de serviço tem no máximo 10 chaves (não alterável)** ([IAM quotas and limits](https://docs.cloud.google.com/iam/quotas)). O "~100" lembrado pelo dono é o padrão que costuma aparecer em projetos novos — **confira no console do projeto antes de dimensionar** [hipótese → PoC passo 12].
- Estratégia: tabela `google_sa_projects` (id do projeto, cota conhecida, ocupação) e **pool de robôs pré-criados** por projeto (script offline que o dono/devops roda: cria 50 robôs + 1 chave cada; o app só *atribui*). Vantagens: o aplicativo **não guarda credencial com poder de criar contas de serviço** (a credencial mais perigosa fica fora do runtime); o cliente nunca espera criação; e-mails com ID aleatório (`arq-<8 chars>`), sem nome do cliente.
- Regras: manter ≥ 10 robôs livres; alerta quando < 10; ao passar de ~70% de um projeto, criar outro projeto e pré-criar mais robôs. Pedir aumento de cota ao Google é alternativa (sem garantia).
- Aviso de ambiente: organizações Google Cloud criadas **a partir de 3/mai/2024** nascem com a política `iam.disableServiceAccountKeyCreation` ligada ([Secure by default organizations](https://cloud.google.com/resource-manager/docs/secure-by-default-organizations?hl=pt) — via resultado de busca, não li a página inteira). Se o projeto do ArquivIO está dentro de uma organização assim, será preciso **abrir exceção** de política para o projeto-pool. Conferir antes do PoC.

---

## 3. Como fica o sync

### 3.1 Princípio: reaproveitar o pipeline atual, trocar só a fonte de credencial

O pipeline de ingestão não muda: `GoogleDriveDocumentProvider.discover()` (`backend/app/ingestion/google_drive.py:64-230`) já faz snapshot completo → `changes.list` incremental com cursor cifrado por seleção → reconciliação em mudança de pasta; `GoogleDriveOAuthClient` (`integrations/google_drive.py:144-455`) já fala `files.list`/`changes.list`/`files.export`/`alt=media` com `supportsAllDrives`/`includeItemsFromAllDrives` (`:286-287,404-405`) e backoff (`integrations/http.py:20-110`). O que muda é **de onde vem o access token**:

| Hoje (OAuth) | Modo robô |
|---|---|
| `_current_credentials`/`_refresh_credentials` (`ingestion/google_drive.py:352-401`) decifra `{access, refresh, expires}` da `DataSource` e renova com `refresh_token` | novo `ServiceAccountTokenSource`: assina JWT (`iss=email do robô`, `scope=drive.readonly`, `aud=https://oauth2.googleapis.com/token`, `exp≤1h`) com a chave do robô e troca por access token via `urn:ietf:params:oauth:grant-type:jwt-bearer` ([Server to Server](https://developers.google.com/identity/protocols/oauth2/service-account)); **sem refresh token, sem expiração de 7 dias**. `pyjwt[crypto]` já é dependência (`backend/pyproject.toml:14`) — não precisa `google-auth` |
| `GoogleRefreshTokenInvalid` → `reauth_required` (`integrations/google_drive.py:45,209-210`) | falha de token do **robô** = problema nosso (alerta interno), **não** "reconectar" do cliente |
| 401/403 genérico → `GoogleRemoteUnauthorized` → fonte `reauth_required` (`integrations/google_drive.py:128-141`, `ingestion/tasks.py:696-710`) | precisa **distinguir**: 404/403 na **pasta raiz** = `access_lost` (vínculo); 403 por arquivo = item bloqueado; falha de token = alerta ops |

Cache do token: um access token por robô (≈ 55 min), guardado em Redis (já usado como broker, `settings.redis_url`) com TTL, para não bater no endpoint de token a cada tarefa/worker.

### 3.2 Listagem, arquivos novos e mudanças

- **Primeira sincronização:** `start_page_token` + `list_folder_files` (BFS por `'<id>' in parents`, `integrations/google_drive.py:249-260,309-349`) já funciona sobre o que o robô enxerga.
- **Incremental:** `changes.list` do robô. Como o robô é da org, o feed contém **só** o que ela compartilhou — o `in_scope` por seleção (`ingestion/google_drive.py:128-140`) continua a barreira final. **[hipótese → PoC]**: mudanças em *filhos* de pasta compartilhada aparecem no feed do robô (esperado, pois ele tem acesso por herança; o PoC `drive.file` não vale aqui porque aquele escopo é por-app, não por-compartilhamento).
- **Plano B se o feed não trouxer filhos:** varredura por `files.list q="modifiedTime > '<último ciclo − 5 min>' and trashed=false"` na conta do robô (consulta única por ciclo; `modifiedTime` é otimizado para isso, [doc](https://developers.google.com/workspace/drive/api/guides/search-files)) + reconciliação completa diária para pegar remoções/movimentações.
- **Novos arquivos:** aparecem no próximo ciclo (Celery beat a cada 15 min, `ingestion/tasks.py:61-91`; `changes.watch` continua opcional, §3.3 do review).
- **`root_files` e `all_accessible`:** `'root' in parents` (`:354`) é o "Meu Drive" **do robô** (vazio). Em modo robô, `root_files` fica `available:false` e `all_accessible` pode virar "Tudo que foi compartilhado com o ArquivIO" (útil: o cliente só compartilha e tudo entra), mas o padrão é pastas explícitas (menor surpresa).

### 3.3 Drives compartilhados (Shared Drives)

Compartilhar uma pasta de Shared Drive individualmente nem sempre é possível; o caminho é **adicionar o robô (ou grupo) como membro do drive compartilhado**, papel Leitor/Comentador (orientação vinda do guia de terceiros já citado em `drive-alternatives.md` §2; não confirmada em página oficial). O código já passa `supportsAllDrives`/`includeItemsFromAllDrives`. **[hipótese → PoC passo 6]**: `changes.list` sem `driveId` inclui itens de drives dos quais o robô é membro; se não, usar `drives.list` + `changes.list?driveId=` por drive (hoje não há `drives.list`, `google-drive-deploy-review.md` §3.5). Pontos de UX: no "Passo 1" mostrar uma aba "Drive compartilhado" com instruções ("Gerenciar membros → adicionar → Leitor"), e o configurador de drive compartilhado pode bloquear download por leitores (mesmo erro `cannotDownloadFile`).

### 3.4 Gmail pessoal × Workspace

| | Gmail pessoal | Workspace |
|---|---|---|
| Compartilhar com e-mail de conta de serviço | funciona (uso comum em integrações; **confirmar no PoC**) | funciona **se** a política permitir compartilhar externamente; **domínios de conta de serviço não podem ser "permitidos"** (§1.4) |
| Admin | ninguém bloqueia | TI pode bloquear; fornecer texto pronto + fase 2 (grupo) |
| Shared Drives | não existe | sim, robô como membro |
| Visibilidade para o cliente | no Drive: "Compartilhado com arq-xxxx@…" | idem + **log de auditoria do Drive** do admin pode mostrar acessos do robô **[hipótese → PoC]** (argumento de transparência) |

### 3.5 Quando o cliente remove o compartilhamento (poda)

Remover o compartilhamento é, na prática, **um pedido de revogação**. Fluxo proposto:

1. Sync detecta 404 na raiz do vínculo (ou `removed`). Marca `suspect` e **repete em ≥1 h** (evita 404 transitório).
2. Confirmado → vínculo `access_lost`; **para o sync imediatamente** e notifica os admins (sino em `NotificationFollowedQuery`/notificações existentes, migração `0028`).
3. **Conteúdo indexado:** recomendação — **ocultar imediatamente** dos resultados do chat/busca (status do vínculo/`WorkspaceFolder.status`, mesmo mecanismo das exclusões da biblioteca, migração `20260930_0019_library_exclusions.py`) e **apagar definitivamente após 14 dias** se o acesso não voltar, ou na hora pelo botão "Apagar agora". Se o cliente recompartilhar dentro de 14 dias, reativa com snapshot completo (cursor zerado).
4. Texto da política de privacidade e do RFQ (§3.2 item 7) devem refletir: "remover o compartilhamento interrompe a leitura; apagamos o conteúdo em até 14 dias".
5. Remoção de **um arquivo** dentro da pasta já é tratada (`removed_file_ids`, `ingestion/google_drive.py:159-165,205-216`).

> Decisão em aberto para o dono: 14 dias vs. apagar na hora (§6).

### 3.6 Cotas, backoff e escala

- Cada robô tem balde próprio "por usuário" (SA conta como uma conta, [Usage limits](https://developers.google.com/workspace/drive/api/guides/limits)); o teto do **projeto** (1.000.000 unidades/min) é compartilhado pelos robôs do pool. Para dezenas de clientes com ciclo de 15 min, o consumo fica muito abaixo; medir no PoC (passo 10).
- Backoff já existente: até 5 tentativas, jitter, teto 30 s, `Retry-After`, bloqueio compartilhado entre threads (`integrations/http.py:20-110`) e 403 de cota como retentável (`integrations/google_drive.py:99-100,124-125`). Em modo robô, **não** transformar 403 desconhecido em `reauth` (hoje `:140`): classificar por `reason`.
- Limite de concorrência por robô: ≤3 downloads simultâneos (já `MAX_EXTRACTION_WORKERS=3`, `ingestion/google_drive.py:36`).
- Evolução (só se a escala pedir): `changes.list` **uma vez por robô por ciclo** distribuído entre seleções (hoje 1 token por seleção, `ingestion/google_drive.py:78-82,145-153`; sugestão do review §3.3).

### 3.7 Chaves: armazenamento, rotação e operação

- **Armazenamento:** `encrypted_key` (JSON da chave) cifrada com Fernet usando chave **própria** `GOOGLE_SA_KEY_ENCRYPTION_KEY` (nova entrada em `Settings.cipher_keys`, `backend/app/core/config.py:166-176`, e no validador de chaves distintas `:178-190`), com `MultiFernet` para rotação (`integrations/keyring.py`). Alternativa de endurecimento (fase 3): **envelope com Cloud KMS** (a chave-mestra nunca sai do KMS; Railway só vê data keys) — faz sentido porque a infraestrutura de robôs já está no Google Cloud.
- **Rotação:** a cada 90 dias ou sob suspeita: criar nova chave (máx. 10 por robô, [IAM quotas](https://docs.cloud.google.com/iam/quotas)), gravar `key_version+1`, validar com `about.get`, apagar a antiga. Em comprometimento: desativar o robô, **aposentar** (§2.5), atribuir outro à org e **pedir recompartilhamento** — por isso o grupo (fase 2) é interessante.
- **Segredo mais valioso:** a credencial que *cria* robôs (se houver automação) — por isso a recomendação do **pool pré-criado** (§2.6) mantém essa credencial fora do app.
- **Logs:** nunca logar chave, JWT, token nem corpo de erro do Google (padrão já seguido, `integrations/google_drive.py:526-531`).
- **Alertas ops:** falha de token de robô, robô com muitos `access_lost`, pool < 10 livres.

---

## 4. Coexistência com o OAuth atual e impacto em Google/CASA

### 4.1 Coexistência

- **Manter o OAuth como segunda opção.** Dois providers distintos: `google_drive` (atual) e novo `google_drive_sa`. Evita misturar semânticas (token do usuário × robô) e simplifica a flag. Registro: nova entrada em `IntegrationRegistry._factories` (`backend/app/integrations/registry.py:235-241`) e novo ramo em `get()` (`:246`) que passa `session`/`source_id` (como já faz para `google_drive`, `:247`).
- **Feature flag em dois níveis:** `GOOGLE_SA_ENABLED` (env; global) + lista de organizações habilitadas (`GOOGLE_SA_ALLOWED_ORGS`) para rollout por cliente-piloto. Sem a flag, nada novo aparece na UI.
- **Migração dos clientes atuais:** **não forçar.** Hoje há poucos; oferecer botão opcional "Trocar para pasta compartilhada" que cria o robô, mantém `WorkspaceFolder`/documentos e **reinicia cursores** (mesmo mecanismo de troca de conta, `integrations/google_drive.py:617-640`), com revogação do token OAuth antigo (`_before_disconnect`, `:514-532`). Só vale a pena depois do PoC e de resposta do Google.
- **Uma org pode ter os dois** (fontes diferentes); a UI hoje escolhe uma `primary` única (`integrations-screen.tsx:116`) → precisa listar por modo.
- **Reuso:** `WorkspaceFolder`/`WorkspaceFolderSelection` (`workspaces/models.py:10,39`) e `WorkspaceService.select_scope` (`workspaces/service.py:78`) ficam como estão: o vínculo verificado cria uma seleção `kind='folder'`.

### 4.2 Verificação Google / CASA — o que muda e o que NÃO muda

Fatos **[doc]**: escopos restritos (como `drive.readonly`) exigem verificação + avaliação de segurança para apps que acessam dados "de ou através de servidor de terceiros"; isenções são uso pessoal, dev/teste, dados do próprio serviço, uso interno e instalação em todo o domínio (só marca) ([Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)). Esse processo é descrito para apps que **solicitam escopos ao usuário via OAuth**. Uma conta de serviço **não tem tela de consentimento** e a política de dados do usuário é redigida para "solicitar acesso a dados de usuário" via autorização, **sem mencionar contas de serviço** ([API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)).

Leitura honesta: **zona cinzenta por silêncio** (mesma conclusão de `drive-alternatives.md` §2). Detalhes que merecem atenção específica:
- O robô pede o escopo `drive.readonly` no JWT (necessário para ler arquivos compartilhados por terceiros; `drive.file` só vale para arquivos criados pelo próprio app, por isso é inútil aqui). Um revisor pode argumentar que "escopo restrito + dados de terceiros em servidor nosso" = CASA, independentemente de ser OAuth. Não há texto que diga o contrário nem que confirme.
- Atenuantes reais: o cliente escolhe pasta a pasta (menor privilégio do que o `drive.readonly` global do OAuth); acesso revogável a qualquer instante por ele; chave isolada por cliente.
- **Pergunta formal (recomendada):** enviar ao suporte do Google (Cloud Support e canal de verificação OAuth do Console) e **guardar a resposta por escrito**. Rascunho:

> *"Our B2B product lets each customer share specific Google Drive folders (read-only) with a dedicated Google service account owned by us. We read only those folders using the Drive API, with the `https://www.googleapis.com/auth/drive.readonly` scope obtained through the service-account JWT bearer flow; no end-user OAuth consent flow is involved, and we apply the Limited Use requirements in practice. Does this access pattern require OAuth app verification and a security assessment (CASA) for the restricted scope, or is it outside that program? If a security assessment is required, which tier applies?"*

- **Também perguntar ao laboratório CASA** (na cotação) se o fluxo por conta de serviço entra no escopo da avaliação — o auditor pode querer cobrir a gestão de chaves de qualquer jeito.

### 4.3 O que muda no `casa-rfq.md` (se adotarmos o modo robô)

| Seção do RFQ | Hoje | Alteração |
|---|---|---|
| §3.1 Escopos (`casa-rfq.md:29-37`) | só OAuth `drive.readonly` | acrescentar linha: "Service-account JWT bearer, scope `drive.readonly`, **sem consentimento do usuário**; cliente compartilha pasta com e-mail dedicado" e posição do dono sobre inclusão no escopo |
| §3.2 Fluxos (`:39-47`) | consentimento → tokens | novo fluxo: atribuição de robô, compartilhamento pelo cliente, verificação, assinatura de JWT, cache de token, poda ao perder acesso, **retenção 14 dias** |
| §3.3 Componentes | token store cifrado | acrescentar **armazenamento/rotação de chaves de robô** (Fernet dedicado ou KMS), pool de robôs, projeto(s) GCP dedicados |
| §3.4 Autorização | admin da org | "somente Owner/Admin habilitam e vinculam pastas; isolamento por robô por org; testes automatizados de isolamento entre tenants" |
| §4 Controles | Fernet + `state` OAuth | inventário de chaves, rotação 90 d, alerta de acesso, auditoria `drive_sa.*` |
| Decisão estratégica | "CASA obrigatório" | **se** o Google responder "fora do programa" para o modo robô e **se** o produto lançar *só* com ele, o OAuth público deixa de existir e o CASA deixa de ser requisito de lançamento; **enquanto não houver resposta escrita, manter RFQ e cotação** |

**Não presumir isenção.** Plano em duas trilhas: (1) lançar o modo robô para pilotos B2B com contrato e transparência; (2) manter o processo OAuth/CASA vivo até a resposta do Google chegar. Se a resposta for desfavorável, o custo foi 1 semana de engenharia reaproveitável (a fonte de credencial é isolada, §3.1).

---

## 5. Plano de implementação

### 5.1 Modelo de dados (migração Alembic `20261014_0032_drive_service_accounts.py`, `down_revision = "20261013_0031"` — cabeça atual: `backend/alembic/versions/20261013_0031_webhooks.py`)

Tabelas novas:

```text
google_sa_projects            -- projetos GCP do pool
  id uuid pk · gcp_project_id text unique · sa_quota int · created_at

google_sa_identities          -- um robô; 1 organização na vida
  id uuid pk
  project_id fk google_sa_projects
  sa_email text unique not null
  encrypted_key text not null            -- JSON da chave, Fernet(GOOGLE_SA_KEY_ENCRYPTION_KEY)
  key_version int not null default 1
  status text  ck IN ('free','assigned','retired','compromised')
  organization_id uuid null fk organizations  UNIQUE (parcial: where organization_id is not null)
  group_email text null                  -- fase 2 (alias do nosso domínio)
  assigned_at · rotated_at · retired_at · created_at

drive_folder_links            -- vínculo pasta↔org (a "prova" do que foi autorizado)
  id uuid pk
  organization_id fk · data_source_id fk data_sources
  workspace_folder_id fk workspace_folders null
  external_folder_id text(128) not null
  folder_name text · is_shared_drive bool
  status text ck IN ('pending','verified','suspect','access_lost','purge_scheduled','removed')
  verified_via text ck IN ('visible_to_org_robot','link_public')
  shared_by_email text null · shared_at timestamptz null    -- sharingUser / sharedWithMeTime
  blocked_download_count int default 0
  suspect_since · access_lost_at · purge_after · last_checked_at · last_error_code
  created_by_user_id fk users · created_at
  UNIQUE (organization_id, external_folder_id)
  INDEX (external_folder_id)             -- só para detectar a mesma pasta em duas orgs (alerta, não bloqueio)
```

Coluna nova em `data_sources` (`integrations/models.py:20-41`): `sa_identity_id uuid null fk google_sa_identities` + índice único parcial "uma fonte `google_drive_sa` por organização" (modelo igual ao índice SharePoint, `models.py:33-40`). Novos status de fonte: `awaiting_share` (habilitado, sem pasta verificada) e `provider_error` (problema do robô).

Config (`core/config.py:100-103`): `GOOGLE_SA_ENABLED`, `GOOGLE_SA_KEY_ENCRYPTION_KEY`, `GOOGLE_SA_ALLOWED_ORGS`.

### 5.2 Backend — o que muda (arquivo:linha)

| Fase | Mudança | Onde |
|---|---|---|
| F1 | `ServiceAccountTokenSource` (JWT bearer, cache Redis), `SaDriveClient` herdando/compondo `GoogleDriveOAuthClient` só para os métodos de leitura (`list_folders :230`, `start_page_token :249`, `get_file :262`, `changes :277`, `list_folder_files :309`, `export_pdf :413`, `read_file :430`) sem os de OAuth (`authorization_url :159`, `exchange_code :173`, `refresh_access_token :192`) | novo `backend/app/integrations/google_drive_sa.py` |
| F1 | Classificação de erros por `reason` para SA: `FolderAccessLost` (404/403 na raiz), `ItemForbidden` (por arquivo, já existe), `RobotUnavailable` (token). Não reaproveitar o `raise ... GoogleRemoteUnauthorized` genérico de `:140` | `integrations/google_drive_sa.py`; `integrations/errors.py` |
| F1 | Adapter `GoogleDriveSaProviderAdapter` (`capabilities`: `supports_oauth=False`) e registro | `integrations/registry.py:18-67` (modelo), `:233-247` |
| F1 | Provider de ingestão: parametrizar `GoogleDriveDocumentProvider` com fonte de credencial injetável (substitui `_current_credentials/_refresh_credentials`, `ingestion/google_drive.py:352-401`) | `ingestion/google_drive.py` |
| F1 | Tratar `FolderAccessLost` sem marcar a fonte inteira como `reauth_required` | `ingestion/tasks.py:696-710` |
| F1 | Modelos + migração + cifra da chave | `integrations/models.py`, novo `integrations/google_sa_models.py`, `alembic/versions/20261014_0032_…py`, `core/config.py:166-190` |
| F1 | Serviço `DriveSaConnectionService` (habilitar/atribuir robô do pool, verificar link, vincular, desvincular) com `require_admin` (`oauth_base.py:28`) e `AuditLog` | novo `integrations/google_drive_sa_service.py` |
| F2 | Rotas (abaixo) | `backend/app/api/integrations.py` (padrão das rotas, `:77-81`, `:428-500`, `:535-556`) ou novo `api/drive_sa.py` incluído em `main.py` |
| F2 | `scope-catalog`/`select_scope` com ramo `google_drive_sa` (`root_files` indisponível) | `api/integrations.py:604-704`, `:739-821` |
| F3 | Poda: job diário que confirma `suspect` → `access_lost` → `purge_scheduled` → apaga; ocultação imediata | `ingestion/tasks.py` (beat, `:61-80`); `workspaces/service.py` |
| F3 | Rotação de chave, alertas, métricas, script de pool (`scripts/` fora do runtime) | `scripts/drive_sa_pool.py`, observabilidade existente |
| F4 (opcional) | Grupo/alias do nosso domínio (Directory API) e KMS | novo módulo |

**Endpoints (todos com `organization_id`, Owner/Admin):**

| Método e rota | Função |
|---|---|
| `POST /data-sources/google-sa/enable` | atribui robô à org, cria `DataSource(provider="google_drive_sa", status="awaiting_share")`, devolve `{source_id, robot_email, share_role:"reader"}` |
| `GET /data-sources/google-sa/{source_id}/inbox` | pastas `sharedWithMe` no robô da org (`id, name, shared_by_email, shared_at, linked`) — rate-limit por org |
| `POST /data-sources/google-sa/{source_id}/folders/verify` `{url_or_id}` | valida regex, `files.get` (`fields=id,name,mimeType,trashed,capabilities(canDownload),sharingUser,sharedWithMeTime,driveId`), amostra de download, contagem; resposta com `code` estável (`not_shared`, `not_a_folder`, `download_blocked_partial`, `ok`) |
| `POST /data-sources/google-sa/{source_id}/folders` `{folder_id}` | cria `drive_folder_links` (`verified`) e a seleção em `workspace_folders` |
| `DELETE /data-sources/google-sa/{source_id}/folders/{link_id}` | desvincula; `?purge=true` apaga conteúdo na hora |
| `POST /data-sources/google-sa/{source_id}/recheck` | força nova checagem de acesso |
| `DELETE /data-sources/{source_id}` (existente, `:535`) | no modo robô **aposenta** o robô e agenda remoção da chave; ramo em `disconnect_source` (`:549-556`) |

Respostas de erro: **mesmo corpo e mesmo status** para "não existe" e "sem acesso" (§2.5).

### 5.3 Frontend

| Mudança | Onde |
|---|---|
| Modal de método (Tela 0) e fluxo em 3 passos (Telas 1–4) como componente novo | novo `frontend/app/product/drive-share-flow.tsx`; gancho no `ToolsCatalog` (`integrations-screen.tsx:113-119`) e no `connect()` (`:41`) |
| Listagem de fontes passa a distinguir modo (hoje `primary` único, `:116`) e `statusLabel` ganha `awaiting_share`/`access_lost`/`provider_error` | `integrations-screen.tsx:116-119` |
| Reaproveitar o modal de escopo (`loadCatalog`, `:46`) | sem mudança estrutural |
| Biblioteca: badge "acesso removido" / "apagando em N dias" | `frontend/app/product/` (tela de biblioteca; `library-view-logic.ts`) |
| Polling do inbox (5 s, 5 min, retomar) reutiliza padrão de polling já usado em `:35-39` | `drive-share-flow.tsx` |
| Textos legais: privacidade e termos (modo robô, retenção, revogação) | `frontend/app/privacidade/page.tsx`, `termos/page.tsx` |

### 5.4 Testes (TDD, antes do código de cada fase)

- **Isolamento (crítico):** 2 orgs / 2 robôs — org B tenta `verify` na pasta de A → `not_shared`, nenhuma linha em `drive_folder_links`, nada de A em resposta/log de B; um robô nunca é atribuído a 2 orgs (constraint + teste de concorrência com `SELECT … FOR UPDATE SKIP LOCKED`); robô aposentado nunca volta ao pool.
- **Validação de entrada:** regex de ID; URLs variantes (`/drive/folders/`, `/drive/u/0/folders/`, `open?id=`, `file/d/`, link de Drive compartilhado); tentativa de injeção em `q`.
- **Classificação de erros:** tabela 404/403(reason)/401 → `FolderAccessLost`/`ItemForbidden`/`RobotUnavailable`; `access_lost` só após 2 checagens ≥1 h; recompartilhamento reativa.
- **Token source:** JWT bem formado, expiração, cache Redis, falha de token não vira `reauth_required`.
- **Poda:** ocultação imediata, expurgo em 14 dias, "apagar agora".
- **Shortcut/anyone-with-link:** atalho não é seguido; vínculo `link_public` rotulado.
- **Regressão OAuth:** suíte atual de `google_drive` continua verde (a flag desligada não altera nada).
- **Frontend:** testes de lógica do fluxo (estados, mensagens por `code`), a11y do botão copiar (`aria-live`), mobile.
- **Smoke manual:** conta Gmail e conta Workspace de teste (§7).

### 5.5 Estimativa

| Fase | Conteúdo | Dias de eng. |
|---|---|---|
| F0 | **PoC isolado** (§7) | 1 |
| F1 | Núcleo: modelos/migração, token source, cliente, adapter, erros, ingestão com credencial injetável | 4–5 |
| F2 | Serviço + rotas + UI dos 3 passos + inbox + mensagens de erro | 4–5 (back 2, front 2–3) |
| F3 | Poda/retenção, rotação de chave, alertas, auditoria, script de pool, docs/política/RFQ | 3 |
| F4 (opcional) | Grupo/alias de domínio, KMS, pool automático | 4–5 |
| **MVP (F0–F3)** | | **≈ 12–14 dias** (a estimativa de 4–7 dias em `drive-alternatives.md` §2 cobria só o código do conector, sem UI de 3 passos, poda, pool e auditoria) |

---

## 6. Riscos e perguntas em aberto (decisão do dono)

| # | Pergunta/risco | Recomendação |
|---|---|---|
| 1 | **1 robô global (simples) ou 1 por empresa (seguro)?** | **Por empresa**, com pool pré-criado. Vazamento entre clientes é o risco máximo; o isolamento vem do Google. |
| 2 | **Zona cinzenta com o Google/CASA.** Aceitamos lançar o modo robô sem resposta escrita? | Enviar a pergunta (§4.2) **antes** do lançamento; manter CASA/RFQ em paralelo; lançar só para pilotos com contrato. Reavaliar quando a resposta chegar. |
| 3 | **Clientes Workspace com allowlist** (não conseguem compartilhar com `gserviceaccount.com`). | Texto para o TI + alternar para OAuth no curto prazo; **fase 2** com grupo `@arquivio.com.br` se aparecer demanda (precisa PoC antes de prometer). |
| 4 | **Retenção ao remover compartilhamento:** 14 dias ou apagar na hora? | Ocultar na hora, apagar em 14 dias (com "apagar agora"). Se o dono quiser a promessa mais forte ("revogou, sumiu"), usar 0 dias e perder a janela de recuperação. |
| 5 | **Quem pode vincular pastas:** só Owner/Admin ou também membros? | Só Owner/Admin (igual hoje). A pessoa que sai da empresa **não** invalida o acesso (diferente do OAuth, onde o token morria com ela) — avisar no onboarding: "o acesso é controlado pelo compartilhamento no Drive; para encerrar, remova o e-mail do robô". |
| 6 | **Cota de robôs por projeto / política de chaves da organização Google Cloud.** | Conferir `Service Account Count` e a política `iam.disableServiceAccountKeyCreation` **antes** de qualquer código (§2.6). Se bloqueada, abrir exceção só no projeto-pool. |
| 7 | **Migrar clientes atuais do OAuth?** | Não forçar; botão opcional pós-PoC. |
| 8 | **Pasta "qualquer pessoa com o link" lida sem compartilhamento explícito.** | Aceitar com rótulo e aviso; ou bloquear no MVP para evitar dúvida jurídica. Sugestão: **bloquear no MVP** (só pastas que aparecem em `sharedWithMe`), liberar depois. |
| 9 | **Chaves no Railway (Fernet) × KMS.** | MVP com Fernet dedicado + rotação; KMS na fase 4 ou quando um cliente/CASA exigir. |
| 10 | **Marca/UX:** e-mail do robô mostra `…iam.gserviceaccount.com` (desconfiança). | Aceitável no MVP com explicação; alias `@arquivio.com.br` (fase 2) melhora confiança e resolve allowlist. |
| 11 | **Mudanças não aparecem no feed do robô** (hipótese do §3.2). | PoC decide; plano B de varredura por `modifiedTime` já descrito. |
| 12 | **Concorrência com upload direto** (alternativa 5 do `drive-alternatives.md`) | Independentes; upload continua sendo o conector sem Google recomendado em paralelo. |

---

## 7. PoC de 1 dia — validar antes de escrever código

Local sugerido: `spikes/drive-service-account/` (mesmo padrão de `spikes/drive-file-picker/`), script curto em Python usando `pyjwt` + `httpx` (já dependências). **Entregável:** `specs/google/drive-service-account-poc-result.md` com tabela "hipótese → resultado → evidência (JSON)". Contas necessárias: 1 Gmail pessoal, 1 Workspace de teste (trial) — idealmente com uma org Workspace onde se possa ligar "bloquear compartilhamento externo" e "só domínios permitidos".

| # | O que medir | Critério de sucesso |
|---|---|---|
| 1 | Criar projeto-pool, ativar Drive API, criar 2 robôs (A e B) e 1 chave cada; **conferir cota `Service Account Count` e a política de chaves da organização** | chaves criadas (ou política bloqueia → anotar a exceção necessária); número real de robôs permitidos |
| 2 | Token via JWT bearer com `drive.readonly`: latência, validade, comportamento com relógio/clock skew | token em < 1 s; 1 h de validade |
| 3 | No Gmail pessoal: compartilhar pasta com e-mail do robô A pela UI (com "notificar" ligado e desligado); **tempo até o robô enxergar** | 200 em `files.get`; atraso medido (s) |
| 4 | `files.get` na pasta: `sharingUser`, `sharedWithMeTime`, `capabilities.canDownload`, `owners`; `files.list q=sharedWithMe`; **quais campos vêm preenchidos para um Leitor** (`permissions` não deve vir, [doc](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)) | `sharingUser.emailAddress` presente em pasta de topo; `sharedWithMe` lista a pasta e **não** lista filhos |
| 5 | Isolamento: robô B faz `files.get` da pasta compartilhada só com A; e com pasta "qualquer pessoa com o link" | B → 404 idêntico a ID inexistente; registrar status/`reason` exatos |
| 6 | **Feed de mudanças:** `startPageToken` do robô A → criar/alterar/mover/apagar arquivos em pasta e subpasta (por outro usuário) → `changes.list`; medir latência até aparecer e se vem `file` com `parents`; remover compartilhamento → tempo até 404 e se o feed marca `removed` | filhos novos aparecem no feed do robô; senão validar plano B (`modifiedTime`) |
| 7 | Conteúdo: `alt=media` (PDF, DOCX), `files.export` (Doc→text/plain, Sheet→xlsx, Slide→pptx), arquivo > 10 MB export; **pasta com "impedir leitores de baixar/copiar" ligado** → `reason` real | mapeia em `ITEM_FORBIDDEN_REASONS` (`integrations/google_drive.py:103-105`) |
| 8 | Drive compartilhado (Workspace): robô como membro Leitor; `changes.list` sem e com `driveId`; `supportsAllDrives` | itens aparecem; definir se precisa `drives.list` |
| 9 | **Workspace restritivo:** (i) bloquear compartilhamento externo → o que a UI do Drive mostra ao digitar o e-mail do robô; (ii) "só domínios permitidos" sem `gserviceaccount.com` → rejeita? | confirma a limitação do §1.4 e o texto de erro para o TI |
| 10 | **Grupo:** criar grupo `drive-teste@dominio` (Cloud Identity Free ou Workspace) com o robô como membro; compartilhar pasta com o grupo; o robô enxerga? aparece em `sharedWithMe`? o allowlist aceita o domínio? | decide viabilidade da fase 2 |
| 11 | Cota/consumo: sync de árvore sintética (~1.000 arquivos, 50 pastas): nº de chamadas, tempo, 403/429; simular 20 orgs × ciclo de 15 min | folga ≥ 10× sobre os limites de [Usage limits](https://developers.google.com/workspace/drive/api/guides/limits) |
| 12 | Auditoria do lado do cliente: o **log de auditoria do Drive** do admin Workspace mostra os acessos do robô? | sim/não (argumento de transparência) |
| 13 | Parser de links: formatos reais (`/drive/folders/…`, `/u/0/`, `open?id=`, link de arquivo, atalho, Meu Drive vs Drive compartilhado) | regex cobre todos; resto → `not_a_folder` |

Se os passos **3, 4, 5 e 6** passarem, a arquitetura (b) está validada; **9** e **10** decidem se a fase 2 existe; **1** pode mudar a logística do pool.

---

## 8. Não coberto / limites

- Nenhuma chamada real ao Google foi feita aqui: o comportamento do robô com pastas compartilhadas (visibilidade de filhos no feed, 404 vs 403, Shared Drives, grupo como membro) é **hipótese** até o PoC; pontos marcados.
- A cota padrão de contas de serviço por projeto **não foi confirmada** (a página oficial só diz que varia, [IAM quotas](https://docs.cloud.google.com/iam/quotas)); o limite de 10 chaves por robô foi lido na mesma página. A política de chaves "secure by default" vem de resultado de busca ([Secure by default organizations](https://cloud.google.com/resource-manager/docs/secure-by-default-organizations?hl=pt)), não de leitura integral.
- Não li `workspaces/service.py` nem `ingestion/tasks.py` por inteiro (reenfileiramento em `RemoteThrottled` etc.), nem todos os testes do conector; as âncoras de ingestão vêm das linhas citadas.
- Não há definição jurídica do Google sobre o modo robô; o texto de §4 é leitura da documentação pública, **não parecer legal**.
- O frontend foi lido só na região de integrações (`integrations-screen.tsx:20-46,113-119`); a tela de Biblioteca e as mensagens de a11y precisam ser vistas na implementação.
- Nada alterado em código, prd, ADR ou PRD; sem commit.

## Fontes

- [Drive API: File resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/files) — `sharingUser`, `sharedWithMeTime`, `permissions` (só quem pode compartilhar), `capabilities.canDownload`, `copyRequiresWriterPermission`, `shortcutDetails`.
- [Search for files and folders](https://developers.google.com/workspace/drive/api/guides/search-files) — `sharedWithMe`, `modifiedTime`, `corpora`.
- [Drive API usage limits](https://developers.google.com/workspace/drive/api/guides/limits) — cota por projeto/usuário e SA como uma conta.
- [Drive API: Resolve errors](https://developers.google.com/workspace/drive/api/guides/handle-errors)
- [IAM quotas and limits](https://docs.cloud.google.com/iam/quotas) — contas de serviço por projeto variam; 10 chaves por conta de serviço.
- [Allow external sharing with only trusted domains](https://support.google.com/a/answer/6160020?hl=en) — domínios `gserviceaccount.com` não podem ser permitidos.
- [Secure by default organizations](https://cloud.google.com/resource-manager/docs/secure-by-default-organizations?hl=pt) — `iam.disableServiceAccountKeyCreation` em organizações novas (via busca).
- [Using OAuth 2.0 for Server to Server Applications](https://developers.google.com/identity/protocols/oauth2/service-account)
- [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
- Internas: [`drive-alternatives.md`](drive-alternatives.md), [`drive-file-poc-result.md`](drive-file-poc-result.md), [`google-drive-deploy-review.md`](google-drive-deploy-review.md), [`casa-rfq.md`](casa-rfq.md).
