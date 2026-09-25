# ADR-0008: Conector OneDrive com OAuth delegado e Graph delta

- **Status:** Aprovado para implementação
- **Data:** 2026-09-23
- **Decisor:** produto (usuário)
- **Contexto:** adicionar arquivos OneDrive ao produto Arquivio, preservando isolamento por organização, consentimento de leitura e os conectores existentes.
- **Atualização:** a decisão 1 sobre audiência foi substituída pela ADR-0009 em 2026-09-24; as demais decisões continuam válidas.

## Decisões

1. A primeira versão aceita somente contas Microsoft 365 corporativas/escolares e usa o endpoint de autoridade `organizations`.
2. Acesso é delegado à conta que conecta, somente ao OneDrive padrão desse usuário. Não usar permissões application-wide nem incluir SharePoint, drives de grupo ou conteúdo compartilhado nesta entrega.
3. Solicitar a menor permissão delegada do Graph necessária para listar itens, ler conteúdo e consultar alterações (`Files.Read`), mais os escopos mínimos para identificar a conta e renovar acesso.
4. Mapear identidades remotas usando o item ID do Graph, pois cada `DataSource` representa um único OneDrive padrão; os links de origem persistidos usam `webUrl` do Graph.
5. Fixar a fonte ao ID do drive padrão retornado pelo Graph. Reconexão com outro drive é recusada para evitar reutilizar seleções e conteúdo indexado de outra conta; uma troca de conta exige um fluxo explícito de redefinição de escopos.
6. Usar delta query por seleção de pasta. Guardar delta link como valor opaco cifrado em cada `WorkspaceFolderSelection`. Só persistir novos checkpoints junto do commit que conclui ingestão, embeddings e projeção na biblioteca.
7. Um delta inicial é uma enumeração completa daquela seleção. Deltas seguintes carregam somente itens alterados e tombstones; o pipeline aplica mudanças incrementais sem tratar a lista parcial como snapshot. `root_files` usa o delta da raiz e filtra filhos diretos pelo ID do item raiz, pois `parentReference.path` pode faltar. Ao mesclar seleções, um arquivo removido de um escopo permanece indexado se outra seleção do mesmo espaço ainda o incluir.
8. Mudanças em itens de pasta podem não incluir descendentes no delta. Para seleções que incluem subpastas, qualquer evento de pasta força uma enumeração completa dos escopos; `root_files` continua incremental porque só inclui filhos diretos da raiz.
9. Respostas 401/403 do Graph marcam a fonte `reauth_required`; rate limits usam `Retry-After` e a política de retry já existente do worker.

## Consequências

- Migrations adicionam checkpoint cifrado por seleção e identidade do drive vinculado à fonte; falhas antes da confirmação repetem com o checkpoint anterior e o delta é idempotente.
- Mudanças de pasta podem provocar uma enumeração adicional para assegurar a inclusão e remoção de documentos em subárvores.
- OAuth usa authorization code de servidor e segredo mantido em configuração; o cadastro real da aplicação Microsoft e configuração de redirect URI permanecem uma tarefa operacional do ambiente.
- A integração segue `SourceProvider` e o fluxo comum de ingestion; Google Drive e Notion mantêm seus comportamentos atuais.
- O escopo explícito evita consentimento tenant-wide e não promete acesso a bibliotecas que o OneDrive do usuário não possui.

## Referências

- Roadmap do repositório: `docs/integrations-roadmap.md`.
- Microsoft Graph: `driveItem children`, `driveItem delta` e OAuth authorization code para contas organizacionais.
