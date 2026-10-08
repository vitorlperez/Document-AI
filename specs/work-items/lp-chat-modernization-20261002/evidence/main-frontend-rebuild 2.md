# Rebuild do frontend principal (localhost:3000) — 2026-10-03

Pedido do humano, repassado pelo piloto: "vc rebuildou as alteracoes, pq parece que nao mudou nada". O preview dedicado em `:5181` já tinha o código novo; o serviço principal `document-ai-frontend-1` em `localhost:3000` ainda rodava uma imagem de 2026-10-02 sem nenhuma das mudanças. Executor: pane-361. Nenhuma edição de código, compose, env ou backend; sem commit/push.

## O que foi feito (só o serviço `frontend`)

Segui a convenção do repositório: `docker-compose.yml` → serviço `frontend` (`image: arquivio-frontend:local`, `build: ./frontend`, porta `3000:3000`). O `frontend/Dockerfile` existente roda o dev server Vinext na porta 3000 e usa `frontend/.dockerignore` sem alteração.

```bash
docker compose build frontend            # exit 0 — log: main-frontend-rebuild/compose-build.log
docker compose up -d --no-deps frontend  # exit 0 — "Recreate / Recreated / Started"
```

Não rodei `down`, nada com volumes, nem reiniciei outro serviço. `--no-deps` impediu que api, worker, beat, redis, postgres e docling fossem tocados. Os IDs e uptimes deles estão iguais antes e depois do `up` (`containers-before-up.txt` / `containers-after-up.txt`; ex.: `document-ai-api-1 c186d59a7ac2 Up 25 hours (healthy)`). O preview `arquivio-lp-preview-20261002` (`7e5e014818e7`, imagem `arquivio-lp-preview:motion-review-20261003`) também ficou intacto e continua respondendo 200.

## Antes → depois

| Item | Antes | Depois |
| --- | --- | --- |
| Container | `8adf705e8a92…`, iniciado 2026-10-02T17:25:38Z | `95da528d03a491d4e92b0c4dbebca6d76131f2788a214896910a68279b5d0f10`, iniciado 2026-10-03T14:55:06Z |
| Imagem `arquivio-frontend:local` | `sha256:72e57dbba8b7e5b0b27ab550811b084e6c7d413c34a06cfe21c006d74ba12d1b` (criada 2026-10-02T17:25:33Z) | `sha256:8b90af61020fb977bcf6c4e39f0c5354b7fe524bcc59795ea50697aa2220639f` |
| Porta / comando / restart | `3000:3000`, `node scripts/run-framework.mjs dev --hostname 0.0.0.0 --port 3000`, restart `no` | idênticos (configuração do compose não foi alterada) |
| `app/landing.css` no container | `a37e7cd9…` (baseline `main`) | `a58bb3a9…` = árvore atual |
| `app/landing-page.tsx` | `7a534433…` | `de5dacad…` = árvore atual |
| `app/interface-motion.css` / `.ts` | **ausentes** | `f16cabdb…` / `000a7784…` = árvore atual |
| `app/conversation-tour.tsx` | `002981d0…` | `21b0c43b…` = árvore atual |
| `components/ui/sheet.tsx` | `63863cf2…` | `734cecaf…` = árvore atual |
| Markers servidos em `/app/landing.css` | nenhum de `Arquivio LP Display`, `lp-case-in`, `lp-disclosure-in`, `lp-menu-in`, `--lp-case` | todos presentes |
| `/app/interface-motion.css` | 404 | 200 com `aq-panel-in`, `aq-sheet-in`, `aq-backdrop-color-in`, `prefers-reduced-motion` |
| `/landing/fonts/*.woff2`, `/landing/document-context.webp` | 404 | 200 (`font/woff2`, `image/webp`) |

Paridade do código: `app/ components/ lib/ hooks/ public/ scripts/` e os arquivos de config/pacote batem nos dois lados. São 153 arquivos com sha256 idênticos entre a árvore local e `/app` no container (`local-src.sha256`, `container-src.sha256`, `src-parity.diff` vazio, exit 0). Arquivos de estado: `before-hashes.txt`, `after-hashes.txt`, `before-markers.txt`, `after-markers.txt`.

A imagem anterior (`72e57dbb…`) não existe mais no Docker local: ela perdeu a tag no rebuild e o Docker Desktop a removeu. Para voltar ao estado anterior seria preciso rebuildar a partir de `main`.

## Verificação fresca, sem mocks

| Verificação | Resultado |
| --- | --- |
| `curl http://localhost:3000/` | 200 |
| CORS do API para a origem principal (`curl -H "Origin: http://localhost:3000" localhost:8000/me`) | 401 (anônimo) com `access-control-allow-origin: http://localhost:3000`, o que mantém a configuração de auth/CORS existente |
| Seams dos modais servidos pelo dev server (`served-modal-seams.txt`) | `library-screen` e `access-settings`: `data-arquivio-motion-root` + `panel`; `integrations-screen`: `aq-motion-overlay` + `panel-scale`; `conversation-tour`: `tour-card` + `playSurfaceEntry`; `mobile-nav`: `motionProfile`; `sheet`: `sheet-panel`/`sheet-backdrop`; todos importam `interface-motion.css` |
| Navegador real Playwright, 1440×900 e 390×844 (`main-3000-browser.json`) | **18/18**: nova LP (stage, fontes Manrope/Plex carregadas), 3 casos, 7 FAQ, sem overflow, sem alerta de sessão; caso `lp-case-in` 200ms; FAQ `lp-disclosure-in` 200ms; menu móvel `lp-menu-in` 200ms; sessão real anônima (`GET localhost:8000/me` → 401), só requisições GET; console apenas com o 401 anônimo esperado |
| CTAs | Criar conta, Começar com o Arquivio e Criar minha conta → `http://localhost:8000/auth/login?screen_hint=sign-up` (navegação registrada e abortada para não iniciar auth real). Entrar e Já tenho uma conta → `/login`. Privacidade e Termos ok |
| Screenshots | `main-3000-1440-fold.png`, `main-3000-390-fold.png`, `main-3000-390-menu.png` |

Os modais autenticados não foram exercitados com auth real. A prova de comportamento deles continua sendo a QA com fixtures (98/98 testes + checks de navegador, já aprovados). Aqui a verificação é de entrega: o mesmo código, por hash, servido no endereço principal.

## Persistência e parada

O container é gerido pelo daemon do Docker (compose), sem nenhum vínculo com pane ou PTY: fechar os panes não o derruba. A política de restart continua `no`, como já estava no compose. Ele sobrevive ao fechamento dos panes, mas não volta sozinho se o Docker Desktop reiniciar (subir de novo com `docker compose up -d --no-deps frontend`). Parar: `docker compose stop frontend`.
