# Subagentes do Arquivio

Estes perfis são playbooks reutilizáveis para delegar trabalho com contexto curto.
Eles existem para reduzir leituras amplas do repositório e preservar o modelo mais
capaz para decisões de produto, segurança, arquitetura e integração final.

## Roteamento recomendado

| Perfil | Modelo preferido | Pode editar? | Uso |
| --- | --- | --- | --- |
| `graph-navigator` | leve | não | localizar código e relações por meio do Graphify |
| `impact-scout` | leve | não | avaliar impacto de uma mudança antes de implementá-la |
| `test-designer` | leve | testes e dossiê somente | criar matriz de cenários e testes focados |
| `ui-qa` | leve | não | conferir fluxo, acessibilidade e regressões visuais |
| `validator-lite` | leve | não | revisão independente final e evidências de aceitação |
| `small-change-implementer` | médio | somente arquivos explicitamente atribuídos | correções pequenas com teste focado |

## Regra de delegação

1. Envie ao subagente somente o objetivo, os arquivos/diretórios permitidos e o
   resultado esperado.
2. Para perguntas sobre o código, use `graph-navigator` antes de pedir leitura
   ampla de arquivos.
3. Não delegue segredos, arquivos `.env`, conteúdo de documentos de clientes ou
   tokens OAuth.
4. Mudanças de autorização, isolamento por organização, dados, integrações,
   arquitetura ou decisões de produto continuam com o agente principal.
5. Para features, siga `sdd-feature-delivery`: implementação e validação
   independente nunca são responsabilidade do mesmo subagente.
