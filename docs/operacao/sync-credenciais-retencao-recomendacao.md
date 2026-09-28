# Recomendações para frescor, credenciais e retenção

**28 de setembro de 2026 — proposta para decisão; não descreve uma política já implantada.** Responsável: Vitor Perez, lagevitor.dev@gmail.com. Este documento não autoriza deploy, mudança de OAuth/backend ou rotina de exclusão.

## Situação verificada no código

| Tema | Estado atual | Evidência |
| --- | --- | --- |
| Frescor | Sincronização iniciada manualmente por Owner/Admin; o enfileiramento evita outro trabalho ativo no mesmo escopo. Perguntas usam o índice, sem leitura ao vivo do provedor. Não existe polling agendado. | `backend/app/api/ingestion.py` (`enqueue_sync`), `backend/app/ingestion/service.py` (`enqueue`), `specs/adr/0003-pilot-sync-ai-and-usage.md` |
| Incremental | Google Drive usa Changes API e OneDrive usa delta. Google refaz fotografia completa após cursor inválido ou mudança de ancestralidade; Notion não anuncia suporte incremental. | `specs/work-items/google-drive-incremental-resync.md`, `backend/app/integrations/registry.py` |
| Credenciais Google | O OAuth solicita `drive.readonly`, `access_type=offline` e salva o refresh token criptografado quando fornecido. O código atual não executa troca de refresh token para renovar o access token do Google; falhas 401/403 levam a `reauth_required`. Assim, configurar apenas o consentimento não resolve a continuidade dos syncs. | `backend/app/integrations/google_drive.py` (`authorization_url`, `exchange_code`, `CredentialCipher`), `backend/app/ingestion/tasks.py` |
| Outras credenciais | OneDrive implementa renovação e persistência de refresh token; Notion armazena token de acesso sem refresh token neste adaptador. A duração real depende do provedor e da configuração da integração. | `backend/app/integrations/onedrive.py`, `backend/app/integrations/notion.py` |
| Dados de perguntas | Pergunta, trechos e referências são usados para a resposta; a chamada Responses usa `store=false`. Não há tabela de histórico de perguntas/respostas. Somente consultas salvas explicitamente pelo usuário persistem texto e filtros; contadores mensais registram quantidade de perguntas. | `backend/app/knowledge/questions.py`, `backend/app/audit_usage/models.py`, `backend/app/audit_usage/service.py` |
| Exclusão | Desconectar remove credenciais, mas preserva índice. Remover escopo apaga documentos, trechos, vetores, consultas salvas e trabalhos locais associados. Não há TTL/purge geral ou processo de backup/expurgo comprovado. | `backend/app/integrations/google_drive.py` (`disconnect`), `backend/app/ingestion/service.py` (`remove_workspace`), `specs/security-hardening-followups.md` |

## Alternativas para manter o índice recente

1. **Sincronização periódica:** scheduler durável enfileira cada escopo conectado a cada 24 horas; para clientes que precisam de maior frescor, a cada 2 a 4 horas. Reusar o trabalho incremental existente, limitar concorrência por organização/provedor, aplicar jitter e backoff, e registrar `last_synced_at`, fila, falha e idade do índice. É a primeira opção recomendada porque atende o requisito com menor dependência de webhooks. Um disparo periódico não garante conclusão no prazo: definir um SLO, por exemplo 95% dos escopos concluídos há menos de 24 horas, e alertar quando a idade ultrapassar o limite.
2. **Sinais de mudança + reconciliação periódica:** Drive push notifications ou Microsoft Graph change notifications podem antecipar a execução quando houver alteração; manter o polling periódico como reconciliação para eventos perdidos, expiração de inscrição e falhas. Maior complexidade operacional; avaliar após medir volume e latência da opção 1.
3. **Sincronização sob demanda antes da consulta:** quando o índice estiver antigo, enfileirar e mostrar o estado ao usuário; só responder após conclusão se a experiência permitir esperar. Evita resposta silenciosamente antiga, mas pode aumentar latência e custo. Pode complementar a opção 1.

**Decisão sugerida para análise:** começar com 24 horas como limite operacional, medir duração/custo/falhas por escopo e então oferecer 2 a 4 horas onde houver necessidade. Mostrar na biblioteca e na resposta a hora do último sync bem-sucedido e aviso quando exceder o limite. Manter a resposta existente baseada no índice enquanto a sincronização está pendente, com aviso explícito de idade.

## Continuidade das autorizações

- Implementar em trabalho futuro a renovação do access token Google com o refresh token cifrado, persistindo substituições se retornadas e distinguindo token expirado de autorização revogada. Cobrir concorrência entre workers e `invalid_grant` com testes. Isso é pré-requisito para sincronização autônoma duradoura; o refresh token pode ser revogado ou expirar e nunca deve ser apresentado como permanente.
- Conferir no Google Cloud Console o status de publicação do consentimento. Para app externo em **Testing**, refresh tokens de escopos além de perfil básico expiram em sete dias; publicar em **Production** e cumprir a verificação aplicável ao escopo restrito `drive.readonly` remove essa condição específica, mas não impede outras causas de revogação. Revisar usuários de teste, domínios, URLs públicas, política de privacidade e tela de consentimento antes da verificação.
- Para OneDrive e Notion, validar a duração real e eventos de revogação no ambiente do cliente. Nunca prometer um prazo único para integrações distintas. Alertar administradores sobre `reauth_required` e oferecer reconexão explícita.

Fontes oficiais Google: [escopos do Drive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [OAuth para aplicações web](https://developers.google.com/identity/protocols/oauth2/web-server), [expiração e limites de refresh tokens](https://developers.google.com/identity/protocols/oauth2), [boas práticas de tokens](https://developers.google.com/identity/protocols/oauth2/resources/best-practices).

## Retenção futura — proposta separada da política pública atual

Nenhum prazo abaixo está implementado ou prometido ao usuário. O responsável deve aprovar os valores, confirmar obrigações legais/contratuais e a configuração real da Railway antes de publicar uma política com prazos.

| Classe | Proposta inicial para discussão | Gatilho e verificação exigidos |
| --- | --- | --- |
| Conteúdo indexado e consultas salvas | Enquanto o escopo estiver ativo; apagar do banco ativo ao remover escopo. Definir prazo para índice preservado após desconexão (sugestão: 30 dias) e opção de remoção imediata. | Job idempotente para desconexões antigas, relatório de itens removidos e teste de isolamento por organização. |
| Sessões expiradas e estados OAuth consumidos/expirados | Expurgo diário após 30 dias. | Definir exceções de auditoria e verificar referências antes do job. |
| Trabalhos e logs de auditoria | 90 dias para detalhes de trabalhos; 12 meses para auditoria, sujeitos a revisão jurídica. | Separar registros necessários a segurança, custo e suporte; medir volume e testar exclusão. |
| Backups | Definir prazo e destino externos com restore testado; proposta inicial de 30 dias para cópias diárias. | Confirmar Railway e armazenamento externo, chave de criptografia, acesso, restauração e expurgo comprovável. A exclusão do banco ativo não elimina automaticamente backups. |
| Pedidos de titular | Registrar solicitação, identidade, escopo, decisão, execução e confirmação. | Aprovar procedimento humano, responsável, prazo legal aplicável e teste de ponta a ponta antes de prometer SLA. |

## Checklist restante para produção

- [ ] Aprovar os prazos de retenção e tratamento de backups; implementar e testar os processos antes de colocá-los na política pública.
- [ ] Concluir renovação de credenciais Google e testar expiração, revogação, falhas e reconexão; revisar estado OAuth em Production e exigências de verificação do Google.
- [ ] Implementar e monitorar scheduler, alertas de idade do índice e indicação de frescor na interface; medir SLO de 24 horas e custo antes de reduzir o intervalo.
- [ ] Testar backups e restauração reais da Railway, inclusive expurgo; confirmar região, acesso e processo para pedidos de exclusão.
- [ ] Fazer deploy autorizado das páginas públicas e conferir `/privacidade` e `/termos` na produção. Em 28/09/2026, `https://frontend-production-e02d.up.railway.app` ainda respondia 404 para as páginas, esperado antes do deploy.
- [ ] Fazer validação visual e responsiva após o usuário liberar essa etapa; a validação no navegador foi interrompida nesta tarefa e não foi retomada.
