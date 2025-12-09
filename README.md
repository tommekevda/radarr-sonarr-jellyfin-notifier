# Radarr/Sonarr Jellyfin Notifier

This is a simple Flask application that listens for webhook events from Radarr or Sonarr and triggers a library refresh on Jellyfin.

## How it works

- The app exposes two endpoints: `/radarr-webhook` for Radarr and `/sonarr-webhook` for Sonarr.
- Radarr/Sonarr should send custom headers: `X-Jellyfin-Url` (your Jellyfin server URL) and `X-Jellyfin-Api-Key` (your Jellyfin API key).
- Upon receiving a Radarr or Sonarr event, the app triggers a refresh on the Jellyfin library by calling the Jellyfin API.
- Optionally, you can target specific libraries by sending `X-Jellyfin-Library-Ids` with a comma-separated list of Jellyfin library `ItemId` values. If omitted, all libraries are refreshed.

## Flask Application

The app runs a Flask server on port `5001` and listens for Radarr and Sonarr webhook events.

### Health check

- `GET /health` returns HTTP 200 with `{"status": "ok"}`.

### List libraries

- `GET /libraries` returns JSON with your Jellyfin libraries (name, itemId, collectionType, locations).
- Provide Jellyfin credentials via headers (`X-Jellyfin-Url`, `X-Jellyfin-Api-Key`) or query params (`?url=<...>&api_key=<...>`).
- Use this to copy `ItemId`s for the optional `X-Jellyfin-Library-Ids` header.
- Example (browser-friendly URL; `jellyfin-notifier-ip`):

```
http://<jellyfin-notifier-ip>:5001/libraries?url=http://jellyfin.local:8096&api_key=<your-jellyfin-api-key>
```

## Running with Docker

### Dockerfile

The Dockerfile uses Python 3.12 slim image, installs dependencies via `uv` package manager, defines a container healthcheck on `/health`, and runs the app with:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY uv.lock .

RUN pip install --no-cache-dir uv && uv install

COPY . .

EXPOSE 5001

CMD ["uv", "run", "main.py"]
```

### docker-compose.yml

The docker-compose file builds the Docker image named `radarr-jellyfin-notifier`, maps port 5001, and mounts the local directory for easy development:

```yaml
services:
  radarr-jellyfin-notifier:
    build: https://github.com/tommekevda/radarr-jellyfin-notifier.git
    container_name: radarr-jellyfin-notifier
    restart: unless-stopped
    ports:
      - "5001:5001"
    # volumes:
    #   - .:/app
```

## Using Radarr Webhook

- In Radarr, go to **Settings > Connect**.
- Add a new **Webhook**.
- Set the URL to `http://<jellyfin-notifier-ip>:5001/radarr-webhook`.
- Add the following custom headers:
  - `X-Jellyfin-Url`: Your Jellyfin server URL (e.g. `http://jellyfin.local:8096`)
  - `X-Jellyfin-Api-Key`: Your Jellyfin API key
  - (Optional) `X-Jellyfin-Library-Ids`: Comma-separated Jellyfin library `ItemId`s to refresh (leave out to refresh all libraries)
- Save and test the webhook.

Test webhooks from Radarr (eventType `Test`) perform a Jellyfin reachability + API key check (`/System/Info`) and list your virtual folders (name, id, paths) in the logs so you can copy `ItemId`s. They **do not** trigger a library refresh.

![Alt text](readme/radarr.png)

## Using Sonarr Webhook

- In Sonarr, go to **Settings > Connect**.
- Add a new **Webhook**.
- Set the URL to `http://<jellyfin-notifier-ip>:5001/sonarr-webhook`.
- Add the following custom headers:
  - `X-Jellyfin-Url`: Your Jellyfin server URL (e.g. `http://jellyfin.local:8096`)
  - `X-Jellyfin-Api-Key`: Your Jellyfin API key
  - (Optional) `X-Jellyfin-Library-Ids`: Comma-separated Jellyfin library `ItemId`s to refresh (leave out to refresh all libraries)
- Save and test the webhook.

Test webhooks from Sonarr (eventType `Test`) perform a Jellyfin reachability + API key check (`/System/Info`) and list your virtual folders (name, id, paths) in the logs so you can copy `ItemId`s. They **do not** trigger a library refresh.

## Running Locally (without Docker)

Make sure you have `uv` installed and your dependencies in `uv.lock`.

Run:

```bash
uv run main.py
```

The app will listen on port 5001.
