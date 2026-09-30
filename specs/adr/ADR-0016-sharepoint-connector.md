# ADR-0016: Conector SharePoint / Microsoft 365

- **Status:** Aprovado (implementação A1–A6); piloto em tenant real pendente
- **Data:** 2026-09-30
- **Decisor:** produto (usuário); demais defaults do plano 02
- **Supersede parcialmente:** ADR-0008 dec. 2 (modelo delegado passa a valer também para SharePoint) e ADR-0009 dec. 5 ("uma fonte OneDrive por org" não se aplica ao provider `sharepoint`, que é separado)

## Contexto

Clientes com Microsoft 365 guardam documentos em bibliotecas de sites SharePoint/Teams, não no OneDrive pessoal. O conector OneDrive (ADR-0009) lê apenas `/me/drive`. Plano: `specs/plans/integracoes/02-sharepoint-e-google.md`, Parte A.

## Decisões

| # | Decisão |
|---|---|
| D-A1 | Provider novo `sharepoint` (`DataSource` próprio, botão e status próprios), reaproveitando `MicrosoftGraphClient`, `OneDriveDocumentProvider` e `OneDriveConnectionService` por herança/parametrização (`AUTHORITY`, `SCOPES`, `bind_identity`, `document_provider`). |
| D-A2 | Autoridade `organizations` (sem contas pessoais). Mesmo app Entra do OneDrive, redirect adicional `/data-sources/sharepoint/oauth/callback` (`MICROSOFT_SHAREPOINT_REDIRECT_URI`). |
| D-A3 | Um `DataSource` = um tenant; `provider_account_id` = hostname de `GET /sites/root` (`siteCollection.hostname`, minúsculo). Reconexão a outro tenant é recusada (`?error=sharepoint_tenant_mismatch`). Índice único parcial `uq_data_sources_sharepoint_tenant` (migração `20260930_0021`) impede duas fontes do mesmo tenant na mesma organização. Alternativa mais forte (`tid` do `id_token`) fica como melhoria. |
| D-A4 | ID externo composto `"{driveId}|{itemId}"` (separador `|`, porque driveIds SharePoint começam com `b!`); nó de site `"site|{siteId}"`. |
| D-A5 | Árvore `Fonte → Site → Biblioteca → pastas`; só biblioteca e pasta são selecionáveis (`selectable:false` no scope-catalog para sites). |
| D-A6 | Escopos delegados `openid profile offline_access User.Read Sites.Read.All`; sem `Files.Read.All`, sem escrita. `Sites.Selected` fica para a fase A9. |
| D-A7 | Cursor por seleção = `deltaLink` de `/drives/{d}/root/delta`; snapshot = `?token=latest` **antes** da travessia `children`; delta incremental filtrado por pertencimento (`within_scope`, memoizado); evento de pasta no escopo, cursor expirado (410) ou `force_full` → snapshot. |
| D-A8 | Sem `all_accessible` e sem `root_files` (422 na API); confirmação de acesso uniforme com texto reforçado. |
| D-A9 | `Retry-After` honrado em 429 e 503; downloads paralelos `SHAREPOINT_DOWNLOAD_WORKERS` (padrão 2); arquivos acima de `SHAREPOINT_MAX_FILE_BYTES` (50 MiB) viram `file_too_large` sem download; catálogo limitado a `SHAREPOINT_CATALOG_MAX_SITES` (200). |
| D-A10 | Conexão delegada depende de uma pessoa; se o admin conector sair, a fonte vira `reauth_required` (risco R-A5; modo aplicativo fora de escopo). |

Credenciais e cursores são cifrados com `MICROSOFT_TOKEN_ENCRYPTION_KEY` (mesma chave do OneDrive; `cipher_keys("sharepoint")`). O worker projeta a biblioteca da empresa com `folders_for_selections` (só drives tocados pelas seleções).

## Consequências

- OneDrive, Google e Notion inalterados (suíte completa verde; ver commits `[02-A1]`…`[02-A5]`).
- **R-A2 confirmado (A0.3):** projetar o sync de um espaço apaga nós de outro espaço da mesma fonte. Rollout SharePoint multi-espaço bloqueado até correção própria (`specs/security-hardening-followups.md`).
- Conteúdo lido com o token do admin conector fica visível a todos os membros da organização (R-A3); ACL por arquivo é trabalho futuro.
- Pendências que exigem tenant real: spike Graph (formato de IDs, item-delta, `token=latest`), consentimento/publisher verification, formatos reais e piloto de 7 dias (`docs/integracoes/sharepoint-spike-tenant-teste.md`, runbook `docs/integracoes/sharepoint-runbook-consentimento-admin.md`).
