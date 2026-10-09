# Production deployment

Every push to `main` builds all Plane images, pushes them to GitHub Container Registry (ghcr.io) and deploys them to your server over SSH.

```
push to main
   │
   ▼
GitHub Actions (.github/workflows/deploy-production.yml)
   ├─ build 6 images in parallel ──► ghcr.io/<owner>/plane-*:<commit-sha> and :latest
   └─ deploy job
        ├─ copy docker-compose.yml, deploy.sh, plane.env.example to the server
        └─ run deploy.sh: pull images → docker compose up -d → wait for the API
```

## Files in this folder

| File | Purpose |
|---|---|
| `docker-compose.yml` | The production stack: web, admin, space, live, API, workers, Postgres, Redis, RabbitMQ, MinIO and the Caddy proxy. Same as `deployments/cli/community/docker-compose.yml`, except the images come from your registry. |
| `plane.env.example` | Template for the server's settings. Copy it to `plane.env` **on the server** and never commit that copy. |
| `deploy.sh` | Runs on the server: pulls the images, starts the stack and checks the API is healthy. |

## 1. Prepare the server (once)

You need an Ubuntu 22.04+ server (x86-64) with at least 4 GB of RAM, plus ports 80 and 443 open.

```bash
# Install Docker Engine and the compose plugin
curl -fsSL https://get.docker.com | sh

# Create a deploy user that can run docker
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy

# Create the deployment folder
sudo mkdir -p /opt/plane && sudo chown deploy:deploy /opt/plane
```

## 2. Create an SSH key for GitHub Actions (once)

On your own computer:

```bash
ssh-keygen -t ed25519 -f plane_deploy_key -N "" -C "github-actions-deploy"
```

Then add the **public** key to the server:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < plane_deploy_key.pub
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

## 3. Create `plane.env` on the server (once)

Copy `plane.env.example` from this folder to `/opt/plane/plane.env` on the server and edit it:

```bash
nano /opt/plane/plane.env
```

At minimum, set these values:

| Setting | Value |
|---|---|
| `IMAGE_PREFIX` | `ghcr.io/<your-github-username-in-lowercase>` |
| `APP_DOMAIN` | Your domain (e.g. `plane.example.com`) or the server IP |
| `WEB_URL`, `CORS_ALLOWED_ORIGINS` | `http://<APP_DOMAIN>` (or `https://…` once HTTPS is on) |
| `SECRET_KEY` | Output of `openssl rand -hex 32` |
| `LIVE_SERVER_SECRET_KEY` | Output of `openssl rand -hex 32` (a different value) |
| `POSTGRES_PASSWORD` and `DATABASE_URL` | A strong password, used in both |
| `RABBITMQ_PASSWORD` and `AMQP_URL` | A strong password, used in both |
| `AWS_SECRET_ACCESS_KEY` | A strong value (MinIO password) |

**HTTPS:** point your domain's DNS at the server, then set `SITE_ADDRESS=plane.example.com` and `CERT_EMAIL=you@example.com`. Use `https://` in `WEB_URL` and `CORS_ALLOWED_ORIGINS`. The Caddy proxy then gets a Let's Encrypt certificate automatically.

## 4. Configure the GitHub repository (once)

In **Settings → Secrets and variables → Actions**:

| Type | Name | Value |
|---|---|---|
| Secret | `SSH_HOST` | Server IP or hostname |
| Secret | `SSH_USER` | `deploy` |
| Secret | `SSH_PRIVATE_KEY` | Contents of `plane_deploy_key` (the private key) |
| Secret (optional) | `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan <server>`; pins the server's host key |
| Variable (optional) | `SSH_PORT` | Default `22` |
| Variable (optional) | `DEPLOY_PATH` | Default `/opt/plane` |

In **Settings → Environments**, a `production` environment is created on the first run. You can add **Required reviewers** there to approve each deploy by hand.

The workflow publishes to ghcr.io using the built-in `GITHUB_TOKEN`, so registry passwords aren't needed.

## 5. Deploy

- **Automatically:** push or merge to `main`.
- **By hand:** **Actions → Deploy Production → Run workflow**.

The first deploy takes longer (roughly 15–25 minutes) because every image is built from scratch and the database migrations run. Later builds reuse the build cache.

When it finishes, open `http://<APP_DOMAIN>/god-mode/` to create the instance admin, then go to `http://<APP_DOMAIN>/`.

## Rolling back

Every deploy is tagged with the commit SHA (first 12 characters). The server keeps a list in `/opt/plane/releases.log`.

- **From GitHub:** **Actions → Deploy Production → Run workflow**, then enter the old tag in **image_tag**. Nothing is rebuilt.
- **On the server:** `cd /opt/plane && APP_RELEASE=<old-tag> ./deploy.sh`

A rollback doesn't undo database migrations. Take a backup before deploying changes that include migrations.

## Day-to-day commands (on the server)

```bash
cd /opt/plane
docker compose -p plane --env-file plane.env ps                 # status
docker compose -p plane --env-file plane.env logs -f api        # follow API logs
docker compose -p plane --env-file plane.env restart api        # restart one service
docker compose -p plane --env-file plane.env down               # stop (data volumes are kept)

# Database backup
docker compose -p plane --env-file plane.env exec -T plane-db \
  pg_dump -U plane plane | gzip > plane-$(date +%F).sql.gz
```
