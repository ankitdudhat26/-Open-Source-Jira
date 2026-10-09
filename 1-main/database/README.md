# Database

The Main app (and the Admin panel) store their data in **PostgreSQL**. They also use **Redis** for cache and background-job queues, **RabbitMQ** as the Celery broker, and **MinIO** (S3-compatible) for file uploads.

## Where the database pieces live

| What | Location |
|---|---|
| Table definitions (Django models) | `1-main/backend/plane/db/models/` |
| Schema migrations | `1-main/backend/plane/db/migrations/` |
| Connection settings | `1-main/backend/.env` (`POSTGRES_*`, `DATABASE_URL`, `REDIS_URL`, `AMQP_URL`) |
| Local services (this folder) | `docker-compose.yml`: Postgres, Redis, RabbitMQ, MinIO |
| Production services | `deployments/production/docker-compose.yml` |

## Start the services locally with Docker

```bash
# once, from the repository root
./setup.sh

# from this folder
docker compose --env-file ../../.env up -d
```

If port 5432 is already used on your machine, add `DB_PORT=5434` to the root `.env` and set `POSTGRES_PORT=5434` in `1-main/backend/.env`.

## Without Docker

`./run-local.sh` at the repository root starts Homebrew Postgres (port 5434), Redis and MinIO natively. In that setup Redis is also the Celery broker, so RabbitMQ isn't needed.

## Common tasks

```bash
cd 1-main/backend
set -a; source .env; set +a

python manage.py migrate          # apply migrations
python manage.py makemigrations   # create migrations after changing models
python manage.py showmigrations   # list migration status

# backup / restore (adjust host/port to your setup)
pg_dump  -h localhost -p 5432 -U plane plane | gzip > plane-$(date +%F).sql.gz
gunzip -c plane-YYYY-MM-DD.sql.gz | psql -h localhost -p 5432 -U plane plane
```
