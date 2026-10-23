# LP do Arquivio — Pessoal + Empresa

Estratégia e copy. Nenhum código foi alterado. Preços e limites são **[A CONFIRMAR]**: são hipóteses para calibrar com o dono, não números do produto.

> **Revisão 2 — decisões do dono refletidas aqui** (modelo, limites, Stripe e comps em `docs/contas-pessoal-empresa.md`):
> - **Não existe plano grátis permanente.** O "grátis" é um **trial de 14 dias** `[A CONFIRMAR: 7 ou 14]`, **sem cartão** `[A CONFIRMAR]`, ao fim do qual a conta fica em **somente leitura** até assinar. Nenhum CTA diz "Começar grátis"; todos dizem **"Testar grátis por 14 dias"**.
> - **4 planos pagos**: Pessoal (Básico, Pro) e Empresa (Team, Scale). Empresa varia em assentos incluídos; empacotamento recomendado = **preço base + assentos incluídos + assento extra**.
> - **Cobrança via Stripe** (Checkout hospedado), em **BRL**, com **campo de cupom**.
> - Contas atuais seguem como estão (não aparecem na LP). "Contas especiais" (cortesias) são tratadas internamente, não são marketing.

---

## 1. Diagnóstico da LP atual

Arquivo único: `frontend/app/landing-page.tsx` (469 linhas), montado por `product-app.tsx:110` quando `pathname === "/"` e sem sessão (`page.tsx:5` só renderiza `ProductApp screen="home"`).

**Produto/posicionamento hoje:** "pergunte aos seus documentos, receba resposta com fontes". Conecta 5 fontes (Google Drive, OneDrive, Notion, SharePoint, ClickUp), somente leitura.

**O texto já é majoritariamente de equipe**, ainda que não diga isso:
- Hero: "A resposta está nos arquivos. Agora você sabe onde." (`landing-page.tsx:408`); subtítulo "Pergunte ao Arquivio…" (`:409`).
- Seção história: "O conhecimento da equipe já está nos documentos" (`:434`).
- FAQ: "Somente Owner/Admin da organização… pode conectar fontes" e "Todos os membros da organização podem consultar" (`:318-323`).
- Footer: "Conhecimento que encontra o seu contexto" (`:466`).

**Seções atuais, na ordem:** Header com âncoras Produto/Integrações/Como funciona/Dúvidas (`:399`) → Hero (`:406`) → Preview animado do produto (`:414`, `ProductPreview` `:100`) → Integrações "5 fontes. 1 lugar para perguntar." (`:417`) → História em 3 passos Encontre/Delimite/Confira (`:432-440`) → Como funciona em 3 passos (`:444-449`) → FAQ com 6 perguntas (`:454`, array `questions` `:318`) → Fechamento "Menos procura. Mais contexto." (`:459-461`) → Footer (`:466`).

**CTAs atuais (todos iguais, sem intenção):**
- Header: "Criar conta" (`:400`), "Entrar".
- Hero: "Começar com o Arquivio" + "Já tenho uma conta" (`:410`).
- Fechamento: "Criar minha conta" (`:462`).
- Todos chamam `onSignUp` = `router.push("/login?mode=sign-up")` (`product-app.tsx:107`).

**Lacunas:** não há seção de preços, não há segmentação de público, não há menção a uso individual, nem a segurança/admin/permissões como argumento comercial. O signup não carrega nenhum sinal de intenção.

---

## 2. Arquitetura proposta

### Decisão: LP única com seletor + página dedicada /empresas

| Opção | Veredito |
|---|---|
| Só um hero genérico para ambos | Descartado: dilui a mensagem e deixa o comprador de empresa sem argumento (admin, segurança, compra). |
| Duas LPs completas separadas | Descartado agora: dobra a manutenção, divide SEO e o produto ainda é um só. |
| **`/` com hero que fala com ambos + seção "Para você / Para sua equipe" + preços; `/empresas` dedicada** | **Recomendado.** `/` converte o individual (self-serve) e roteia o comprador de equipe para `/empresas`, que tem profundidade de venda e CTA "Falar com vendas". |

Evitar o seletor tipo toggle no hero (esconde conteúdo atrás de clique, ruim para SEO e para o preview animado). Preferir **dois cards lado a lado logo abaixo do hero** que são, ao mesmo tempo, o seletor e o primeiro roteador de CTA.

### Estrutura de `/`

1. **Header**: âncoras `Produto · Para quem · Preços · Dúvidas`; link extra "Para empresas" → `/empresas`. CTAs: "Entrar" e **"Testar grátis por 14 dias"**.
2. **Hero** (mantém a promessa atual, adiciona os dois públicos).
3. **Preview do produto** (existente, `ProductPreview`, sem mudança).
4. **Para quem: dois cards** (Pessoal / Empresa), cada um com CTA próprio.
5. **Integrações** (existente, `:417`).
6. **Casos de uso** em duas colunas, individual e equipe.
7. **Como funciona** (existente, 3 passos) com uma linha extra para equipe.
8. **Segurança e controle** (curta, só o que o produto já faz hoje).
9. **Preços**: tabela comparativa e faixa do caminho de upgrade.
10. **Prova social**: ver ressalva abaixo.
11. **FAQ** (existente, ampliada com perguntas de plano).
12. **Fechamento** com dois CTAs.
13. **Footer** com "Para empresas", "Preços", Privacidade, Termos, API.

### Estrutura de `/empresas`

Hero de equipe → o problema ("o conhecimento está espalhado em 5 ferramentas") → controle de acesso e admin → integrações com nuance de Owner/Admin → como a equipe entra (convites) → planos Empresa → FAQ de compras/segurança → CTA "Testar grátis por 14 dias" + "Falar com vendas".

### Prova social: ressalva

Não há depoimentos, logos ou números no repo. **Não inventar.** Enquanto não houver clientes citáveis, a seção vira "Por que confiar": fontes sempre visíveis, conexões somente leitura, originais intocados (o que `landing-page.tsx:413` e `:447` já afirmam). Quando existirem depoimentos reais, entram no mesmo bloco. `[A CONFIRMAR: ter pelo menos 2 clientes dispostos a serem citados]`.

### Voz da marca

Direta, calma, sem exagero. Fala de resultado concreto (achar a resposta, ver a fonte), nunca de "IA revolucionária". Evita "poderoso", "seamless", "next-gen". Mantém o tom da LP atual: frases curtas, `<em>` no segundo tempo da frase.

---

## 3. Copy por seção (PT-BR)

### 3.1 Header
- Âncoras: Produto · Para quem · Preços · Dúvidas · **Para empresas**
- Botão primário: **Testar grátis por 14 dias** · Secundário: Entrar

### 3.2 Hero (`/`)
- Eyebrow: SEU CONHECIMENTO, COM CONTEXTO *(mantém `:407`)*
- H1: **A resposta está nos arquivos.** *Agora você sabe onde.* *(mantém `:408`)*
- Subheadline: **Pergunte ao Arquivio sobre seus documentos, sozinho ou com o time inteiro. Receba uma resposta direta e os arquivos que a sustentam.**
- CTA primário: **Testar grátis por 14 dias** → conta pessoal
- CTA secundário (texto/ghost): **Testar com minha empresa** → conta empresa
- Nota abaixo: ✓ 14 dias para testar, sem cartão `[A CONFIRMAR: "sem cartão"]` · conexões somente leitura · originais preservados
- *Regra de copy:* nunca "grátis" sem o prazo ao lado; nunca "plano grátis". Após o trial é preciso assinar (a nota de rodapé do preço diz isso).

### 3.3 Para quem (seletor em dois cards)

**Card Pessoal**
- Título: **Para você**
- Texto: **Seus documentos do Drive, Notion e outros num só lugar para perguntar. Pare de abrir arquivo por arquivo.**
- Bullets: Conecte suas fontes em minutos · Respostas com a fonte ao lado · Fica só com você
- CTA: **Testar grátis por 14 dias** → `/login?mode=sign-up&tipo=pessoal`

**Card Empresa**
- Título: **Para sua equipe**
- Texto: **Todo mundo pergunta ao mesmo acervo, com as mesmas fontes. Você controla quem entra e o que está conectado.**
- Bullets: Convide membros e defina funções · Admins conectam as fontes da empresa · Limites maiores de documentos e consultas
- CTA: **Testar com minha equipe por 14 dias** → `/login?mode=sign-up&tipo=empresa`
- Link: Ver página para empresas →

### 3.4 Casos de uso

**Título:** *Do dia a dia à rotina do time.*

**Para você**
- **Estudar e pesquisar:** "Onde eu anotei aquela decisão?" Pergunte e abra o trecho exato.
- **Freela e consultoria:** Reúna contratos, briefings e entregas de clientes e consulte sem caçar pastas.
- **Vida organizada:** Notas do Notion e arquivos do Drive respondendo na mesma conversa.

**Para sua equipe**
- **Onboarding:** Quem entra no time pergunta em vez de interromper alguém.
- **Comercial e atendimento:** Achar política, preço e proposta anterior sem pedir no chat.
- **Operações e jurídico:** Confirmar o que foi combinado, com o documento original à mão.

### 3.5 Como funciona
Mantém os 3 passos atuais (`:447-449`). Acrescentar uma linha de rodapé:
**Em equipe:** o Owner ou Admin conecta as fontes uma vez; todos os membros consultam o que foi sincronizado.

### 3.6 Segurança e controle
- Título: **Seus arquivos não saem do lugar.**
- **Somente leitura.** O Arquivio não altera nem apaga nada nas suas ferramentas.
- **Fonte em toda resposta.** Se não houver evidência suficiente, ele diz que não achou.
- **Funções claras.** Na conta da empresa, só Owner e Admin conectam fontes e convidam membros.
- Link: Privacidade →

*(Só afirmar o que o produto já faz; "SSO" aparece em `custom-login.tsx:107` mas validar antes de prometer.)* `[A CONFIRMAR: SSO/SAML como recurso de plano]`

### 3.7 Preços

**Título:** *Teste por 14 dias. Escolha o plano quando fizer sentido.*
**Subtítulo:** Todo plano começa com um teste grátis de 14 dias, sem cartão `[A CONFIRMAR]`. Mude de plano ou de tipo de conta sem perder o que já conectou.

Toggle da tabela: **Para você | Para empresas** (ambas visíveis no desktop; abas no mobile). Toggle **Mensal | Anual** (anual ≈ 2 meses grátis `[A CONFIRMAR]`).

> Todos os valores e limites abaixo são âncoras para discussão. `[A CONFIRMAR]` (limites reais em `docs/contas-pessoal-empresa.md` §2.3).

**Para você (Pessoal)**

| | **Básico** | **Pro** |
|---|---|---|
| Para quem | Organizar seus arquivos | Uso individual intenso |
| Preço | **R$ 39/mês** `[A CONFIRMAR]` | **R$ 99/mês** `[A CONFIRMAR]` |
| Pessoas | 1 | 1 |
| Documentos indexados | 500 | 2.000 |
| Perguntas por mês | 200 | 600 |
| Fontes conectadas | 2 (Google Drive + upload) | 5 (+ OneDrive, Notion) |
| Automações · API · MCP | 3 · — · — | 10 · 1 chave · MCP |
| Suporte | E-mail | E-mail |
| CTA | **Testar grátis por 14 dias** | **Testar grátis por 14 dias** |

**Para empresas**

| | **Team** | **Scale** | **Enterprise** |
|---|---|---|---|
| Para quem | Times pequenos | Times em crescimento | Operações grandes |
| Preço base | **R$ 299/mês** `[A CONFIRMAR]` | **R$ 899/mês** `[A CONFIRMAR]` | Sob consulta |
| Pessoas incluídas | **5** | **20** | sob consulta |
| Pessoa extra | **+ R$ 49/mês** (até 15) `[A CONFIRMAR]` | **+ R$ 39/mês** (até 100) `[A CONFIRMAR]` | sob consulta |
| Documentos indexados | 3.000 | 20.000 | sob consulta |
| Perguntas por mês (de toda a empresa) | 1.000 | 5.000 | sob consulta |
| Espaços com acesso por pessoa | 25 | 200 | sob consulta |
| Fontes conectadas | 10, todas as integrações | 30 | sob consulta |
| API e MCP | ✓ | ✓ | ✓ |
| Histórico de auditoria | 180 dias | 365 dias | sob consulta |
| SSO | ✗ | `[A CONFIRMAR]` | `[A CONFIRMAR]` |
| Suporte | E-mail prioritário | SLA `[A CONFIRMAR]` | Gerente dedicado |
| CTA | **Testar grátis por 14 dias** | **Testar grátis por 14 dias** | **Falar com vendas** |

Linha de exemplo (calculadora estática abaixo da tabela, ajuda a vender o modelo base + extra): *"Time de 8 pessoas no Team: R$ 299 + 3 × R$ 49 = **R$ 446/mês**."* `[A CONFIRMAR]`

Notas de rodapé (obrigatórias — evitam a ideia de plano grátis):
- *O teste grátis dura 14 dias. Depois dele, a conta fica em modo de leitura (seus arquivos continuam lá) até você assinar um plano.*
- *Contas pessoais não adicionam pessoas. Para trabalhar em equipe, transforme sua conta em conta de empresa.*
- *Preços em reais (BRL). Pagamento por cartão `[A CONFIRMAR: boleto/PIX no plano anual]`.*

**Cupom**
- Abaixo da tabela, discreto: link **"Tem um cupom?"** → abre campo; o código viaja como `?cupom=CODIGO` até o cadastro e é aplicado no checkout (e o Stripe também mostra o campo "código promocional" na página de pagamento). Mensagem de validação: *"Cupom aplicado: 20% de desconto nos 3 primeiros meses."* / *"Cupom inválido ou expirado."* Cupons são criados e geridos no Stripe, não na LP.

**Faixa do caminho de upgrade** (logo abaixo da tabela):
- Título: **Começou sozinho? Leve o Arquivio para o time.**
- Texto: **Quando outras pessoas precisarem entrar, transforme sua conta pessoal em conta de empresa. Seus documentos e suas fontes conectadas ficam onde estão — e o que você já pagou no mês é abatido.** `[A CONFIRMAR: copy do abatimento só depois de validar a proration no Stripe]`
- CTA: **Transformar em conta de empresa** (logado) / **Ver como funciona** (anônimo, abre FAQ)

### 3.8 Prova social / confiança
Enquanto não houver depoimentos reais:
- Título: **Feito para você conferir.**
- Três afirmações verificáveis: *Toda resposta mostra os documentos usados.* · *Seus originais ficam no Drive, OneDrive, Notion, SharePoint ou ClickUp.* · *Se não houver evidência, o Arquivio avisa.*

### 3.9 FAQ (existentes mantidas, `:318-323`, e novas)

1. **Qual a diferença entre conta pessoal e conta de empresa?** A conta pessoal é só sua: um usuário, limites menores, ideal para uso individual. A conta de empresa tem membros, funções (Owner, Admin e Membro) e limites maiores, e é a forma de usar o Arquivio em equipe.
2. **Posso começar pessoal e depois virar empresa?** Sim. Converta sua conta pessoal em conta de empresa quando precisar convidar outras pessoas. `[A CONFIRMAR: o que é preservado na conversão]`
3. **Dá para voltar de empresa para pessoal?** Sim, quando a conta tiver só você (sem outras pessoas nem convites pendentes). Nada é apagado; o que passar do limite pessoal continua consultável, mas novos itens esperam você liberar espaço. `[A CONFIRMAR: cooldown de 30 dias]`
4. **Conta pessoal pode ter mais de uma pessoa?** Não. Para trabalhar com colegas, use a conta de empresa.
5. **Quem pode conectar as fontes na conta da empresa?** Somente Owner e Admin. Todos os membros consultam o que foi sincronizado.
6. **Meu time vê meus documentos pessoais?** Não. Conta pessoal e conta de empresa são separadas. Só é compartilhado o que for conectado à conta da empresa.
7. **O que acontece se eu passar do limite do plano?** O Arquivio avisa antes de chegar e não apaga nada. Você pode mudar de plano ou, na empresa, adicionar pessoas. `[A CONFIRMAR: comportamento ao estourar]`
8. **Existe plano grátis?** Não. Você testa por 14 dias sem cartão `[A CONFIRMAR]`. Depois, assina um plano para continuar adicionando arquivos e perguntando.
9. **O que acontece quando o teste acaba?** A conta fica em modo de leitura: você continua entrando, vendo e baixando seus documentos, mas não adiciona arquivos, não convida pessoas e não faz novas perguntas até assinar. Nada é apagado.
10. **Como funciona a cobrança da empresa?** Preço base mensal com as primeiras pessoas incluídas (5 no Team, 20 no Scale) e um valor por pessoa extra. Você adiciona ou remove pessoas quando quiser e o ajuste é proporcional. Pagamento por cartão em reais; os dados do cartão ficam com o Stripe, não conosco. `[A CONFIRMAR: nota fiscal; boleto/PIX]`
11. **Posso trocar de plano depois?** Sim, a qualquer momento: o valor é ajustado proporcionalmente. Para sair de uma conta de empresa para pessoal, a conta precisa ter só você.
12. **Tenho um cupom, onde uso?** No pagamento (campo "código promocional") ou antes, em "Tem um cupom?" na tabela de preços.
13. **O que acontece se o pagamento falhar?** Você é avisado e tem alguns dias `[A CONFIRMAR: 7]` para atualizar o cartão sem perder acesso. Depois, a conta fica em modo de leitura até regularizar. Nada é apagado.
14. **Posso falar com alguém antes de contratar?** Sim, use **Falar com vendas**. `[A CONFIRMAR: canal]`

### 3.10 Fechamento
- Eyebrow: COMECE PELOS SEUS DOCUMENTOS *(mantém `:460`)*
- H2: **Menos procura.** *Mais contexto.* *(mantém `:461`)*
- CTA 1: **Testar grátis por 14 dias** · CTA 2: **Testar com minha empresa**
- Linha: Precisa de algo sob medida? **Falar com vendas** →

### 3.11 Footer
Frase mantida (`:466`). Links: Para empresas · Preços · Privacidade · Termos de uso · API.

---

## 3.12 Página `/empresas`

- Eyebrow: ARQUIVIO PARA EMPRESAS
- H1: **O conhecimento do time, em uma só pergunta.**
- Subheadline: **Conecte Drive, OneDrive, Notion, SharePoint e ClickUp. Seu time pergunta, o Arquivio responde e mostra de qual documento veio.**
- CTAs: **Testar grátis por 14 dias** · **Falar com vendas**
- Nota: ✓ 14 dias sem cartão `[A CONFIRMAR]` · ✓ Somente leitura nas suas fontes · ✓ Você define quem entra · ✓ Fonte em toda resposta

**Seção "O problema"**
- Título: **Ninguém sabe onde está. Todo mundo pergunta no chat.**
- Texto: **Política num PDF, decisão no Notion, proposta no Drive. Cada pergunta vira uma busca em cinco lugares ou um colega interrompido.**

**Seção "Você no controle"**
- **Funções claras:** Owner, Admin e Membro. Só Owner/Admin conectam fontes e convidam pessoas.
- **Convites por link:** O time entra pelo convite e já consulta o acervo.
- **Escopo por pergunta:** Busque em tudo ou restrinja a uma ferramenta ou pasta.
- **Aviso honesto:** Sem evidência suficiente, a resposta diz isso.

**Seção "Atenção à permissão"** (transparência, vem do FAQ atual `:320`)
- **Todos os membros consultam o que foi sincronizado. Conecte materiais compartilháveis com a equipe.**

**Seção "Como o time começa"** (4 passos)
1. Comece o teste da empresa · 2. Conecte as fontes · 3. Convide o time · 4. Pergunte com contexto.

**Planos:** tabela "Para empresas" de §3.7 (Team, Scale, Enterprise) com a calculadora de pessoa extra e o campo de cupom.

**FAQ próprio:** cobrança · segurança · onde ficam os dados · SSO `[A CONFIRMAR]` · migração de conta pessoal · suporte.

**Fechamento:**
- H2: **Seu time já tem as respostas. Falta achá-las.**
- CTAs: **Testar grátis por 14 dias** · **Falar com vendas**

---

## 4. Mudanças no signup/onboarding

### O que existe hoje
- `onSignUp` → `router.push("/login?mode=sign-up")` (`product-app.tsx:107`).
- `SignIn` lê só `mode` (`product-app.tsx:110`). O formulário de cadastro pede só e-mail (`custom-login.tsx:99`; `/auth/register` recebe `{email, return_to}` em `custom-login.tsx:63`, `backend/app/api/auth.py:216-235`).
- Fluxo hospedado: `beginLogin(screenHint)` → `/auth/login?...` (`product-app.tsx:103`; `auth.py:291-301`).
- Existe `OrganizationOnboarding` (`organization-onboarding.tsx`) e picker de organizações (`product/org-picker`).

### Armadilha importante
`return_to` passa por `_safe_invitation_return_to` (`auth.py:66`), que só aceita caminho de convite. **Não dá para usar `return_to` para carregar a intenção.** A intenção precisa de canal próprio, igual ao cookie `document_intelligence_return_to` (`auth.py:224`).

### Proposta

1. **Parâmetros de intenção** `tipo` (`pessoal` | `empresa`; padrão `pessoal`; qualquer outro valor é ignorado), `plano` (`basico|pro|team|scale`, opcional) e `cupom` (código, opcional). Rotas:
   - Card Pessoal / "Testar grátis por 14 dias" → `/login?mode=sign-up&tipo=pessoal`
   - Card Empresa / "Testar com minha empresa" → `/login?mode=sign-up&tipo=empresa`
   - Botão de um plano da tabela → mesmas rotas + `&plano=pro|team|…` (pré-seleciona o plano que será assinado **ao fim do trial**; o trial começa igual).
   - Link com cupom → `&cupom=CODIGO` (validado só no checkout; o cadastro não depende dele).
   - "Falar com vendas" → rota/URL de contato `[A CONFIRMAR]`, nunca signup.
2. **Leitura:** `product-app.tsx:110` repassa `tipo` a `SignIn`; `SignIn` o preserva ao alternar entre `sign-in`/`sign-up` e o envia no corpo de `/auth/register` (campo novo `account_type`, validado com enum no backend).
3. **Persistência da intenção por todo o fluxo** (verificação de e-mail, SSO, OAuth): gravar em cookie httpOnly curto (mesmo padrão do `return_to`, `auth.py:224`) e também aceitar `tipo` em `/auth/login` (`auth.py:291`) para o caminho hospedado. Sem isso a intenção se perde no redirect.
4. **Primeiro acesso (onboarding) e início do trial:**
   - A criação da organização **inicia o trial de 14 dias** (`personal_trial`/`business_trial`); a faixa "Faltam N dias — Assinar" aparece no app.
   - `tipo=pessoal`: cria organização pessoal automaticamente (nome derivado do e-mail, como já se faz em `displayNameFromEmail` na LP), cai direto em conectar fontes. Sem tela de convite.
   - `tipo=empresa`: pergunta **nome da empresa**, cria a organização com o usuário como Owner, e a próxima etapa oferece **convidar membros** (pulável) antes de conectar fontes.
   - Sem `tipo` (usuário foi por "Entrar"/link antigo): tratar como pessoal.
   - Trial é **um por usuário e por tipo** (anti-abuso); quem já usou o trial vê direto "Assinar" em vez de "Testar grátis".
5. **Backend:** campo de tipo na organização (`account_type`: `personal` | `business`, nomes do modelo em `docs/contas-pessoal-empresa.md` §2.1), com limites e capacidades derivados do plano no servidor. Endpoints de convite devem retornar erro claro para `personal` (mensagem: "Contas pessoais não adicionam membros. Converta para conta de empresa.") e o frontend esconder a UI de convite.
6. **Conversão pessoal → empresa:** ação dentro do app (menu de conta, onde hoje há "Ir para o app"/sair, `landing-page.tsx:381`) que pede o nome da empresa e o plano/assentos, troca o tipo da organização in place (preservando fontes e índice) e abre o fluxo de convite. Com assinatura ativa é uma **troca de price na mesma subscription Stripe com proration**; em trial só muda o tipo (dias restantes preservados). É o destino do CTA "Transformar em conta de empresa" da faixa de upgrade.
6b. **Assinar / pagar:** a LP não coleta pagamento. Botões de plano de usuário **logado** levam a `/billing` (tela de assinatura do app), que cria um **Stripe Checkout Session** hospedado (BRL, locale pt-BR) com o plano, os assentos (Empresa) e o cupom (`?cupom=` ou campo "Tem um cupom?").
7. **Usuário logado na LP:** como hoje a LP é acessível logado (commit `82654be3`), na tabela de preços os CTAs mudam conforme o estado da org: em trial → "Assinar este plano"; assinante → "Seu plano atual" / "Trocar para este plano"; trial expirado → "Assinar para voltar a editar"; pessoal → "Transformar em conta de empresa" nos planos Empresa; conta `legacy` → "Assinar este plano" (voluntário).
8. **Invitation flow:** quem entra por convite (`invitations/[token]`) ignora `tipo`, sempre entra como membro da empresa que convidou.
9. **Analytics:** registrar `tipo`, `plano`, `cupom` (sim/não) e origem (`hero`, `card`, `pricing`, `closing`, `empresas`) no evento de cadastro; medir também **trial→assinatura** por origem.
10. **Testes:** estender o contrato de origem de `/auth/register` (commit `12baf465`) para cobrir `account_type` inválido, ausente e preservação de `tipo`/`plano`/`cupom` pelo fluxo de verificação; teste de lógica pura da LP: nenhum CTA contém "Começar grátis"/"plano grátis" (guarda de copy).

### Já decidido pelo dono (revisão 2)
Sem plano grátis permanente · 2 planos pessoais + 2 empresariais · Stripe · contas atuais intocadas · cupons e comps.

### Pendências que precisam de decisão do dono
- **Modelo de venda Empresa**: confirmar base + assentos incluídos + pessoa extra (recomendado) vs. faixas fechadas vs. por assento.
- **Valores finais em BRL** (mensal/anual) e limites de cada plano.
- **Trial**: 7 ou 14 dias; sem cartão (recomendado) ou com cartão; texto "sem cartão" só se confirmado.
- Mensagem de pós-trial (somente leitura) e se há perguntas de cortesia.
- Boleto/PIX na LP: só depois de validar com o Stripe; **nota fiscal** (quem emite).
- Conversão pessoal→empresa: o abatimento proporcional pode aparecer na copy? (validar a proration).
- SSO e auditoria: em que plano (hoje: Scale).
- Enterprise "sob consulta": existe no lançamento? Canal de "Falar com vendas".
- Existência de clientes citáveis para a seção de prova social.
- Política de cupons de marketing (quais códigos, duração, limite de resgates) — operada no Stripe pelo dono.
