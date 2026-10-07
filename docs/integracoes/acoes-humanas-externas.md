# Ações humanas externas pendentes (integrações)

Data: 2026-09-29. Nada abaixo é executável por agente; cada item tem dono e prazo. Origem: plano 02 (B.5), índice §5–6, ADR-0017.

| # | Ação | Dono | Prazo sugerido | Bloqueia |
|---|---|---|---|---|
| 1 | **Domínio próprio**: registrar, apontar ao frontend, atualizar `PUBLIC_APP_URL`, publicar `/privacidade` e `/termos` (hoje `*.up.railway.app`, 404 em 28/09) | dono | 02/10/2026 | Google, Microsoft, `api.`/`mcp.` |
| 2 | **Verificar o domínio no Google Search Console** com a conta dona do projeto Cloud e adicioná-lo em "Authorized domains" | dono | após 1 | verificação de marca |
| 3 | **Verificação de marca Google** (nome, logo 120x120, home/privacidade/termos): 2–3 dias úteis | dono | após 2 | escopo restrito |
| 4 | **Cotação do lab CASA** por escrito com 2–3 labs (TAC Security, Leviathan, DEKRA); definir o **teto de orçamento** | dono | S1 | submissão, ADR-0017 |
| 5 | **Revisão jurídica** da política de privacidade (Limited Use, OpenAI como processador, LGPD) | dono/jurídico | S2 | submissão |
| 6 | **Vídeo de demonstração** (YouTube não listado) e formulário de escopo restrito | dono + eng. | após 3 e 5 | aprovação |
| 7 | **Submissão do escopo restrito e contratação do CASA** (Tier 2, scans, Letter of Assessment) | dono | S2–S3 | produção Google |
| 8 | **Microsoft AI Cloud Partner Program (ID)** e **publisher verification** (exige domínio verificado); tenant de teste M365 (Developer Program) para o spike do SharePoint | dono | S1 | consentimento sem aviso "não verificado" |
| 9 | Escolher a **ponte do piloto** Google (Testing com reconexão semanal × não verificado × Trusted) e anotá-la na ADR-0017 | dono | 02/10/2026 | piloto |
| 10 | Lembrete de **renovação anual do CASA** (90 dias antes do vencimento da LOA) e dono nomeado | dono | após aprovação | continuidade |
| 11 | **ClickUp**: criar o app OAuth em Settings → Apps (redirect `…/api/data-sources/clickup/oauth/callback`), copiar Client ID/Secret, gerar `CLICKUP_TOKEN_ENCRYPTION_KEY`, definir as variáveis `CLICKUP_*` em API e worker no Railway (`ACTIVE_DOCUMENT_LIMIT=1500` já decidido e aplicado). Passo a passo: `docs/integracoes/clickup-runbook.md` | dono | antes do piloto | conexão ClickUp, piloto |
