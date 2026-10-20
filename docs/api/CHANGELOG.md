# Changelog da API

## 1.1.0 — 2026-10-19

Espaços: `whoami.spaces`, `sources[].spaces`, `search.results[].spaces` e o filtro opcional `space_ids` em `/v1/search` e `/v1/ask` (só estreita; Espaço alheio = 404). O alcance da chave passa a ser a interseção do que o membro vinculado lê com os `node_ids`; sair de um Espaço reduz o alcance na requisição seguinte. Campos novos são aditivos; nenhum campo existente mudou.

## 1.0.0 — 2026-09-30

Primeira API pública: whoami, sources, search, documents e ask (desabilitado por padrão). Chaves por organização, escopos e raízes opcionais; rate limit compartilhado e auditoria sem conteúdo.
