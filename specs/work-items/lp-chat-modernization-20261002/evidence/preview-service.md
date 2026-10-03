# Preview persistente — LP Arquivio direção A (H3)

Registrado por pane-361 em 2026-10-03, depois do ECONNREFUSED em `:5181` quando o pane que mantinha o `npm run start` foi fechado. Mudou só a infraestrutura de preview: nenhum TSX, CSS, asset, backend, CORS, auth ou config global foi alterado, e não houve commit nem push.

## URL

**http://127.0.0.1:5181/** (bind só em loopback)

## Mecanismo de persistência

Um container Docker dedicado e destacado (`docker run -d`), gerido pelo daemon do Docker Desktop, com `--restart unless-stopped`. Ele não depende de nenhum pane, PTY ou sessão de shell, sobrevive ao fechamento de todos os panes e volta sozinho quando o Docker Desktop reinicia, até alguém parar o container de propósito.

| Campo | Valor |
| --- | --- |
| Container | `arquivio-lp-preview-20261002` |
| ID | `2ec62ad1db9e0f3ef4b2400f093b83f6a2ab5bb05e982daa43e392b7ed6fa060` |
| Imagem | `arquivio-lp-preview:20261002` (`sha256:dbbaeb01fd515643076c86bd093db41318fe4dd7f65a2ce9c2587ce07fc920dc`), tag dedicada; a `arquivio-frontend:local` não foi tocada |
| Status na verificação | `running`, iniciado em 2026-10-03T04:18:38Z, restart `unless-stopped` |
| Porta | `127.0.0.1:5181 → 3000/tcp` |
| Runtime | `NODE_ENV=production`, `API_UPSTREAM_URL=http://host.docker.internal:8000` (backend real `document-ai-api-1` via host), sem secrets |
| Label | `mission=lp-chat-modernization-20261002` |

## Como foi construído (convenção existente, sem código novo)

Reutilizei o `frontend/Dockerfile.production` do repositório, sem modificá-lo: o estágio de build roda `npm ci` + `npm run build` com `VITE_API_BASE_URL=/api`, e o runtime roda `wrangler dev` sobre `dist/`, com o binding `API_UPSTREAM_URL` via `scripts/sites-env.mjs`. O resultado é a mesma configuração validada no QA (`/api` same-origin, BFF para o backend real).

```bash
cd frontend
docker build -f Dockerfile.production --build-arg VITE_API_BASE_URL=/api -t arquivio-lp-preview:20261002 .
docker run -d --name arquivio-lp-preview-20261002 --restart unless-stopped \
  -p 127.0.0.1:5181:3000 \
  -e API_UPSTREAM_URL=http://host.docker.internal:8000 \
  --add-host host.docker.internal:host-gateway \
  --label mission=lp-chat-modernization-20261002 \
  arquivio-lp-preview:20261002
```

Contexto de build: os fontes que entraram na imagem têm os mesmos hashes da versão aprovada no QA, `landing-page.tsx` sha256 `755fbc39…7d7a6` e `landing.css` sha256 `d59d1031…eeed1`. O `.dockerignore` existente exclui `node_modules`, `dist`, `.env*` e `.sites-runtime`. Log do build: `preview-service/docker-build.log`.

## Operação

| Ação | Comando |
| --- | --- |
| Status | `docker ps --filter name=arquivio-lp-preview-20261002` |
| Logs | `docker logs --tail 50 arquivio-lp-preview-20261002` |
| **Parar** | `docker stop arquivio-lp-preview-20261002` |
| Reiniciar | `docker start arquivio-lp-preview-20261002` |
| Remover | `docker rm -f arquivio-lp-preview-20261002 && docker rmi arquivio-lp-preview:20261002` |

Dependência: o backend `document-ai-api-1` precisa estar ativo em `:8000` para `/api/session`. A LP renderiza mesmo sem ele, mas a sessão falharia.

## Verificação (fresh, sem mocks nem intercepts)

| Verificação | Resultado |
| --- | --- |
| `curl http://127.0.0.1:5181/` | HTTP 200 |
| `curl http://127.0.0.1:5181/api/session` | HTTP 200, body `null` (visitante anônimo, backend real) |
| Navegador real Playwright Chromium, 1440×900 e 390×844 (`preview-service/service-browser-check.json`) | H1 literal, 3 casos, grade 517/715 (1440) e 358 (390), sem overflow, sem alerta de sessão, 0 erros de console, 0 requests falhos |
| Fontes e imagem | `manrope-latin-var.woff2` e `ibm-plex-sans-latin-var.woff2` 200 `font/woff2` (`document.fonts.check` true); `document-context.webp` 200 `image/webp`, slot renderizado |
| Screenshots | `preview-service/service-1440-fold.png`, `preview-service/service-390-fold.png` |
| Output igual à versão do QA | `dist/client` do container × build local validado: 49 × 49 arquivos. CSS (`index`, `product-app`, `legal-layout`), fontes e webp têm sha256 **byte-idênticos**. Os chunks JS diferem só pelo build ID aleatório (UUID) que o vinext gera a cada build e pelos nomes de chunk que dependem dele. Normalizando UUID e hash de nome de arquivo, os 49 arquivos ficam **idênticos** (`preview-service/dist-client-normalized-compare.txt`; listas brutas em `dist-client-{local,container}.sha256`) |
| Containers e servidores alheios | `document-ai-*` intocados (mesmos uptimes); nenhum processo de host em `:5181` além do proxy do Docker |

Não rodei a suíte inteira porque o código não mudou; ela continua em 88/88 pela QA final h-ek.

## Atualização H4 (motion), 2026-10-03

Imagem reconstruída com o build H4 e container recriado com a **mesma** configuração (porta 127.0.0.1:5181, `API_UPSTREAM_URL=http://host.docker.internal:8000`, `--restart unless-stopped`, mesma label). Nenhum outro container foi tocado.

| Campo | Valor atual |
| --- | --- |
| Container ID | `5998033254f302850c6774952f3710397d9f9833dad2a320edf08eb40d1a8b1b` |
| Imagem | `arquivio-lp-preview:20261002` = `sha256:5ed2aaf7a472f53c164391b2535e8aa434304dd55392ecc07a101c0aa1de3fb7` |
| Verificação | `/` 200; `/api/session` 200 `null`; LP pública sem mocks 26/26 checks; `dist/client` do container idêntico ao build local (normalizado) |

Os IDs da seção anterior referem-se ao build pré-H4 e estão obsoletos. Parar: `docker stop arquivio-lp-preview-20261002`.

## Atualização da re-review H4 final — 2026-10-03

O mesmo container dedicado foi atualizado uma segunda vez para que `:5181` reflita os fontes H4 mais recentes. Foi reconstruído com `VITE_API_BASE_URL=/api` e reiniciado com o mesmo bind, restart policy, upstream real e label. Nenhum container alheio foi tocado.

| Campo | Valor atual |
| --- | --- |
| Container ID | `7e5e014818e7ec664b483ceac91d6d5896360068486f33bba226cab5edb67222` |
| Imagem | `arquivio-lp-preview:motion-review-20261003` · `sha256:a700f3f0b90b2c8b511f76bf532364329514d93c1609e1f91d904f931e527cfd` |
| Estado/porta | `running`, `unless-stopped`, `127.0.0.1:5181 → 3000/tcp` |
| Upstream | `http://host.docker.internal:8000` |
| Verificação independente | `/` HTTP 200; `/api/session` real HTTP 200 `null`; browser público sem mock 19/19; M1–M5 fail-closed + LP adversarial 92/92 |
| Relatório | `motion-extension/review/round2/qa-report.md`; provas em `motion-extension/review/round2/evidence/` |

## Nota 2026-10-03 — endereço principal

O preview dedicado `arquivio-lp-preview-20261002` (porta 5181) não foi alterado. O serviço principal do projeto em `http://localhost:3000` agora serve o mesmo código; ver `main-frontend-rebuild.md`.
