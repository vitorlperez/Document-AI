# M31 — Notion: conteúdo próprio e hierarquia na biblioteca

- Status: implemented and locally verified; executor: pane-298; branch compartilhada: main.
- Pedido: revisar e ajustar leitura do Notion e apresentação compreensível na biblioteca.
- Causa reproduzível: `folders()` retorna todas as páginas com IDs reais; a projeção cria
  pastas e faz upsert de documentos com os mesmos IDs sem corrigir `kind`. Os blocos
  de subpáginas são incorporados ao pai; seleção não inclui descendentes; pais são descartados.
- Hipótese: identidades distintas para agrupamentos e conteúdo, seleção por ancestralidade
  e leitura delimitada por página eliminam a colisão e a duplicação de conteúdo.
- Contrato: páginas sem descendentes são documentos; páginas com descendentes aparecem como
  agrupamentos com um documento de conteúdo próprio; bases são agrupamentos. Links são referências,
  não filhos. Conteúdo/indexação continuam limitados à organização e às seleções autorizadas.
- IDs reais de documentos e seleções são preservados; agrupamentos usam `notion:container:<id>`.
- Leitura: blocos internos, paginação, tabelas, equações e referências; subpáginas/bases
  descobertas por relações reais; nenhum download automático de anexos/URLs externos.
- Escopo: adapter Notion, passagem de metadados da ingestão, reparo da projeção antiga,
  seleção/re-sync de agrupamentos Notion e textos/ícones na integração/biblioteca.
- Verificação: regressões red/green para colisão, conteúdo pai/filho, descendentes,
  paginação/base, links, índice incremental, exclusão e escopo; suíte backend e frontend.
- Limite: sem credencial Notion fornecida para validar um workspace real.

skills: inline [oc-builder, oc-blackbox, oc-stamp]

## Decisão de dados e biblioteca

| Entidade Notion | Documento indexado | Biblioteca |
| --- | --- | --- |
| Página com conteúdo, sem descendentes selecionados | ID real da página | Arquivo com título e URL originais |
| Página com conteúdo e subpáginas | Conteúdo próprio, sem texto das subpáginas | Agrupamento e arquivo “Conteúdo de <título>” |
| Página apenas com subpáginas | Sem documento vazio artificial | Agrupamento com seus filhos |
| Base | Sem documento de esquema artificial | Agrupamento da base |
| Coleção (`data_source`) | Registros indexados individualmente | Coleção dentro da base; seleção da base inclui todas as coleções |
| Registro com propriedades e sem blocos | Valores de propriedades não vazias | Documento do registro |
| Link/menção/relação | Referência textual/URL no documento de origem | Não altera o parentesco e não importa o alvo |
| Anexo | Nome/legenda quando disponíveis | Não cria documento dos bytes do anexo |

- Notion-Version passa a `2025-09-03`, com busca de `data_source`, descoberta das
  coleções via metadata da base e query paginada em `/v1/data_sources/<id>/query`.
- Blocos de página/bases são fronteiras; toggles/colunas/tabelas continuam sendo
  conteúdo interno da página. Pais por bloco são resolvidos pela API.
- Agrupamentos são uma projeção com IDs distintos, compatível com os tipos atuais
  `folder`/`file`; não há migração de schema nem mudança no escopo das perguntas.
- `DiscoveryResult.catalog_documents` separa metadados completos da lista de conteúdo
  alterado. A tarefa usa o delta para indexar e os metadados para a biblioteca.
- Na próxima sincronização, um espaço com documentos indexados sem a versão
  `v2:notion-page-v1` faz descoberta completa para eliminar conteúdo duplicado do pai;
  a versão é persistida por documento/espaço, independentemente do nó compartilhado da biblioteca.
  Preserva IDs dos arquivos,
  remove placeholders sem índice e mantém documentos de outros espaços.
- Exclusões antigas de pastas continuam valendo para os novos agrupamentos e descendentes.
- Busca do Notion é eventual: ausência de um documento conhecido é confirmada por GET;
  árvores de páginas inalteradas ainda são consultadas para descobrir filhos ausentes da busca.
  Isso poupa reindexação/embeddings, mas não todas as requisições de blocos.
- A interface diferencia Página/Base/Coleção, exibe o caminho completo das opções,
  oferece “Atualizar páginas” e explica conteúdo próprio versus descendentes/referências.

## Evidência

- Antes da correção: 4 regressões falharam (título, fronteira pai/filho, tabelas/referências,
  colisão pasta/documento). Mais 2 regressões falharam para seleção de descendentes/metadados;
  teste de bases/propriedades e links falhou antes da implementação; fixture de bases modernas
  falhou antes da mudança para data sources. Todos passaram após as correções.
- `.venv/bin/python -m pytest -q tests/unit tests/api`: **1253 passed**, 4 warnings,
  **exit 0**, 41.81s. Inclui paginação, múltiplas coleções, propriedades sem corpo, filho
  ausente da busca, documento conhecido omitido pela busca, ciclos, exclusões legadas,
  ressincronização por seleção real e reparo da projeção.
- `.venv/bin/ruff check .`: **All checks passed**, exit 0.
- `node --import tsx --test tests/*.test.mjs`: **40 passed**, 0 failures, exit 0.
- `npx tsc --noEmit`, ESLint dos arquivos alterados e `npm run build`: exit 0.
- `.venv/bin/python scripts/export_openapi.py --check`: export matches `/v1`, exit 0.
- `graphify update .`: 6021 nodes, 17556 edges, 332 communities, exit 0. Grafo
  atualizado no workspace; arquivos gerados já estavam alterados e ficam fora do commit.
- `git diff --check`: exit 0.
- A primeira rodada completa detectou 2 mocks antigos incompletos em fault injection;
  o stub de coleções foi adicionado mantendo o teste de recuperação real de GET 429/503.

## Limites da validação e da leitura

- Verificação local com HTTP/Notion simulados; nenhum workspace real foi sincronizado.
- Anexos binários/OCR e tipos de bloco não suportados pela API não foram incorporados.
- Propriedades de relações truncadas pelo Notion indicam referências adicionais na origem;
  não prometemos conteúdo completo dos alvos nem importação automática dessas páginas.
- Páginas totalmente vazias não geram documentos artificiais.

## Revisão independente de c059e1a — pane-299

- A evidência inicial foi reproduzida: 1253 testes backend e 40 frontend passando.
- Encontrados e corrigidos F-203 (migração por espaço), F-204 (referências de páginas/bases
  copiadas em blocos sincronizados) e F-205 (poda de agrupamentos vazios de outros espaços).
- Seis casos de regressão adicionados; os casos focais falharam antes das correções.
- Após as correções: 1259 testes backend, 40 frontend, Ruff, TypeScript, ESLint dos arquivos
  frontend alterados pelo commit original, build frontend e contrato OpenAPI aprovados.
- Limite permanece: validação local de HTTP/Notion simulados e banco SQLite; sem sync de
  workspace Notion real nem inspeção visual de uma biblioteca autenticada.
- Evidência e matriz de requisitos: `TASK/evidence/notion-c059e1a-review.md`.

skills: inline [oc-conveyor, oc-stamp]

## M31 — seleção apenas das páginas pais

- Status: implementado e verificado localmente; executor: pane-302; branch compartilhada: main.
- Complemento solicitado: Gerenciar oferece apenas raízes acessíveis do Notion.
  Selecionar uma raiz ou todo o conteúdo inclui filhos em todos os níveis.
- Escopo desta etapa: opções e textos do gerenciador frontend; catálogo completo e
  projeção hierárquica da biblioteca preservados para descoberta/sincronização.
- Raízes incluem bases independentes e páginas cujo pai não esteja acessível no catálogo.
- Correção de escopo do usuário respeitada: nenhuma mudança na apresentação da biblioteca.
- Duas regressões frontend falharam antes da mudança e passaram depois; a suíte ficou
  em 42/42. Demais provedores continuam oferecendo suas opções completas.
- Regressão de descoberta estendida: seleção do pai e Todo o conteúdo percorrem
  filho/neto ausentes da busca sem incorporar corpos dos descendentes ao pai.
- Verificação: 43 testes backend focais; Ruff; TypeScript; ESLint dos arquivos
  frontend alterados; build frontend (5 etapas); todos exit 0.
- Limite: validação local com HTTP simulado; sem sincronização de workspace Notion real
  nem nova inspeção visual de sessão autenticada.
- skills: inline [oc-builder, oc-stamp].

## Referências oficiais

- [Upgrade para bases com várias coleções](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03).
- [Parentesco de páginas, bases, coleções e blocos](https://developers.notion.com/reference/parent-object).
- [Limitações da busca](https://developers.notion.com/reference/search-optimizations-and-limitations).
- [Tipos de bloco](https://developers.notion.com/reference/block).
