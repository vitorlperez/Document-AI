# Claims audit — LP Arquivio chat-first

**Escopo:** auditar somente os claims já publicados na LP e impedir expansão no redesign.  
**Resultado:** nenhuma nova promessa comercial, funcional, técnica ou de integração foi adicionada.  
**Preços:** ausentes; nenhuma alegação de preço, plano, gratuidade ou teste foi criada.

## 1. Hierarquia de evidência usada

1. `frontend/app/landing-page.tsx` é a fonte literal da copy aprovada.
2. `brief-baseline.md` e `work-item.md` registram a decisão humana de preservá-la.
3. `specs/001-mvp-document-intelligence.md` e `specs/work-items/M31-landing-integrations.md` servem apenas para verificar limites já expressos; não autorizam acrescentar texto à LP nesta fase.
4. A empresa e os dados da prévia são declarados fictícios pela própria interface; não contam como prova social.

## 2. Registro de claims existentes

| ID | Claim literal ou conjunto inseparável | Tipo | Qualificador que deve permanecer | Decisão para o redesign |
| --- | --- | --- | --- | --- |
| C01 | `A resposta está nos arquivos. Agora você sabe onde.` | Posicionamento | A descrição seguinte restringe o resultado a uma resposta acompanhada dos documentos que a sustentam. | Preservar literal; não converter em garantia de encontrar qualquer resposta. |
| C02 | `Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.` | Resultado/capacidade | Deve aparecer junto da demonstração de fontes e do caso sem evidência. | Promessa dominante aprovada. Sem métricas, velocidade ou precisão adicional. |
| C03 | `Converse com seus documentos. Confira a origem.` | Experiência/capacidade | `Prévia ilustrativa` e `Exemplos fictícios.` identificam a demonstração. | Preservar. Não apresentar o transcript como cliente, caso real ou depoimento. |
| C04 | `4 fontes. 1 lugar para perguntar.` | Integrações/número | A lista fechada é Google Drive, OneDrive, Notion e SharePoint. | Preservar número e lista juntos. Não incluir provider adicional por analogia. |
| C05 | `Conexões de leitura · originais preservados` e `As conexões são de leitura e preservam os originais.` | Dados/risco | A FAQ explica que há conteúdo sincronizado/indexado e processamento de texto por IA. | Preservar sem extrapolar para “nenhum dado sai da fonte”, “zero armazenamento” ou promessa de compliance. |
| C06 | `A conversa usa somente as ferramentas e menções selecionadas na mensagem.` | Escopo da consulta | Composer, escopo do caso e menção precisam continuar visíveis. | Preservar. Não dizer que isso reproduz permissões originais por arquivo. |
| C07 | `Consulte todo o conteúdo indexado ou restrinja a pergunta a uma ferramenta ou pasta específica.` | Escopo/capacidade | `Somente conteúdo já indexado.` limita o universo consultado. | Preservar ambas; não reduzir o qualificador. |
| C08 | `O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta.` | Confiança/estado de falha | O terceiro caso não tem fontes; os casos com evidência exibem `Documentos utilizados`. | Preservar o estado negativo com paridade visual. Não prometer ausência de alucinação ou exatidão absoluta. |
| C09 | `Veja as fontes apresentadas com a resposta e abra os originais para verificar o contexto completo.` | Rastreabilidade/capacidade | Refere-se às fontes apresentadas, não a todos os arquivos conectados. | Preservar literal; não adicionar “citação em cada frase” ou cobertura total. |
| C10 | `Somente Owner/Admin da organização no Arquivio pode conectar fontes.` | Autorização | A consulta é descrita separadamente como disponível aos membros da organização. | Preservar capitalização e barra `Owner/Admin`; não dizer que qualquer membro conecta. |
| C11 | `No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso.` | Integração/permissão externa | “Teams” qualifica sites/bibliotecas SharePoint; não é promessa de chat ou integração Microsoft Teams autônoma. | Preservar literal e integral. Não criar card/logo `Microsoft Teams`. |
| C12 | `Todos os membros da organização podem consultar o conteúdo sincronizado. O Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe.` | Compartilhamento/risco | As três frases são um bloco inseparável. Há uma versão curta visível em Como funciona. | Preservar sem suavizar ou esconder em tooltip. |
| C13 | `Documentos Google, PDFs com texto, DOCX, páginas do Notion e Markdown.` | Compatibilidade | `Imagens escaneadas, planilhas e apresentações ainda não são indexadas.` | Preservar lista positiva e exclusões juntas. Não inferir OCR ou suporte a planilhas/apresentações. |
| C14 | `Depois da sincronização e do processamento em segundo plano. Alterações nos originais exigem uma nova sincronização.` | Disponibilidade/freshness | Não há promessa de tempo nem atualização instantânea. | Preservar; não usar “tempo real”, “sempre atualizado” ou duração inventada. |
| C15 | `O texto necessário para busca e resposta é processado pelo provedor de IA configurado. Confira se esse uso atende às políticas da sua organização.` | Tratamento de dados/risco | As duas frases são inseparáveis. | Preservar literal. Não nomear provedor, política ou certificação não presentes. |
| C16 | `Encontre arquivos e pastas pelo nome em todas as fontes conectadas.` | Busca/capacidade | `A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.` | Preservar junto da limitação; não prometer busca full-text nesse painel. |
| C17 | `Menos procura. Mais contexto.` | Benefício qualitativo | Não possui métrica, prazo ou prova quantitativa. | Preservar como fechamento; não anexar percentual ou tempo economizado. |

## 3. Claims de integração — limite fechado

### Aprovados e já visíveis

- `Google Drive`
- `OneDrive`
- `Notion`
- `SharePoint`

### Não autorizados por esta LP

- Microsoft Teams como conector independente ou acesso a chats do Teams;
- GitHub, Airtable ou qualquer provider apenas porque existe no código, documentação ou roadmap;
- “todas as ferramentas”, fora do rótulo de escopo do exemplo, como promessa de compatibilidade universal;
- integração bidirecional, escrita, edição, movimentação ou organização automática dos originais.

## 4. Adjacências obrigatórias

- C02 (resposta direta) deve compartilhar o primeiro contato com C08 (sem evidência) e com a visualização de `Documentos utilizados`.
- C04 (`4 fontes`) deve ficar imediatamente associado à lista das quatro fontes.
- C05 (leitura/originais) não pode apagar C12 (acesso de toda a organização) nem C15 (processamento pelo provedor de IA).
- C06/C07 (escopo) devem permanecer ligados ao composer, à menção e ao estado selecionado.
- C13 (formatos compatíveis) deve manter a frase de formatos não indexados no mesmo item de FAQ.
- `Prévia ilustrativa` e `Exemplos fictícios.` devem enquadrar visualmente todos os transcripts, não apenas o caso default.

## 5. Expansões proibidas sem nova aprovação

Não acrescentar, ainda que pareça coerente com o produto:

- superlativos (`melhor`, `mais inteligente`, `líder`, `revolucionário`);
- precisão, confiabilidade ou ausência de alucinações em termos absolutos;
- números de tempo economizado, produtividade, clientes, documentos, usuários ou taxa de acerto;
- urgência, escassez, contagem regressiva ou “comece hoje” como pressão temporal;
- segurança, criptografia, LGPD, residência de dados, certificação ou compliance não escritos;
- sincronização em tempo real, automática ou com frequência definida;
- reprodução de permissões originais por arquivo/pasta;
- suporte a OCR, imagens escaneadas, planilhas ou apresentações;
- integrações além das quatro listadas;
- preço, plano, desconto, gratuidade, trial ou garantia comercial;
- prova social atribuída ao `Estúdio Aurora` ou aos documentos fictícios;
- ação real nos controles ilustrativos da prévia.

## 6. Auditoria de ausência

| Categoria | Estado no baseline | Invariante |
| --- | --- | --- |
| Preços | Ausente | Continuar ausente. |
| Planos/pricing | Ausente | Continuar ausente. |
| Trial/gratuidade | Ausente | Continuar ausente. |
| Depoimentos/logos de clientes | Ausente | Não transformar a demo fictícia em prova social. |
| Métricas de performance/ROI | Ausente | Não inventar. |
| Urgência temporal | Ausente | Não inventar. |

## 7. Fontes localizadas

- Promessa, integrações, estados, avisos e FAQ: `frontend/app/landing-page.tsx:14-189`
- Decisão humana de preservação: `specs/work-items/lp-chat-modernization-20261002/brief-baseline.md:7-11`
- Registro de proposta/público e restrição de integração: `specs/work-items/lp-chat-modernization-20261002/brief-baseline.md:27-35`
- Preços ausentes: `specs/work-items/lp-chat-modernization-20261002/brief-baseline.md:37-39`
- Critério literal: `specs/work-items/lp-chat-modernization-20261002/work-item.md:39-48`
- Base de evidência insuficiente e fontes originais: `specs/001-mvp-document-intelligence.md:185,226`
- Limite SharePoint/Teams: `specs/work-items/M31-landing-integrations.md:5-10,23-38`

