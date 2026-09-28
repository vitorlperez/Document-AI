# F-202 — regressão da revisão independente e reprodução pós-correção

## Diagnóstico

O commit `cee9ca4` calculava `covered_document_ids` diretamente de
`generated.citation_indexes`. Essa lista é produzida pelo modelo e podia declarar
um documento coberto mesmo quando a resposta não continha uma afirmação citada
para ele. Além disso, `_validate_citations` rejeitava toda a geração ao encontrar
um único índice inválido ou duplicado, apagando uma parte útil que ainda era
verificável.

## Regressão antes da correção

Comando:

```text
cd backend && .venv/bin/python -m pytest tests/unit/test_document_inventory_summary.py -q
```

Resultado antes da correção: `3 failed, 5 passed`. Os três casos reproduziram:

- índice `[2]` declarado, mas afirmação sobre `Profile.pdf` sem marcador na resposta;
- `Profile.pdf [2]` citado apenas pelo nome, sem síntese;
- lista declarada `[1, 1, 99, 2]`, que invalidava também a afirmação útil com `[1]`.

Foram acrescentadas ainda regressões para marcador de outro documento e trecho
vazio. A cobertura agora deriva somente de frases retidas que nomeiam o
documento, contêm marcador em faixa declarado para evidência do mesmo documento,
possuem conteúdo além do nome e apontam para trecho não vazio.

## Reprodução real pós-correção

Backend usado: Compose local `document-ai-api-1`, reconstruído somente com
`docker compose build api` e recriado com `docker compose up -d --no-deps api`.
Os volumes de PostgreSQL e Redis e os demais serviços foram preservados.

Escopo real: menção da pasta da biblioteca `Test Document-AI`, autorizada para o
usuário membro existente. A resolução encontrou dois documentos indexados e 40
chunks com embeddings atuais: `A Gravidade do pecado de impuresa` (35) e
`Profile.pdf` (5).

Pergunta:

```text
Quais arquivos temos dentro dessa pasta e quais sao as principais informacoes dentro deles?
```

Resultado observado:

```text
retrieval_status: sufficient_evidence
provider_outcome: summary_partial
selected_candidate_count: 8
Cobertura da síntese: 1 de 2 arquivos.
Sem síntese verificável nesta resposta: Profile.pdf.
```

A resposta preservou o inventário citado dos dois arquivos, reteve apenas a
síntese efetivamente citada do primeiro e declarou `Profile.pdf` como não
resumido. O status `sufficient_evidence` descreve a parte útil disponível; não é
usado como prova de cobertura integral.

Limitação observada: o provedor, nessa execução, não produziu uma síntese válida
e citada para `Profile.pdf`. O sistema não inventou um resumo nem elevou a
cobertura para `2 de 2`.
