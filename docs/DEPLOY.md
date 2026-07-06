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

The app is now on http://localhost:7474 (Docker publishes host port 7474 → the
container's 8001). From other devices on the LAN use http://<host-ip>:7474.
Log in with the seeded `admin` / `changeme` account and **change the password
immediately**.

> Firewall: allow inbound TCP 7474 on the host so other devices can reach it.

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
# One-off backup into ./backups/range-<UTC timestamp>.db
python scripts/backup_db.py

# Keep only the newest 14 backups
python scripts/backup_db.py --keep 14
```

Schedule that command with cron or Windows Task Scheduler from the repository
directory. The script uses `docker compose cp`, so the app can keep using the
named Docker volume. It also makes the local `backups/` directory and copied
`.db` backup files owner-only where the host filesystem permits it.

Restore procedure:

```bash
# Stop the app before replacing the SQLite file
docker compose stop web

# Copy a known-good backup back into the container/volume
docker compose cp ./backups/range-YYYYMMDD-HHMMSSZ.db web:/app/data/range.db

# Start the app; init_db.py will run its idempotent migrations
docker compose start web
```

Keep backups access-controlled. They contain the operational log, audit history,
users, and password hashes. Admin Config → System Health shows the live SQLite
database and server archive permission modes; investigate any warning that
group/other permissions are present.

## Upload Limits

Operator upload flows are intentionally small-file only. Package/CBM imports and
CDA CSV imports enforce extension and size checks before processing. Defaults:

- `MAX_UPLOAD_BYTES=2097152` per uploaded file or zip member.
- `MAX_UPLOAD_TOTAL_BYTES=8388608` combined upload payload.
- `MAX_UPLOAD_ZIP_MEMBERS=100` files inside a package import zip.

Adjust these only if an operational import format genuinely needs more room.

## Configuration

Set in `.env` (see `.env.example`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — | Signs session cookies. Use a long random value. |
| `DATABASE_URL` | no | `sqlite:////app/data/range.db` | DB connection string. |
| `SESSION_TIMEOUT_MINUTES` | no | `480` | Inactivity timeout for normal sessions. |
| `SESSION_MAX_AGE_DAYS` | no | `30` | Lifetime of "remember this terminal" sessions. |
| `AUDIT_HASH_SECRET` | no | `SECRET_KEY` | HMAC secret for audit integrity hashes. Keep stable. |
| `MAX_UPLOAD_BYTES` | no | `2097152` | Per-file upload limit for operator imports. |
| `MAX_UPLOAD_TOTAL_BYTES` | no | `8388608` | Combined upload limit for one import request. |
| `MAX_UPLOAD_ZIP_MEMBERS` | no | `100` | Maximum files accepted inside a package import zip. |

## Notes / scaling

- The container runs a **single** uvicorn process. SQLite does not handle highly
  concurrent writers well, so do not add multiple workers while on SQLite. For
  higher load, point `DATABASE_URL` at Postgres (note: the `init_db.py` migration
  helper uses SQLite `ALTER TABLE` syntax and would need adjusting for Postgres).
- The image runs as a non-root user (`appuser`). Compose also sets a read-only
  root filesystem, `/tmp` tmpfs, `no-new-privileges`, drops Linux capabilities,
  and applies basic memory/process limits. Keep persistent writes under
  `/app/data`, which is the named volume.
- A `HEALTHCHECK` polls `/login`; check status with `docker compose ps`.
