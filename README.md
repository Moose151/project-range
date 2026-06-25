# Project Range

A FastAPI + SQLite application for managing RF range operations: signal packages,
serials, real-time dashboard, RF/power calculators, shift handover, and audit logs.

## Quick start (local)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python init_db.py          # creates the DB and a default admin / changeme account
python run.py              # dev server on http://localhost:8001
```

## Docker

```bash
cp .env.example .env           # then set a SECRET_KEY in .env
docker compose up -d --build
```

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for full deployment, backup, and scaling notes.

## Project layout

```
app/            FastAPI application (routers, templates, static, models)
init_db.py      DB init + idempotent migrations + seed data
run.py          Dev server entry point
Dockerfile      Production image
docker-compose.yml
docs/           DEPLOY.md, HANDOVER.md, Scope.txt
```

## Documentation

- [docs/DEPLOY.md](docs/DEPLOY.md) — Docker deployment guide
- [docs/HANDOVER.md](docs/HANDOVER.md) — project handover notes
- [docs/Scope.txt](docs/Scope.txt) — project scope
