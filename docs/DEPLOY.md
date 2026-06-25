# Deploying Project Range with Docker

The app is a FastAPI service (uvicorn) using a SQLite database. The image bundles
the code and dependencies; the database lives on a Docker **named volume** so it
survives rebuilds and restarts. The DB migration runs automatically on every
container start (it is idempotent — safe to re-run).

## Prerequisites

- Docker and Docker Compose v2 (`docker compose ...`)

## Deploy from git

```bash
# 1. Clone
git clone https://github.com/Moose151/project-range.git
cd project-range

# 2. Create the env file and set a real secret
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
#   (then edit .env so there is only one SECRET_KEY line, with the generated value)

# 3. Build and start
docker compose up -d --build
```

The app is now on http://localhost:8001 — log in with the seeded
`admin` / `changeme` account and **change the password immediately**.

## Common operations

```bash
# View logs
docker compose logs -f web

# Apply DB migrations after pulling new code (also runs automatically on start)
git pull
docker compose up -d --build           # rebuild + restart; entrypoint migrates
# or migrate without restarting traffic:
docker compose exec web python init_db.py

# Stop
docker compose down                     # keeps the data volume
docker compose down -v                  # ALSO deletes the database volume
```

## Backing up the database

The SQLite file lives in the `range-data` volume at `/app/data/range.db`:

```bash
# Copy the DB out of the running container
docker compose cp web:/app/data/range.db ./range-backup.db
```

## Configuration

Set in `.env` (see `.env.example`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — | Signs session cookies. Use a long random value. |
| `DATABASE_URL` | no | `sqlite:////app/data/range.db` | DB connection string. |
| `SESSION_TIMEOUT_MINUTES` | no | `480` | Inactivity timeout for normal sessions. |
| `SESSION_MAX_AGE_DAYS` | no | `30` | Lifetime of "remember this terminal" sessions. |

## Notes / scaling

- The container runs a **single** uvicorn process. SQLite does not handle highly
  concurrent writers well, so do not add multiple workers while on SQLite. For
  higher load, point `DATABASE_URL` at Postgres (note: the `init_db.py` migration
  helper uses SQLite `ALTER TABLE` syntax and would need adjusting for Postgres).
- The image runs as a non-root user (`appuser`).
- A `HEALTHCHECK` polls `/login`; check status with `docker compose ps`.
