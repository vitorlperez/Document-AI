# ADR-0017 - Estratégia para o escopo restrito do Google Drive

**Status:** aceito em 2026-09-29 (decisão do dono do produto)

## Contexto

O Arquivio pede `https://www.googleapis.com/auth/drive.readonly` (`backend/app/integrations/google_drive.py:25`), escopo **restrito** do Google. Como o texto extraído, os trechos e os vetores ficam em servidor próprio e servem organizações de terceiros, o app não se enquadra em nenhuma isenção e exige verificação OAuth de escopo restrito + avaliação de segurança CASA, renovada a cada 12 meses. Sem isso, o app fica em *Testing* (refresh token de 7 dias) ou "não verificado" (limite de 100 usuários).

Alternativa avaliada: `drive.file` (non-sensitive) + Google Picker. Ele libera só arquivos criados pelo app ou abertos por ele via Picker; a documentação não afirma que escolher uma pasta libera o conteúdo dela. O produto sincroniza **pastas de trabalho recursivamente** (unidade de conhecimento = pasta, spec 001) e acompanha arquivos novos por `changes.list`; com `drive.file` isso deixa de funcionar sem novo Picker.

Comparativo completo: `specs/plans/integracoes/02-sharepoint-e-google.md` §B.2–B.3.

## Decisão

- **Opção A: manter `drive.readonly` e iniciar agora a verificação OAuth restrita + CASA Tier 2.** Motivo: `drive.file` não cobre o conteúdo de pastas escolhidas, o que quebraria o modelo de sincronização recursiva de pastas.
- **Contingência formal (não construir agora): `drive.file` + Picker**, acionada apenas se ocorrer um gatilho:
  - **G1** - Google ou o laboratório reprovar, ou a cotação exceder o teto aprovado pelo dono.
  - **G2** - mais de 8 semanas sem aprovação com cliente-âncora aguardando.
  - **G3** - Google exigir um Tier que a empresa não sustente.
  Antes de migrar, executar o PoC de 1 dia (plano 02, B7.0), registrado em `docs/integracoes/google-picker-poc.md`. Se pasta escolhida não liberar filhos nem `changes.list`, a contingência é descartada para o caso de pastas.
- **Teto de orçamento do lab:** a definir pelo dono após cotação escrita de 2–3 laboratórios. Referência provisória do plano: US$ 5–10 mil/ano até haver cotação (fontes divergem: US$ 0,5–6 mil por rodada até valores bem maiores). Pendente: ação humana.
- **Ponte do piloto:** até a aprovação, manter o app em *Testing* com usuários de teste e reconexão semanal, ou publicar sem verificação (aviso "app não verificado", até 100 usuários). A escolha final é do dono e deve ser anotada aqui quando feita. Confirmar na documentação oficial antes de depender de qualquer uma.
- **B2 (revogação do token no Google e expurgo do índice ao desconectar) fica registrado e adiado.** A política de privacidade (rascunho B3) não pode prometer revogação/expurgo até B2 existir; ver `docs/legal/google-politica-privacidade-rascunho.md`.

## Consequências

- Engenharia mínima no produto; custo é externo: 4–8 semanas de verificação, taxa do lab e renovação anual (lembrete a 90 dias do vencimento da Letter of Assessment).
- O escopo pedido continua exatamente `drive.readonly`; um teste automatizado deve impedir regressão (parte de B2).
- Dependências externas antes da submissão: domínio próprio, páginas públicas `/privacidade` e `/termos` no ar, verificação de marca. Lista em `docs/integracoes/acoes-humanas-externas.md`.
- Se um gatilho disparar, a migração custa cerca de 8–12 dias e muda o modelo de seleção (arquivos, não pastas).
