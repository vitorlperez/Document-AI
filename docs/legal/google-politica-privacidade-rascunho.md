# Rascunho - política de privacidade: dados do Google (B3)

**RASCUNHO. Não publicado.** Não altera `frontend/app/privacidade/page.tsx`. Requer revisão jurídica e só pode ser publicado depois que cada frase for conferida contra o código. Decisão de base: ADR-0017.

## Bloqueio de publicação

O texto marcado com **[DEPENDE DE B2]** promete revogação e expurgo que **ainda não existem** (`disconnect` só zera credenciais e mantém o índice: `backend/app/integrations/google_drive.py:591-633`). Publique esses trechos só depois de B2. Até lá, use a variante "estado atual" indicada.

## Texto proposto (seção "Integrações e uso de dados do Google")

> O uso e a transferência, para qualquer outro aplicativo, de informações recebidas das APIs do Google adotarão a Política de Dados de Usuário dos Serviços de API do Google, incluindo os requisitos de Uso Limitado.
>
> *The use of information received from Google APIs will adhere to the Google API Services User Data Policy, including the Limited Use requirements.*

**Acesso solicitado.** Ao conectar o Google Drive, solicitamos a permissão `drive.readonly`, que permite visualizar e baixar arquivos do Drive aos quais a conta conectada tem acesso. Não alteramos, apagamos nem compartilhamos arquivos no Google Drive. O administrador escolhe pastas ou arquivos; a escolha delimita o que o Arquivio sincroniza, mas não reduz a permissão concedida pelo Google.

**Como usamos.** Usamos o conteúdo dos arquivos escolhidos apenas para fornecer ao usuário as funções visíveis do serviço: indexar, buscar e responder perguntas com referência aos documentos. Guardamos o texto extraído, trechos, índices de busca e vetores; os arquivos originais permanecem no Google.

**O que não fazemos.** Não usamos dados obtidos das APIs do Google para publicidade, nem os vendemos. Não usamos esses dados para treinar modelos de IA generalizados. Não permitimos que pessoas leiam esses dados, exceto com consentimento do usuário para fins específicos, por segurança/abuso, para cumprir a lei, ou quando agregados e anonimizados para operar o serviço.

**Transferência a terceiros.** Trechos e perguntas são enviados à OpenAI para gerar embeddings e respostas, com `store: false` (retenção de conteúdo desativada na API), e somente para prestar a funcionalidade ao usuário. Hospedagem e banco: Railway. Autenticação: WorkOS. **[VALIDAR com jurídico/contrato antes de afirmar que a OpenAI não treina com esses dados.]**

**Revogação e exclusão.**
- *Estado atual (publicável hoje):* desconectar a fonte remove as credenciais do Arquivio; o usuário também pode revogar o acesso em `myaccount.google.com/permissions`. O índice permanece até a remoção do escopo da biblioteca, que apaga documentos, trechos, vetores, consultas salvas e trabalhos do banco ativo. Não há prazo fixo de retenção; cópias de backup podem persistir até seu ciclo de expiração.
- *Após B2 **[DEPENDE DE B2]**:* ao desconectar, revogamos o token junto ao Google e, se o administrador escolher, apagamos o conteúdo indexado dessa fonte.

**Contato para pedidos de titular:** lagevitor.dev@gmail.com.

## Conferência frase a frase

| Afirmação | Confirmada por |
|---|---|
| Escopo `drive.readonly` | `google_drive.py:25` |
| Arquivo original não guardado | `knowledge/models.py:57-60` (só texto/vetores) |
| `store: False` na OpenAI | `knowledge/questions.py:408,464,517,561,596,652` |
| Sem treino/venda/publicidade | política interna; **validar contratualmente** |
| Revogação e expurgo | **não confirmado (B2 pendente)** |
| Prazo de retenção | inexistente; proposta em `docs/operacao/sync-credenciais-retencao-recomendacao.md` |
