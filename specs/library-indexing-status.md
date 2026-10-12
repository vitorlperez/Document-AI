# Contrato — estado de indexação por arquivo na Biblioteca

Status: **contrato fechado (v1)** · Missão M55 · Backend: `backend/app/library/service.py`, `backend/app/api/library.py`
Consumidor: frontend (selo por arquivo na Biblioteca). O backend implementa exatamente este contrato; mudanças exigem
atualizar este arquivo primeiro.

## Por quê

Um nó de biblioteca (`LibraryNode`, `kind="file"`) existe no catálogo compartilhado da fonte, mas o conteúdo
pesquisável vive em `documents` (um por workspace). Hoje a API só devolve `workspace_documents` dos documentos
**indexados**, então o usuário não sabe distinguir "ainda vai ser indexado" de "falhou", "formato não suportado" ou
"sumiu da fonte". Este contrato expõe o estado e o motivo, de forma segura (somente códigos, nunca texto de arquivo).

## Onde aparece

Todo item `kind == "file"` devolvido pelos endpoints que já serializam nós da Biblioteca ganha o campo `indexing`:

- `GET /library/nodes/{node_id}/children?organization_id=…`
- `GET /library/search?organization_id=…&query=…`

(`GET /library` devolve só raízes `kind="source"`; não tem `indexing`.) Para `kind != "file"` (pasta/fonte) o campo é
**omitido** (não vem `null`). Os campos existentes (`workspace_folder_ids`, `workspace_documents`, …) não mudam.

## Forma

```jsonc
{
  "id": "…", "kind": "file", "name": "ACAP.pdf", "...": "…campos atuais…",
  "indexing": {
    "state": "indexed",          // enum abaixo
    "error_code": null,          // string | null (ver tabela)
    "document_id": "…uuid…",     // uuid | null — documento que originou o estado
    "workspace_folder_id": "…",  // uuid | null — workspace desse documento
    "indexed_at": "2026-10-01T17:57:01Z" // ISO-8601 | null — só quando state == "indexed"
  }
}
```

`state` (string fechada; o frontend deve tratar valor desconhecido como `pending`):

| state | Significado | `error_code` | Selo sugerido |
|---|---|---|---|
| `indexed` | Há ao menos um documento indexado (conteúdo pesquisável) | `null` | "Indexado" |
| `pending` | O arquivo está no catálogo mas **não existe nenhuma linha em `documents`** em nenhum workspace — ainda será (ou precisa ser) ingerido pelo próximo sync | `null` | "Aguardando indexação" |
| `failed` | Tentamos ler e falhou (inclui PDF escaneado sem OCR) | obrigatório (tabela) | "Falhou" + motivo |
| `ignored` | Arquivo lido como não elegível (formato fora da lista indexável) | `unsupported_file_type` | "Formato não suportado" |
| `skipped` | Lido, mas sem conteúdo útil (arquivo vazio) | `empty_content` | "Vazio — não indexado" |
| `not_found_in_source` | O sync completo não encontrou mais o arquivo na fonte (documento marcado `removed`) | `null` | "Não encontrado na fonte" |

### Precedência quando o mesmo arquivo tem documentos em vários workspaces

`indexed` > `failed` > `skipped` > `ignored` > `not_found_in_source` > `pending`.
Empate dentro do mesmo estado: documento mais recente (`indexed_at`/`id` decrescente). Ou seja, basta um workspace
com o documento indexado para o arquivo contar como `indexed`.

### `error_code` (estável; mostrar mensagem local, nunca o código cru ao usuário final)

| code | state | Mensagem sugerida |
|---|---|---|
| `unsupported_file_type` | ignored | Tipo de arquivo não suportado |
| `empty_content`, `empty_document` | skipped | Arquivo vazio |
| `empty_extracted_text` | failed | PDF sem texto legível (digitalizado); habilite OCR ou envie versão com texto |
| `file_too_large` | failed | Arquivo maior que o limite de leitura |
| `file_encrypted` | failed | Arquivo protegido por senha |
| `text_extraction_failed` | failed | Não foi possível ler o conteúdo |
| `source_file_unavailable` | failed | A fonte negou/limitou a leitura deste arquivo (permissão ou exportação) |
| `ocr_failed`, `ocr_document_too_large`, `ocr_budget_exceeded` | failed | OCR indisponível, documento grande demais ou orçamento de OCR esgotado |
| `embedding_failed` | failed | Falha ao gerar a busca semântica; tentar de novo no próximo sync |
| qualquer outro | qualquer | "Motivo técnico: `<code>`" (fallback genérico) |

## Ações

Nenhum endpoint novo. "Reprocessar" continua sendo `POST /library/nodes/{node_id}/reprocess`; para `pending` e
`failed` o próximo sync (agendado ou manual) tenta ingerir de novo sem ação do usuário. `not_found_in_source` é
limpo pelo backend no próximo sync completo.

## Notas de implementação (backend)

- Uma única consulta por página (`LibraryService.indexing_for_nodes`), sem N+1.
- Somente metadados: `state`, `error_code`, ids e `indexed_at`; nada de texto de documento.
- Escopo de tenant idêntico a `documents_for_nodes` (organização do escopo; workspaces da fonte do nó).
- `pending` não promete data: depende do próximo sync do workspace que cobre o arquivo.
