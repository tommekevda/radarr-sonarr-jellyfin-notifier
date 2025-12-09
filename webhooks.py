import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from jellyfin import (
    JellyfinClient,
    merge_ids,
    select_library_ids_by_collection,
)

webhooks_bp = Blueprint("webhooks", __name__)


def is_test_event(event_type: Any) -> bool:
    return isinstance(event_type, str) and event_type.lower() == "test"


def parse_library_ids_header(req) -> List[str]:
    raw = req.headers.get("X-Jellyfin-Library-Ids", "")
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_collection_types_header(req) -> List[str]:
    raw = req.headers.get("X-Jellyfin-Collection-Types", "")
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def extract_jellyfin_headers(
    req,
) -> Tuple[Optional[str], Optional[str], Optional[Tuple[str, int]]]:
    missing = []
    jellyfin_url = req.headers.get("X-Jellyfin-Url")
    jellyfin_api_key = req.headers.get("X-Jellyfin-Api-Key")

    if not jellyfin_url:
        missing.append("X-Jellyfin-Url")
    if not jellyfin_api_key:
        missing.append("X-Jellyfin-Api-Key")

    if missing:
        joined = ", ".join(missing)
        logging.warning("Rejecting request missing headers=%s", joined)
        return None, None, (f"Missing headers: {joined}", 400)

    return jellyfin_url, jellyfin_api_key, None


def _pretty_json(payload: Dict[str, Any], status: int = 200):
    return current_app.response_class(
        json.dumps(payload, indent=2), status=status, mimetype="application/json"
    )


def _log_radarr_event(data: Dict[str, Any]) -> None:
    movie = data.get("movie", {}) or {}
    movie_file = data.get("movieFile", {}) or {}
    logging.info(
        "Radarr event\n  type=%s\n  title=%s\n  year=%s\n  path=%s",
        data.get("eventType"),
        movie.get("title"),
        movie.get("year"),
        movie_file.get("relativePath") or movie_file.get("path"),
    )


def _log_sonarr_event(data: Dict[str, Any]) -> None:
    series = data.get("series", {}) or {}
    episode_file = data.get("episodeFile", {}) or {}
    logging.info(
        "Sonarr event\n  type=%s\n  series=%s\n  episode_path=%s",
        data.get("eventType"),
        series.get("title"),
        episode_file.get("relativePath") or episode_file.get("path"),
    )


def _resolve_collection_types(
    client: JellyfinClient, collection_types: List[str]
) -> Tuple[Optional[List[str]], Optional[Tuple[str, int]]]:
    ok, vf_message, vf_status, folders = client.fetch_virtual_folders()
    if not ok:
        return None, (vf_message, vf_status)

    selected_ids, missing_types, available_types = select_library_ids_by_collection(
        folders or [], collection_types
    )
    if missing_types:
        return (
            None,
            (
                f"Unknown collection types: {', '.join(missing_types)}. "
                f"Available: {', '.join(available_types)}",
                400,
            ),
        )
    if not selected_ids:
        return (
            None,
            (
                f"No libraries matched collection types: {', '.join(collection_types)}",
                400,
            ),
        )
    return selected_ids, None


@webhooks_bp.route("/radarr-webhook", methods=["POST"])
def handle_radarr_event():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    _log_radarr_event(data)

    jellyfin_url, jellyfin_api_key, error_response = extract_jellyfin_headers(request)
    if error_response:
        return error_response

    client = JellyfinClient(jellyfin_url, jellyfin_api_key)
    library_ids = parse_library_ids_header(request)
    collection_types = parse_collection_types_header(request)

    if is_test_event(data.get("eventType")):
        ok, message, status = client.ping()
        if ok:
            logging.info("Radarr test event: Jellyfin reachable")
        else:
            return message, status

        vf_ok, vf_message, vf_status, folders = client.fetch_virtual_folders()
        if vf_ok:
            selected_ids: List[str] = []
            if collection_types:
                selected_ids, missing_types, available_types = (
                    select_library_ids_by_collection(folders or [], collection_types)
                )
                if missing_types:
                    return (
                        f"Unknown collection types: {', '.join(missing_types)}. "
                        f"Available: {', '.join(available_types)}",
                        400,
                    )
            combined_ids = merge_ids(library_ids, selected_ids)
            if combined_ids:
                logging.info("Radarr test: libraries=%s", ", ".join(combined_ids))
            if collection_types:
                logging.info(
                    "Radarr test: collection types=%s resolved libraries=%s",
                    ", ".join(collection_types),
                    ", ".join(selected_ids) if selected_ids else "(none)",
                )
            return f"{message}; {vf_message}", 200
        return vf_message, vf_status

    resolved_ids: List[str] = []
    if collection_types:
        resolved_ids_or_error, error = _resolve_collection_types(
            client, collection_types
        )
        if error:
            return error
        resolved_ids = resolved_ids_or_error or []

    combined_ids = merge_ids(library_ids, resolved_ids)
    if combined_ids:
        logging.info("Radarr refresh targeting libraries=%s", ", ".join(combined_ids))

    refresh_ok, refresh_message, refresh_status = client.refresh(
        library_ids=combined_ids or None
    )
    return refresh_message, refresh_status


@webhooks_bp.route("/sonarr-webhook", methods=["POST"])
def handle_sonarr_event():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    _log_sonarr_event(data)

    jellyfin_url, jellyfin_api_key, error_response = extract_jellyfin_headers(request)
    if error_response:
        return error_response

    client = JellyfinClient(jellyfin_url, jellyfin_api_key)
    library_ids = parse_library_ids_header(request)
    collection_types = parse_collection_types_header(request)

    if is_test_event(data.get("eventType")):
        ok, message, status = client.ping()
        if ok:
            logging.info("Sonarr test event: Jellyfin reachable")
        else:
            return message, status

        vf_ok, vf_message, vf_status, folders = client.fetch_virtual_folders()
        if vf_ok:
            selected_ids: List[str] = []
            if collection_types:
                selected_ids, missing_types, available_types = (
                    select_library_ids_by_collection(folders or [], collection_types)
                )
                if missing_types:
                    return (
                        f"Unknown collection types: {', '.join(missing_types)}. "
                        f"Available: {', '.join(available_types)}",
                        400,
                    )
            combined_ids = merge_ids(library_ids, selected_ids)
            if combined_ids:
                logging.info("Sonarr test: libraries=%s", ", ".join(combined_ids))
            if collection_types:
                logging.info(
                    "Sonarr test: collection types=%s resolved libraries=%s",
                    ", ".join(collection_types),
                    ", ".join(selected_ids) if selected_ids else "(none)",
                )
            return f"{message}; {vf_message}", 200
        return vf_message, vf_status

    resolved_ids: List[str] = []
    if collection_types:
        resolved_ids_or_error, error = _resolve_collection_types(
            client, collection_types
        )
        if error:
            return error
        resolved_ids = resolved_ids_or_error or []

    combined_ids = merge_ids(library_ids, resolved_ids)
    if combined_ids:
        logging.info("Sonarr refresh targeting libraries=%s", ", ".join(combined_ids))

    refresh_ok, refresh_message, refresh_status = client.refresh(
        library_ids=combined_ids or None
    )
    return refresh_message, refresh_status


@webhooks_bp.route("/libraries", methods=["GET"])
def list_libraries():
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
        return f"Missing credentials: {joined}", 400

    client = JellyfinClient(jellyfin_url, jellyfin_api_key)
    ok, message, status, folders = client.fetch_virtual_folders()
    if not ok:
        return message, status

    libraries = []
    for folder in folders or []:
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

    return _pretty_json({"libraries": libraries})
