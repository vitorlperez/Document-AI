# arquivio-identity-20261003 - Migração integral da identidade visual Arquivio (LP + app)

**Status:** cancelado pelo humano em 2026-10-03 após rodadas de H4. Frontend revertido byte a byte à baseline (174/174 sha256) e localhost:3000 rebuildado com a identidade antiga. O redesign completo ficou guardado em `arquivio-identity-20261003/build/redesign-backup/` (patch dos arquivos rastreados + tar dos novos). PDFs, capturas e evidências do estudo foram descartados.

## Source and outcome

- Source specification: intake aprovado pelo humano (opção 1) nesta missão; `specs/001-mvp-document-intelligence.md` (produto, papéis, integrações); entregas anteriores `specs/work-items/lp-chat-modernization-20261002*` (LP direção A, motion H4, F-206 a F-210).
- User outcome: LP e app inteiro com uma única identidade visual nova, coerente e moderna (cores, tipografia e estrutura livres, tema escuro opcional se aprovado no H2), mantendo marca/nome, textos, funções, permissões e destinos, e preservando as melhorias de LP/motion já entregues.
- Non-goals: mudar nome/marca (`arquivio.` + Layers3), copy, funções, endpoints, payloads, permissões, papéis, destinos, regras de dismiss/busy, OAuth/auth; criar telas/modais/funcionalidades; migrar primitives shadcn não usadas só por existirem; remover/regredir LP e motion H4; alterar backend/infra.
- Baseline: [arquivio-identity-20261003/baseline/BASELINE.md](arquivio-identity-20261003/baseline/BASELINE.md) · `ROUTES-ACTIONS.md` · `STATES-COMPONENTS.md` · `FILE-MAP.md` · `BASELINE-CONTACT-SHEET.pdf` · hashes.

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |
| Escopo LP + app inteiro, direção visual livre (pode abandonar cores atuais), reorganização visual autorizada | humano | aprovado (intake opção 1) | brief da missão |
| Manter marca/nome, textos, funções, permissões e destinos | humano | aprovado | brief |
| Preservar LP direção A e motion H4 entregues | humano | aprovado | QA h-ek / motion QA |
| Sem prazo adicional | humano | aprovado | brief |
| Duas direções em PDF + escolha de cores/tema/estrutura | humano | **aprovado (H2, 2026-10-03)** | `direction/STYLEBOARD.pdf`; direção única A+B (Margem de evidência, azul/papel, nav lateral) |
| Tema escuro (sim/não, escopo) | humano | **aprovado (H2, 2026-10-03)** | Claro/Escuro/Sistema no app inteiro, padrão Sistema, `arquivio:theme` local; LP/login/legal sempre claros (`direction/THEME-H2.md`) |
| Fontes novas globais (self-hosted OFL) | humano | **aprovado (H2, 2026-10-03)** | Newsreader (títulos) + Source Sans 3 (UI), WOFF2 subset locais, `font-display: swap` |
| F-208/F-209/F-210 corrigidos dentro da migração | humano | proposto, pós-H2 | STATES-COMPONENTS §4; sem mudar autorização/dados |
| Preview final no frontend principal `localhost:3000` + gate H4 | humano | aprovado | brief; rebuild só do serviço `frontend` (`main-frontend-rebuild.md` como precedente) |

## Ready checklist

- [x] Acceptance criteria written in Given/When/Then form. (abaixo; finalizar paleta/tema após H2)
- [x] Owning module, API/data impact and failure states identified. (frontend apenas; seams em FILE-MAP §2; **impacto API/dados: zero**)
- [x] Authorization, tenant and workspace-folder impact assessed. (nenhuma mudança: gates de papel listados em ROUTES-ACTIONS §2 devem permanecer idênticos)
- [x] Performance and observability impact assessed. (fontes self-hosted com subset/`swap`; sem libs novas previstas; CSS por tokens; sem telemetria nova)
- [x] Protected decisions approved or marked not applicable. (H2 aprovado em 2026-10-03)

## Scope

- **Dentro:** tokens semânticos globais (cor, tipo, raio, sombra, foco, estados, tema), wordmark/cores de marca dentro da marca existente, shell/navegação (reorganização com os mesmos itens/papéis), LP, auth/entrada, onboarding, conversa/composer/fontes/@, Biblioteca (lista/grade/menu/M1), Integrações/catálogo/M2, Equipe, Desenvolvedor/chaves/M4, staff, legal, toasts/alertas, menu móvel/M5, tour/M3, estados (empty/loading/populated/invalid/pending/success/error/long/responsivo), F-208/F-209/F-210.
- **Fora:** backend, API, auth/OAuth, dados, permissões, copy, rotas, novos fluxos.

## Modules and ownership (pós-H2)

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | esta baseline + test matrix (pane-361) |
| Implementation owner (pane-361, mesmo worker) | `frontend/app/globals.css`, `layout.tsx` (fontes), `brand.*`, `product/*.tsx`, CSS de tela (`chat-workspace`, `product-layout`, `integration-cards`, `library-view`, `tools-sidebar`, `sync-status`, `onboarding`, `mobile-chat`, `mention-composer`, `question-scope`, `legal`), `landing.*`, `interface-motion.*` (só se necessário), `components/ui/sheet.tsx` (já seam), `modal-dismiss.tsx` (F-210), `public/` (fontes/assets próprios) | migração visual |
| Test engineer | `frontend/tests/*` (contrato LP, motion, novo teste de paridade de ações/papéis e de tokens) | testes |
| Media (se H2 pedir) | `frontend/public/**` | assets próprios, sem terceiros |
| Feature validator | Read-only | gate independente + H4 |

## Acceptance criteria and test matrix

| # | Given / When / Then | Test layer | Evidence (baseline → esperado) |
| --- | --- | --- | --- |
| AC1 | Dada qualquer tela da baseline, quando migrada, então todas as ações de `ROUTES-ACTIONS.md` continuam presentes, com o mesmo rótulo acessível, handler e destino | teste estático de paridade (extração `tools/extract-actions.py` antes×depois) + browser | 299 ocorrências → mesma contagem/label/destino (diferenças só de markup visual, justificadas) |
| AC2 | Dado cada papel (owner/admin/member/staff), quando navega, então vê exatamente as mesmas abas, ações e restrições da matriz | browser fixture fail-closed | ROUTES-ACTIONS §2 |
| AC3 | Dada a LP, quando renderizada, então copy, CTAs, destinos, 3 casos, FAQ, avisos e contrato de testes passam; a direção visual pode mudar | `landing-contract.test.mjs` + browser público real | 5/5 + checks públicos |
| AC4 | Dado motion H4, quando há interação, então os timings 180–220 ms e o reduced-motion ficam iguais ou melhores; nada anima dados/polling | `interface-motion.test.mjs` + harness motion | 98/98 testes; checks de navegador |
| AC5 | Dada a nova paleta, quando aplicada, então texto ≥4.5:1, UI/foco ≥3:1, estados não dependem só de cor | browser (contraste computado) | 0 falhas AA |
| AC6 | Dadas as larguras 375/390/768/1024/1440, quando percorridas, então não há overflow horizontal, copy cortada nem alvo <44 px | browser | 0/0/0 |
| AC7 | Dado tema escuro (se aprovado), quando o sistema/usuário escolhe, então todas as telas têm tokens dark e contraste AA; sem flash de tema | browser | — (H2) |
| AC8 | Dado F-208/F-209/F-210, quando corrigidos, então M4 fica centralizado, `failed:null` não mostra "()" e o fundo do M2 fica inerte, sem mudar dados/autorização/dismiss | browser fixture | STATES-COMPONENTS §4 |
| AC9 | Dado o frontend principal `localhost:3000`, quando rebuildado só o serviço `frontend`, então ele serve o código migrado por hash e o browser público real fica limpo | hash + browser público | precedente `main-frontend-rebuild.md` |
| AC10 | Dada qualquer chamada de rede no QA, quando executado, então só fixtures locais ou GET públicos reais; zero dados/contas reais | harness fail-closed | 0 inesperados/0 externos |

## Definition of ready (implementação)

H2 aprovado (direção, paleta, tipo, tema, estrutura do shell); lista final de tokens; decisão sobre fontes; confirmação de que F-208/F-209/F-210 entram; baseline e hashes congelados (feito).

## API / data impact, estimates, performance, reversibility

- **API/dados:** zero mudanças previstas (CSS/markup/tokens). Nenhum endpoint, payload, permissão ou armazenamento novo.
- **Estimativa:** não aplicável (sem prazo adicional, por decisão do humano); trabalho em fases por domínio (tokens → shell → conversa → Biblioteca → Integrações → Equipe/Dev/staff → auth/legal → LP) com QA por fase.
- **Performance:** fontes self-hosted em subset (~25–50 KB cada) com `font-display: swap`; nenhuma lib nova prevista; meta: sem regressão de LCP/CLS na LP e no shell.
- **Reversibilidade:** mudanças isoladas no frontend em branch dedicada; tokens centralizados permitem rollback por arquivo; baseline de hashes (`baseline/source-hashes.sha256`) e capturas para comparação; o frontend principal pode ser reconstruído a partir de qualquer commit.

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `git checkout -b design/arquivio-identity-20261003` | ok; HEAD a43dbdd; working tree idêntico | pane-361 | — |
| `init-work-item.sh arquivio-identity-20261003 …` | exit 0 | pane-361 | — |
| `graphify query "…screens routes components…"` | exit 0 | pane-361 | — |
| `tools/extract-actions.py` | 299 ocorrências | pane-361 | — |
| `node /tmp/oc-arquivio-identity-baseline.cjs` (localhost:3000, fixtures fail-closed) | exit 0; 33 telas; 0 inesperados; 0 externos; 0 overflow | pane-361 | — |
| PDF contact sheet | gerado | pane-361 | — |
| Fase 1 build (pane-400): `tsc` 0 · `eslint` 0 · `npm run build` 0 · LP 5/5 · motion 10/10 · extração **301** (299+seletor) · rebuild só `frontend` · paridade 146 arquivos · Playwright localhost:3000 42/42 | ver `build/phase1/PHASE1.md` | pane-400 | — |

## Validator report

- Blocking:
- Important:
- Suggestions:
- Independent evidence:
- Gate decision:
