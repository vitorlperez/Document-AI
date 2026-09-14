# ADR-0001 - Autenticação e convites do MVP

**Status:** aprovado em 2026-09-10

## Contexto

O MVP precisa de identidade verificada, sessões web e convites sem transformar o
provedor de autenticação na fonte de verdade de organizações e permissões.

## Decisão

- Usar WorkOS AuthKit Hosted UI, habilitando Google social login e magic link.
- Usar o fluxo authorization-code do AuthKit no backend FastAPI. O callback só
  aceita a identidade verificada entregue pelo provedor.
- Persistir a identidade externa em `auth_identities`; `provider_subject` é a
  chave estável. O e-mail é normalizado, mas não une identidades por si só.
- Criar sessões opacas próprias, persistindo apenas o hash do segredo; o cookie
  é `HttpOnly`, `SameSite=Lax` e `Secure` fora do ambiente local.
- O produto mantém `organizations`, `memberships`, papéis e convites internos
  como sua fonte de verdade. Toda autorização resolve a membership ativa no
  banco, nunca um papel ou organização enviado pelo navegador ou pelo token.
- Entregar e-mails de convite via Resend, atrás de uma porta de entrega. Token
  de convite é aleatório, tem sete dias de validade e só seu hash é persistido.

## Consequências

- A configuração de implantação precisa de `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`,
  URI de callback autorizada, `RESEND_API_KEY` e domínio remetente verificado.
- Essas credenciais não são necessárias para testes de domínio; adaptadores são
  substituíveis por fakes nos testes.
- O OAuth de Google Drive é uma credencial de integração futura e não reutiliza
  a sessão de login desta decisão.
