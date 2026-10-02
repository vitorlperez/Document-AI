# Arquivos vazios no acompanhamento de sincronizações

A leitura de `ManualSyncRun` reclassifica os códigos comprovados `empty_document` e
`empty_content` como `skipped`, reason `empty_content`. A contagem de falhas desconta
somente os outcomes convertidos: snapshots compactos podem ter falhas adicionais
fora da amostra. O serializer não altera o JSON original. As consultas de documentos
com falha e o cálculo de falha ao finalizar uma sincronização excluem esses códigos.

A migração Alembic `20261001_0027`, filha da `20260930_0026`, aplica a mesma regra
congelada aos snapshots persistidos e aos documentos `failed`. Corrige o job exato
referenciado pelo snapshot quando não restam falhas nem erro de job. Jobs antigos
sem snapshot são convertidos quando o próprio código de erro comprova vazio. Também
corrige o job mais recente `partial_failure` sem erro nem snapshot quando o espaço
tem vazios comprovados, nenhuma falha de documento restante e nenhum job ativo;
falhas de provedor e jobs mais antigos sem evidência são preservados.
Um espaço passa a `ready` se foi afetado, não tem documentos com falha nem job ativo
e seu último job terminou `ready`. Nenhum documento, chunk, arquivo original ou
registro histórico é apagado. Rodar a reparação novamente não muda os dados.
O downgrade não recria falsas falhas; essa correção semântica é irreversível.

Auditoria no banco local antes da migração: 9 documentos e 30 outcomes com
`empty_document`; 3 outcomes com `empty_extracted_text`. O código de extração só
produz `empty_document` e `empty_extracted_text` como erros de texto vazio.
`empty_extracted_text` **não** é convertido: também representa PDF escaneado sem
OCR, um erro recuperável real. `empty`, `no_text` e `no_extractable_text` não foram
encontrados no código nem no banco local; não são tratados por inferência.

O modal mostra `X de Y arquivos processados · N falhas · K ignorados`, com os
ignorados em texto neutro. Badge, lista de falhas por documento, erros por task,
badge do espaço e arquivos com falha recebem dados coerentes do backend.
O `sync-status` utiliza os counters corrigidos e jobs/espaços reparados, mantendo
badges e onboarding coerentes. Um sync só de vazios termina `ready`, mas continua
`queryable=false`: conclusão não promete conteúdo disponível para o chat.

Validação da migração em PostgreSQL descartável separado: dados sem falhas reais,
mistura de vazio e PDF sem OCR, upgrade pelo Alembic, reparação repetida, endpoint
lógico de documentos com falha e `sync-status`. Não resetar o banco de aplicação
para executar a suíte: use `TEST_DATABASE_URL` de um banco exclusivamente de testes.

O botão da ferramenta em `library-screen.tsx:215` usa
`POST /library/nodes/{id}/reprocess?organization_id=...&reprocess_all=false`.
O backend já aceita esse opt-in booleano (`api/library.py:216`) e persiste
`mode=incremental` por padrão. Title/aria-label em `library-screen.tsx:236`:
“Sincronizar alterações de <Ferramenta>”. A opção completa em Integrações continua
separada, com confirmação e `reprocess_all=true`. O teste de sync de source confirma
que todos os espaços usam modo incremental e os chunks inalterados são mantidos.
