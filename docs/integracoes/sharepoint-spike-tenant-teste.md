# Spike SharePoint / Microsoft 365

> Execução: sem tenant M365 disponível em 2026-09-30. Nenhum resultado real
de Graph, consentimento ou publisher verification foi confirmado. Fixtures
usam IDs b!drive|item; o limite de 255 caracteres é validado no código.

Pendências externas: obter tenant com Team e Communication site, bibliotecas
com subpastas, Global Admin e usuário comum; registrar redirect adicional
/data-sources/sharepoint/oauth/callback e Sites.Read.All delegado no Entra.

Registrar com tokens mascarados: consentimento do usuário e admin, hostname
/sites/root, IDs e comprimentos reais, paginação de sites/drives, token=latest,
delta de pasta interna, parentReference sem path, mudanças durante snapshot,
movimentos e exclusões entre escopos, 429/503 e documentos IRM.

## Publisher verification
Status: não iniciado, depende de domínio próprio verificado e conta de parceiro.
Responsável: produto/infra (a designar). Validar requisitos com Microsoft.
Não simular início do processo.

## Caracterização local A0.3
Teste confirma que a projeção do espaço B apaga nós do espaço A na mesma fonte.
R-A2 registrado em specs/security-hardening-followups.md. Rollout multi-espaço
bloqueado; piloto inicial deve usar uma única seleção de espaço por fonte.
