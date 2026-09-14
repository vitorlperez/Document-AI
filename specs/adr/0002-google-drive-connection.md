# ADR-0002 - Conexão somente leitura com Google Drive

**Status:** aprovado para o MVP em 2026-09-11

## Decisão

- O primeiro conector é Google Drive, via OAuth authorization-code executado
  exclusivamente no backend e associado a uma organização e ao Admin que o
  iniciou.
- Solicitar `https://www.googleapis.com/auth/drive.readonly`: ele é necessário
  para enumerar e posteriormente ler o conteúdo de Docs, PDF e DOCX. Nenhum
  escopo de escrita é solicitado.
- `data_sources.encrypted_credentials` guarda somente tokens JSON cifrados com
  Fernet usando `GOOGLE_TOKEN_ENCRYPTION_KEY`, fornecida pelo ambiente. Tokens
  nunca são retornados por API, e não entram em logs, estados OAuth ou testes.
- Estados OAuth são de uso único, expiram em dez minutos e são vinculados ao
  usuário, à organização e à sessão autenticada que iniciou o fluxo.
- Admin pode conectar/listar/selecionar pastas; Owner também, por ser Admin
  funcional no MVP. Member não pode operar fontes ou pastas.
- Uma pasta só pode ser selecionada após confirmação explícita de que todos os
  membros da organização podem vê-la. A confirmação é persistida e não tenta
  espelhar ACLs do Drive.

## Consequências

- O escopo é restrito pelo Google e requer configuração/verificação apropriada
  antes de uso público. Credenciais, callback URI e chave de cifragem serão
  inseridas apenas no ambiente de deploy.
- A leitura remota é encapsulada em `GoogleDrivePort`; testes usam um fake e
  nunca chamam a API Google.
- Tokens inválidos ou revogados alteram a fonte para `reauth_required` e
  bloqueiam novas sincronizações futuras.
