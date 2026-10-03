---
name: arquivio-connectors-ingestion
description: Implementar ou validar sincronização e ingestão do Arquivio com OAuth, cursores incrementais, idempotência, exclusões e estados recuperáveis nos adaptadores existentes.
---

# Conectores e ingestão do Arquivio

Pacote fonte do projeto, ainda não instalado no catálogo do Overclock. Use por referência em briefings de backend e testes quando um conector, extração ou job mudar.

## Fontes e fronteiras

Leia o dossiê, `docs/integrations-roadmap.md` e o runbook do provedor quando aplicável. Localize o adaptador com Graphify; preserve as fronteiras entre `backend/app/integrations/`, `backend/app/ingestion/`, `backend/app/library/` e `backend/app/knowledge/`.

Não transplante permissões ou semântica de cursor entre Google Drive, Microsoft Graph e Notion. Mudanças em contratos externos exigem documentação oficial atual. Não adicione microserviços, conectores ou banco vetorial por analogia com um concorrente.

## Checklist dirigido pela mudança

- OAuth: testar expiração, refresh, revogação e ausência de consentimento; preservar criptografia e redaction. Não registrar tokens, URLs assinadas, conteúdo ou cursores sensíveis.
- Incremental: identificar quando o cursor pode ser confirmado, como retomar após falha parcial e como recuperar cursor inválido. Persistir progresso sem pular alterações não aplicadas.
- Idempotência: repetir evento/job e retry após crash sem duplicar documentos, chunks, embeddings ou cobrança indevida. Verificar o estado persistido, não só o retorno do método.
- Exclusão e acesso: distinguir arquivo removido, fora do escopo, excluído manualmente e acesso revogado; testar que conteúdo antigo deixa de ser recuperável conforme o contrato aprovado.
- Extração: tamanho, formato, conteúdo vazio, falha de parser e formato desabilitado devem produzir estado explicável. Reindexação respeita versão/hash e evita trabalho redundante.
- Jobs: retries limitados, backoff, concorrência e estados terminais observáveis. Worker usa os mesmos serviços de domínio e autorização da API.

## Evidência

Derive testes do critério afetado, utilizando fakes de provider. Pontos de partida: `backend/tests/unit/test_ingestion_service.py`, `test_sync_incremental_modes.py`, `test_sync_removed_chunks.py`, `test_oauth_service_contract.py` e `backend/tests/api/test_library_sync_permissions.py`.

Rode pytest focado a partir de `backend/`, registre comando e resultado no dossiê, e valide os estados no banco de teste. Testes externos só quando necessários e autorizados, sem mudar consentimentos ou dados reais por iniciativa própria. O validador independente reexecuta os checks pertinentes após integração.
