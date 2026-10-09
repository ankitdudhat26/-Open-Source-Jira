# Production deployment

Plane is deployed as **two stacks on one server**, each from its own repository:

| Stack        | Repository                      | Server folder         | Contains                                                          |
| ------------ | ------------------------------- | --------------------- | ----------------------------------------------------------------- |
| **App**      | this repo (`-Open-Source-Jira`) | `/opt/plane`          | Frontend (web, admin, space, live), backend (API, workers), proxy |
| **Database** | `plane-database`                | `/opt/plane-database` | Postgres, Redis, RabbitMQ, MinIO, backups                         |

```
                 Server
 ┌──────────────────────────────────────────────────────────────┐
 │  App stack (/opt/plane)            Database stack (/opt/plane-database)
 │                                                               │
 │  proxy :80/:443 ──► web, admin,      plane-db     (Postgres)  │
 │                     space, live,     plane-redis  (Valkey)    │
 │                     api, workers ──► plane-mq     (RabbitMQ)  │
 │                                      plane-minio  (MinIO)     │
 │            └──────── Docker network "plane-data" ────────┘    │
 └──────────────────────────────────────────────────────────────┘
```

The app reaches the database services by name over the private `plane-data` network. Only the proxy (ports 80 and 443) is reachable from the internet.

## How a deploy works

```
push to main (this repo)
   │
   ▼
GitHub Actions (.github/workflows/deploy-production.yml)
   ├─ build 6 images in parallel ──► ghcr.io/<owner>/plane-*:<commit-sha> and :latest
   └─ deploy job
        ├─ copy docker-compose.yml, deploy.sh, plane.env.example to /opt/plane
        └─ run deploy.sh:
             check settings → check the database stack is up → back up the database
             → pull images → docker compose up -d → wait for the API
```

## Files in this folder

| File                 | Purpose                                                                                                                                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker-compose.yml` | The app stack: web, admin, space, live, API, worker, beat, migrator, proxy. Based on `deployments/cli/community/docker-compose.yml`, minus the database services and with images from your registry |
| `plane.env.example`  | Template for the server's settings. Copy it to `plane.env` **on the server**; never commit that copy                                                                                                |
| `deploy.sh`          | Runs on the server: checks, backup, pull, start, health check                                                                                                                                       |

## 1. Prepare the server (once)

You need Ubuntu 22.04+ (x86-64) with at least 6 GB of RAM (about 4 GB for the app, 2 GB for the database), plus ports 80 and 443 open. Keep every other port closed.

```bash
curl -fsSL https://get.docker.com | sh

sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy

sudo mkdir -p /opt/plane /opt/plane-database
sudo chown deploy:deploy /opt/plane /opt/plane-database
```

## 2. Create an SSH key for GitHub Actions (once)

On your own computer:

```bash
ssh-keygen -t ed25519 -f plane_deploy_key -N "" -C "github-actions-deploy"
```

Add the **public** key to the server:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < plane_deploy_key.pub
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

## 3. Deploy the database stack first

Follow the `plane-database` repository's README: create `/opt/plane-database/.env`, add the same three SSH secrets to that repository, and run its **Deploy Database** workflow. This creates the `plane-data` network the app needs.

## 4. Create `plane.env` for the app (once)

Copy `plane.env.example` from this folder to `/opt/plane/plane.env` on the server and edit it:

| Setting                                | Value                                                                                                                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `IMAGE_PREFIX`                         | `ghcr.io/<your-github-username-in-lowercase>`                                                                                                                            |
| `APP_DOMAIN`                           | Your domain (e.g. `plane.example.com`) or the server IP                                                                                                                  |
| `WEB_URL`, `CORS_ALLOWED_ORIGINS`      | `http://<APP_DOMAIN>` (or `https://…` once HTTPS is on)                                                                                                                  |
| `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY` | Two different outputs of `openssl rand -hex 32`                                                                                                                          |
| Every `CHANGE-ME`                      | **The same passwords as in `/opt/plane-database/.env`**: `POSTGRES_PASSWORD` (also in `DATABASE_URL`), `RABBITMQ_PASSWORD` (also in `AMQP_URL`), `AWS_SECRET_ACCESS_KEY` |

Use passwords made only of letters and numbers (`openssl rand -hex 24` does this). Symbols such as `@`, `:` or `/` break `DATABASE_URL` and `AMQP_URL`.

**HTTPS:** point your domain's DNS at the server, then set `SITE_ADDRESS=plane.example.com` and `CERT_EMAIL=you@example.com`. Use `https://` in `WEB_URL` and `CORS_ALLOWED_ORIGINS`. The proxy then gets a Let's Encrypt certificate automatically.

## 5. Configure this GitHub repository (once)

In **Settings → Secrets and variables → Actions**:

| Type                | Name              | Value                                                        |
| ------------------- | ----------------- | ------------------------------------------------------------ |
| Secret              | `SSH_HOST`        | Server IP or hostname                                        |
| Secret              | `SSH_USER`        | `deploy`                                                     |
| Secret              | `SSH_PRIVATE_KEY` | Contents of `plane_deploy_key` (the private key)             |
| Secret (optional)   | `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan <server>`; pins the server's host key |
| Variable (optional) | `SSH_PORT`        | Default `22`                                                 |
| Variable (optional) | `DEPLOY_PATH`     | Default `/opt/plane`                                         |

In **Settings → Environments**, a `production` environment appears after the first run. Add **Required reviewers** there if you want to approve each deploy by hand.

## 6. Deploy

- **Automatically:** push or merge to `main`.
- **By hand:** **Actions → Deploy Production → Run workflow**.

The first deploy takes about 15–25 minutes (images are built from scratch and migrations run). When it finishes, open `http://<APP_DOMAIN>/god-mode/` to create the instance admin, then go to `http://<APP_DOMAIN>/`.

## Rolling back

Every deploy is tagged with the commit SHA (first 12 characters). The server keeps a list in `/opt/plane/releases.log`.

- **From GitHub:** **Actions → Deploy Production → Run workflow**, then enter the old tag in **image_tag**. Nothing is rebuilt.
- **On the server:** `cd /opt/plane && APP_RELEASE=<old-tag> ./deploy.sh`

Rolling back the app does not undo database migrations. To return the data to its state before a deploy, restore the automatic pre-deploy backup with `/opt/plane-database/scripts/restore.sh` (see the `plane-database` README).

## Day-to-day commands (on the server)

```bash
cd /opt/plane
docker compose -p plane --env-file plane.env ps                 # status
docker compose -p plane --env-file plane.env logs -f api        # follow API logs
docker compose -p plane --env-file plane.env restart api        # restart one service
docker compose -p plane --env-file plane.env down               # stop the app (database keeps running)
```
