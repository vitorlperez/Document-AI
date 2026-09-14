# Document AI

An AI-powered document intelligence platform for organizations. It connects document sources, ingests and indexes files, and provides a secure company library for search, retrieval, and AI-assisted questions.

## Highlights

- Connect Google Drive folders and control the scope of synchronized content
- Extract text from PDF and DOCX files and process ingestion asynchronously
- Search company knowledge with text and semantic retrieval
- Ask AI-assisted questions grounded in the indexed document library
- Manage organizations, workspaces, invitations, and platform staff access
- Track usage and expose health checks for operational visibility

## Architecture

| Area | Technology |
| --- | --- |
| Frontend | React 19, Next.js/Vinext, TypeScript, Tailwind CSS |
| API | Python 3.12, FastAPI, SQLAlchemy, Alembic |
| Background processing | Celery and Redis |
| Database | PostgreSQL 16 |
| Integrations | Google Drive OAuth, OpenAI, WorkOS, Resend |

The project is organized as a modular monolith:

```text
.
├── backend/        # FastAPI API, domain modules, migrations, and tests
├── frontend/       # Web application
├── specs/          # Product specification, ADRs, and work items
├── docker-compose.yml
└── .env.example
```

## Quick start with Docker

### Prerequisites

- Docker Desktop with Docker Compose

### Run locally

```bash
cp .env.example .env
docker compose up --build
```

This starts PostgreSQL, Redis, database migrations, the API, Celery worker, and frontend.

- Web app: http://localhost:3000
- API: http://localhost:8000
- Interactive API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/health/live

Stop the stack with:

```bash
docker compose down
```

To remove local database volumes as well:

```bash
docker compose down --volumes
```

## Configuration

Copy `.env.example` to `.env` and add credentials only for the integrations you intend to use. The local stack starts without optional integration credentials.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Enables AI-assisted questions and semantic capabilities |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Enables Google Drive connection and sync |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Encrypts stored Google OAuth tokens |
| `WORKOS_API_KEY` / `WORKOS_CLIENT_ID` | Enables authentication and organization identity |
| `RESEND_API_KEY` / `INVITATION_FROM_EMAIL` | Enables email invitations |
| `PUBLIC_APP_URL` | Public URL allowed by the API CORS policy |

Never commit `.env` files or credentials. The repository includes `.env.example` as a safe template.

## Local development

### Backend

Requirements: Python 3.12 and a running PostgreSQL/Redis instance.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal, start the worker:

```bash
cd backend
source .venv/bin/activate
celery -A app.ingestion.tasks worker --loglevel=INFO
```

Run backend checks:

```bash
cd backend
pytest
ruff check .
```

### Frontend

Requirements: Node.js 22.13 or later.

```bash
cd frontend
npm ci
npm run dev
```

Run frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

## Documentation

- [Product specification](specs/001-mvp-document-intelligence.md)
- [Architecture decision records](specs/adr/)
- [Feature work items](specs/work-items/)

## Contributing

1. Create a branch from `main`.
2. Keep changes focused and include relevant tests.
3. Run the checks for the component you changed.
4. Open a pull request describing the problem, solution, and verification.
