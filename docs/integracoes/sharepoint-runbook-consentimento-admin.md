# Runbook — SharePoint: consentimento de administrador e operação

Referência: ADR-0016. Validar cada passo no tenant de teste antes do piloto (itens marcados **[VALIDAR]**).

## 1. Pré-requisitos

- App Entra multi-tenant do Arquivio com redirect `https://<api>/data-sources/sharepoint/oauth/callback` (além do de OneDrive) e permissões delegadas `openid`, `profile`, `offline_access`, `User.Read`, `Sites.Read.All`.
- Variáveis: `MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET`, `MICROSOFT_SHAREPOINT_REDIRECT_URI`, `MICROSOFT_TOKEN_ENCRYPTION_KEY`.
- Quem conecta: Owner/Admin da organização no Arquivio **e** conta corporativa/escolar do Microsoft 365 (contas pessoais não têm SharePoint).
- Publisher verification iniciada (sem ela, tenants que exigem publisher verificado bloqueiam consentimento de usuário) **[VALIDAR]**.

## 2. Link de consentimento do administrador

```
https://login.microsoftonline.com/organizations/v2.0/adminconsent?client_id=<CLIENT_ID>&scope=https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/User.Read offline_access openid profile&redirect_uri=<MICROSOFT_SHAREPOINT_REDIRECT_URI>
```

(Rota dedicada fica para a fase A8; até lá o link é enviado manualmente.)

## 3. Texto sugerido para o e-mail ao TI

> Olá, vamos conectar bibliotecas do SharePoint ao Arquivio para busca e perguntas sobre documentos. O Arquivio pede somente leitura (`Sites.Read.All`, delegada): ele enxerga apenas o que a conta que conectar já enxerga e não altera arquivos. Precisamos que um administrador global ou de aplicativos aprove o acesso pelo link abaixo. Depois da aprovação, escolhemos quais bibliotecas indexar; todos os membros da nossa organização no Arquivio poderão consultar o conteúdo indexado dessas bibliotecas. [link]

## 4. Modo restrito `Sites.Selected` (fase A9)

Exige consentimento de admin **e** concessão por site (`POST /sites/{siteId}/permissions` com `roles:["read"]` para o app, feita por alguém com `Sites.FullControl.All`). Não enumera sites; o admin informa a URL do site.

## 5. Revogação

- No Arquivio: Integrações → SharePoint → Desconectar (apaga credenciais, mantém conteúdo indexado; remova escopos pela biblioteca se necessário).
- No Entra: Aplicativos empresariais → Arquivio → Excluir/Revogar consentimento. O próximo sync marca a fonte como `reauth_required`.

## 6. Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `?error=sharepoint_admin_consent` / `AADSTS65001` | consentimento de usuário bloqueado; falta aprovação do admin | enviar link da §2 ao TI |
| `AADSTS90094` | política do tenant exige admin para qualquer app | idem §2 |
| `AADSTS50105` | usuário não atribuído ao aplicativo empresarial | TI atribui o usuário/grupo ao app |
| `?error=sharepoint_tenant_mismatch` | reconexão com conta de outro tenant | reconectar com conta do mesmo tenant ou criar nova fonte |
| fonte `reauth_required` | refresh token revogado/expirado; admin conector saiu ou foi desativado | outro Owner/Admin reconecta com conta do mesmo tenant (cursores são zerados e o próximo sync refaz o snapshot) |
| arquivos `file_too_large` | acima de `SHAREPOINT_MAX_FILE_BYTES` | ajustar variável se aceitável |
| arquivos com rótulo de sensibilidade/IRM em `text_extraction_failed` | conteúdo cifrado pelo Purview | comportamento esperado (R-A10) |
| muitos 429/503 | throttling do SharePoint | já há `Retry-After`; reduzir `SHAREPOINT_DOWNLOAD_WORKERS` |

## 7. Piloto (pendente — tenant real)

1 tenant (cliente-âncora), 1 biblioteca, 7 dias sem intervenção. Medir: tempo do snapshot, nº de 429/503 (log `ingestion_sync`), % `ignored/unsupported_file_type`, `reauth_required` espúrio. **Uso multi-espaço na mesma fonte bloqueado (R-A2).**
