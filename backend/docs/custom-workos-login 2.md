# Login personalizado com WorkOS

A tela `/login` usa marca, cores e tipografia do Arquivio. O backend integra o SDK Python WorkOS 10.3; nenhuma chave WorkOS ou segredo de proxy chega ao cliente. SSO, social, MFA, seleção de organização e políticas adicionais continuam no AuthKit hospedado, com o callback e o `state` existentes.

## Fluxos

- `POST /auth/password`: e-mail/senha; sessão local opaca somente para identidade verificada.
- `POST /auth/register`: recebe **apenas e-mail**, cria usuário sem senha quando necessário e solicita um link de definição de senha. Endereço existente recebe a mesma resposta e o mesmo fluxo de recuperação; nenhuma credencial existente é sobrescrita antes da prova de posse da caixa. O dono define a senha em `/login?token=…`. O WorkOS documenta que confirmar um reset também verifica um e-mail ainda não verificado. Não há senha escolhida pelo atacante para ser vinculada posteriormente por OAuth/SSO. Não se pressupõe que o WorkOS invalida senhas não verificadas ao vincular identidades: esse comportamento específico não foi demonstrado. Contas com senha criadas anteriormente devem usar recuperação para substituí-la.
- `POST /auth/verify-email`: mantém o desafio para contas existentes que precisam de confirmação; token pendente em cookie HttpOnly de 10 minutos. Há limite local compartilhado Redis de 5 tentativas/minuto por hash do token, além do limite de 60/IP/minuto. Trocar IP não reinicia o limite do token. Nenhum código/token aparece na chave Redis.
- `POST /auth/verify-email/resend`: exige contexto HttpOnly assinado, vinculado ao token pendente e válido por 10 minutos. Recupera o objeto de verificação e chama `send_verification_email` para o usuário associado; não aceita um e-mail/ID arbitrário do navegador. Limite adicional de 1 reenvio/minuto por verificação. Cookie expirado exige novo login.
- `POST /auth/password-reset`: resposta genérica, incluindo endereço inexistente; `sent` significa solicitação aceita, **não confirmação de entrega**.
- `POST /auth/password-reset/confirm`: define a senha e revoga **todas** as sessões locais do usuário associado ao subject WorkOS, incluindo sessões em outros dispositivos. Não autentica automaticamente. O WorkOS revoga automaticamente todas as suas sessões ativas quando confirma o reset, inclusive quando ainda não existe `AuthIdentity` local.

A revogação local é persistida antes da resposta de sucesso. Não há segunda chamada de revogação no provedor, fila, marcador que bloqueie login ou tarefa Beat de autenticação. Login por senha e callback hospedado podem criar uma nova sessão imediatamente após o reset bem-sucedido. A revogação pontual WorkOS no logout continua existente.

A migração experimental `20261008_0028` foi removida antes de qualquer aplicação externa. O head permanece `20261001_0027`; este login não acrescenta migração nem exige worker/Beat ou credenciais WorkOS nesses serviços para revogar sessões. Beat continua sendo usado pelo agendamento de ingestão existente.

Convites usam somente `/invitations/<token ASCII>`. O retorno é preservado também em `/login?return_to=…`, no fallback hospedado e após definir a senha quando o cookie de convite ainda existe. Em outro navegador/dispositivo, reabra o convite original: o link padrão de reset não transporta o convite. Retornos externos são rejeitados.

## Contrato de emissão de token e entrega de e-mail

Conferido na documentação oficial em 08/10/2026:

1. O SDK Python `reset_password(email=…)` chama `POST /user_management/password_reset`, que **cria o objeto/token** e cuja referência também marca envio de e-mail. E-mails AuthKit são enviados pelo WorkOS por padrão, conforme a configuração do ambiente. Logo, descartar o objeto retornado não é, por si só, um defeito de entrega.
2. Com e-mails padrão desabilitados em **Emails → Configuration → Manage**, a aplicação passa a ser responsável por entregar o link usando `password_reset_url`/token retornado ou os eventos e a API de consulta. Este app escolheu entrega gerenciada pelo WorkOS e NÃO implementa esse remetente alternativo. Não desabilite essa opção sem implementar e validar um provedor próprio.
3. `create_user` não é usado como prova de envio. Nosso cadastro solicita explicitamente o link pelo endpoint de reset. O template padrão será de recuperação/definição de senha; não prometemos um template exclusivo de boas-vindas.
4. Para login que retorna `email_verification_required`, a autenticação emite token/desafio e o WorkOS envia o código **se o e-mail de verificação estiver habilitado**. Se estiver desabilitado, a aplicação deve recuperar o código pelo `email_verification_id` e enviá-lo por outro provedor; esse modo não está implementado.
5. A documentação de limites estabelece 10 autenticações/minuto por e-mail ou challenge ID e limites adicionais de envio/entregabilidade. Não afirma um bloqueio permanente após um número fixo de códigos inválidos. O app possui seu próprio limite por token. `429` do SDK vira `429` local com `Retry-After` do provedor; sem esse valor, há espera inicial conservadora de 60 segundos, sem afirmar o momento de liberação do WorkOS.

Falta conferir o estado efetivo dessas opções no Dashboard. Não houve envio real, leitura de caixa ou teste real de cadastro/login/reset/SSO/MFA. A ausência dessa execução é uma pendência de validação, não evidência de que os endpoints não enviam e-mail.

## Fronteira de confiança do IP

`X-Forwarded-For`, `Forwarded` e `X-Real-IP` isolados nunca autorizam contexto na API.

O caminho implementado é: cliente → ingress Railway que define/substitui `X-Real-IP` → frontend → API. **O frontend deve ser acessível exclusivamente pelo ingress confiável**, sem um caminho alternativo que permita ao cliente fornecer esse header diretamente. Railway documenta `X-Real-IP` como IP remoto. Em outro ingress, não habilite o modo Railway sem estabelecer o mesmo contrato de substituição e impedir bypass.

O frontend só ativa essa fonte com `AUTH_CLIENT_IP_SOURCE=railway`. Ele descarta contexto fornecido pelo navegador e assina IP, timestamp, método e caminho com HMAC-SHA256 **somente para caminhos `/auth/*`**. `/api/session` (encaminhado a `/me`), healthcheck e demais rotas do proxy permanecem disponíveis sem `X-Real-IP` ou contexto assinado. A API exige assinatura válida com no máximo 60 segundos, IP válido e **peer TCP pertencente a `AUTH_TRUSTED_PROXY_CIDRS`**. Ela usa o IP verificado para Redis e WorkOS/Radar. Os CIDRs devem identificar o frontend ou sua rede estritamente delimitada; `/0` é rejeitado. HMAC continua obrigatório mesmo para um peer permitido. IPv6 é normalizado para não fragmentar buckets.

Configure, sem expor os valores:

| Serviço | Variável/requisito |
| --- | --- |
| Frontend | `AUTH_CLIENT_IP_SOURCE=railway`; `AUTH_PROXY_SECRET` aleatório de pelo menos 32 caracteres; upstream da API |
| API | Mesmo `AUTH_PROXY_SECRET`; `AUTH_TRUSTED_PROXY_CIDRS` dos peers do frontend; `ENVIRONMENT=production`; Redis; origem pública correta |
| ASGI | `uvicorn … --no-proxy-headers`, inclusive no start override da Railway; nunca `--forwarded-allow-ips=*` |

O Dockerfile já desabilita a interpretação implícita de forwarded headers. O wrapper Wrangler transporta as variáveis novas como bindings secretos por arquivo temporário privado (0600), sem segredo em argumentos CLI ou bundle do navegador. Com `ENVIRONMENT=production`, a construção de `Settings` falha antes de iniciar a API se faltar `AUTH_PROXY_SECRET` ou uma lista não vazia de `AUTH_TRUSTED_PROXY_CIDRS` válidos. Segredo curto/branco, CIDR inválido e rede `/0` são rejeitados com erro claro e sem valores secretos. Defina `ENVIRONMENT=production` explicitamente; o padrão local continua `development`. Worker, MCP e demais processos que construam o mesmo `Settings` em produção também precisam dessas duas variáveis, embora não executem revogação WorkOS. Contexto inválido em requisições de autenticação continua sendo rejeitado; não volta silenciosamente ao bucket global do proxy. Desenvolvimento local sem esse contrato usa o peer TCP e ignora headers forjados.

Valide a substituição de headers e os peers na infraestrutura real, junto à impossibilidade de bypass. Este checkout ainda usa Wrangler e diverge da main, que usa `vinext start`; esta correção não altera Dockerfile/runtime nem faz rebase. Reexecute o smoke no artefato/runtime final antes de publicar. Os testes locais de proxy simulam o ingress, não validam a Railway ao vivo.

## Token de reset e Referer

`/login` responde com `Referrer-Policy: no-referrer` e `Cache-Control: no-store`; a metadata também define `no-referrer` para subrecursos iniciais. O token é capturado apenas em memória no componente e removido da URL com `replaceState` antes do envio do formulário. Não é gravado em storage. Recarregar a página depois da remoção exige reabrir o link de e-mail; a conclusão substitui a navegação por `/login?password_reset=1`. Não foram encontrados scripts de terceiros na tela de login. O token necessariamente chega na URL da primeira navegação; não registrá-lo nos logs do ingress continua sendo requisito operacional.

## Configuração e validação externas

- Acesso autenticado com papel **Admin** ao ambiente correspondente ao `WORKOS_CLIENT_ID` para conferir e-mail/senha habilitado, verificação obrigatória, e-mails gerenciados de verificação/reset e **Applications → aplicação → Redirects → Password reset URL = origem pública + `/login`**, preservando o callback existente.
- Conta de teste designada e caixa controlada para validar entrega, cadastro, endereço existente, código, reenvio com o mesmo token pendente, reset e invalidação de sessões anteriores. Conta/organização com MFA, IdP/usuário SSO e Radar habilitado conforme política para testar os fallbacks reais. Desafios Radar conhecidos e desafios 4xx pendentes seguem para o AuthKit hospedado; erros de credencial continuam como erros.
- Configurar a confiança de proxy e `ENVIRONMENT=production`, origem pública, Redis e start command ASGI com `--no-proxy-headers`; comprovar peers, headers do ingress sem bypass e ausência de token nos logs. Não há migração nova nem fila de revogação a operar.

Evidências de execução e dados da demonstração local ficam em `TASK/evidence/f211/`, separados deste contrato permanente. Testes com gateway simulado não comprovam autenticação ou entrega WorkOS reais.

Referências oficiais:

- [Password reset: emissão, envio e verificação](https://workos.com/docs/reference/authkit/password-reset)
- [E-mails gerenciados e customizados](https://workos.com/docs/authkit/custom-emails)
- [Desafio de verificação e envio configurável](https://workos.com/docs/reference/authkit/authentication-errors)
- [Identity linking](https://workos.com/docs/authkit/identity-linking)
- [Limites](https://workos.com/docs/reference/rate-limits)
- [API de sessões](https://workos.com/docs/reference/authkit/session)
- [Headers do ingress Railway](https://docs.railway.com/networking/public-networking/specs-and-limits)
