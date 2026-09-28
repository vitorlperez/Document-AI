# Revisão independente final de F-202 — commit 726c04b

Data: 2026-09-28. Revisão sem alteração de código.

## Decisão

**Segurança factual e integridade extrativa aprovadas; encerramento funcional de F-202 bloqueado se o aceite continua exigindo síntese das principais informações.** O commit remove a geração de afirmações na pergunta composta. Os oito blocos da resposta Docker atual foram conferidos, um por um, contra `DocumentChunk.text[:500].strip()` do mesmo `document_id`; nenhum bloco introduziu negação ou fato adicional pelo modelo. A apresentação avisa que é extração literal, não resumo semântico, e a cobertura 2/2 corresponde a dois documentos com trechos exibidos.

O pedido original em `TASK/items/F-202.md` exige sintetizar o conteúdo consultado. A saída real entrega quatro recortes pré-selecionados por documento. Para `A Gravidade do pecado de impuresa`, os quatro blocos somam apenas 168 caracteres e consistem principalmente em título e frases curtas. Para `Profile.pdf`, três dos quatro blocos são cortados em 500 caracteres, alguns no meio de palavras. Isso é útil como prévia com proveniência, mas não informa de forma confiável quais são as principais informações dos arquivos. A seleção é por posições distribuídas, sem ranqueamento por relevância à pergunta; quatro chunks de 35 e quatro de cinco aparecem na resposta. O rótulo “trechos relevantes” descreve mal essa seleção determinística. Não tratar esta entrega como resumo validado nem como leitura completa.

## Causa final

As versões anteriores aceitavam afirmações geradas após checagem de citação literal e sobreposição lexical. Essa checagem não provava entailment: negava uma frase verdadeira ou acrescentava um fato inexistente sem ser barrada. A correção substituiu as afirmações do modelo por trechos do índice. Isso elimina a classe de invenção **nesta modalidade composta**, ao custo de deixar o requisito de síntese semântica sem implementação.

## Evidência de código e testes

- `backend/app/knowledge/questions.py`: ramo composto em torno da linha 434, seleção em 829-864, filtro de trechos não vazios em 867-868, agrupamento por `UUID` em 871-895, citação extraída de `chunk.text[:500]` em torno da linha 903. Inventário e cobertura usam `document_id`; nomes duplicados são apenas rótulos. A lista de evidências passa pelos filtros de organização, pasta, documento indexado, organização/pasta do chunk e embedding compatível antes de chegar ao renderizador. O serviço exige acesso de membro à pasta.
- Regressões em `backend/tests/unit/test_document_inventory_summary.py`: provedor não chamado; negação e fatos adicionados não exibidos; nomes iguais com IDs distintos e citações separadas; linhas e marcadores preservados; documento com trecho vazio não conta na cobertura. O teste de nomes iguais passou na execução focada. As ressalvas de insuficiência geradas anteriormente não entram no novo caminho porque não há geração; ressalvas da própria fonte, se existentes, ainda podem ser copiadas e contar como trecho não vazio.
- Arquivo isolado do commit por `git archive 726c04b`, em `/tmp/f202-review.t5WBjT`: `./.venv/bin/pytest -q` em `backend` → **311 passed, 8 skipped**; suíte focada de inventário, semântica, isolamento de tenant e guards → **57 passed, 5 skipped**. `ruff check app/knowledge/questions.py tests/unit/test_document_inventory_summary.py` → passou. `git diff 726c04b^ 726c04b --check` → passou.

## Replay Docker e auditoria do conteúdo

- `docker compose ps --format json`: serviço `document-ai-api-1` saudável. `curl --fail http://localhost:8000/health/ready` → `{"status":"ready"}`.
- Nó lógico da biblioteca `Test Document-AI`: `cafa63fd-986a-40b1-ab45-d838f5bf4307`. A seleção de um membro ativo, provedor `google_drive` e menção de pasta resolveu uma pasta indexada e exatamente dois IDs autorizados: `80d9f68a-c23a-49e5-bcbe-2518fdd00911` (`A Gravidade do pecado de impuresa`, 35 chunks compatíveis) e `3da94f25-665b-41a8-8b97-4c16d816d034` (`Profile.pdf`, cinco chunks compatíveis).
- Pergunta executada via `QuestionService.ask_selection` no container: “Quais arquivos temos dentro dessa pasta e quais sao as principais informacoes dentro deles?” Um provedor sentinela que falharia se `answer` ou `embed` fosse chamado não foi acionado. Resultado: `sufficient_evidence`, oito citações, dois `document_id`; SHA-256 da resposta de 2.572 caracteres `9fdf1b04fdde27671caecc9406f852072ecfb090c40950f146b301e17b5f5d7a`, igual ao replay do resolvedor.
- Auditoria independente: parse dos cabeçalhos `fonte 1/2` e dos oito blocos citados; cada bloco foi comparado, em ordem, ao texto do chunk persistido citado, após o mesmo limite de 500 caracteres e remoção de espaços periféricos. **8/8 correspondências exatas**, 4/4 por documento, sem cruzamento de IDs. Primeira fonte: 168 caracteres de citação. Segunda: 1.931 caracteres, três blocos atingindo o limite de 500. A numeração é por documento, embora a lista de citações tenha oito chunks.
- A imagem Docker incorpora outras mudanças paralelas posteriores ao commit; comparação por AST confirmou identidade do ramo composto e das funções de seleção, renderização, numeração e extração de evidências com `726c04b`. O replay testa esse código idêntico, mas não representa um deployment isolado de todo o commit.
- Credencial configurada no container; GET autenticado a `https://api.openai.com/v1/models` retornou HTTP **200** nesta revisão. O 401 anterior não se repetiu. A modalidade extrativa não depende desse serviço, e a sondagem 200 não comprova disponibilidade futura.

## Limites

“2 de 2” significa documentos selecionados com ao menos um trecho não vazio exibido, não proporção dos 40 chunks examinados, qualidade/resumo das informações, nem leitura integral dos PDFs. O inventário cobre documentos indexados com embeddings compatíveis no escopo selecionado, não uma verificação independente de todos os arquivos remotos da pasta. Os oito testes de integração pulados na suíte completa permanecem fora desta evidência. A resposta direta pelo serviço Docker valida o backend e os dados; não valida a renderização visual do frontend.
