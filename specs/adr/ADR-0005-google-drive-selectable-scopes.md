# ADR-0005: Escopos selecionáveis do Google Drive

**Status:** Accepted

## Context

O MVP inicialmente modelava cada pasta selecionada do Google Drive como um
`WorkspaceFolder`. Isso impede uma seleção útil de múltiplas pastas e pode
duplicar conteúdo/custo quando uma pasta-pai e uma filha são escolhidas.

## Decision

`WorkspaceFolder` continua sendo o espaço lógico de busca e RAG. Ele ganha
entradas `workspace_folder_selections`, com os tipos:

- `folder`: uma pasta remota e todos os seus descendentes;
- `root_files`: somente arquivos diretamente em `root`, sem percorrer pastas;
- `all_accessible`: todos os arquivos não apagados que a conta OAuth permite
  ao aplicativo ler.

O modo `selected` requer pelo menos uma pasta ou `root_files`. O modo
`all_accessible` é exclusivo e exige confirmação explícita de acesso uniforme.
Uma descoberta reúne todas as entradas em memória por `external_file_id` antes
de ler ou extrair conteúdo. IDs externos Google permanecem strings; IDs de
recursos locais e URLs da aplicação permanecem UUIDs.

## Consequences

- Perguntas seguem obrigatoriamente limitadas a um único `workspace_folder_id`.
- Pastas sobrepostas não criam documentos, chunks ou embeddings duplicados no
  mesmo espaço.
- A migração é aditiva: cada configuração antiga recebe uma seleção `folder`.
  Um rollback de aplicação anterior não deve ser usado após criar seleções
  múltiplas; a restauração segura é reimplantar com a migração mantida.
- A enumeração completa é manual/assíncrona, paginada e não grava nada no Drive.
- Os registros operacionais contêm apenas contagens, modo e códigos de falha;
  não incluem conteúdo, tokens nem nomes de documentos.
