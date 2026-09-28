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

## Segunda correção após revisão h-3r

A revisão do commit `4ddb9f0` mostrou três defeitos adicionais: bullets sob um
cabeçalho de documento eram descartados, uma afirmação inventada podia passar
somente por apontar para uma citação do documento correto e uma ressalva podia
contar como cobertura. As três regressões foram escritas primeiro e produziram
`3 failed, 10 passed`.

O provedor agora usa um contrato JSON estruturado por documento. Cada afirmação
traz referências compostas de índice e citação literal curta; o backend confere
que a citação existe no excerto do mesmo documento, rejeita ressalvas como
afirmações e exige sobreposição lexical substancial entre afirmação e evidência.
A renderização e a cobertura derivam somente das afirmações retidas. O parser
legado continua aceitando listas sob cabeçalhos, mas passa pelos mesmos filtros.

Limite explícito: a sobreposição lexical e a ocorrência literal do excerto são
checagens conservadoras de fundamentação, não uma garantia geral de verdade ou
entailment semântico. Por isso o prompt estruturado pede síntese extrativa no
idioma do trecho. O caso específico `Vitor fundou uma empresa milionária` com
uma referência válida ao trecho `Vitor é engenheiro de software em Manaus` foi
rejeitado tanto no contrato legado quanto no estruturado e não contou cobertura.

Validação pós-correção:

- suíte backend no workspace compartilhado: `328 passed, 8 skipped`;
- commit F-202 isolado em worktree limpo: `317 passed, 8 skipped` na suíte
  completa e `62 passed` nas regressões focadas de síntese + semântica;
- Ruff e `git diff --check`: sem erros;
- serviço `api` reconstruído/recriado isoladamente; PostgreSQL, Redis e seus
  volumes foram preservados; `/health/ready` retornou `{"status":"ready"}`;
- reprodução direta no backend Docker, com membro, organização, pasta lógica e
  os dois IDs de documentos autorizados: `sufficient_evidence`, referências para
  os dois nomes e `Cobertura da síntese: 2 de 2 arquivos`.

Conteúdo efetivamente observado na resposta real: o primeiro documento reteve
afirmações sobre Jesus tratar o pecado de impureza com vigor, temor/reverência e
graça de Deus; `Profile.pdf` reteve contato/LinkedIn, cinco anos de experiência
Full Stack com Python/Django, integração de LLMs e arquitetura multi-tenant,
tecnologias (Python, Django, Fast API, AWS, bancos e testes) e experiência com
Flask/MySQL/MariaDB. Assim a prova verifica conteúdo dos dois resumos, não apenas
status, contagem ou presença de referências.
