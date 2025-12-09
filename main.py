import json
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


def _fetch_virtual_folders(jellyfin_url, jellyfin_api_key):
    base_url = jellyfin_url.rstrip("/")
    url = f"{base_url}/Library/VirtualFolders"
    headers = {"X-Emby-Token": jellyfin_api_key}
    params = {"api_key": jellyfin_api_key}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
    except requests.RequestException as exc:
        logging.warning("Jellyfin virtual folders request failed error=%s", exc)
        return False, f"Failed to fetch Jellyfin virtual folders: {exc}", 502, None

    if response.status_code != 200:
        logging.warning(
            "Jellyfin virtual folders request failed status=%s", response.status_code
        )
        if response.status_code in (401, 403):
            return (
                False,
                f"Jellyfin API key rejected for virtual folders (status {response.status_code})",
                401,
                None,
            )
        return (
            False,
            f"Failed to fetch Jellyfin virtual folders (status {response.status_code})",
            502,
            None,
        )

    try:
        folders = response.json()
    except ValueError as exc:
        logging.warning("Jellyfin virtual folders parse failed error=%s", exc)
        return False, "Failed to parse Jellyfin virtual folders response", 502, None

    if isinstance(folders, dict):
        folders = [folders]

    folders = sorted(
        folders, key=lambda f: (str(f.get("Name") or "").lower(), f.get("ItemId") or "")
    )

    logging.info("Jellyfin virtual folders count=%s", len(folders))
    for folder in folders:
        name = folder.get("Name")
        item_id = folder.get("ItemId") or folder.get("Id")
        collection_type = folder.get("CollectionType")
        locations = folder.get("Locations") or []
        path_infos = folder.get("LibraryOptions", {}).get("PathInfos") or []
        if not locations and path_infos:
            locations = [p.get("Path") for p in path_infos if p.get("Path")]
        location_str = ", ".join([loc for loc in locations if loc]) or "-"
        logging.info(
            "Virtual folder\n  name=%s\n  item_id=%s\n  collection_type=%s\n  locations=%s",
            name,
            item_id,
            collection_type,
            location_str,
        )

    return True, "Jellyfin virtual folders listed", 200, folders


def _parse_library_ids_header():
    raw = request.headers.get("X-Jellyfin-Library-Ids", "")
    if not raw:
        return []
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return ids


def _refresh_jellyfin(jellyfin_url, jellyfin_api_key, library_ids=None):
    base_url = jellyfin_url.rstrip("/")
    headers = {"X-Emby-Token": jellyfin_api_key}

    if library_ids:
        failures = []
        for lib_id in library_ids:
            refresh_url = f"{base_url}/Items/{lib_id}/Refresh"
            try:
                response = requests.post(
                    refresh_url,
                    headers=headers,
                    params={"Recursive": "true"},
                    timeout=10,
                )
            except requests.RequestException as exc:
                logging.warning(
                    "Jellyfin refresh failed for library_id=%s error=%s", lib_id, exc
                )
                failures.append(f"{lib_id} (error)")
                continue

            if response.status_code == 204:
                logging.info(
                    "Triggered Jellyfin refresh for library_id=%s", lib_id
                )
            else:
                logging.warning(
                    "Jellyfin refresh failed for library_id=%s status=%s",
                    lib_id,
                    response.status_code,
                )
                failures.append(f"{lib_id} (status {response.status_code})")

        if failures:
            return (
                False,
                f"Failed to refresh libraries: {', '.join(failures)}",
                500,
            )
        return True, "Triggered Jellyfin refresh for selected libraries", 200

    refresh_url = f"{base_url}/Library/Refresh"
    try:
        response = requests.post(refresh_url, headers=headers, timeout=10)
    except requests.RequestException as exc:
        logging.warning("Jellyfin refresh request failed error=%s", exc)
        return False, f"Failed to trigger Jellyfin: {exc}", 502

    if response.status_code == 204:
        return True, "Triggered Jellyfin refresh", 200

    logging.warning("Jellyfin refresh failed status=%s", response.status_code)
    return False, f"Failed to trigger Jellyfin ({response.status_code})", 500


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
        "Radarr event\n  type=%s\n  title=%s\n  year=%s\n  path=%s",
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
        else:
            return message, status

        vf_ok, vf_message, vf_status, _ = _fetch_virtual_folders(
            jellyfin_url, jellyfin_api_key
        )
        if vf_ok:
            return f"{message}; {vf_message}", 200
        return vf_message, vf_status

    library_ids = _parse_library_ids_header()
    if library_ids:
        logging.info("Radarr refresh targeting libraries=%s", ", ".join(library_ids))

    refresh_ok, refresh_message, refresh_status = _refresh_jellyfin(
        jellyfin_url, jellyfin_api_key, library_ids=library_ids or None
    )
    return refresh_message, refresh_status


@app.route("/sonarr-webhook", methods=["POST"])
def handle_sonarr_event():
    data = request.get_json(silent=True) or {}
    event_type = data.get("eventType")
    series = data.get("series", {}) or {}
    episode_file = data.get("episodeFile", {}) or {}
    series_title = series.get("title")
    episode_path = episode_file.get("relativePath") or episode_file.get("path")

    logging.info(
        "Sonarr event\n  type=%s\n  series=%s\n  episode_path=%s",
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
        else:
            return message, status

        vf_ok, vf_message, vf_status, _ = _fetch_virtual_folders(
            jellyfin_url, jellyfin_api_key
        )
        if vf_ok:
            return f"{message}; {vf_message}", 200
        return vf_message, vf_status


def _extract_jellyfin_credentials_for_list():
    jellyfin_url = request.headers.get("X-Jellyfin-Url") or request.args.get("url")
    jellyfin_api_key = request.headers.get("X-Jellyfin-Api-Key") or request.args.get(
        "api_key"
    )
    missing = []
    if not jellyfin_url:
        missing.append("X-Jellyfin-Url or url query param")
    if not jellyfin_api_key:
        missing.append("X-Jellyfin-Api-Key or api_key query param")
    if missing:
        joined = ", ".join(missing)
        return None, None, (f"Missing credentials: {joined}", 400)
    return jellyfin_url, jellyfin_api_key, None

    library_ids = _parse_library_ids_header()
    if library_ids:
        logging.info("Sonarr refresh targeting libraries=%s", ", ".join(library_ids))

    refresh_ok, refresh_message, refresh_status = _refresh_jellyfin(
        jellyfin_url, jellyfin_api_key, library_ids=library_ids or None
    )
    return refresh_message, refresh_status


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/libraries", methods=["GET"])
def list_libraries():
    jellyfin_url, jellyfin_api_key, error_response = (
        _extract_jellyfin_credentials_for_list()
    )
    if error_response:
        return error_response

    ok, message, status, folders = _fetch_virtual_folders(
        jellyfin_url, jellyfin_api_key
    )
    if not ok:
        return message, status

    libraries = []
    for folder in folders:
        name = folder.get("Name")
        item_id = folder.get("ItemId") or folder.get("Id")
        collection_type = folder.get("CollectionType")
        locations = folder.get("Locations") or []
        path_infos = folder.get("LibraryOptions", {}).get("PathInfos") or []
        if not locations and path_infos:
            locations = [p.get("Path") for p in path_infos if p.get("Path")]
        libraries.append(
            {
                "name": name,
                "itemId": item_id,
                "collectionType": collection_type,
                "locations": [p for p in locations if p],
            }
        )

    payload = {"libraries": libraries}
    return app.response_class(
        json.dumps(payload, indent=2), status=200, mimetype="application/json"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
