# punta-scraper

DigiSnow ski-station scraper. It follows lift and slope status for DigiSnow-powered resorts and publishes it to Home Assistant over MQTT, with a small web UI for choosing stations and settings.

It runs either as a Home Assistant add-on (`digisnow-scraper/config.yaml`) or as a Docker Compose service (`docker-compose.yml`).

## Running with Docker Compose

1. Copy `.env.example` to `.env` and fill it in. `.env` is gitignored; never commit it.
2. `docker compose up -d`.

The web UI listens on port 8099 inside the container. The Compose file only exposes it to the shared `web` network for the reverse proxy; it publishes no host port.

### State

`./data` is mounted at `/app/app/data` and holds `config.json`: the stations, the MQTT and status-mapping settings, the fetched DigiSnow credentials and the generated session key. It is gitignored and contains secrets, so back it up as protected state and never commit it.

On Bella the deployment directory is `/opt/punta-scraper`, so `data/config.json` and `.env` are covered by Bella's nightly Backrest/restic backup of `/opt` (Backrest source `/sources/docker`, 03:15 Europe/Paris; see homelab-docs [`backups/restic-rest-server.md`](https://github.com/TimMonks/homelab-docs/blob/main/backups/restic-rest-server.md)). The infra registry sets a 48-hour backup-age limit. No Watchtower pre-update backup or idle hook runs, by decision (Tim, 2026-10-18, [issue #24](https://github.com/TimMonks/punta-scraper/issues/24#issuecomment-6106669866)), because:

- an update has no schema migration;
- `Config` merges defaults for missing keys, so a newer image reads an older file;
- the file changes only when settings are edited;
- the load path never overwrites an unreadable file (see below).

Saves are atomic: the new file is written beside the old one and then swapped in, so an interrupted save leaves the previous `config.json` intact.

If `config.json` cannot be parsed (invalid JSON, not UTF-8, or not a JSON object), the service moves it to `config.json.corrupt-<UTC timestamp>` in the same directory, logs an ERROR naming both files, and starts with defaults. The backup contains the same secrets and is covered by the same gitignore. Restore the stations and credentials from it, then delete it. If `config.json` exists but cannot be read, or cannot be moved aside, the service logs an ERROR and refuses to start, so the file is never overwritten.

## Image, updates and rollback

The image is built and pushed to `ghcr.io/timmonks/punta-scraper` by `.github/workflows/docker-publish.yml` on **every push to `main`**, but only after the workflow's `test` job (`python -m pytest tests -q`) passes. It carries three tags:

| Tag | Moves? | Use |
|---|---|---|
| `latest` | Yes, on every push to `main` | The tag Compose tracks by default. |
| the add-on version from `digisnow-scraper/config.yaml` (for example `1.4.0`) | Yes, re-pushed on every push until the version is bumped | Not a reliable rollback target. |
| the short commit SHA (7 characters) | No | The rollback and pinning target. |

The `test` job runs the suite on every pull request to `main` and before every image push, and a failing suite publishes no image. Pull-request runs only test and never push.

**Update mode: `auto`.** The service carries `com.centurylinklabs.watchtower.enable=true`, so the host's Watchtower pulls a new `latest` and recreates the container. Every merge to `main` therefore reaches the deployment without a separate release step. This deploy-on-merge channel is a recorded owner exception to the [Bella container policy](https://github.com/TimMonks/homelab-docs/blob/main/services-and-media/bella-container-policy.md#update-mode)'s own-app prerequisite that `latest` moves only on a tested release (table "Owner exception: deploy on merge"). The reason is that no test environment exists. The compensating measures are the CI `test` job on every pull request and before every image push, the `/api/health` health check, rollback by pinning `APP_IMAGE_TAG` to a short-SHA tag (below), and the nightly backup of `config.json` (see [State](#state)). Decision: Tim, 2026-10-18, on [issue #24](https://github.com/TimMonks/punta-scraper/issues/24#issuecomment-6106669866). Review it by 2027-10-18, or earlier if a test environment is added.

**Rollback.** Set `APP_IMAGE_TAG` in `.env` to the short-SHA tag of the last good build, then run `docker compose up -d`. A SHA tag never moves, so Watchtower has nothing newer to pull while it is set. To return to automatic updates, remove `APP_IMAGE_TAG` (it defaults to `latest`) and run `docker compose up -d` again.

## Logs and health

Logs are JSON lines on stdout (`LOG_FORMAT=json`), rotated by the Docker `json-file` driver and labelled `logging=digisnow` for Loki. `GET /api/health` (no login) reports whether the DigiSnow and MQTT connections are up.

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests -q
```

CI runs the same command on every pull request and before every image push (`.github/workflows/docker-publish.yml`, job `test`).
