# Pergunta formal ao Google: modo "e-mail-robô" (service account) do ArquivIO

Data: 2026-10-14 · **Rascunho, nada foi enviado** · Sem commit · Contexto: [`drive-service-account-design.md`](drive-service-account-design.md) §4.2 e [`drive-alternatives.md`](drive-alternatives.md) §2.

---

## PARA O DONO (PT-BR): por onde enviar

**Resumo.** Não existe um canal público único do Google para "essa arquitetura exige CASA?". Os canais abaixo foram verificados em páginas oficiais (14/10/2026). A recomendação é um **caso no Google Cloud Customer Care**, se o plano pago valer o custo de 1 mês, mais uma **pergunta pública sem dados sensíveis** no Stack Overflow como alternativa gratuita. Nenhum canal garante resposta escrita vinculante; guarde qualquer resposta (PDF/e-mail) para o dossiê CASA.

| # | Canal | Serve para esta pergunta? | Custo / requisito | Observação verificada |
|---|---|---|---|---|
| 1 | **Google Cloud Customer Care: caso de suporte** (console Cloud → Support) | **Sim, é o mais adequado**: pergunta de política/uso de produto sobre um projeto Cloud, com resposta por escrito ligada ao caso | O Basic é gratuito e a página oficial só garante **suporte de cobrança**; o Standard é pago e abre casos técnicos (resposta P2 em 4 h). A página oficial **não deixa claro** se o Basic abre caso técnico; fontes de terceiros dizem que não. Criar caso exige o papel IAM **Tech Support Editor** (`roles/cloudsupport.techSupportEditor`) no projeto/organização. **Confirme no console** se o botão "Create case" aparece antes de assinar. Preço atual: ver a tabela em cloud.google.com/support (não consegui ler a tabela; um terceiro cita US$ 29/usuário/mês + 3% do consumo, a verificar) | [Getting support](https://docs.cloud.google.com/docs/get-started/getting-support) · [Create and manage cases](https://docs.cloud.google.com/support/docs/customer-care-procedures) · [Compare packages](https://cloud.google.com/support) |
| 2 | **Resposta ao e-mail da equipe de verificação OAuth** (só existe se o app já estiver em processo de verificação) | Sim, **se** houver uma thread ativa de verificação do projeto | Grátis. A FAQ oficial **não oferece formulário de contato**: a rota é "responder diretamente ao último e-mail" da equipe de verificação. Para problemas de service account/IAM, a própria FAQ manda ao Cloud Support. Relatos de terceiros dizem que as respostas são lentas e nem sempre vêm | [OAuth Application Verification FAQ](https://support.google.com/cloud/answer/13463817?hl=en) |
| 3 | **Google Workspace support / Customer Care Portal** | **Fraco**: só administradores de Workspace pagantes; cobre APIs "centrais" do Workspace, não consulta de política do Google Cloud/OAuth | Exige ser admin de um Workspace com plano que inclua suporte | [Contact Google Workspace support](https://knowledge.workspace.google.com/admin/support/contact-google-workspace-support) · [Developer support](https://knowledge.workspace.google.com/admin/support/developer-support) · [Workspace developer support](https://developers.google.com/workspace/support) |
| 4 | **Stack Overflow, tag `google-drive-api`** (alternativa pública, sem dados sensíveis) | Parcial: a comunidade pode apontar documentação, mas **não é resposta oficial do Google** | Grátis. A página de suporte da Drive API lista essa tag, o fórum "Google Workspace Developers" e o Issue Tracker (componente 191650) | [Drive API support](https://developers.google.com/drive/v3/web/support) · [Tag google-drive-api](https://stackoverflow.com/questions/tagged/google-drive-api) · [Fórum Google Workspace Developers](https://discuss.google.dev/c/google-workspace/20) · [Issue Tracker Drive](https://issuetracker.google.com/issues?q=componentid:191650%2B) |
| 5 | **Não existe formulário público de "contato com Políticas de API Services"** | n/a | A [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy) **não lista contato nem e-mail de conformidade**; a página de Workspace support também não tem formulário geral de contato para desenvolvedores | Por isso a rota realista é o caso Cloud (#1) |

**Recomendação.**
1. **Primeiro:** abrir o caso no Cloud Customer Care (#1) usando o texto da seção "Texto para enviar" abaixo, no projeto GCP real do ArquivIO, categoria técnica / APIs e serviços (Drive API). Se o console só oferecer suporte de cobrança, avaliar 1 mês de Standard apenas para esta pergunta.
2. **Se houver verificação OAuth em curso:** responder à thread da equipe de verificação (#2) com a Pergunta 2 resumida.
3. **Fallback gratuito:** postar a versão pública curta (seção "Versão pública") no Stack Overflow (#4). Não inclua nome de clientes, IDs de projeto nem e-mails de service accounts reais.
4. **Cuidado:** o Google pode responder de forma genérica ("consulte a política"). Peça explicitamente "written confirmation". Enquanto não houver resposta escrita, mantenha a cotação do CASA (conforme `drive-service-account-design.md` §4.2).
5. **O que não afirmamos:** os fatos abaixo vêm das páginas oficiais; nenhuma delas fala de service account na API Services User Data Policy (a expressão "service account" não aparece na página), e a página diz que as regras valem "when you request access to Google user data". É exatamente essa lacuna que a pergunta fecha.

**Antes de enviar, preencher:** o ID do projeto GCP (placeholder `[GCP_PROJECT_ID]`) e o e-mail de contato do dono (`[OWNER_EMAIL]`). O restante está pronto.

---

# TEXTO PARA ENVIAR (English)

**Subject:** Policy clarification: Drive API read access via service account to folders that customers share manually (no end-user OAuth consent)

**Case details**

- Company: VL PEREZ LTDA (Brazil), product ArquivIO, https://www.arquivio.com.br
- Google Cloud project ID: `[GCP_PROJECT_ID]`
- Contact: `[OWNER_EMAIL]`
- Product area: Google Drive API / API Services policy and OAuth verification

**Scenario**

ArquivIO is a B2B SaaS that indexes customers' documents so users can search them and ask questions about them. We are evaluating a Google Drive connection mode that does not use end-user OAuth:

1. Each customer organization is assigned **its own dedicated service account** (one organization per service account, never reused across organizations). The service accounts live in project(s) we own.
2. The customer **manually shares specific folders** from the Drive UI, with the **Viewer** role, with that service account's email address. The customer chooses the folders and can remove the share at any time.
3. Our backend authenticates with the service account's key using the JWT bearer flow (`urn:ietf:params:oauth:grant-type:jwt-bearer`) with the scope `https://www.googleapis.com/auth/drive.readonly`. It reads only what the service account can see.
4. **No OAuth consent screen is shown to any end user** and we do not obtain any end-user tokens. We do not use domain-wide delegation and do not impersonate users.
5. We extract text from the files, create search indexes and embeddings, and store them in our own datastore. We use **OpenAI as a sub-processor** to generate embeddings and answers; the content is sent only to process the customer's own requests, and the customer's data is not used to train generalized models. We would apply the Limited Use requirements in practice. Content is deleted when the customer stops sharing.

**Questions**

1. **Terms and policy.** Is this use permitted under the Google APIs Terms of Service and the Google API Services User Data Policy? Specifically, does it comply with the policy for an application that reads files shared by third-party customers with a service account owned by the developer?
2. **Verification and security assessment.** Does this access pattern require OAuth app verification for the restricted scope `drive.readonly`, and/or a security assessment (CASA), given that there is no user consent flow? If a security assessment is required, which tier applies? If it is out of scope, please confirm in writing.
3. **Limited Use.** Do the Limited Use requirements in the API Services User Data Policy apply to data accessed this way (service account, files shared manually by the customer)? In particular, is sending that content to a sub-processor (OpenAI) to provide the user-facing feature, under contract and without training, consistent with the requirements?
4. **Limits and best practices.** Are there limits or recommendations we should follow, such as: per-service-account Drive API quotas (we understand that all calls by a service account are counted as a single user); the maximum number of service accounts per project and the quota to request more; recommended key management and rotation (we understand a maximum of 10 keys per service account); and any guidance on running many dedicated service accounts for different customers in one or several projects?
5. **Google Workspace customers.** Are there restrictions for customers on Google Workspace? We understand that administrators who limit external sharing to allowlisted domains cannot add `gserviceaccount.com` domains to the allowlist ([Allow external sharing with only trusted domains](https://support.google.com/a/answer/6160020)). Does Google recommend or support a different approach for such customers (for example sharing with a group address on a domain we own, or another mechanism) that is consistent with policy?

We would appreciate a written response that we can reference in our security review. Thank you.

**References we already read**
- API Services User Data Policy: https://developers.google.com/terms/api-services-user-data-policy
- Restricted scope verification: https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- Using OAuth 2.0 for Server to Server Applications: https://developers.google.com/identity/protocols/oauth2/service-account
- Drive API usage limits: https://developers.google.com/workspace/drive/api/guides/limits
- IAM quotas and limits: https://docs.cloud.google.com/iam/quotas

---

# Versão pública curta (Stack Overflow, tag `google-drive-api`; sem dados sensíveis)

**Title:** Service account reading Drive folders that customers share manually: any OAuth verification / CASA or Limited Use implications?

**Body:**

We run a B2B SaaS that wants to index documents from customers' Google Drive without a per-user OAuth consent flow. Each customer gets a dedicated service account; the customer shares chosen folders as Viewer with that account's email; our backend uses the JWT bearer flow with `drive.readonly` to read them (no domain-wide delegation, no impersonation).

1. Is this allowed by the Google APIs Terms of Service / API Services User Data Policy?
2. Does it still trigger restricted-scope OAuth verification and a CASA assessment, even though no user consent screen is involved?
3. Do the Limited Use requirements apply to data read this way?
4. Any limits or best practices for many service accounts per project (quotas, key rotation)?
5. For Workspace customers that allow external sharing only with allowlisted domains, is there a supported alternative (service account domains can't be allowlisted)?

I've read the policy pages, which describe these rules for apps that "request access to Google user data" and never mention service accounts. Official confirmation or experience from others is welcome.

> Nota: resposta de comunidade **não** é confirmação oficial do Google.

---

## Fontes verificadas (14/10/2026)

- [Google Cloud: Getting support](https://docs.cloud.google.com/docs/get-started/getting-support): Basic inclui suporte de cobrança; Standard/Enhanced/Premium pagos.
- [Create and manage support cases](https://docs.cloud.google.com/support/docs/customer-care-procedures): papel `roles/cloudsupport.techSupportEditor`; a página não esclarece se o Basic abre caso técnico.
- [OAuth Application Verification FAQ](https://support.google.com/cloud/answer/13463817?hl=en): sem formulário de contato; responder ao último e-mail da equipe; service account/IAM vai ao Cloud Support.
- [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy): aplica-se a "when you request access to Google user data"; "service account" não aparece; sem canal de contato.
- [Google Workspace developer support](https://developers.google.com/workspace/support): tags `google-oauth` e `openid`; suporte de especialista só para administradores Workspace.
- [Drive API support](https://developers.google.com/drive/v3/web/support): tag `google-drive-api`, fórum Google Workspace Developers, Issue Tracker.
- [Contact Google Workspace support](https://knowledge.workspace.google.com/admin/support/contact-google-workspace-support) e [Developer support](https://knowledge.workspace.google.com/admin/support/developer-support) (resumo de busca).
- Planos pagos: preços **não** confirmados em página oficial (a tabela de cloud.google.com/support não carregou); o valor citado vem de terceiro ([DigitalOcean](https://www.digitalocean.com/resources/articles/google-cloud-support)).
