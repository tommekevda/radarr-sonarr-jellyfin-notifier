import logging
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# Configure basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Filter out healthcheck requests from werkzeug logs
class _HealthLogFilter(logging.Filter):
    def filter(self, record):
        args = getattr(record, "args", ())
        # record.args[0] holds the request line, e.g. "GET /health HTTP/1.1"
        return not (args and "/health" in str(args[0]))


logging.getLogger("werkzeug").addFilter(_HealthLogFilter())


def _is_test_event(event_type):
    return isinstance(event_type, str) and event_type.lower() == "test"


def _ping_jellyfin(jellyfin_url, jellyfin_api_key):
    base_url = jellyfin_url.rstrip("/")
    # First, check if the Jellyfin host is reachable
    try:
        requests.get(base_url, timeout=5)
    except requests.RequestException as exc:
        logging.warning("Jellyfin ping failed: host unreachable error=%s", exc)
        return False, f"Failed to reach Jellyfin: {exc}", 502

    # Then, validate the API key against /System/Info
    headers = {"X-Emby-Token": jellyfin_api_key}
    ping_url = f"{base_url}/System/Info"
    try:
        response = requests.get(ping_url, headers=headers, timeout=5)
    except requests.RequestException as exc:
        logging.warning("Jellyfin /System/Info request failed error=%s", exc)
        return False, f"Failed to reach Jellyfin: {exc}", 502

    if response.status_code == 200:
        return True, "Jellyfin connection and API key OK", 200

    if response.status_code in (401, 403):
        logging.warning(
            "Jellyfin API key rejected status=%s", response.status_code
        )
        return (
            False,
            f"Jellyfin API key rejected (status {response.status_code})",
            401,
        )

    logging.warning("Jellyfin /System/Info failed status=%s", response.status_code)
    return False, f"Failed to reach Jellyfin (status {response.status_code})", 502


def _extract_jellyfin_headers():
    missing = []
    jellyfin_url = request.headers.get("X-Jellyfin-Url")
    jellyfin_api_key = request.headers.get("X-Jellyfin-Api-Key")

    if not jellyfin_url:
        missing.append("X-Jellyfin-Url")
    if not jellyfin_api_key:
        missing.append("X-Jellyfin-Api-Key")

    if missing:
        joined = ", ".join(missing)
        logging.warning("Rejecting request missing headers=%s", joined)
        return None, None, (f"Missing headers: {joined}", 400)

    return jellyfin_url, jellyfin_api_key, None


@app.route("/radarr-webhook", methods=["POST"])
def handle_radarr_event():
    data = request.get_json(silent=True) or {}
    event_type = data.get("eventType")
    movie = data.get("movie", {}) or {}
    movie_file = data.get("movieFile", {}) or {}
    movie_title = movie.get("title")
    movie_year = movie.get("year")
    movie_path = movie_file.get("relativePath") or movie_file.get("path")

    logging.info(
        "Radarr event=%s title=%s year=%s path=%s",
        event_type,
        movie_title,
        movie_year,
        movie_path,
    )

    jellyfin_url, jellyfin_api_key, error_response = _extract_jellyfin_headers()
    if error_response:
        return error_response

    if _is_test_event(event_type):
        ok, message, status = _ping_jellyfin(jellyfin_url, jellyfin_api_key)
        if ok:
            logging.info("Radarr test event: Jellyfin reachable")
        return message, status

    headers = {"X-Emby-Token": jellyfin_api_key}
    refresh_url = f"{jellyfin_url}/Library/Refresh"
    response = requests.post(refresh_url, headers=headers)

    if response.status_code == 204:
        return "Triggered Jellyfin refresh", 200
    else:
        return f"Failed to trigger Jellyfin ({response.status_code})", 500


@app.route("/sonarr-webhook", methods=["POST"])
def handle_sonarr_event():
    data = request.get_json(silent=True) or {}
    event_type = data.get("eventType")
    series = data.get("series", {}) or {}
    episode_file = data.get("episodeFile", {}) or {}
    series_title = series.get("title")
    episode_path = episode_file.get("relativePath") or episode_file.get("path")

    logging.info(
        "Sonarr event=%s series=%s episode_path=%s",
        event_type,
        series_title,
        episode_path,
    )

    jellyfin_url, jellyfin_api_key, error_response = _extract_jellyfin_headers()
    if error_response:
        return error_response

    if _is_test_event(event_type):
        ok, message, status = _ping_jellyfin(jellyfin_url, jellyfin_api_key)
        if ok:
            logging.info("Sonarr test event: Jellyfin reachable")
        return message, status

    headers = {"X-Emby-Token": jellyfin_api_key}
    refresh_url = f"{jellyfin_url}/Library/Refresh"
    response = requests.post(refresh_url, headers=headers)

    if response.status_code == 204:
        return "Triggered Jellyfin refresh", 200
    else:
        return f"Failed to trigger Jellyfin ({response.status_code})", 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
