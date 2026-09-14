# ADR-0004 - Acesso de staff da plataforma por grants temporários

**Status:** aprovado em 2026-09-11

## Contexto

A plataforma precisa de usuários internos que possam atender mais de uma
Company. Transformá-los em memberships normais de todos os tenants violaria o
isolamento, esconderia a finalidade do acesso e permitiria leitura silenciosa
de conteúdo de clientes.

## Decisão

- `Organization` continua sendo o tenant e Company é apenas sua denominação na
  interface. Todos os IDs persistidos expostos em URL e API são UUIDs.
- Um usuário de staff é identificado por um registro global separado de
  `Membership`; ele não recebe membership automática em nenhuma Company.
- Cada acesso exige um grant explícito contendo UUID do staff, UUID da Company,
  motivo, emissor, expiração e revogação. A seleção de Company do staff lista
  somente grants ativos.
- No piloto, grants de staff são **metadata-only**: permitem visualizar Company,
  pastas, estado de sincronização e códigos seguros de falha. Não permitem
  ler documentos/chunks, abrir links de fonte, pesquisar, fazer perguntas,
  operar Drive, ver consultas salvas ou administrar membros.
- Entrar em suporte registra auditoria; a interface exibe Company, motivo e
  prazo do grant em banner persistente. Tentativas sem grant, revogadas ou
  expiradas retornam 403 e não revelam dados do tenant.
- A criação/revogação de grants é uma operação de plataforma, não uma API de
  Owner/Admin de cliente. O primeiro corte terá serviço e testes; a console de
  operações interna fica fora da UI do cliente.

## Consequências

- Staff tem visibilidade suficiente para suporte operacional sem ganhar acesso
  implícito a conteúdo privado ou custos de IA.
- A eventual necessidade de acesso a conteúdo exigirá outro ADR, consentimento
  explícito, escopo mais estreito e auditoria reforçada.
- A auditoria deve diferenciar actor staff, Company alvo, motivo e ação para
  investigação posterior.
