# Integrações

## Organização do catálogo

- **Arquivos:** Google Drive e OneDrive estão ativos; Dropbox permanece futuro.
- **Documentação:** Notion está ativo; GitHub Markdown, GitLab e Confluence permanecem futuros.
- **Comunicação:** Slack, Microsoft Teams e outras fontes de decisões da equipe.

Integrações futuras podem aparecer como "Em breve", mas somente fontes com adapter e fluxo OAuth implementados devem permitir conexão.

## OneDrive

1. Owner/Admin conecta uma conta Microsoft pessoal, corporativa ou escolar com OAuth delegado e escolha explícita da conta no login.
2. O acesso cobre o OneDrive padrão da conta conectada; SharePoint, drives compartilhados/de grupo e atalhos estão fora desta versão.
3. O backend usa `Files.Read` e `User.Read`, cifra tokens e cursores, lista pastas pelo Graph e sincroniza alterações com delta.
4. O catálogo reutiliza seleção, sincronização e biblioteca existentes. Downloads e extração de documentos rodam em paralelo com concorrência limitada; embeddings seguem a fila e os limites já usados pelo produto.
5. O registro do app Entra deve aceitar contas em qualquer diretório organizacional e contas Microsoft pessoais. Callbacks públicos e segredos são provisionados por ambiente, conforme README e guia do piloto.

O conector está implementado para contas pessoais e organizacionais. Ainda é necessário observar rate limits e volumes reais em cada ambiente e decidir, em escopo próprio, se SharePoint ou drives compartilhados devem receber uma tela dedicada.

## Histórico de implementação

1. Contrato de adapter e refatoração mínima do Google Drive.
2. OAuth Microsoft e persistência segura.
3. Catálogo Graph e seleção de escopo.
4. Ingestão incremental e remoções.
5. UI ativa, testes de integração e rollout controlado.

O produto atual concluiu essa sequência para OneDrive; a lista é mantida como registro da decomposição adotada, não como backlog pendente.
