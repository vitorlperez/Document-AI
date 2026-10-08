# Frontend do Arquivio

Aplicação web do Arquivio para organizações consultarem documentos indexados, navegarem pela biblioteca, administrarem equipe e configurarem fontes de conhecimento.

## Stack e execução

- React 19 e TypeScript
- Next.js 16 executado pelo Vinext/Vite
- Tailwind CSS 4 e componentes locais
- Node.js `>=22.13.0`

```bash
npm ci
npm run dev
```

O desenvolvimento portátil inicia em `http://localhost:5173`. O frontend usa `VITE_API_BASE_URL` ou `NEXT_PUBLIC_API_BASE_URL`; sem uma delas, usa `http://localhost:8000`.

No Docker local, acesse `http://localhost:3000`: a interface e a API usam essa mesma origem. O Compose define `VITE_API_BASE_URL=/api` e `API_UPSTREAM_URL=http://api:8000`; a porta interna 8000 não é publicada. Os callbacks locais usam `http://localhost:3000/api/...`.

Em produção com `VITE_API_BASE_URL=/api`, configure `API_UPSTREAM_URL` somente no runtime do servidor. A imagem de produção (`Dockerfile.production`) inicia `vinext start` (servidor Node, ~150 MB de RAM); o `npm start` local ainda usa Wrangler e converte essa variável em binding privado do Worker. Em ambos os casos ela não é incorporada ao JavaScript enviado ao navegador.

## Rotas e fluxos implementados

- `/`: apresentação pública ou redirecionamento para a primeira organização autenticada
- `/login`: entrada e criação de conta pelo fluxo de autenticação da API
- `/invitations/[token]`: aceite de convite
- `/companies/[companyId]`: conversa fundamentada em conteúdo indexado
- `/companies/[companyId]/library`: navegação, busca por nome e gestão do índice local
- `/companies/[companyId]/team`: membros e convites, disponível ao responsável da organização
- `/companies/[companyId]/integrations`: conexão, escopo e sincronização de fontes
- `/staff`: visão operacional restrita a staff, sem conteúdo dos clientes

As telas autenticadas consomem a API com cookies (`credentials: include`). A interface não consulta arquivos novos em tempo real durante uma pergunta: ela usa somente conteúdo já sincronizado e indexado no escopo selecionado.

## Provedores exibidos no produto

Os fluxos ativos no frontend são:

- Google Drive: OAuth, escolha de escopo, sincronização e reconexão
- OneDrive: OAuth delegado para conta pessoal, corporativa ou escolar, escolha de escopo, sincronização e reconexão
- Notion: OAuth, escolha de escopo, sincronização e reconexão

GitHub Markdown, Slack e Microsoft Teams aparecem apenas como “Em breve” e não oferecem conexão. O frontend não promete SharePoint, drives compartilhados/de grupo ou múltiplas contas OneDrive simultâneas.

## Estrutura relevante

- `app/product-app.tsx`: shell autenticado, conversa, biblioteca, equipe, integrações e staff
- `app/question-scope.tsx`: seleção do escopo usado nas perguntas
- `app/landing-page.tsx`: página pública
- `app/globals.css`, `app/product-layout.css`, `app/chat-workspace.css`: tokens e layout do produto
- `app/answer-display.ts`: limpeza defensiva do texto de respostas
- `tests/`: testes unitários executados pelo runner nativo do Node

## Checagens

```bash
node --test tests/*.test.mjs
npm run lint
npm run build
```

Antes de entregar mudanças de interface, valide lint e build e confira a responsividade nas larguras 375, 768, 1024 e 1440.

## Limites de responsabilidade

O frontend inicia OAuth pela API e apresenta estados retornados por ela; credenciais, tokens, isolamento por organização, ingestão, embeddings e autorização permanecem no backend. Não adicione segredos ou arquivos `.env` ao repositório.
