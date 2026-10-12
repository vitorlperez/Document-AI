# Integrações

## Organização do catálogo

- **Arquivos:** Google Drive e OneDrive estão ativos; Dropbox permanece futuro.
- **Documentação:** Notion está ativo; GitHub Markdown, GitLab e Confluence permanecem futuros.
- **Projetos:** ClickUp está ativo (tarefas e Docs, leitura; ADR-0019) e permite uma escrita pontual: criar tarefa a partir de uma resposta, por ação humana aprovada e fora do agente/MCP (ADR-0020).
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
| Google Drive | Docs (export TXT), PDF, DOCX, Markdown, TXT, CSV, XLSX, PPTX, Sheets (export XLSX), Slides (export PPTX) |
| OneDrive | PDF, DOCX, Markdown, TXT, CSV, XLSX, PPTX |
| Notion | Markdown do adapter existente |
| ClickUp | Markdown: uma tarefa ou um Doc por documento (sem comentários nem anexos); escrita só "Criar tarefa a partir da resposta" (ADR-0020) |

Todos os formatos acima são indexados por padrão (a flag `NEW_FORMATS_ENABLED` foi removida na M55; o registry de `extraction/__init__.py` é a única fonte de elegibilidade). `ACTIVE_DOCUMENT_LIMIT` mantém o default 500.
Extração limita bytes a 100 MiB por arquivo (`MAX_FILE_BYTES`) e, para XLSX/PPTX, 40 MiB (`MAX_OOXML_BYTES`; ZIP descomprimido 120 MiB e razão 200, checado antes de abrir o contêiner), texto a 600.000 caracteres **lidos** (planilhas e apresentações param de ler ao esgotar o orçamento, não só ao gravar) e chunks a 2.000 por documento. Apresentações: até 400 slides. Planilhas: 20 abas, 5.000 linhas/aba, 60 colunas, 2.000 caracteres/célula; cada bloco carrega cabeçalhos e número das linhas. Abas ocultas são ignoradas; linhas/colunas ocultas são incluídas; fórmulas usam o valor em cache, sem calcular fórmulas. Slides preservam número e título; notas do orador são rotuladas separadamente. Imagens, macros, gráficos e formatos legados continuam fora do escopo.

Google limita exportações a 10 MB. `exportSizeLimitExceeded` é falha do arquivo, sem reconectar a fonte.
Arquivos que estavam `ignored/unsupported_file_type` e hoje são elegíveis são relidos no próximo sync (o sync força a leitura de ignorados cujo MIME normalizado passou a ser elegível). Para antecipar numa pasta, execute de `backend/`:
`.venv/bin/python -m scripts.requeue_ignored --folder UUID` (dry-run) e depois `--apply`.
O script só atua nas pastas explicitamente selecionadas, preserva arquivos não elegíveis e enfileira sincronização após commit. Compare proporção de ignorados, custo de embeddings e perguntas com citações antes de ampliar o rollout.
