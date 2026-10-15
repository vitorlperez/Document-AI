# WA-POC-01 — WhatsApp como fonte de conhecimento (somente leitura)

Owner: pane-708; branch: main (shared tree; commit exclusivamente com pathspec).
Autorização: pedido explícito de 15/10/2026 para implementar POC isolada.

Entregável: spike Node independente em `spikes/whatsapp-readonly/`; comparação de
whatsapp-web.js/Baileys; runner humano por QR e seleção explícita; biblioteca local,
instrumentação, fixtures/testes e instruções. Sem alteração de backend/frontend,
ACL, produção, envio, acesso real ou credenciais no git. Sem conta real o resultado
é **validação simulada**, não validação da integração.

Gate real: consentimento consciente → vínculo humano pelo QR no navegador local →
seleção de conversas → confirmação de ingestão. Nenhuma etapa humana presumida.

Revisão h-si F1–F5 (base 0de870b): owner pane-710; branch main compartilhada.
Escopo exclusivo: este spike; preservar trabalho alheio. Corrigir evidência por
run/seleção, duração, ignores, recuperação de lock/tmp e testar live com injeção.
Sem override Puppeteer, vínculo, sincronização ou conta real. Dívida de audit fica.
Verificação revisão: 43/43 testes offline, 0 falhas; demo/report 2 mensagens,
1 tombstone, 2 documentos; evidência fresh em RESULTS/FINDINGS/evidence.

Investigação WA-POC-02: owner pane-713; branch main compartilhada. Usuário
autorizou a conta pessoal já vinculada. Escopo: origem de LOCAL_SETUP_FAILED,
diagnóstico sanitizado executável, regressões e avisos locais. Sem live real
autônomo, leitura de conteúdo/perfil, exclusão de auth/cache, nova autorização,
seleção, ingestão ou envio. Corrigir apenas causa demonstrada; falha real não
reproduzível sem conta exige diagnóstico humano antes de patch especulativo.

Correção WA-POC-03: owner pane-714; branch main compartilhada; base 77669c1.
Diagnóstico REAL recebido: initialize → authenticated → ready; list_chats falha
OPAQUE_WEB_ERROR em Client.getChats/ExecutionContext.evaluate. Não demonstra
a etapa interna. Escopo: reproduções sintéticas com fonte 1.34.7, comparação
upstream primário atual, correção local da listagem + passagem para histórico
sem serialização integral de chat, probes fechados e regressões. Preservar
auth/cache; sem live/diagnose pessoal, novo vínculo, seleção, ingestão ou envio
autônomos. Commit somente spike; grafo atualizado fora do commit.

WA-POC-03 implementado e verificado: 65/65 testes offline e Chromium/CDP sintético
exit 0; diagnóstico fechado por etapa. Comparação e limites em UPSTREAM.md.
Nenhum ensaio pessoal autônomo. Próxima tentativa: live humano no mesmo perfil.

WA-POC-05 — retenção zero: owner pane-716; branch main compartilhada; base 9b290b3.
Autorização explícita para investigação/correção da POC read-only. Contrato:
reprodução com biblioteca instalada/fixtures sintéticos; contadores numéricos
por etapa/motivo, somas coerentes em report/stats; correção somente sustentada
por regressão e identidade segura; mensagem ativa informa zero documentos.
Sem contornar seleção, remapear PN/LID sem prova, aceitar autor como conversa,
live/diagnose pessoal, leitura de library.private.json/auth/cache ou envio.
Preservar sessão e evidência h-sq; realIntegrationValidated permanece false.
Commit exclusivo do spike; graphify update fora do commit.

WA-POC-05 implementado (assumido por pane-717 após limite do pane-716): 73/73
testes offline e Chromium/CDP sintético exit 0. 38→0 reproduzido com `$1` na
biblioteca instalada e corrigido; contadores por etapa/motivo no report. Nenhum
live/diagnose pessoal executado. realIntegrationValidated segue false. Próxima
tentativa: live humano; se ainda zero, ler `stats.ingestion.history.rejections`.
Revisão h-st (pane-718) aplicada: revoke usa só protocolMessageKey quando
completo (envelope não veta), revoke repetido = already_deleted, gate fechado
não conta (sem NaN), eventos live de chats não selecionados não geram contagem,
remote embutido no id serializado veta endpoint divergente, resumo só da
execução atual, mídia só por tipo. 78/78 offline; CDP sintético exit 0.
