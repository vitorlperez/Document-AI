# Relatório de QA independente — logos de integrações

Data: 2026-09-26  
Commit validado: `a21138aaf6e71aa29c192d612cb0c30ba38c2f2f` (`a21138a`)  
Escopo: `ProviderLogo`, consulta/biblioteca, catálogo de ferramentas, preservação da LP, interações, ProductApp e autenticação. Nenhum código de produto foi editado.

## Veredito

**APROVADO COM RESSALVA DE AMBIENTE — a correção dos logos atende ao objetivo e nenhum defeito funcional/visual atribuível ao commit foi confirmado.**

- Findings novos: 0
- Cobertura visual: Google Drive, OneDrive, Notion, GitHub e Microsoft Teams
- Build: PASS
- Testes: 7/7 PASS
- Lint: PASS com 2 warnings preexistentes
- Browser: fluxos e renderização PASS; 1 erro de console do runtime Vinext ao navegar da LP para `/login`, sem quebra funcional e sem nexo confirmado com o diff

## Resultado por check

| Check | Resultado | Evidência |
| --- | --- | --- |
| Diff e escopo | PASS | `git show a21138a`; somente CSS, LP, ProductApp e o novo `provider-logo.tsx`. Nenhum handler de auth/API ou callback de integração foi alterado. |
| Cobertura de marcas | PASS | `ProviderLogoName` cobre `google`, `google_drive`, `notion`, `onedrive`, `github` e `teams`; browser confirmou as cinco marcas no catálogo e três na biblioteca. |
| Google Drive | PASS | SVG com fills `#0F9D58`, `#F4B400`, `#4285F4`; renderizado na LP, biblioteca, catálogo e modal. |
| OneDrive | PASS | SVG com fills `#1686D9`, `#075CAD`; renderizado na LP, biblioteca e catálogo. |
| Notion | PASS | SVG branco/preto, borda preservada; renderizado na LP, biblioteca e catálogo. |
| GitHub | PASS | SVG `#24292F` renderizado no card “GitHub Markdown”. |
| Teams | PASS | SVG multicolorido renderizado no card “Slack e Microsoft Teams”. |
| Tamanhos/opacity/overflow | PASS | LP: caixa 25×25 e SVG 19×19; biblioteca: 18×18/26×26; catálogo: 26×26; todos `opacity: 1` e `overflow: visible`. |
| Responsividade | PASS | Catálogo sem overflow horizontal em 375×812 (`scrollWidth === clientWidth === 375`); captura desktop também sem corte ou sobreposição visível. |
| Texto acessível | PASS | LP usa `role="img"` e `aria-label` para Google Drive, Notion e OneDrive; logos junto a texto redundante no ProductApp são decorativos com `aria-hidden="true"`. |
| Preservação da LP | PASS | Browser confirmou dimensões anteriores efetivas (25px externo/19px SVG), labels e cores; sem overflow em 1440px. |
| Interações | PASS | Card Google abriu o dialog com logo e heading “Google Drive”; botão “Fechar” removeu o dialog. Callbacks de conectar/gerenciar/desconectar não mudaram no diff. |
| ProductApp/auth | PASS funcional / ressalva de console | Com `/api/session` mockado como anônimo, “Entrar” navegou para `/login` e exibiu “Sua equipe sabe. Encontre a resposta.”; ocorreu um erro de console do prefetch RSC do Vinext, sem falha da navegação. |
| Layer 0 HTTP | PASS | Build isolado servido em `127.0.0.1:8787`; `curl /` retornou HTTP 200. |
| Console/page errors | RESSALVA | LP, biblioteca e integrações: 0 erros. Transição LP→login: 1 `console.error` (`[vinext] RSC prefetch setup error: TypeError: p is not a function`), 0 `pageerror` e fluxo concluído. Não registrado como finding por não haver defeito funcional nem causalidade confirmada com o commit. |

## Evidência visual final

- Desktop (integrações): `TASK/evidence/qa-a21138a-desktop.png`
- Mobile (integrações): `TASK/evidence/qa-a21138a-mobile.png`
- Snapshot estruturado: `TASK/evidence/qa-a21138a-results.json`

As capturas finais mostram os cinco logos reconhecíveis, alinhados, sem opacidade indevida, sem clipping e sem overflow horizontal. A inspeção visual não encontrou regressão de layout.

## Verificação fresca

| Comando | Exit | Resultado |
| --- | ---: | --- |
| `VITE_API_BASE_URL=/api npm run build` | 0 | Build Vinext completo. |
| `npm run lint` | 0 | 0 erros; 2 warnings preexistentes em `product-app.tsx` (variável `_rows` e dependência de hook). |
| `node --test tests/*.test.mjs` | 0 | 7 passed, 0 failed. |
| `node /tmp/oc-qa-a21138a/qa.mjs` | 0 | LP, biblioteca, integrações, modal, login, medições e duas capturas concluídos. |
| `curl http://127.0.0.1:8787/` | 0 | HTTP 200. |

## Limitações e gap restante

- O backend real não estava disponível no ambiente isolado; biblioteca, integrações e usuário autenticado foram validados no frontend com respostas de API interceptadas e representativas. Não houve tentativa de OAuth real nem mutação de dados.
- O servidor já existente em `:3000` foi descartado como evidência porque `/api/session` retornava 404; o QA usou um build fresco do commit em `:8787`.
- `graphify` não estava disponível no PATH (`command not found`), então a revisão de relações foi feita pelo diff e busca estática direta.
- O erro de prefetch RSC na navegação para login merece observação em validação futura com o stack completo, mas não bloqueou o fluxo nem foi atribuído à alteração de logos.

skills: inline [qa-finding-protocol, oc-browser, oc-stamp]
