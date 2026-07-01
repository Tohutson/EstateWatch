# Estate Sale Finder

Estate Sale Finder is a single-process Python batch app for a Linux home server. It runs once per day, finds EstateSales.NET estate and moving sales near ZIP `14221`, scans new sale photos for approved targets, persists all state in SQLite, and emails only newly found positive matches.

The application searches for golf clubs, golf bags, golf balls, modern digital cameras, and modern camera lenses.

```mermaid
flowchart LR
  Timer[systemd timer] --> Docker[docker compose run --rm scanner run]
  Docker --> Lock[file lock]
  Lock --> ES[EstateSales.NET adapter]
  ES --> DB[(SQLite in data/)]
  ES --> Images[image download + thumbnail]
  Images --> Prefilter[optional CLIP prefilter]
  Prefilter --> Vision[vision provider]
  Vision --> DB
  DB --> Email[SMTP digest]
```

## Current EstateSales.NET Assumption

The ZIP, discovery, and hydration API endpoints were verified with live responses on June 30, 2026. A dependable full-gallery API endpoint was not found. The app uses a tested public HTML fallback parser that extracts `picturescdn.estatesales.net/<sale_id>/...` gallery URLs and raises `GalleryUnavailableError` when the page structure no longer exposes gallery metadata. It does not fabricate sequential image URLs and does not bypass authentication, CAPTCHA, or access controls.

## Local Setup

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
estate-sale-finder migrate
estate-sale-finder doctor
estate-sale-finder run --dry-run
```

If `uv` is available:

```bash
uv sync --extra dev
uv run estate-sale-finder run --dry-run
```

## Configuration

Configuration is loaded from environment variables and `.env`. Important defaults:

- `POSTAL_CODE=14221`
- `SEARCH_RADIUS_MILES=35`
- `LOOKAHEAD_DAYS=15`
- `MIN_PICTURE_COUNT=5`
- `ALLOWED_SALE_TYPES=EstateSales,MovingSales`
- `DATA_DIR=/app/data` in Docker
- `ANALYSIS_VERSION=golf-camera-v2`
- `PROMPT_VERSION=targets-v2`
- `ANALYSIS_PROVIDER=mock` until OpenAI credentials are configured
- `EMAIL_ENABLED=false` until SMTP is configured

Set `ANALYSIS_PROVIDER=openai`, `VISION_API_KEY`, and `VISION_MODEL` to use the hosted vision provider. SMTP uses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_FROM`, and comma-separated `EMAIL_TO`.

Use `VISION_MAX_IMAGES_PER_RUN` as a paid-call safety valve during diagnostics or backlog catch-up. For example, `VISION_MAX_IMAGES_PER_RUN=5` analyzes at most five eligible images in one run and leaves the rest for later idempotent runs. Leave it empty for no cap.

Set `OPENAI_SAVE_RESPONSES=true` to save raw OpenAI response snapshots under `DATA_DIR/logs/openai-responses` by default, or set `OPENAI_RESPONSE_LOG_DIR` to choose another directory. Snapshots include image IDs, status codes, request IDs, response bodies, and error bodies, but not the API key or base64 image request payload.

Keep `.env` mode restrictive on the server:

```bash
chmod 600 .env
```

## Commands

```bash
estate-sale-finder run
estate-sale-finder run --dry-run
estate-sale-finder run --reanalyze
estate-sale-finder run --reanalyze-version-mismatch
estate-sale-finder run --sale-id 4975674
estate-sale-finder doctor
estate-sale-finder migrate
estate-sale-finder test-email
estate-sale-finder inspect-sale 4975674
```

## Deduplication And Rescans

Sales are unique by `source + external_id`. Images are unique by `sale_id + source_url`, with SHA-256 and perceptual hashes stored after download. A sale refreshes when `pictureCount`, `utcDateModified`, or `latestPicturesAddedCount` changes, and eligible sales with a failed or incomplete prior gallery scan are retried. Sales below `MIN_PICTURE_COUNT` are still persisted and reconsidered during later discovery runs.

An image is analyzed only when it has not been analyzed, `--reanalyze` is used, or `--reanalyze-version-mismatch` is used after changing `ANALYSIS_VERSION`. Normal startup does not automatically reanalyze old images after a version change; run the explicit flag when you want that paid work. Database records retain provider, model, prompt version, and analysis version.

Detections are marked emailed only after SMTP send succeeds. A failed email leaves detections eligible for the next run.

The process lock prevents overlapping runs. If a previous process was interrupted after recording a run as `running`, the next run marks that stale record failed after acquiring the lock.

## Local Prefilter

`LOCAL_PREFILTER_ENABLED=false` by default. When enabled with the optional `prefilter` dependency, the app lazily loads `open-clip-torch` and caches model files under `XDG_CACHE_HOME` (`/app/model-cache` in Docker). The threshold is recall-oriented and must be tuned with saved scores in the database.

Each run logs `local_prefilter_complete` with `images_prefiltered`, `images_prefilter_passed`, and `images_prefilter_rejected`. The final `run_complete` log includes those counters plus `vision_batches_sent`, `vision_batches_succeeded`, and `vision_batches_failed`.

When `ANALYSIS_PROVIDER=openai`, the OpenAI provider logs `openai_vision_request_sent`, `openai_vision_request_succeeded`, and `openai_vision_request_failed` events. Successful request logs include the HTTP status code and OpenAI request ID when the API returns one.

If OpenAI returns a single result with an incorrect `image_id` for a one-image request, the pipeline remaps that result to the requested image and logs `vision_single_result_id_remapped`. Multi-image response mismatches still trigger an individual-image retry so the run does not silently attach results to the wrong records.

## Testing

Normal tests do not call EstateSales.NET, SMTP, OpenAI, or paid services.

```bash
ruff format --check .
ruff check .
mypy src
pytest
```

Live smoke tests should be added only behind an explicit environment flag.

## Docker

Build and run locally:

```bash
docker build -t estate-sale-finder:local .
docker compose run --rm scanner run
```

Run the published image:

```bash
docker run --rm --env-file .env -v "$PWD/data:/app/data" -v "$PWD/model-cache:/app/model-cache" ghcr.io/tohutson/estate-sale-finder:latest run
```

The image runs as a non-root user and stores mutable state only in `/app/data` and `/app/model-cache`.

## GHCR Publishing

GitHub Actions runs Ruff, mypy, tests, builds with Buildx, and pushes:

- `ghcr.io/tohutson/estate-sale-finder:latest`
- `ghcr.io/tohutson/estate-sale-finder:<commit-sha>`
- semantic version tags such as `v1.2.3`

For a private GHCR package on the server:

```bash
echo "$GHCR_READ_TOKEN" | docker login ghcr.io -u tohutson --password-stdin
```

Use a minimally scoped package read token.

## Linux Server Deployment

Install Docker Engine and the Compose plugin using the official apt repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Create the application directory and persistent state:

```bash
sudo mkdir -p /opt/estate-sale-finder
sudo mkdir -p /opt/estate-sale-finder/data /opt/estate-sale-finder/model-cache
sudo cp compose.yaml /opt/estate-sale-finder/
sudo cp .env.example /opt/estate-sale-finder/.env
sudo chmod 600 /opt/estate-sale-finder/.env
sudo chown -R "$USER":"$USER" /opt/estate-sale-finder
```

Edit `/opt/estate-sale-finder/.env` with the server ZIP code, OpenAI settings, and SMTP settings. Keep runtime secrets only in this server-side file.

For a private GHCR package, log in with a read-only package token:

```bash
echo "$GHCR_READ_TOKEN" | docker login ghcr.io -u tohutson --password-stdin
```

Pull, migrate, check configuration, send a test email, and run one manual scan:

```bash
cd /opt/estate-sale-finder
docker compose pull scanner
docker compose run --rm scanner migrate
docker compose run --rm scanner doctor
docker compose run --rm scanner test-email
docker compose run --rm scanner run
```

Install and enable the timers:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now estate-sale-image-pull.timer
sudo systemctl enable --now estate-sale-scanner.timer
```

The image pull timer runs hourly. The scanner timer runs daily at 06:15 local time with `Persistent=true`, so missed runs execute after the server returns.

Manual server run:

```bash
cd /opt/estate-sale-finder
docker compose run --rm scanner run
```

View timers and logs:

```bash
systemctl list-timers 'estate-sale-*'
journalctl -u estate-sale-scanner.service -n 200 --no-pager
journalctl -u estate-sale-image-pull.service -n 100 --no-pager
```

Rollback to a known commit-SHA image:

```bash
cd /opt/estate-sale-finder
sed -i 's|ghcr.io/tohutson/estate-sale-finder:.*|ghcr.io/tohutson/estate-sale-finder:sha-<commit-sha>|' compose.yaml
docker compose pull scanner
docker compose run --rm scanner doctor
```

## Backups

Stop active runs first, then back up:

```bash
sqlite3 data/estate-sale-finder.db '.backup backup/estate-sale-finder.db'
rsync -a data/thumbnails/ backup/thumbnails/
```

The SQLite DB contains run state and deduplication; thumbnails are needed for historical email context.

Restore:

```bash
cp backup/estate-sale-finder.db data/estate-sale-finder.db
rsync -a backup/thumbnails/ data/thumbnails/
docker compose run --rm scanner doctor
```

## Troubleshooting

- `doctor` fails ZIP lookup: EstateSales.NET may have changed or blocked the endpoint. Check outbound HTTPS and the adapter tests.
- Gallery unavailable: capture the current sale page HTML, add it under `tests/fixtures/`, update `extract_gallery_from_html`, and run parser tests.
- No email: verify `EMAIL_ENABLED=true`, SMTP settings, `EMAIL_TO`, and server outbound SMTP policy.
- Repeated detections: inspect `detections.included_in_email`; failed SMTP sends intentionally leave records unsent.
- Slow first prefilter run: model weights are downloading to `model-cache`.

## Security And Compliance

The app needs outbound HTTPS to EstateSales.NET, image CDNs, GHCR, and optionally OpenAI. It does not need inbound webhooks or SSH from GitHub, does not mount the Docker socket, and does not store secrets in the image. EstateSales.NET APIs are undocumented and may change; review their terms and your usage risk before relying on the scanner.
