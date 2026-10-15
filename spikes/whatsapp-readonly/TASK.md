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
