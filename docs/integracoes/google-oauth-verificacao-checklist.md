# Google Drive: mapa de dados (B1) e checklist de verificação (B0/B4)

Data: 2026-09-29 · Decisão: ADR-0017 (Opção A, CASA com `drive.readonly`). Âncoras valem para o `HEAD` `f5f3a1e`; reancore pelo símbolo se o arquivo mudar.

## B0 - Registro da decisão

Ver `specs/adr/ADR-0017-google-restricted-scope-strategy.md`: Opção A; contingência `drive.file` + Picker pelos gatilhos G1–G3; teto de orçamento e ponte do piloto pendentes do dono (`acoes-humanas-externas.md`, itens 4 e 9).

## B1 - Mapa do fluxo de dados

| Etapa | O que acontece | Onde |
|---|---|---|
| Consentimento | Escopo único `drive.readonly`, `access_type=offline`; `state` OAuth de uso único | `backend/app/integrations/google_drive.py:25,484` |
| Token guardado | Refresh/access token cifrados com Fernet (chave `GOOGLE_TOKEN_ENCRYPTION_KEY`) em `DataSource.encrypted_credentials` | `integrations/google_drive.py:391-431` |
| Token usado e renovado | Renovação automática do access token; falha vira `reauth_required` | `backend/app/ingestion/google_drive.py:332-379` |
| Metadados lidos | Listagem de pastas/arquivos e `changes.list` (sync incremental) | `ingestion/google_drive.py:64-286`, `integrations/google_drive.py` |
| Conteúdo baixado | Download de arquivos elegíveis e exportação de Google Docs; extração de texto | `ingestion/google_drive.py:289-330,390-460` |
| Armazenado (Postgres) | Texto extraído, trechos (`text`, `search_text`), vetores (`embedding`, JSON) e metadados; **arquivo original não é guardado** | `backend/app/knowledge/models.py:57-60` |
| Saída para terceiros | Trechos e perguntas enviados à OpenAI para embeddings e respostas, com `store: False`; hospedagem e banco na Railway; autenticação WorkOS | `knowledge/questions.py:408,464,517,...`; `frontend/app/privacidade/page.tsx:15` |
| Quem acessa | Membros ativos da mesma organização; isolamento por `organization_id` | testes de isolamento de tenant |
| Desconexão hoje | Zera credenciais e e-mail; status `disconnected`; **não revoga o token no Google e mantém o índice** | `integrations/google_drive.py:591-633` |
| Exclusão hoje | Remover o escopo da biblioteca apaga documentos, trechos, vetores, consultas e trabalhos do banco ativo; sem TTL geral nem expurgo de backups | `ingestion/service.py` (`remove_workspace`); `docs/operacao/sync-credenciais-retencao-recomendacao.md` |

**Lacunas a declarar com honestidade no questionário do Google:** sem revogação no Google ao desconectar e sem expurgo automático (ambos = B2, adiado); sem retenção fixa; backups sem prazo comprovado.

## B2 - Registro (adiado)

Revogação (`POST https://oauth2.googleapis.com/revoke`, best effort) e expurgo opcional do índice ao desconectar, com testes primeiro. **Não implementado nesta entrega**; especificação em plano 02, B2. Precisa existir antes de a política prometer revogação/expurgo e antes da submissão.

## B3 - Rascunho da política

`docs/legal/google-politica-privacidade-rascunho.md` (não publicado).

## B4 - Scans e submissão do CASA

Marque e date cada item. Use as ferramentas e o formato exigidos pelo laboratório escolhido (confirmar no kickoff).

### Scans e evidências
- [ ] Controles existentes listados com evidência: Fernet nos tokens, CSRF/origem (`backend/tests/api/test_csrf_origin.py`), isolamento de tenant (`tests/integration/test_organization_tenant_isolation.py`), logs sem segredos (`tests/unit/test_auth_log_redaction.py`), `state` OAuth com hash e uso único.
- [ ] Dependências backend: `pip-audit` sem críticos/altos abertos.
- [ ] Dependências frontend: `npm audit --omit=dev` sem críticos/altos abertos.
- [ ] SAST: `semgrep --config auto` ou `bandit -r backend/app`, achados tratados.
- [ ] DAST baseline (OWASP ZAP) contra staging, sem segredos nos relatórios.
- [ ] Relatórios arquivados em `docs/seguranca/` (sem segredos); lacuna conhecida: rotação de chave Fernet (`MultiFernet`), abrir item se o lab pedir.
- [ ] Script `scripts/security-scan.sh` e CI (ver CI criado nesta missão) reproduzem os scans.

### Pré-requisitos e configuração
- [ ] Domínio próprio, verificado no Search Console, em "Authorized domains"; `/privacidade` e `/termos` em produção.
- [ ] Projeto Cloud de produção, usuário External, e-mails de suporte/contato monitorados.
- [ ] Nome igual ao produto (Arquivio), logo 120x120, URLs no domínio verificado.
- [ ] Redirect URIs de produção (`/data-sources/google/oauth/callback`); sem `localhost`.
- [ ] Escopo declarado: somente `drive.readonly`.
- [ ] Justificativa do escopo (por que não `drive.file`: link para ADR-0017); declaração Limited Use; subprocessadores (OpenAI, Railway, WorkOS).
- [ ] Vídeo de demonstração em produção: Conectar, consentimento em inglês com client ID visível, escolha de pastas, sync, pergunta com citação, desconectar/revogar.
- [ ] Teste com conta Google sem relação com o projeto (janela anônima), incluindo revogação em `myaccount.google.com/permissions`.

### Submissão
- [ ] Verificação de marca aprovada (2–3 dias úteis).
- [ ] Verificação do escopo restrito submetida; e-mails do OAuth review team respondidos.
- [ ] CASA Tier 2: lab escolhido, scans enviados, achados corrigidos, Letter of Assessment (LOA) emitida.
- [ ] LOA enviada ao Google; aprovação recebida.
- [ ] App em *Production*; aviso "não verificado" e limite de 100 usuários sumiram.
- [ ] Renovação anual agendada (90 dias antes do vencimento); dono nomeado.
