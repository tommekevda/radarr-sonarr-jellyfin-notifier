import ipaddress
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from .jellyfin import (
    JellyfinClient,
    merge_ids,
    select_library_ids_by_collection,
)

webhooks_bp = Blueprint("webhooks", __name__)

_RATE_LIMIT_STATE: Dict[str, List[float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()
_REFRESH_QUEUE: Dict[Tuple[str, str], "RefreshBucket"] = {}
_REFRESH_COND = threading.Condition()


@dataclass
class RefreshBucket:
    pending_all: bool = False
    pending_ids: List[str] = field(default_factory=list)
    next_run: Optional[float] = None
    first_seen: Optional[float] = None


def _get_rate_limit_per_minute() -> int:
    raw = os.getenv("JELLYFIN_NOTIFIER_RATE_LIMIT_PER_MINUTE", "")
    if not raw:
        return 0
    try:
        limit = int(raw)
    except ValueError:
        logging.warning("Invalid rate limit value: %s", raw)
        return 0
    return max(0, limit)


def _get_refresh_debounce_seconds() -> int:
    raw = os.getenv("JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS", "")
    if not raw:
        return 10
    try:
        seconds = int(raw)
    except ValueError:
        logging.warning("Invalid refresh debounce value: %s", raw)
        return 10
    return max(0, seconds)


def _get_refresh_max_wait_seconds() -> int:
    raw = os.getenv("JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS", "")
    if not raw:
        return 60
    try:
        seconds = int(raw)
    except ValueError:
        logging.warning("Invalid refresh max wait value: %s", raw)
        return 60
    return max(0, seconds)


def _parse_allowlist() -> Tuple[List[Any], Optional[str]]:
    raw = os.getenv("JELLYFIN_NOTIFIER_ALLOWLIST", "")
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    if not entries:
        return [], None
    networks: List[Any] = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logging.warning("Invalid allowlist entry: %s", entry)
            return [], f"Invalid allowlist entry: {entry}"
    return networks, None


def _is_rate_limited(
    remote_addr: str, limit: int, window_seconds: int = 60
) -> bool:
    now = time.time()
    with _RATE_LIMIT_LOCK:
        timestamps = _RATE_LIMIT_STATE.get(remote_addr, [])
        cutoff = now - window_seconds
        timestamps = [ts for ts in timestamps if ts > cutoff]
        if len(timestamps) >= limit:
            _RATE_LIMIT_STATE[remote_addr] = timestamps
            return True
        timestamps.append(now)
        _RATE_LIMIT_STATE[remote_addr] = timestamps
        return False


def _enqueue_refresh_request(
    jellyfin_url: str, jellyfin_api_key: str, library_ids: Optional[List[str]]
) -> Tuple[bool, str, int]:
    debounce_seconds = _get_refresh_debounce_seconds()
    max_wait_seconds = _get_refresh_max_wait_seconds()
    if debounce_seconds <= 0:
        client = JellyfinClient(jellyfin_url, jellyfin_api_key)
        return client.refresh(library_ids=library_ids or None)

    key = (jellyfin_url, jellyfin_api_key)
    now = time.time()
    with _REFRESH_COND:
        bucket = _REFRESH_QUEUE.get(key)
        if bucket is None:
            bucket = RefreshBucket()
            _REFRESH_QUEUE[key] = bucket
        if bucket.first_seen is None:
            bucket.first_seen = now
        if library_ids:
            if not bucket.pending_all:
                bucket.pending_ids = merge_ids(bucket.pending_ids, library_ids)
        else:
            bucket.pending_all = True
            bucket.pending_ids = []
        scheduled = now + debounce_seconds
        if max_wait_seconds > 0 and bucket.first_seen is not None:
            max_deadline = bucket.first_seen + max_wait_seconds
            if scheduled > max_deadline:
                scheduled = max_deadline
        bucket.next_run = scheduled
        _REFRESH_COND.notify()

    target_desc = "(all)" if not library_ids else ", ".join(library_ids)
    logging.info(
        "Refresh queued targets=%s delay_seconds=%s max_wait_seconds=%s",
        target_desc,
        debounce_seconds,
        max_wait_seconds,
    )
    return True, "Refresh queued", 202


def _get_next_due_bucket() -> Optional[Tuple[Tuple[str, str], RefreshBucket, float]]:
    if not _REFRESH_QUEUE:
        return None
    key = min(
        _REFRESH_QUEUE,
        key=lambda k: _REFRESH_QUEUE[k].next_run or float("inf"),
    )
    bucket = _REFRESH_QUEUE.get(key)
    if not bucket or bucket.next_run is None:
        return None
    return key, bucket, bucket.next_run


def _refresh_worker() -> None:
    while True:
        with _REFRESH_COND:
            while True:
                next_item = _get_next_due_bucket()
                if not next_item:
                    _REFRESH_COND.wait()
                    continue
                key, bucket, run_at = next_item
                delay = run_at - time.time()
                if delay > 0:
                    _REFRESH_COND.wait(timeout=delay)
                    continue
                _REFRESH_QUEUE.pop(key, None)
                break

        jellyfin_url, jellyfin_api_key = key
        if bucket.pending_all or not bucket.pending_ids:
            targets = None
            target_desc = "(all)"
        else:
            targets = bucket.pending_ids
            target_desc = ", ".join(bucket.pending_ids)
        client = JellyfinClient(jellyfin_url, jellyfin_api_key)
        ok, message, status = client.refresh(library_ids=targets)
        if ok:
            logging.info("Refresh completed targets=%s status=%s", target_desc, status)
        else:
            logging.warning(
                "Refresh failed targets=%s status=%s message=%s",
                target_desc,
                status,
                message,
            )


_WORKER_THREAD = threading.Thread(
    target=_refresh_worker, name="refresh-worker", daemon=True
)
_WORKER_THREAD.start()


@webhooks_bp.before_request
def _enforce_request_restrictions():
    remote_addr = request.remote_addr or ""
    allowlist, allowlist_error = _parse_allowlist()
    if allowlist_error:
        return allowlist_error, 500
    if allowlist:
        if not remote_addr:
            logging.warning("Request rejected missing remote_addr path=%s", request.path)
            return "Forbidden", 403
        try:
            ip = ipaddress.ip_address(remote_addr)
        except ValueError:
            logging.warning(
                "Request rejected invalid remote_addr=%s path=%s",
                remote_addr,
                request.path,
            )
            return "Forbidden", 403
        if not any(ip in network for network in allowlist):
            logging.warning(
                "Request rejected remote_addr=%s not in allowlist path=%s",
                remote_addr,
                request.path,
            )
            return "Forbidden", 403
    limit = _get_rate_limit_per_minute()
    if limit > 0:
        key = remote_addr or "unknown"
        if _is_rate_limited(key, limit):
            logging.warning(
                "Rate limit exceeded remote_addr=%s path=%s",
                remote_addr,
                request.path,
            )
            return "Rate limit exceeded", 429, {"Retry-After": "60"}
    return None


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
    jellyfin_url = req.headers.get("X-Jellyfin-Url") or os.getenv("JELLYFIN_URL")
    jellyfin_api_key = req.headers.get("X-Jellyfin-Api-Key") or os.getenv(
        "JELLYFIN_API_KEY"
    )

    if not jellyfin_url:
        missing.append("X-Jellyfin-Url or JELLYFIN_URL")
    if not jellyfin_api_key:
        missing.append("X-Jellyfin-Api-Key or JELLYFIN_API_KEY")

    if missing:
        joined = ", ".join(missing)
        logging.warning("Rejecting request missing credentials=%s", joined)
        return None, None, (f"Missing credentials: {joined}", 400)

    return jellyfin_url, jellyfin_api_key, None


def _pretty_json(payload: Dict[str, Any], status: int = 200):
    return current_app.response_class(
        json.dumps(payload, indent=2), status=status, mimetype="application/json"
    )


def _log_radarr_event(data: Dict[str, Any]) -> None:
    movie = data.get("movie", {}) or {}
    movie_file = data.get("movieFile", {}) or {}
    logging.info(
        "Webhook received source=radarr event_type=%s endpoint=%s remote=%s title=%s year=%s file=%s",
        data.get("eventType"),
        request.path,
        request.remote_addr,
        movie.get("title"),
        movie.get("year"),
        movie_file.get("relativePath") or movie_file.get("path"),
    )


def _log_sonarr_event(data: Dict[str, Any]) -> None:
    series = data.get("series", {}) or {}
    episode_file = data.get("episodeFile", {}) or {}
    logging.info(
        "Webhook received source=sonarr event_type=%s endpoint=%s remote=%s series=%s episode_path=%s",
        data.get("eventType"),
        request.path,
        request.remote_addr,
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
            logging.info(
                "Test event ok source=radarr event_type=%s endpoint=%s remote=%s",
                data.get("eventType"),
                request.path,
                request.remote_addr,
            )
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
                logging.info(
                    "Test event targets source=radarr event_type=%s endpoint=%s targets=%s",
                    data.get("eventType"),
                    request.path,
                    ", ".join(combined_ids),
                )
            if collection_types:
                logging.info(
                    "Test event collection types source=radarr event_type=%s endpoint=%s collection_types=%s targets=%s",
                    data.get("eventType"),
                    request.path,
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
    targets = ", ".join(combined_ids) if combined_ids else "(all)"
    logging.info(
        "Refresh request source=radarr event_type=%s endpoint=%s targets=%s collection_types=%s",
        data.get("eventType"),
        request.path,
        targets,
        ", ".join(collection_types) if collection_types else "(none)",
    )

    _, refresh_message, refresh_status = _enqueue_refresh_request(
        jellyfin_url, jellyfin_api_key, combined_ids or None
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
            logging.info(
                "Test event ok source=sonarr event_type=%s endpoint=%s remote=%s",
                data.get("eventType"),
                request.path,
                request.remote_addr,
            )
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
                logging.info(
                    "Test event targets source=sonarr event_type=%s endpoint=%s targets=%s",
                    data.get("eventType"),
                    request.path,
                    ", ".join(combined_ids),
                )
            if collection_types:
                logging.info(
                    "Test event collection types source=sonarr event_type=%s endpoint=%s collection_types=%s targets=%s",
                    data.get("eventType"),
                    request.path,
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
    targets = ", ".join(combined_ids) if combined_ids else "(all)"
    logging.info(
        "Refresh request source=sonarr event_type=%s endpoint=%s targets=%s collection_types=%s",
        data.get("eventType"),
        request.path,
        targets,
        ", ".join(collection_types) if collection_types else "(none)",
    )

    _, refresh_message, refresh_status = _enqueue_refresh_request(
        jellyfin_url, jellyfin_api_key, combined_ids or None
    )
    return refresh_message, refresh_status


@webhooks_bp.route("/libraries", methods=["GET"])
def list_libraries():
    jellyfin_url = (
        request.headers.get("X-Jellyfin-Url")
        or request.args.get("url")
        or os.getenv("JELLYFIN_URL")
    )
    jellyfin_api_key = (
        request.headers.get("X-Jellyfin-Api-Key")
        or request.args.get("api_key")
        or os.getenv("JELLYFIN_API_KEY")
    )
    missing = []
    if not jellyfin_url:
        missing.append("X-Jellyfin-Url header, url query param, or JELLYFIN_URL")
    if not jellyfin_api_key:
        missing.append(
            "X-Jellyfin-Api-Key header, api_key query param, or JELLYFIN_API_KEY"
        )
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
