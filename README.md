# Radarr/Sonarr Jellyfin Notifier

[![GitHub release](https://img.shields.io/github/v/release/tommekevda/radarr-sonarr-jellyfin-notifier)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/releases)
[![License](https://img.shields.io/github/license/tommekevda/radarr-sonarr-jellyfin-notifier)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/blob/master/LICENSE)
[![Build](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/actions/workflows/docker-image.yml/badge.svg)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/actions/workflows/docker-image.yml)
[![Docker](https://img.shields.io/badge/ghcr.io%2Ftommekevda%2Fradarr--sonarr--jellyfin--notifier-blue?logo=docker&logoColor=white)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/pkgs/container/radarr-sonarr-jellyfin-notifier)
[![Last commit](https://img.shields.io/github/last-commit/tommekevda/radarr-sonarr-jellyfin-notifier)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/commits/master)
[![Stars](https://img.shields.io/github/stars/tommekevda/radarr-sonarr-jellyfin-notifier)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/stargazers)
[![Issues](https://img.shields.io/github/issues/tommekevda/radarr-sonarr-jellyfin-notifier)](https://github.com/tommekevda/radarr-sonarr-jellyfin-notifier/issues)

This is a simple Flask application that listens for webhook events from Radarr or Sonarr and triggers a Jellyfin refresh.

## How it works

- The app exposes webhook endpoints: `/radarr-webhook` for Radarr and `/sonarr-webhook` for Sonarr.
- Helper endpoints `/health` and `/libraries` are available for status checks and library discovery.
- Radarr/Sonarr should send custom headers: `X-Jellyfin-Url` (your Jellyfin server URL) and `X-Jellyfin-Api-Key` (your Jellyfin API key). You can also set `JELLYFIN_URL` and `JELLYFIN_API_KEY` as a fallback if you prefer not to send headers.
- Upon receiving a Radarr or Sonarr event, the app queues a Jellyfin refresh and coalesces multiple requests into a single refresh per target set.
- Webhook responses return `202` when a refresh is queued; set `JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS=0` to refresh immediately.
- Optionally, you can target specific libraries by sending:
  - `X-Jellyfin-Library-Ids`: comma-separated Jellyfin library `ItemId` values.
  - `X-Jellyfin-Collection-Types`: comma-separated library `CollectionType` values (e.g. `movies,tvshows,music,boxsets`), which are resolved to matching libraries.
  - You can combine both headers; duplicates are ignored. If both headers are absent, all libraries are refreshed.
- Optionally, you can control the refresh behavior per request with:
  - `X-Jellyfin-Refresh-Profile`: preferred request header for Radarr/Sonarr webhooks.
  - `refresh_profile`: request parameter for clients that can send extra POST fields.
- If both `X-Jellyfin-Refresh-Profile` and `refresh_profile` are provided, the header wins.
- No dedicated environment variable exists for `refresh_profile`; the refresh behavior is intentionally selected per webhook request.

## Flask Application

The app runs a Flask server on port `5001` (or `JELLYFIN_NOTIFIER_PORT`/`PORT`) and listens for Radarr and Sonarr webhook events.

### Health check

- `GET /health` returns HTTP 200 with `{"status": "ok"}`.

### List libraries

- `GET /libraries` returns JSON with your Jellyfin libraries (name, itemId, collectionType, locations).
- Provide Jellyfin credentials via headers (`X-Jellyfin-Url`, `X-Jellyfin-Api-Key`), query params (`?url=<...>&api_key=<...>`), or env vars (`JELLYFIN_URL`, `JELLYFIN_API_KEY`).
- Use this to copy `ItemId`s for the optional `X-Jellyfin-Library-Ids` header or to see available `collectionType` values.
- Example (browser-friendly URL; `jellyfin-notifier-ip`):

```
http://<jellyfin-notifier-ip>:5001/libraries?url=http://jellyfin.local:8096&api_key=<your-jellyfin-api-key>
```

## Running with Docker

### docker-compose.yml

The docker-compose file uses the `ghcr.io` image and maps port 5001:

```yaml
services:
  radarr-sonarr-jellyfin-notifier:
    image: ghcr.io/tommekevda/radarr-sonarr-jellyfin-notifier:latest
    container_name: radarr-sonarr-jellyfin-notifier
    restart: unless-stopped
    environment:
      # JELLYFIN_API_KEY: ""                                  # Jellyfin API key (optional if headers used)
      # JELLYFIN_URL: ""                                      # Jellyfin base URL (optional if headers used)
      # JELLYFIN_NOTIFIER_ALLOWLIST: ""                       # Comma-separated IPs/CIDRs
      JELLYFIN_NOTIFIER_LOG_LEVEL: "INFO"                     # Log level
      JELLYFIN_NOTIFIER_PORT: "5001"                          # Bind port
      JELLYFIN_NOTIFIER_RATE_LIMIT_PER_MINUTE: "0"            # Per-IP limit (0=off)
      JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS: "10"        # Queue debounce
      JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS: "60"        # Max queue delay
    tmpfs:
      - /tmp
    ports:
      - "5001:5001"
```

For local builds, use `docker-compose.local.yml` (it builds from `.`).

## Configuration

- `JELLYFIN_URL` / `JELLYFIN_API_KEY`: Fallback credentials for webhook requests and `/libraries` if headers or query params are missing.
- `JELLYFIN_NOTIFIER_PORT` or `PORT`: Port to bind (default `5001`).
- `JELLYFIN_NOTIFIER_LOG_LEVEL`: Log level (default `INFO`).
- `JELLYFIN_NOTIFIER_RATE_LIMIT_PER_MINUTE`: Per-IP request limit for `/radarr-webhook`, `/sonarr-webhook`, and `/libraries` (default `0`, disabled).
- `JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS`: Buffer window after the *last* event before a refresh runs (default `10`). Set to `0` to disable buffering and refresh immediately.
- `JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS`: Hard cap from the *first* event to the refresh (default `60`). Set to `0` to remove the cap, meaning refresh waits until there is a quiet period of `JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS` (continuous events can delay it indefinitely).
- `JELLYFIN_NOTIFIER_ALLOWLIST`: Comma-separated IPs/CIDRs allowed to access the webhook endpoints and `/libraries` (empty disables). Uses `request.remote_addr` so allowlist the proxy IP if you run behind one. The `/health` endpoint is not restricted.

Example: debounce `10` + max wait `60` means “refresh 10s after the last event, but no later than 60s after the first event.”

## Refresh Profiles

The notifier supports multiple Jellyfin refresh styles through a single request-level option: `refresh_profile`.

- Send it as a request header with `X-Jellyfin-Refresh-Profile`.
- Or send it as a POST parameter named `refresh_profile`.
- If both are present, `X-Jellyfin-Refresh-Profile` takes precedence.
- If neither is present, the notifier falls back to its default refresh behavior.

This makes it possible to keep a single webhook in Radarr or Sonarr while still choosing how aggressive the Jellyfin refresh should be.

### Available profiles

- `auto`: Recommended for a single Radarr or Sonarr webhook. The notifier chooses a sensible refresh strategy based on the incoming event type. Typical import/add events use a metadata-oriented refresh, while rename/delete/upgrade cleanup events stay lightweight.
- `fast`: Runs the lightest refresh. Use this when you mainly want Jellyfin to notice file changes quickly without doing unnecessary remote metadata work. This is a good fit for rename, delete, or upgrade-related events.
- `missing`: Refreshes the target and searches for missing metadata and images without behaving like a full overwrite. This is usually the best option for newly imported content because it fills gaps while avoiding more aggressive refresh behavior.
- `full`: Performs a deeper metadata and image refresh than `missing`. Use this when you want Jellyfin to re-check remote providers more aggressively for the targeted libraries or items.
- `replace`: The most aggressive option. Use this only when you explicitly want Jellyfin to replace existing remote metadata and images. This is useful for correcting a badly identified item or rebuilding stale artwork, but it is not a good everyday default.

### Which profile should I use?

- For one always-on Sonarr webhook: use `auto`.
- For newly added or imported media that often arrives without metadata: use `missing`.
- For rename/delete/upgrade-heavy workflows: use `fast`.
- For troubleshooting a bad match or stale remote data: use `full`.
- For intentionally overwriting existing remote metadata and images: use `replace`.

### Should I always use `missing`?

Usually not.

`missing` is a good default for new media, but it still does more work than a lightweight refresh. If you run it on every event, including rename, delete, and upgrade cleanup events, you add refresh overhead without much benefit. For most single-webhook setups, `auto` is the better choice because it keeps metadata lookups focused on the events that actually benefit from them.

### Header vs POST parameter

- For Radarr and Sonarr, the header form is usually the practical option because both apps already support custom webhook headers cleanly.
- The POST parameter form exists for backward compatibility and for clients that can add custom request fields to the webhook payload.
- If you need deterministic behavior across multiple callers, prefer the header and treat the POST parameter as a fallback.

## Using Radarr Webhook

- In Radarr, go to **Settings > Connect**.
- Add a new **Webhook**.
- Set the URL to `http://<jellyfin-notifier-ip>:5001/radarr-webhook`.
- Add the following custom headers:
  - `X-Jellyfin-Url`: Your Jellyfin server URL (e.g. `http://jellyfin.local:8096`)
  - `X-Jellyfin-Api-Key`: Your Jellyfin API key
  - (Optional) `X-Jellyfin-Collection-Types`: Comma-separated Jellyfin `CollectionType`s (e.g. `movies,tvshows,music,boxsets`) to refresh matching libraries
  - (Optional) `X-Jellyfin-Library-Ids`: Comma-separated Jellyfin library `ItemId`s to refresh (leave out to refresh all libraries)
  - (Optional) `X-Jellyfin-Refresh-Profile`: One of `auto`, `fast`, `missing`, `full`, or `replace`
- If you set `JELLYFIN_URL` and `JELLYFIN_API_KEY`, you can omit the first two headers.
- If your webhook sender supports custom POST fields, you can send `refresh_profile` instead of the header. If both are sent, the header wins.
- Save and test the webhook.

Test webhooks from Radarr (eventType `Test`) perform a Jellyfin reachability + API key check (`/System/Info`) and list your virtual folders (name, id, collection type, paths) in the logs so you can copy `ItemId`s. They **do not** trigger a refresh. If you send `X-Jellyfin-Collection-Types`, invalid types will be reported.

![Alt text](readme/radarr.png)

## Using Sonarr Webhook

- In Sonarr, go to **Settings > Connect**.
- Add a new **Webhook**.
- Set the URL to `http://<jellyfin-notifier-ip>:5001/sonarr-webhook`.
- Add the following custom headers:
  - `X-Jellyfin-Url`: Your Jellyfin server URL (e.g. `http://jellyfin.local:8096`)
  - `X-Jellyfin-Api-Key`: Your Jellyfin API key
  - (Optional) `X-Jellyfin-Collection-Types`: Comma-separated Jellyfin `CollectionType`s (e.g. `movies,tvshows,music,boxsets`) to refresh matching libraries
  - (Optional) `X-Jellyfin-Library-Ids`: Comma-separated Jellyfin library `ItemId`s to refresh (leave out to refresh all libraries)
  - (Optional) `X-Jellyfin-Refresh-Profile`: One of `auto`, `fast`, `missing`, `full`, or `replace`
- If you set `JELLYFIN_URL` and `JELLYFIN_API_KEY`, you can omit the first two headers.
- For a single Sonarr webhook, `X-Jellyfin-Refresh-Profile: auto` is usually the best choice.
- If your webhook sender supports custom POST fields, you can send `refresh_profile` instead of the header. If both are sent, the header wins.
- Save and test the webhook.

Test webhooks from Sonarr (eventType `Test`) perform a Jellyfin reachability + API key check (`/System/Info`) and list your virtual folders (name, id, collection type, paths) in the logs so you can copy `ItemId`s. They **do not** trigger a refresh. If you send `X-Jellyfin-Collection-Types`, invalid types will be reported.

## Running Locally (without Docker)

Make sure you have `uv` installed and your dependencies in `uv.lock`.

Run:

```bash
PYTHONPATH=src uv run -m radarr_sonarr_jellyfin_notifier
```

The app will listen on port 5001.

### Running tests

- Run all tests with:

```bash
./run_tests.sh
```

## License

This project is released under the [CC0 1.0 Universal](LICENSE) public domain dedication.

To the extent possible under law, I have waived all copyright and related rights in this work. You may use, copy, modify, and distribute the code for any purpose, including commercial use, without asking permission.

The code is provided “as is”, without warranty of any kind. Use it entirely at your own risk.
