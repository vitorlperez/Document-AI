# M27 — Organization onboarding and conversation tour

## Product decisions

- New organizations start with a welcome screen and an optional integrations step. Back, next and skip are available; skipping completes setup.
- Setup belongs to the organization. Owners/admins can advance it; members go directly into the app. Partial setup resumes after reload, login or an OAuth callback.
- The integrations step mounts the existing `IntegrationScreen`, preserving OAuth, folder selection, access confirmation, sync queue, history and progress behavior without a second implementation.
- Completing setup always opens the normal conversation route. Sync can continue in the background; indexed content is required for questions.
- Four coachmarks explain the composer, tool selector, new conversation and navigation. Completion/skip is stored on the active membership. A native modal traps focus and Escape skips the tour. “Conhecer o app” allows replay.
- Migration `20260930_0026` backfills existing organizations/members as complete so established accounts keep their current experience.

## Fresh verification

| Check | Result |
| --- | --- |
| Backend `.venv/bin/pytest -q` | 911 passed, 13 skipped, exit 0 |
| Focused API + migration tests | 12 passed, exit 0; initial API tests failed 5/5 before implementation (404) |
| Backend Ruff on changed files | clean, exit 0 |
| Backend `.venv/bin/ruff check .` | exit 1: 18 preexisting findings, verified identical against an archived HEAD |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npm run lint` | exit 0 |
| Frontend `node --import /tmp/document-ai-onboarding-tools/node_modules/tsx/dist/loader.mjs --test tests/*.test.mjs` | 39 passed, 0 failed, exit 0 |
| Frontend `npm run build` | all five Vinext build stages complete, exit 0 |
| `docker compose up --build -d migrate api worker beat frontend` | exit 0; API healthy |
| `docker compose exec -T api alembic current` | `20260930_0026 (head)`, exit 0 |
| PostgreSQL backfill check | 1/1 existing organization and 1/1 existing membership preserved as complete |
| `graphify update .` | AST graph refreshed, exit 0; preexisting graph changes kept outside the feature commit |

Browser QA uses the actual frontend and FastAPI handlers. Only AuthKit, Drive's external provider and ingestion dispatch are replaced with test doubles. SQLite is isolated and stored in a temporary directory, with a separate connection per request. Mutations commit before returning progress. The actual Docker/PostgreSQL app was also rebuilt and migrated.

`browser-check.cjs` runs at 1440×900 and 390×900 and writes `browser-results.json`. It asserts signup → organization → welcome → connect/sync (desktop) or skip (mobile) → normal chat → all four coachmarks → logout → login directly into chat. It also covers persisted back/next/reload, OAuth return, a real HTTP 202 sync with one durable queued history entry, replay, Escape, dialog focus, coachmark alignment and viewport bounds. Screenshots remain local QA artifacts. The final run had zero browser exceptions and zero unexpected HTTP errors. Test totals include concurrent unrelated work in the shared checkout; those files are outside this commit.

## Reproduce browser QA

1. Install test-only tools outside the repo: `npm install --prefix /tmp/document-ai-onboarding-tools --no-save playwright tsx`.
2. In `backend/`: `PYTHONPATH=. .venv/bin/python ../artifacts/onboarding/qa-server.py`.
3. In `frontend/`: `VITE_API_BASE_URL=http://localhost:8011 npm run dev`.
4. From the repo: `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/browser-check.cjs`.

## Limits

- Browser QA does not create real WorkOS/Google accounts or process external documents. It proves the application flow, session persistence, OAuth callback integration and durable sync scheduling. Real provider consent and ingestion remain covered by existing integration behavior/tests.
- The full backend Ruff run reports 18 existing findings, identical in an archived HEAD; no new lint findings.
- 13 PostgreSQL-only tests skip when no disposable `TEST_DATABASE_URL` is configured; the new migration was applied to the running local PostgreSQL instance and tested separately for backfill/defaults/downgrade.
- No remote push was requested. Unrelated library files and existing graph/artifact changes are excluded from the commit.

Skills: inline [oc-builder, oc-stamp].
