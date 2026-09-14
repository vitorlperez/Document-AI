# ADR-0003 - Operação do piloto: sincronização, IA e limites

**Status:** aprovado em 2026-09-11

- Sincronização é manual e faz reconciliação completa de uma pasta e subpastas;
  não há polling nem Changes API no piloto.
- F-006 usa OpenAI via adaptadores próprios: `text-embedding-3-small` para
  embeddings e Responses API com `gpt-5-mini` para respostas. `store=false`;
  nenhum arquivo é enviado à API, somente chunks já autorizados.
- Antes de piloto, a organização deve ser informada do envio desses chunks. A
  configuração padrão de retenção da API deve ser avaliada pelo cliente; contas
  elegíveis podem solicitar controles de retenção à OpenAI.
- Defaults por organização/mês: 500 documentos ativos, 2 GB processados,
  1.000.000 tokens de embedding e 1.000 perguntas. Ao exceder, bloquear apenas
  a nova operação que gera custo, mantendo leitura e busca existentes.
