# Biblioteca: nós de arquivo órfãos (M55)

## Sintoma (produção, 12/10/2026)

34 nós `kind=file` da fonte Google Drive (23 PDF, 8 Google Docs, 3 DOCX; ex.: `ACAP.pdf`, `Application Form - Novacomp.docx`)
criados em 27/09 20:45, **sem nenhuma linha em `documents`** em nenhum workspace. A Biblioteca os listava, mas nada era
pesquisável e nenhum sync os revisitava.

## Causa raiz

1. **Nada podava o catálogo.** `library_nodes` é compartilhado por todos os workspaces da fonte; `remove_workspace`
   apagava `documents`/chunks/jobs do workspace, mas os nós ficavam (comentário antigo: "retain synchronized provider
   metadata"). A poda de `project_successful_sync` só olhava documentos `removed` do workspace corrente — um nó cujo
   `documents` foi apagado nunca entrava nesse conjunto. Houve 7 remoções de workspace entre 27/09 e 01/10.
2. **Delta nunca revisita arquivo não alterado.** Um workspace recriado sem cursor faz snapshot completo, mas só enxerga
   o que a conta autenticada lista no escopo; os deltas seguintes (`changes`) só trazem alterações. Nó sem documento e
   fora da listagem não tinha, portanto, nenhum caminho de volta (nem de saída).
3. **Evidência de que parte do catálogo veio de outra conta Google.** No mesmo `DataSource` coexistem dois `ouid`
   distintos nos `webViewLink` (4 nós com documento vs. 3 órfãos), e 8 dos 42 nós criados em 27/09 foram redescobertos
   enquanto 34 não, mesmo com listagem completa em 01/10 (106 itens) e 12/10 (109). `GoogleConnectionService.complete`
   trocava credenciais e `account_email` em silêncio ao reautenticar, mantendo cursores e nós da conta anterior. Os
   arquivos "ainda existem no Drive", mas na outra conta — o token atual não os enxerga. (Inferência por metadados; a API do
   Drive não foi chamada com token de cliente. Confirme com o usuário qual conta tinha os arquivos.)

## Correção (código)

- `LibraryService.prune_orphan_file_nodes`: remove nós `file` sem documento vivo (status ≠ `removed`) em qualquer workspace da
  fonte e as pastas que ficaram vazias. Chamado em:
  - `remove_workspace` (remover/recriar workspace não deixa órfãos);
  - sync **completo**: poda órfãos não vistos na listagem; órfãos vistos ganham `documents` pelo fluxo normal (fila de ingestão);
  - sync **incremental**: poda só os órfãos que a fonte reportou como removidos/indisponíveis.
- Worker (`reconcile_workspace_folder`): em delta (Drive/OneDrive/SharePoint), os órfãos do catálogo entram em
  `force_file_ids` (máx. 200/execução). Existem na conta → são lidos e indexados; não existem/fora do escopo → tombstone e poda.
- Reautenticar com **outra conta Google** zera os cursores dos escopos da fonte, forçando snapshot completo no próximo sync.
- API: `indexing` por arquivo (`specs/library-indexing-status.md`); órfãos aparecem como `pending` até serem resolvidos.

## Como corrigir os 34 atuais após o deploy (NÃO executado em produção)

**Automático (recomendado, nenhuma ação):** no próximo sync agendado do workspace "Todo o Drive acessível"
(`1febc636…`, roda diariamente ~16h UTC) o Worker força a leitura dos 34 IDs:
- na conta atual → viram `documents` e são indexados;
- inexistentes para a conta atual (404/indisponível) → viram tombstone e os nós são podados.
Acompanhe em `manual_sync_runs` (total = 109 + os recuperados).

**Manual / pré-visualização (idempotente, só banco local):** de `backend/` no Worker (`railway ssh`):

```bash
.venv/bin/python -m scripts.reconcile_library_orphans            # dry-run: conta órfãos por fonte
.venv/bin/python -m scripts.reconcile_library_orphans --apply    # poda (reexecutar não faz nada)
```

`--apply` apenas remove metadados de catálogo sem conteúdo indexado; não toca em Drive, `documents` nem chunks. Se os arquivos
pertencem à outra conta, reconecte essa conta (ou use um segundo `DataSource`) e rode um sync completo.

## Verificação (SELECT somente leitura)

```sql
-- órfãos por fonte (esperado: 0 após o sync/comando)
SELECT n.source_id, count(*) FROM library_nodes n
WHERE n.kind='file' AND NOT EXISTS (
  SELECT 1 FROM documents d JOIN workspace_folders w ON w.id=d.workspace_folder_id
  WHERE w.source_id=n.source_id AND d.external_file_id=n.external_id AND d.index_status<>'removed')
GROUP BY 1;
```

## Formatos novos

`NEW_FORMATS_ENABLED` foi removida: XLSX, Google Sheets, PPTX e Google Slides são indexados por padrão. Os 29 documentos
`ignored/unsupported_file_type` da produção que agora são elegíveis (ex.: Sheets/Slides) são relidos automaticamente no próximo sync.
Limites de memória do Worker: ver `docs/integrations-roadmap.md#formatos-indexáveis` (`MAX_OOXML_BYTES`, orçamento de texto).
