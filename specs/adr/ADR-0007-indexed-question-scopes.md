# ADR-0007 — Escopos de perguntas sobre conteúdo indexado

Status: accepted — solicitação explícita do usuário em 2026-09-22 (F-042).

O usuário autoriza expandir as perguntas de uma pasta para uma ferramenta inteira ou todas as ferramentas da organização. A seleção é resolvida no serviço de biblioteca, com associação ativa e filtros de organização em fontes, pastas, documentos e chunks. Não há chamada ao vivo para descobrir novos arquivos nem novos conectores nesta alteração.

A API de pasta permanece compatível. A API da organização exige `scope=provider` com provider ou `scope=organization` sem provider, retornando proveniência e contagens de cobertura. O seletor único inicia em todas as ferramentas e explica que somente conteúdo sincronizado/indexado participa. Perguntas salvas mantêm o contrato de uma pasta.

A recuperação ranqueia globalmente evidências relevantes, remove duplicatas de arquivos sobrepostos e mantém os limites de evidências existentes. Não se força uma citação de cada ferramenta quando não há relevância. Inventários limitados não podem se apresentar como listagem exaustiva. O modelo recebe ferramenta e arquivo de cada evidência; citações só apontam para evidências validadas.

Fontes desconectadas conservam dados já indexados segundo a política existente. Tentativas de perguntas continuam consumindo cota conforme o comportamento vigente, inclusive quando o provedor falha. Nenhuma migração ou alteração de retenção.
