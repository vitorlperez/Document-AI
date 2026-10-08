# Handoff operacional — ler após aprovação H2

Estado: **direção completa; H2 pendente; não implementar ainda**. skills: inline [oc-design-dna, oc-browser]; PDF skill lida para autoria/renderização. Contrato recomendado A; B somente alternativa no PDF/research. Outputs exclusivamente nesta pasta.

Leia DESIGN.md → design-contract.md → STYLEBOARD.pdf → research.md → tokens.css/report. Baseline ../brief-baseline.md e source/landing-source.snapshot.txt são a autoridade de copy/wiring. Não esperar copywriter nem alterar seus arquivos. tokens.css é a fonte; design-tokens.json/tailwind-v4.css são derivados por `node source/derive-contract.mjs`.

Após H2, a primeira prova deve mostrar 1440×900 e 390×844: H1 literal, CTAs literais, uma única ProductPreview com caso normal ativo, resposta e primeira fonte visíveis, avisos fictícios juntos, sem overflow. Em 375×667, respeitar leitura/scroll antes da meta de dobra. Validar também 375/768/1024/1440, teclado, focus-visible, menu e FAQ abertos e os 3 casos; reduced-motion sem esconder conteúdo.

## Contrato de preservação

- `LandingPage({onLogin,onSignUp})` intocado: Entrar/Já tenho uma conta → /login; Criar conta/Começar com o Arquivio/Criar minha conta → onSignUp → `${API_BASE}/auth/login?screen_hint=sign-up`. Não substituir por href inventado.
- Manter skip link + marcas → #landing-main; nav desktop/mobile → #produto/#integracoes/#como-funciona/#perguntas; legal → /privacidade,/termos. Mesma lista de controles em todo viewport; não omitir Entrar no menu.
- 3 botões `aria-pressed`, `aria-live=polite`, respostas/fontes literais, Estúdio Aurora, Prévia ilustrativa, legenda inteira com Exemplos fictícios; nenhuma animação automática dos casos.
- 7 FAQ nativos details/summary, toda copy comercial, notas, 4 integrações e destinos; snapshots/hashes em preservation-lock. Sem preço/prova social/promoção novos.
- Preservar texto completo de Biblioteca/Buscar arquivos/composer/hints; são decoração de produto, não novos inputs ou botões operacionais. Reorganizar abaixo do núcleo do chat no mobile; nunca apagar para caber.
- Rotina e Como funciona continuam seções distintas; advertência de compartilhamento e FAQ sobre SharePoint não podem diminuir ou sumir.

## Arquivos e aplicação

Só após H2: landing-page.tsx + landing.css, selectors .landing-* dentro .landing-page. Não editar globals/brand/provider/product-app/rotas/auth/legal/app. Fontes propostas devem ser locais à LP; não usar layout.tsx/global font sem aprovação explícita adicional. CSS dos tokens entregue em :root é portátil **somente no contrato**; implementação deve escopar a .landing-page e não vazar para app. assets-policy.md regula logos existentes e slot opcional. Não importar DOM, screenshots, motion.css/js ou marcas da pesquisa.

## Proposta de migração futura ao app (não executada)

1. Em outro work-item, inventariar tokens atuais de app e estados reais. Comparar contraste e densidade antes de alterar globais.
2. Separar primitives (palette/type/spacing/radius/motion) e semantic slots (`chat-surface`,`chat-ink`,`source-surface`,`source-ink`,`focus-ring`,`danger`,`success`); mapear atuais para aliases sem renomear estados.
3. Provar tela de conversa com resposta/fontes e casos Loading/Empty/Error/Populated/Edge; formulário Untouched/Dirty-valid/Submitted-pending se aplicável. Não duplicar essa máquina de estados na LP.
4. Migrar componente a componente, manter marca compartilhada intacta até aprovação própria; typography UI IBM Plex Sans 16/1.55, display do app menor que hero. Testar auth/organização/permissões/layout em work-item separado.

A2/fallback e B-slot estão todos declarados. Tokens sem imagem dependem de zero assets. Hero não usa blur/glass; foco 3 px #965B0D, alvos 44 px, fonte longa quebra, contraste em contrast-report. Motion autoral em motion-plan.md, nunca choreography de referências.
