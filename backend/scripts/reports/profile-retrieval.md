# Profile.pdf: reprodução e validação (2026-09-29)

O corte original estava em `backend/app/knowledge/questions.py:1394`, em
`excerpt=chunk.text[:500]`. Allstacks começa no caractere 667 do chunk 1.
O seletor de conteúdo também limitava cada documento a dois chunks. No seletor
de resumo, vizinhos eram descartados quando compartilhavam mais de 12 palavras,
mesmo quando traziam empresas distintas. Os cinco chunks reais têm 1999, 1713,
2024, 1698 e 431 caracteres e estão preservados na fixture de regressão.

A medição confirmou ainda que os scores híbridos de vários trechos relevantes
ficam abaixo de `MIN_EVIDENCE_SCORE=0.45`. Para a pergunta sobre duração na
Estoca, o trecho correto teve score 0.388. A seleção explícita de arquivo agora
permite ler seu conteúdo sob o orçamento total; selecionar uma pasta continua
usando o limiar de relevância. Nas buscas amplas, só os vizinhos imediatos do
melhor resultado suportado de cada documento entram na expansão, sem recursão.

`EVIDENCE_CONTEXT_CHARS` configura o orçamento total da evidência, incluindo
os wrappers de fonte. O default é 64000 caracteres, aproximadamente 16000
tokens. Os chunks entram inteiros por score; os que não cabem são omitidos.
Trechos adjacentes são mesclados na ordem original do documento e somente
conteúdo literal redundante/sobreposição de sufixo e prefixo é removido. O
alvo de 350 caracteres para resumos de cada arquivo permanece separado.

## Medição real

Banco PostgreSQL e embeddings de consulta reais da stack local, com Profile.pdf
explicitamente selecionado. Mesmos quatro vetores reais foram reutilizados
antes/depois. A geração foi mockada apenas para capturar os chunks enviados à
síntese. O SHA256 confirma que o código anterior do container era o de `3afc9bd`;
o código posterior foi executado em processo isolado com `PYTHONPATH`, sem
rebuild, restart ou mudança no processo da API. Cada transação foi revertida.

Recall = chunks corretos selecionados / chunks esperados. Precisão = chunks
corretos selecionados / todos os chunks selecionados. Os IDs originais são
contados mesmo quando os trechos foram mesclados. Fatos visíveis mede também
se nomes, datas e durações sobreviveram até o contexto de síntese.

| Pergunta | Antes: posições | Depois: posições | Recall antes → depois | Precisão antes → depois | Fatos visíveis antes → depois |
|---|---|---|---|---|---|
| Empresas e períodos | 0 | 0,1,2,3,4 | 0/3 → 3/3 | 0/1 → 3/5 | 0/8 → 8/8 |
| Último emprego | 0 | 0,1,2,3,4 | 0/1 → 1/1 | 0/1 → 1/5 | 0/2 → 2/2 |
| Duração na Estoca | nenhum | 0,1,2,3,4 | 0/1 → 1/1 | 0 → 1/5 | 0/3 → 3/3 |
| Duração na Cloudiabot | 3 | 0,1,2,3,4 | 1/1 → 1/1 | 1/1 → 1/5 | 3/3 → 3/3 |
| Total micro | 3 seleções | 20 seleções | 1/6 (16,7%) → 6/6 (100%) | 1/3 (33,3%) → 6/20 (30%) | 3/16 → 16/16 |

A precisão estrita caiu porque o contexto inclui as páginas contínuas do
perfil, inclusive a introdução e a continuação do último cargo. O ganho medido
é cobertura dos fatos, não precisão. Depois, as cinco páginas se tornam um
trecho contínuo de 7869 caracteres, sem cortes. Esta amostra pequena não mede
qualidade geral do corpus nem garante precisão de respostas em outros arquivos.

Relatórios brutos: `profile-retrieval-before.json`, `profile-retrieval-after.json`,
`profile-retrieval-replay.json` e `profile-retrieval-metadata.json`.
No replay direto com gpt-5-mini, as quatro respostas citaram Profile.pdf com
fonte vinculada: quatro empresas/períodos, Allstacks como último emprego,
Estoca com 2 anos e 5 meses e Cloudiabot com 1 ano e 5 meses, conforme registrado.
O termo `Present` foi tratado como registro do documento, sem atualizar datas
ou recalcular a duração em relação a hoje.

Também foi executada a pergunta original `Qual a ultima empresa que o Vitor
trabalhou?` pelo **fluxo único completo** (`AgentService`, classificador real,
limite de 25 segundos e LLM real), com o arquivo mencionado e histórico vazio.
O classificador escolheu `ask_content`; a resposta foi **Allstacks**, com
`June 2025 - Present (8 months)` e `(fonte 1)`. A citação do Profile.pdf reteve
seu link e a proveniência dos cinco chunks. Evidência em
`profile-agent-replay.json`. A transação foi revertida, sem persistir conversa.

## Executar novamente

Na raiz do projeto, antes do rebuild, medir o código atualmente instalado:

```sh
docker compose cp backend/scripts/profile_retrieval_eval.py api:/tmp/profile_retrieval_eval.py
docker compose cp backend/scripts/profile_retrieval_cases.json api:/tmp/profile_retrieval_cases.json
docker compose exec -T api python /tmp/profile_retrieval_eval.py --cases /tmp/profile_retrieval_cases.json --output /tmp/profile-before.json --embedding-cache /tmp/profile-embeddings.json
```

Para comparar com o checkout atual sem alterar os serviços:

```sh
docker compose exec -T api mkdir -p /tmp/profile-retrieval-eval
docker compose cp backend/app api:/tmp/profile-retrieval-eval/
docker compose exec -T -e PYTHONPATH=/tmp/profile-retrieval-eval api python /tmp/profile_retrieval_eval.py --cases /tmp/profile_retrieval_cases.json --output /tmp/profile-after.json --embedding-cache /tmp/profile-embeddings.json
docker compose exec -T -e PYTHONPATH=/tmp/profile-retrieval-eval api python /tmp/profile_retrieval_eval.py --cases /tmp/profile_retrieval_cases.json --output /tmp/profile-replay.json --embedding-cache /tmp/profile-embeddings.json --replay
```

O script exige exatamente um Profile.pdf indexado; use `--document-id` se
houver várias cópias. Ele usa um membro ativo da organização e reverte os
registros de uso. Os vetores de consulta permanecem somente em `/tmp`; não
estão no commit. O diretório de comparação deve ser novo na primeira cópia;
para repetir após novas alterações, copie `backend/app/knowledge/questions.py`
sobre o arquivo correspondente da cópia isolada.

## Verificação e aplicação

Regressões com LLM mockado verificam texto além de 500 caracteres, Allstacks,
mescla de vizinhos, remoção de overlap literal, ordem cronológica, orçamento
por score, expansão limitada, gate de pasta, configuração e prompt com
enumeração factual citada. A abstenção por falta de fato continua testada no
fluxo único do agente, com fontes e links preservados.

- `cd backend && TEST_DATABASE_URL=<banco descartável local> .venv/bin/pytest -q`:
  **452 passed, zero skipped, exit 0**, quatro avisos de depreciação, 22,01 s.
  Foi criado e removido um banco separado para os oito testes PostgreSQL;
  o banco da aplicação não foi usado para criar ou apagar tabelas de teste.
- Ruff nos arquivos Python alterados: exit 0, `All checks passed!`.
- `docker compose config --quiet`: exit 0.
- `.tools/graphify/bin/graphify update .`: exit 0, atualização AST sem LLM.
  Os arquivos sujos de graphify e as alterações de outros workers não entram
  neste commit.

A API e o worker continuam usando a imagem anterior. Para aplicar a correção,
rebuild da imagem backend e recriação de **api** e **worker** são necessários;
frontend e migração de banco não são necessários. A stack não foi derrubada
e não houve push. Os commits fb8003f, 7d3df7e, e983721 e 3afc9bd permanecem
ancestrais de HEAD.
