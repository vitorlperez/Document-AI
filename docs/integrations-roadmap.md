# Integrações

## Organização do catálogo

- **Arquivos:** Google Drive e OneDrive estão ativos; Dropbox permanece futuro.
- **Documentação:** Notion está ativo; GitHub Markdown, GitLab e Confluence permanecem futuros.
- **Projetos:** ClickUp está ativo (tarefas e Docs, somente leitura; ADR-0018).
- **Comunicação:** Slack, Microsoft Teams e outras fontes de decisões da equipe.

Integrações futuras podem aparecer como "Em breve", mas somente fontes com adapter e fluxo OAuth implementados devem permitir conexão.

## OneDrive

1. Owner/Admin conecta uma conta Microsoft pessoal, corporativa ou escolar com OAuth delegado e escolha explícita da conta no login.
2. O acesso cobre o OneDrive padrão da conta conectada; drives compartilhados/de grupo e atalhos estão fora desta versão. Bibliotecas SharePoint/Teams usam o provider separado `sharepoint` (ADR-0016).
3. O backend usa `Files.Read` e `User.Read`, cifra tokens e cursores, lista pastas pelo Graph e sincroniza alterações com delta.
4. O catálogo reutiliza seleção, sincronização e biblioteca existentes. Downloads e extração de documentos rodam em paralelo com concorrência limitada; embeddings seguem a fila e os limites já usados pelo produto.
5. O registro do app Entra deve aceitar contas em qualquer diretório organizacional e contas Microsoft pessoais. Callbacks públicos e segredos são provisionados por ambiente, conforme README e guia do piloto.

O conector está implementado para contas pessoais e organizacionais. Ainda é necessário observar rate limits e volumes reais em cada ambiente. O SharePoint tem tela e provider próprios (ADR-0016, runbook `docs/integracoes/sharepoint-runbook-consentimento-admin.md`); piloto em tenant real e uso multi-espaço (R-A2) seguem pendentes.

## Histórico de implementação

1. Contrato de adapter e refatoração mínima do Google Drive.
2. OAuth Microsoft e persistência segura.
3. Catálogo Graph e seleção de escopo.
4. Ingestão incremental e remoções.
5. UI ativa, testes de integração e rollout controlado.

O produto atual concluiu essa sequência para OneDrive; a lista é mantida como registro da decomposição adotada, não como backlog pendente.


## Formatos indexáveis

| Fonte | Formatos |
|---|---|
| Google Drive | Docs (export TXT), PDF, DOCX, Markdown; com `NEW_FORMATS_ENABLED=true`: TXT, CSV, XLSX, PPTX, Sheets (export XLSX), Slides (export PPTX) |
| OneDrive | PDF, DOCX, Markdown; com `NEW_FORMATS_ENABLED=true`: TXT, CSV, XLSX, PPTX |
| Notion | Markdown do adapter existente |
| ClickUp | Markdown: uma tarefa ou um Doc por documento (sem comentários nem anexos) |

Formatos novos permanecem desligados por padrão. `ACTIVE_DOCUMENT_LIMIT` mantém o default 500.
Extração limita bytes a 25 MiB (ZIP descomprimido 200 MiB e razão 200), texto a 600.000 caracteres e chunks a 2.000 por documento. Planilhas: 20 abas, 5.000 linhas/aba, 60 colunas, 2.000 caracteres/célula; cada bloco carrega cabeçalhos e número das linhas. Abas ocultas são ignoradas; linhas/colunas ocultas são incluídas; fórmulas usam o valor em cache, sem calcular fórmulas. Slides preservam número e título; notas do orador são rotuladas separadamente. Imagens, macros, gráficos e formatos legados continuam fora do escopo.

Google limita exportações a 10 MB. `exportSizeLimitExceeded` é falha do arquivo, sem reconectar a fonte.
Para canário, habilite a flag no ambiente piloto, execute de `backend/`:
`.venv/bin/python -m scripts.requeue_ignored --folder UUID` (dry-run) e depois `--apply`.
O script só atua nas pastas explicitamente selecionadas, preserva arquivos não elegíveis e enfileira sincronização após commit. O próximo sync também força a leitura de arquivos ignorados cujo MIME normalizado passou a ser elegível. Compare proporção de ignorados, custo de embeddings e perguntas com citações antes de ampliar o rollout.
