# ADR-0009: Contas pessoais e organizacionais no OneDrive

- **Status:** Aprovado para implementação
- **Data:** 2026-09-24
- **Decisor:** produto (usuário)
- **Contexto:** a primeira versão do conector usava a audiência Microsoft `organizations` e aceitava somente contas corporativas/escolares. O produto também deve permitir conectar o OneDrive pessoal da conta que autoriza o acesso.

## Decisão

1. Usar a autoridade Microsoft `common` em autorização, troca do código e renovação do token. O login solicita `prompt=select_account` para que a pessoa escolha a conta, inclusive quando houver sessão Microsoft anterior no navegador.
2. O registro do aplicativo no Microsoft Entra deve aceitar **contas em qualquer diretório organizacional e contas Microsoft pessoais**. Esta configuração externa é necessária além da mudança de código.
3. Manter OAuth delegado, os escopos `openid profile offline_access User.Read Files.Read` e o acesso somente ao OneDrive padrão da conta conectada. Não adicionar permissões application-wide.
4. Manter a fonte vinculada ao ID do drive informado pelo Graph. Uma reconexão ao mesmo drive preserva seleções e documentos; outra conta é recusada até existir um fluxo explícito de troca de fonte.
5. Continuar com uma fonte OneDrive por organização nesta etapa. SharePoint, drives de grupo, conteúdo compartilhado e múltiplas contas simultâneas exigem escopo próprio.

## Consequências

- O formato dos tokens cifrados, o banco e a API do produto não mudam. As fontes existentes permanecem vinculadas ao mesmo drive.
- Uma conta pessoal pode conectar somente após o registro Microsoft aceitar contas pessoais; o erro de audiência ocorre no login Microsoft antes do callback do produto.
- O cadastro do aplicativo ainda exige acesso a um tenant Entra. Uma conta pessoal autorizada a usar o conector não recebe por isso permissão para administrar o tenant.
- Testes simulados cobrem as duas classes de conta; consentimento real e leitura de um OneDrive pessoal dependem da configuração externa do registro.

## Referências

- `specs/adr/ADR-0008-onedrive-connector.md` (decisão inicial substituída apenas quanto à audiência).
- Microsoft identity platform: autorização por `common`, `prompt=select_account` e tipos de conta suportados.
- Microsoft Graph: `GET /me/drive` com permissão delegada `Files.Read` para contas pessoais e corporativas.
