# Plane Database

The data layer for Plane: **PostgreSQL** (all app data), **Redis/Valkey** (cache and sessions), **RabbitMQ** (background job queue) and **MinIO** (uploaded files).

This folder is the database half of the **-Open-Source-Jira** repository; the app half is in `deployments/production`. Both stacks run on the same server and talk over a private Docker network:

```
                 Server
 ┌──────────────────────────────────────────────────────────────┐
 │  App stack (/opt/plane)            Database stack (/opt/plane-database)
 │  deployments/production/           database/ (this folder)
 │                                                               │
 │  proxy :80/:443 ──► web, admin,      plane-db     (Postgres)  │
 │                     space, live,     plane-redis  (Valkey)    │
 │                     api, workers ──► plane-mq     (RabbitMQ)  │
 │                                      plane-minio  (MinIO)     │
 │            └──────── Docker network "plane-data" ────────┘    │
 └──────────────────────────────────────────────────────────────┘
```

Only the app's proxy is reachable from the internet. Database ports are never published.

## Folder layout

| Path                                       | Purpose                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------ |
| `docker-compose.yml`                       | The four services, their data volumes and the shared `plane-data` network            |
| `.env.example`                             | Settings template. Copy it to `.env` on the server and never commit that copy        |
| `scripts/deploy.sh`                        | Starts or updates the stack and waits until it's healthy                             |
| `scripts/backup.sh`                        | Backs up Postgres and uploaded files, and deletes old backups                        |
| `scripts/restore.sh`                       | Restores from a backup                                                               |
| `../.github/workflows/deploy-database.yml` | A push to `main` that changes this folder validates the files, then deploys over SSH |

## First-time setup

**Deploy the database stack before the app stack.** The app needs the `plane-data` network and the database to exist.

1. **Prepare the server.** Follow steps 1–2 of `deployments/production/README.md`: install Docker, create the `deploy` user and the `/opt/plane-database` folder, and set up the SSH key.
2. **Create `.env` on the server.** Copy `.env.example` to `/opt/plane-database/.env` and replace every `CHANGE-ME` (`openssl rand -hex 24` generates a good password).
3. **Add the GitHub secrets** to the repository: `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`. The app deploy uses the same three.
4. **Deploy:** **Actions → Deploy Database → Run workflow**. After that, any push to `main` that changes this folder deploys it again.
5. Deploy the app (**Actions → Deploy Production**).

## Matching settings

The app connects using the values in its own `plane.env` (`/opt/plane/plane.env`). These must match this folder's `.env`:

| Here (`.env`)                                          | App (`plane.env`)                                                                        |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`    | Same three values, plus `DATABASE_URL=postgresql://<user>:<password>@plane-db:5432/<db>` |
| `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_VHOST` | Same three values, plus `AMQP_URL=amqp://<user>:<password>@plane-mq:5672/<vhost>`        |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`           | Same two values                                                                          |

Redis has no password. It's only reachable on the private `plane-data` network.

## Backups

```bash
cd /opt/plane-database
./scripts/backup.sh            # database + uploaded files
./scripts/backup.sh --db-only  # database only
```

The app's deploy runs `backup.sh --db-only` automatically before every update. For daily backups, add a cron job for the `deploy` user (`crontab -e`):

```
30 2 * * * /opt/plane-database/scripts/backup.sh >> /opt/plane-database/backups/backup.log 2>&1
```

Copy the `backups/` folder off the server regularly, for example to S3 or another machine.

## Restore

```bash
cd /opt/plane && docker compose -p plane --env-file plane.env down        # stop the app
cd /opt/plane-database
./scripts/restore.sh backups/plane-db-<time>.dump [backups/plane-uploads-<time>.tar.gz]
cd /opt/plane && docker compose -p plane --env-file plane.env up -d       # start the app
```

## Day-to-day

```bash
cd /opt/plane-database
docker compose --env-file .env ps                       # status
docker compose --env-file .env logs -f plane-db         # logs
docker compose --env-file .env exec plane-db psql -U plane plane   # SQL shell
```

`docker compose down` stops the services but keeps the data. **Never run `down -v`**: it deletes the data volumes.

## Upgrading a service version

Change the image tag in `database/docker-compose.yml` and push. Take a backup first. Postgres major-version upgrades (e.g. 15 → 16) need a dump and restore, not just a tag change.
