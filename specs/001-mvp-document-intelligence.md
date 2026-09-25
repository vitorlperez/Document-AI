# 001 - MVP: Document Intelligence para pastas de trabalho

**Status:** Draft aprovado para implementação inicial
**Versão:** 0.1
**Escopo:** MVP horizontal para equipes de serviços
**Decisão de produto:** uma pasta compartilhada é a unidade de conhecimento. O produto não substitui o Google Drive.

## 1. Problema e resultado esperado

Equipes de agências, consultorias, software houses e operações perdem tempo procurando a versão certa de um briefing, escopo, decisão, relatório ou proposta. A informação existe no Google Drive, mas encontrar e conferir sua origem é lento e depende de quem conhece a estrutura de pastas.

O usuário deve conseguir conectar uma pasta de trabalho, fazer uma pergunta sobre uma pasta, ferramenta ou conjunto de fontes indexadas e receber uma resposta com evidências em menos de dois minutos, sem precisar procurar manualmente em múltiplos arquivos.

### Job to be done

> Quando preciso confirmar uma informação sobre um cliente, projeto ou área, quero encontrá-la e verificar sua fonte original rapidamente para poder tomar uma decisão sem depender de outra pessoa.

## 2. Público e hipótese de validação

### Cliente inicial

- Empresas de serviços com 20 a 150 pessoas.
- Uso recorrente de Google Drive para arquivos de clientes, projetos ou processos.
- Pelo menos uma pasta compartilhada cujo conteúdo possa ser visto por todos os membros que serão convidados ao produto.
- Três a cinco empresas piloto dispostas a fornecer feedback semanal.

### Hipótese

Se a plataforma indexar uma pasta de trabalho e responder perguntas com citações verificáveis, equipes reduzirão o tempo de busca e retornarão semanalmente para consultar a mesma base documental.

### Métricas de sucesso

| Métrica | Critério inicial |
| --- | --- |
| Ativação | 1 pasta com pelo menos 50 documentos indexados e 3 membros ativos por organização |
| Qualidade | 80% das respostas do conjunto de avaliação têm ao menos uma citação que sustenta a resposta |
| Uso | 2 ou mais membros retornam em semanas consecutivas |
| Evidência de valor | 30% das consultas resultam em abertura de fonte ou salvamento de consulta |
| Piloto | 3 empresas usam em trabalho real e ao menos 1 aceita pagar ou assinar uma carta de intenção |

## 3. Escopo

### Incluído

1. Organização, autenticação e convite de membros.
2. Conexão somente leitura com Google Drive e OneDrive Microsoft 365 por administrador.
3. Seleção explícita de uma ou mais pastas, arquivos avulsos da raiz ou todo o conteúdo acessível pelo usuário conectado, dentro da organização.
4. Sincronização de Google Docs, arquivos OneDrive compatíveis, PDF e DOCX presentes no escopo selecionado.
5. Extração de texto, indexação, busca por palavra-chave e busca semântica.
6. Perguntas em linguagem natural sobre uma pasta, uma ferramenta ou todas as fontes indexadas da organização (F-042).
7. Resposta apoiada por evidências recuperadas, com lista compacta dos documentos efetivamente citados e links para as fontes originais.
8. Estado de processamento, última sincronização e falhas por documento.
9. Consultas salvas por usuário dentro de uma pasta.
10. Auditoria mínima de ações sensíveis.

### Excluído

- Dropbox, S3, e-mail e upload de arquivos.
- No OneDrive da primeira versão: contas pessoais, SharePoint, bibliotecas compartilhadas, drives de grupo e atalhos.
- OCR, imagens escaneadas, PPTX, planilhas complexas e CSV/XLSX.
- Edição, movimentação ou reorganização de arquivos no Google Drive.
- Permissões herdadas por arquivo ou pasta do Google Drive.
- Agentes autônomos, alertas, relatórios, exportação, knowledge graph, comparação de documentos, versões e duplicados semânticos.
- Respostas sem citação ou ações automáticas sobre documentos.

## 4. Papéis e permissões

| Papel | Capacidades |
| --- | --- |
| Owner | Gerencia organização, administradores, membros e todas as pastas conectadas |
| Admin | Conecta Google Drive/OneDrive, seleciona pastas, inicia sincronização e visualiza falhas |
| Member | Pesquisa, pergunta e salva consultas nas pastas liberadas para a organização |
| Platform staff | Não é membro do tenant; acessa somente metadados operacionais de Companies explicitamente concedidas, com expiração e auditoria |

### Regra de permissão do MVP

O MVP não suporta ACL granular de arquivo. Um Admin só pode conectar uma pasta se confirmar que todos os membros convidados à organização podem visualizar seu conteúdo. Todos os Members da organização têm acesso a todas as pastas conectadas.

Platform staff não herda esse acesso: seu grant não permite conteúdo de
documento, busca, perguntas, links de fonte ou consultas salvas. Qualquer
expansão para conteúdo depende de uma decisão de produto e segurança separada.

Essa limitação deve aparecer claramente durante a conexão. Pastas de RH, financeiro ou qualquer conteúdo com acesso restrito não são elegíveis para o piloto.

## 5. Termos de domínio

| Termo | Definição |
| --- | --- |
| Organização | Tenant que agrupa usuários, fontes, pastas e dados indexados |
| Fonte | Integração autenticada com Google Drive ou OneDrive |
| Pasta de trabalho | Escopo selecionado em uma fonte de arquivos para indexação e consulta; pode representar cliente, projeto ou área |
| Documento | Arquivo elegível encontrado em uma pasta de trabalho |
| Chunk | Trecho de texto de um documento, com localização e metadados de origem |
| Citação | Referência a um documento usado na resposta, com identidade da ferramenta e link de origem; o trecho de suporte permanece no contrato interno/API para verificação, sem ser exibido na conversa |
| Consulta salva | Pergunta ou busca que um usuário deseja reutilizar em uma pasta |
| Sincronização | Processo assíncrono que descobre mudanças, atualiza documentos e recria índices necessários |

## 6. Fluxos funcionais

### Entrada pública e ativação

- A identidade visual do aplicativo acompanha o exemplo da landing: marca `arquivio.` com símbolo de camadas, fundo claro, tons de verde e painéis de fontes, conversa e biblioteca. O nome em texto corrido permanece Arquivio.
- A rota `/` apresenta a landing page Arquivio em português para visitantes, com exemplos explicitamente ilustrativos e sem promessas de integrações não disponíveis.
- Entrar abre `/login`; criar conta inicia o fluxo de cadastro do provedor de identidade existente. Uma sessão válida encaminha o usuário à organização ou ao onboarding, sem criar um novo sistema de autenticação.
- Falhas ao verificar a sessão apresentam mensagem compreensível e ação de tentar novamente.
- Biblioteca e conversa mantêm navegação por pastas; listagens paginadas devem permitir acessar as páginas seguintes. Trocas de organização/contexto não podem reaproveitar resultados obsoletos de outra seleção.
- Na conversa, a consulta de arquivos à direita pode ser ocultada e reaberta por um controle acessível; a ação de adicionar fonte fica na coluna da Biblioteca e é oferecida somente a Owner/Admin.
- Conversa e Biblioteca reutilizam o cabeçalho, os controles de fonte e o caminho da coluna Biblioteca; os painéis à direita de ambas podem ser ocultados e reabertos por controles acessíveis.
- A área de integrações e suas ações de conexão e gestão são restritas a Owner/Admin; todas as rotas privadas exigem sessão válida, mantendo públicos apenas os fluxos de entrada/autenticação e saúde necessários.

### F1 - Criar organização e convidar membros

**Dado** que uma pessoa ainda não participa de uma organização
**Quando** cria uma organização
**Então** ela se torna Owner e pode convidar Admins e Members por e-mail.

Critérios de aceite:

- Um e-mail só pode ter uma associação ativa por organização.
- Usuário desativado não consegue pesquisar, visualizar fontes ou receber resposta.
- A remoção de um membro é registrada em auditoria.

### F2 - Conectar Google Drive

**Dado** que um Admin está autenticado
**Quando** autoriza o Google Drive em modo somente leitura
**Então** o sistema armazena tokens de forma criptografada e lista pastas acessíveis para seleção.

Critérios de aceite:

- O escopo OAuth deve ser o menor necessário para leitura e metadados.
- A interface deve informar que arquivos não serão alterados.
- A interface deve exibir o aviso de permissão uniforme do MVP antes da primeira sincronização.
- Token inválido ou revogado deixa a fonte como `reauth_required` e impede novas sincronizações.

### F2a - Conectar OneDrive

**Dado** que um Owner/Admin autenticado usa uma conta Microsoft 365 corporativa/escolar
**Quando** autoriza o Arquivio em modo somente leitura
**Então** o sistema cifra tokens, identifica a conta e permite selecionar pastas do OneDrive padrão dessa conta.

Critérios de aceite:

- OAuth delegado com permissão de leitura mínima; nenhum acesso application-wide.
- Somente contas corporativas/escolares e o OneDrive padrão do usuário conectado nesta versão; SharePoint e bibliotecas compartilhadas não são incluídos.
- Listagens Graph seguem paginação; sincronizações incrementais aplicam alterações e remoções por delta sem avançar cursor se a ingestão falhar.
- Seleções sobrepostas não apagam um documento ainda presente em outra seleção do mesmo espaço.
- Conta revogada/expirada passa para `reauth_required`; a tela de integrações oferece reconexão.
- Itens incompatíveis são ignorados com motivo.

### F3 - Selecionar escopo e sincronizar

**Dado** que o Drive está conectado
**Quando** o Admin seleciona pastas de trabalho, opcionalmente arquivos avulsos da raiz, ou o modo explícito de todo o Drive e confirma a sincronização
**Então** um job assíncrono descobre a união deduplicada dos documentos elegíveis e os processa sem bloquear a interface.

Critérios de aceite:

- Cada pasta selecionada e suas subpastas são incluídas; a opção de raiz inclui somente arquivos diretamente na raiz.
- O modo “todo o Drive acessível” é exclusivo, apresenta o impacto de privacidade/custo e exige confirmação de acesso uniforme.
- Google Docs, PDF e DOCX são elegíveis; os demais formatos aparecem como ignorados com motivo.
- O sistema exibe `queued`, `syncing`, `ready`, `partial_failure` ou `failed` para a pasta.
- Enquanto a pasta estiver `queued` ou `syncing`, a interface mostra progresso acessível e atualiza o estado até a conclusão ou falha; ao falhar, o progresso termina e a mensagem de erro permanece visível.
- Um mesmo arquivo não pode criar documentos, chunks ou embeddings duplicados dentro do mesmo espaço de trabalho, inclusive com pastas sobrepostas.
- Documento removido do escopo deixa de aparecer em resultados após a próxima sincronização bem-sucedida.
- Owner e Admin podem remover um documento somente do índice local ou solicitar seu reprocessamento por UUID. Nenhuma dessas ações altera o arquivo original no Google Drive; uma sincronização posterior pode reimportar um arquivo que continuar elegível no escopo.
- Owner e Admin podem remover ou sincronizar novamente uma pasta de trabalho por UUID. Remover a pasta exclui somente o escopo local, seus documentos, chunks, embeddings e consultas salvas; a estrutura e os arquivos no Google Drive permanecem inalterados.

### F4 - Pesquisar e fazer perguntas

**Dado** que o contexto selecionado contém pastas `ready` ou `partial_failure` com conteúdo indexado compatível
**Quando** um Member faz uma pergunta sobre uma pasta, uma ferramenta ou todas as ferramentas da organização
**Então** o sistema resolve as pastas autorizadas dentro do escopo, recupera somente chunks dessas pastas e da mesma organização, gera resposta baseada neles e exibe citações identificando ferramenta e arquivo.

Chunking deve preservar fronteiras estruturais disponíveis (parágrafos, títulos, listas, tabelas e páginas), acrescentar nome do documento e seção disponível ao contexto de busca/embedding, sem alterar o trecho original usado como evidência. A seleção de evidências deve limitar repetição de chunks de um mesmo documento e permitir fontes distintas relevantes em perguntas amplas. O índice vetorial atual permanece uma decisão operacional separada e poderá evoluir após avaliação de escala.

Critérios de aceite:

- O escopo pode ser uma pasta, todas as pastas indexadas de uma ferramenta ou todas as ferramentas da organização. Isso não realiza busca ao vivo nas ferramentas nem garante leitura exaustiva do corpus; a resposta usa as evidências relevantes recuperadas.
- A interface informa conteúdo pendente e cobertura parcial; contextos vazios retornam evidência insuficiente. Consultas salvas continuam limitadas a uma pasta.
- A interface mostra progresso acessível ao carregar a biblioteca e os contextos autorizados ou enquanto a resposta está sendo gerada; em falha, o progresso termina e a mensagem/ação de recuperação permanece disponível.
- Busca textual considera título e texto extraído; busca semântica considera embeddings.
- Resultados e contexto do LLM são filtrados por `organization_id` e `workspace_folder_id` antes de qualquer ranking ou geração.
- A resposta deve dizer que não encontrou evidência suficiente quando a recuperação não sustentar uma resposta. O contrato deve distinguir, sem expor conteúdo, `no_indexed_content`, `no_compatible_embeddings`, `below_evidence_threshold` e `invalid_generation_output` para que a interface indique a ação adequada.
- Cada afirmação factual relevante deve ter uma ou mais citações. Sem fonte, a resposta não deve ser apresentada como fato.
- A área de fontes mostra uma lista compacta de documentos efetivamente citados, identificando nome, ferramenta e link original, sem exibir trechos de texto nem um limite numérico de citações.
- As atribuições no texto da resposta usam apenas números da lista de documentos (`fonte 1`, `fontes 1 e 2`), sem nome ou URL do documento. A lista é numerada; quando há mais de três documentos, o controle acessível permite expandir todos em linhas separadas e recolher a lista novamente.
- Links de origem aparecem somente na área de fontes, nunca no texto principal da resposta. O trecho de evidência continua disponível no contrato da API para verificação e compatibilidade, mas não é apresentado na conversa.
- Na área de fontes, cópias do mesmo arquivo são consolidadas pela origem. Documentos distintos permanecem identificáveis. A seleção de evidências para o modelo respeita um orçamento de texto para limitar custo e latência, sem um corte fixo por quantidade de citações.

### F5 - Salvar consulta

**Dado** que um Member realizou uma busca ou pergunta em uma pasta
**Quando** salva a consulta
**Então** ela aparece na sua lista de consultas salvas daquela pasta.

Critérios de aceite:

- Consulta salva pertence a um único usuário e a uma única pasta.
- Salvar uma consulta não salva a resposta, apenas a expressão de busca/pergunta e filtros.
- Usuário pode renomear ou excluir somente as próprias consultas salvas.

## 7. Regras de negócio e invariantes

### Isolamento

1. Toda entidade de negócio possui `organization_id`.
2. Nenhuma query de documento, chunk, citação, job ou consulta salva pode executar sem filtro de organização.
3. Uma resposta só pode usar chunks do conjunto de pastas autorizado e resolvido para o escopo selecionado na organização atual.
4. Links de origem só podem ser exibidos quando o documento pertence à mesma organização.

### Segurança e privacidade

1. Tokens OAuth são criptografados em repouso e nunca são retornados pela API.
2. O sistema mantém apenas metadados e conteúdo extraído necessários para busca e resposta; arquivos originais permanecem no Drive.
3. Ao desconectar uma fonte, nenhuma nova sincronização é iniciada.
4. Ao remover uma pasta de trabalho, documentos, chunks, embeddings e consultas salvas associados entram em processo de exclusão.
5. Logs não podem registrar conteúdo integral de documentos, tokens OAuth ou prompts contendo texto recuperado.
6. A organização é informada de que o conteúdo é enviado ao provedor de IA configurado para gerar embeddings e respostas.

### Qualidade e confiança

1. O modelo nunca deve inventar uma fonte.
2. A ausência de evidência é uma resposta válida.
3. A interface deve diferenciar resposta gerada da lista de documentos usados e dos links aos originais.
4. Documentos com falha de extração não entram no índice sem texto válido.
5. Todo documento indexado possui versão de processamento, hash de conteúdo e data de indexação.

### Operação e custo

1. Processamento ocorre por jobs idempotentes e assíncronos.
2. Reprocessamento ocorre somente para arquivo novo, modificado, com falha recuperável ou mudança de pipeline.
3. Cada organização possui limites configuráveis para documentos, bytes processados, embeddings e perguntas.
4. Falha de um documento não deve falhar a pasta inteira; a pasta fica `partial_failure` quando aplicável.

## 8. Modelo de dados mínimo

```text
organizations
users
memberships
data_sources
workspace_folders
workspace_folder_selections
documents
document_chunks
processing_jobs
saved_queries
search_events
audit_logs
usage_records
```

Campos obrigatórios por grupo:

- `data_sources`: `organization_id`, `provider`, `encrypted_credentials`, `status`, `connected_by`, `last_synced_at`.
- `workspace_folders`: `organization_id`, `source_id`, `external_folder_id` legado/de compatibilidade, `name`, `status`, `last_synced_at`.
- `workspace_folder_selections`: `workspace_folder_id`, `kind` (`folder`, `root_files` ou `all_accessible`), `external_folder_id` quando aplicável.
- `documents`: `organization_id`, `workspace_folder_id`, `external_file_id`, `name`, `mime_type`, `source_url`, `content_hash`, `modified_at`, `index_status`.
- `document_chunks`: `organization_id`, `workspace_folder_id`, `document_id`, `position`, `page_number`, `text`, `embedding`, `processing_version`.
- `saved_queries`: `organization_id`, `workspace_folder_id`, `user_id`, `name`, `query`, `filters`.

Índices obrigatórios:

- Índice único em `documents(workspace_folder_id, external_file_id)`.
- Índice em `document_chunks(organization_id, workspace_folder_id, document_id)`.
- Índice vetorial filtrável por `organization_id` e `workspace_folder_id`.
- Índice full-text sobre nome e texto extraído.

## 9. Contratos de API iniciais

```text
POST   /organizations
POST   /organizations/{id}/members/invitations
POST   /data-sources/google/oauth/start
POST   /data-sources/google/oauth/callback
GET    /data-sources/onedrive/oauth/start
GET    /data-sources/onedrive/oauth/callback
GET    /data-sources
POST   /workspace-folders
GET    /workspace-folders
POST   /workspace-folders/{id}/sync
GET    /workspace-folders/{id}/documents
POST   /workspace-folders/{id}/search
POST   /workspace-folders/{id}/questions
GET    /workspace-folders/{id}/saved-queries
POST   /workspace-folders/{id}/saved-queries
DELETE /saved-queries/{id}
```

Contrato de resposta de pergunta:

```json
{
  "answer": "O briefing define a campanha para o segundo trimestre.",
  "confidence": "supported",
  "citations": [
    {
      "document_id": "doc_123",
      "document_name": "Briefing - Cliente A.pdf",
      "page_number": 2,
      "excerpt": "A campanha será executada no segundo trimestre...",
      "source_url": "https://drive.google.com/..."
    }
  ],
  "retrieval_status": "sufficient_evidence"
}
```

Quando uma resposta verificável não puder ser produzida, `answer` é `null`, `citations` é uma lista vazia e `confidence` permanece `insufficient_evidence`; `retrieval_status` informa a causa segura. Falha de provedor ou limite de uso continua sendo um erro HTTP explícito, não uma evidência insuficiente.

## 10. Requisitos não funcionais

| Área | Meta inicial |
| --- | --- |
| Segurança | Isolamento por organização e pasta aplicado no banco e no serviço de retrieval |
| Latência de busca | p95 abaixo de 3 segundos sem resposta gerativa; p95 abaixo de 12 segundos com resposta gerativa |
| Processamento | 50 documentos padrão processados em até 10 minutos em condições normais |
| Observabilidade | Logs estruturados, correlação por job, métricas de falha, latência, custo e uso |
| Disponibilidade | Falha de integração ou IA retorna estado explicável e ação de recuperação |
| Acessibilidade | Fluxos principais navegáveis por teclado e com mensagens de erro compreensíveis |

## 11. Estratégia de teste e gates

### Antes de cada release

1. Testes unitários para isolamento de organização, regras de pasta e idempotência.
2. Testes de integração para OAuth simulado, sincronização, remoção e reprocessamento.
3. Testes end-to-end: criar organização, conectar fonte, indexar pasta, perguntar, abrir citação e salvar consulta.
4. Dataset fixo de avaliação com perguntas, documentos esperados e citações esperadas.
5. Teste negativo obrigatório: pergunta sem evidência deve retornar `insufficient_evidence`, não uma resposta inventada.
6. Revisão manual de 20 perguntas do piloto antes de mudar modelo, chunking, embedding ou reranking.

### Definition of Done para cada item

- Critérios de aceite implementados e automatizados quando possível.
- Telemetria e estados de erro adicionados.
- Sem regressão no dataset de avaliação do RAG.
- Sem acesso entre organizações em testes de autorização.
- Decisão de produto que altere escopo registrada neste documento ou em um ADR.

## 12. Sequência de implementação

1. Fundamentos: autenticação, organizações, memberships, auditoria e banco multi-tenant.
2. Integração Google OAuth e seleção de pastas, sem processamento ainda.
3. Fila, extração, documentos, chunks e estados de sincronização.
4. Busca textual e filtros por pasta.
5. Busca semântica, reranking, perguntas e citações.
6. Consultas salvas, telemetria, limites de uso e painel de falhas.
7. Piloto com empresas reais e evolução somente a partir de uso observado.

## 13. Decisões em aberto

- Provedor de autenticação e estratégia de convite.
- Provedor de LLM, embedding e política de retenção de prompts.
- Estratégia de sincronização incremental do Google Drive: polling, Changes API ou ambos.
- Limites iniciais de documentos, tamanho de arquivo, consultas e custo por organização.
- Formato do conjunto de avaliação e processo de revisão de citações.

## 14. Arquitetura e stack aprovadas

### Princípio arquitetural

O produto será um **monólito modular**: um repositório, um modelo de dados transacional e fronteiras explícitas por domínio. API e workers podem executar como processos independentes a partir do mesmo código para escalar carga de processamento sem introduzir microservices.

Não criar serviços distribuídos no MVP. Uma extração de módulo só é considerada após uma limitação mensurada de escala, disponibilidade, propriedade de dados ou cadência de deploy.

### Stack

| Camada | Escolha | Motivo |
| --- | --- | --- |
| Frontend | Next.js + TypeScript | Interface produtiva, autenticação web e tipos consistentes |
| API | Python 3.12 + FastAPI + Pydantic + SQLAlchemy | Ecossistema forte para documentos/IA, contratos explícitos e processamento assíncrono |
| Banco | PostgreSQL + pgvector + full-text search | Dados relacionais, filtros de tenant, busca textual e vetorial no mesmo sistema |
| Jobs | Celery + Redis | Filas, retries, jobs idempotentes e workers escaláveis sem bloquear API |
| Integração | Google Drive API e Microsoft Graph por adaptadores próprios | Conectores isolados atrás de interface de fonte |
| IA | Provedor configurável de embeddings, reranking e geração | Evita lock-in e permite trocar modelo com avaliação controlada |
| Infraestrutura | Docker, Docker Compose local, IaC e serviços gerenciados em produção | Reprodutibilidade local e evolução segura para cloud |
| Observabilidade | Logs estruturados, OpenTelemetry, métricas e error tracking | Medir custo, falha, latência e qualidade antes de escalar; métricas de retrieval não incluem pergunta, trecho, embedding ou segredo |

### Módulos de aplicação

```text
identity        -> usuários, sessões e convite
organizations   -> tenants, memberships e papéis
integrations    -> OAuth, tokens e adaptadores de fonte
workspaces      -> pastas de trabalho e escopo de acesso
ingestion       -> descoberta, extração, hash, chunking e jobs
knowledge       -> documentos, chunks, índices e retrieval híbrido
answers         -> perguntas, contexto, geração e citações
saved_queries   -> consultas reutilizáveis
audit_usage     -> auditoria, limites, custo e telemetria
```

Regras de fronteira:

1. Cada módulo expõe serviços e repositórios próprios; outro módulo não consulta suas tabelas diretamente.
2. `knowledge` só recebe uma referência de escopo já autorizada por `organizations` e `workspaces`.
3. `integrations` não conhece lógica de respostas ou embeddings.
4. Workers usam os mesmos serviços de domínio que a API; não contornam validação ou isolamento.
5. Comunicação assíncrona usa jobs e eventos de domínio versionados, não chamadas entre serviços remotos.

### Caminho de escala

1. API horizontalmente escalável e stateless.
2. Workers separados por tipo de carga: sincronização, extração e indexação; inicialmente no mesmo deploy lógico.
3. PostgreSQL com índices compostos por organização/pasta, full-text e HNSW para embeddings; medir antes de particionar ou adotar banco vetorial dedicado.
4. Cache apenas para metadados e resultados claramente escopados; nunca reutilizar contexto ou resposta entre organizações.
5. Abstrair `SourceProvider`, `TextExtractor`, `Embedder`, `Reranker` e `AnswerGenerator` para evoluir conectores e provedores sem reescrever o domínio.

### Orçamentos de performance

| Caminho | Meta |
| --- | --- |
| Listar pastas e documentos | p95 abaixo de 500 ms, excluindo Google Drive remoto |
| Busca híbrida | p95 abaixo de 2 s para uma pasta com até 10 mil documentos |
| Pergunta com resposta citada | p95 abaixo de 12 s, com timeout explícito para dependências de IA |
| Enfileirar sincronização | p95 abaixo de 300 ms |
| Processar 50 documentos comuns | até 10 min em condições normais |
| Recuperação de job | retry exponencial, limite configurável e estado terminal observável |

## 15. Workflow de Spec-Driven Development

Toda mudança de feature deve usar a skill local `sdd-feature-delivery`.

Cada feature possui um dossiê em `specs/work-items/<feature-id>.md`, criado pela skill antes de qualquer implementação. O dossiê registra o status, requisitos afetados, decisões, ownership de arquivos, plano de testes, comandos executados e decisão independente do validador.

Fluxo obrigatório:

1. O analista transforma a solicitação em critérios de aceite, riscos e checklist no dossiê.
2. A feature só entra em implementação quando o dossiê está `ready`, módulos/arquivos têm donos e decisões protegidas estão aprovadas.
3. O dono implementa a menor mudança coerente no módulo responsável; o engenheiro de testes cobre os critérios, negativos e isolamentos aplicáveis.
4. O validador independente revisa o diff e executa novamente os comandos relevantes, registrando sua própria evidência e findings no dossiê.
5. A feature só fica `done` sem findings bloqueantes, com comandos reproduzíveis e com toda mudança de comportamento refletida em spec ou ADR.

As funções de subagente são: analista de especificação, dono de implementação, engenheiro de testes e validador de feature. Nenhum agente pode marcar sua própria implementação como validada. Em árvore compartilhada, agentes só editam arquivos com ownership explícito; trabalho paralelo de escrita usa worktrees quando Git estiver disponível.
