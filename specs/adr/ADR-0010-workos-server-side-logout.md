# ADR-0010 - Encerrar sessão WorkOS pelo backend

**Status:** aceito em 2026-09-24

## Contexto

O logout da F-034 revogava a sessão local e enviava o navegador à URL de logout do WorkOS. Esse caminho depende de uma URL de retorno configurada no painel WorkOS. No ambiente local, o navegador chegou a `app-homepage-url-not-found` após sair da rota `/companies/...`.

## Decisão

- Usar a API `user_management.revoke_session` do WorkOS no backend para encerrar a sessão remota identificada pelo `sid` já armazenado.
- Sempre revogar a sessão local, limpar o cookie e retornar a rota pública `/login` na origem configurada em `PUBLIC_APP_URL`.
- Substituir a entrada atual do histórico do navegador ao navegar para `/login`.
- Manter o cookie transitório que força reautenticação no próximo login, incluindo quando WorkOS estiver indisponível ou a sessão local for legada.

## Consequências

- O logout deixa de depender de homepage ou logout redirect do WorkOS para chegar ao login da aplicação.
- Falha da API WorkOS não impede a saída local; uma tentativa posterior de login exige autenticação fresca.
- Não há mudança de esquema, tokens armazenados, organização ou permissão.
- A decisão de F-034 de usar redirecionamento do navegador ao logout WorkOS fica substituída por esta ADR.
