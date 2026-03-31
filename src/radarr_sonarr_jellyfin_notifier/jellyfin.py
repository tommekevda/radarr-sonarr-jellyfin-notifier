import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


JellyfinResult = Tuple[bool, str, int]
JellyfinFoldersResult = Tuple[bool, str, int, Optional[List[Dict[str, Any]]]]

ITEM_REFRESH_PROFILES: Dict[str, Dict[str, str]] = {
    "missing": {
        "MetadataRefreshMode": "Default",
        "ImageRefreshMode": "Default",
        "ReplaceAllMetadata": "false",
        "ReplaceAllImages": "false",
    },
    "full": {
        "MetadataRefreshMode": "FullRefresh",
        "ImageRefreshMode": "FullRefresh",
        "ReplaceAllMetadata": "false",
        "ReplaceAllImages": "false",
    },
    "replace": {
        "MetadataRefreshMode": "FullRefresh",
        "ImageRefreshMode": "FullRefresh",
        "ReplaceAllMetadata": "true",
        "ReplaceAllImages": "true",
    },
}


def build_item_refresh_params(refresh_profile: Optional[str] = None) -> Dict[str, str]:
    params = {"Recursive": "true"}
    if refresh_profile:
        params.update(ITEM_REFRESH_PROFILES.get(refresh_profile, {}))
    return params


@dataclass
class JellyfinClient:
    url: str
    api_key: str

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")

    @property
    def headers(self) -> Dict[str, str]:
        return {"X-Emby-Token": self.api_key}

    def ping(self) -> JellyfinResult:
        try:
            requests.get(self.base_url, timeout=5)
        except requests.RequestException as exc:
            logging.warning("Jellyfin ping failed: host unreachable error=%s", exc)
            return False, f"Failed to reach Jellyfin: {exc}", 502

        ping_url = f"{self.base_url}/System/Info"
        try:
            response = requests.get(ping_url, headers=self.headers, timeout=5)
        except requests.RequestException as exc:
            logging.warning("Jellyfin /System/Info request failed error=%s", exc)
            return False, f"Failed to reach Jellyfin: {exc}", 502

        if response.status_code == 200:
            return True, "Jellyfin connection and API key OK", 200

        if response.status_code in (401, 403):
            logging.warning("Jellyfin API key rejected status=%s", response.status_code)
            return (
                False,
                f"Jellyfin API key rejected (status {response.status_code})",
                401,
            )

        logging.warning("Jellyfin /System/Info failed status=%s", response.status_code)
        return False, f"Failed to reach Jellyfin (status {response.status_code})", 502

    def fetch_virtual_folders(self) -> JellyfinFoldersResult:
        url = f"{self.base_url}/Library/VirtualFolders"
        params = {"api_key": self.api_key}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=5)
        except requests.RequestException as exc:
            logging.warning("Jellyfin virtual folders request failed error=%s", exc)
            return False, f"Failed to fetch Jellyfin virtual folders: {exc}", 502, None

        if response.status_code != 200:
            logging.warning(
                "Jellyfin virtual folders request failed status=%s",
                response.status_code,
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
            folders,
            key=lambda f: (str(f.get("Name") or "").lower(), f.get("ItemId") or ""),
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

    def _refresh_items(
        self,
        item_ids: List[str],
        refresh_profile: Optional[str] = None,
        success_message: str = "Triggered Jellyfin refresh for selected libraries",
    ) -> JellyfinResult:
        failures: List[str] = []
        params = build_item_refresh_params(refresh_profile)
        for item_id in item_ids:
            refresh_url = f"{self.base_url}/Items/{item_id}/Refresh"
            try:
                response = requests.post(
                    refresh_url,
                    headers=self.headers,
                    params=params,
                    timeout=10,
                )
            except requests.RequestException as exc:
                logging.warning(
                    "Jellyfin refresh failed for item_id=%s profile=%s error=%s",
                    item_id,
                    refresh_profile or "(default)",
                    exc,
                )
                failures.append(f"{item_id} (error)")
                continue

            if response.status_code == 204:
                logging.info(
                    "Triggered Jellyfin refresh for item_id=%s profile=%s",
                    item_id,
                    refresh_profile or "(default)",
                )
            else:
                logging.warning(
                    "Jellyfin refresh failed for item_id=%s profile=%s status=%s",
                    item_id,
                    refresh_profile or "(default)",
                    response.status_code,
                )
                failures.append(f"{item_id} (status {response.status_code})")

        if failures:
            return False, f"Failed to refresh libraries: {', '.join(failures)}", 500
        return True, success_message, 200

    def refresh(
        self,
        library_ids: Optional[List[str]] = None,
        refresh_profile: Optional[str] = None,
    ) -> JellyfinResult:
        if library_ids:
            return self._refresh_items(library_ids, refresh_profile=refresh_profile)

        if refresh_profile in ITEM_REFRESH_PROFILES:
            ok, message, status, folders = self.fetch_virtual_folders()
            if not ok:
                return False, message, status

            all_library_ids = [
                folder.get("ItemId") or folder.get("Id")
                for folder in folders or []
                if folder.get("ItemId") or folder.get("Id")
            ]
            if not all_library_ids:
                logging.warning(
                    "Jellyfin refresh failed profile=%s no libraries available",
                    refresh_profile,
                )
                return False, "No Jellyfin libraries available to refresh", 500

            return self._refresh_items(
                all_library_ids,
                refresh_profile=refresh_profile,
                success_message="Triggered Jellyfin refresh for all libraries",
            )

        refresh_url = f"{self.base_url}/Library/Refresh"
        try:
            response = requests.post(refresh_url, headers=self.headers, timeout=10)
        except requests.RequestException as exc:
            logging.warning(
                "Jellyfin refresh request failed profile=%s error=%s",
                refresh_profile or "(default)",
                exc,
            )
            return False, f"Failed to trigger Jellyfin: {exc}", 502

        if response.status_code == 204:
            return True, "Triggered Jellyfin refresh", 200

        logging.warning(
            "Jellyfin refresh failed profile=%s status=%s",
            refresh_profile or "(default)",
            response.status_code,
        )
        return False, f"Failed to trigger Jellyfin ({response.status_code})", 500


def select_library_ids_by_collection(
    folders: List[Dict[str, Any]], requested_types: List[str]
) -> Tuple[List[str], List[str], List[str]]:
    requested = set(requested_types)
    available_types = set()
    selected_ids: List[str] = []

    for folder in folders:
        ctype = (folder.get("CollectionType") or "").lower()
        if not ctype:
            continue
        available_types.add(ctype)
        if ctype in requested:
            item_id = folder.get("ItemId") or folder.get("Id")
            if item_id:
                selected_ids.append(item_id)

    missing = sorted(requested - available_types)
    return selected_ids, missing, sorted(available_types)


def merge_ids(*lists_of_ids: Optional[List[str]]) -> List[str]:
    seen = set()
    merged: List[str] = []
    for ids in lists_of_ids:
        for value in ids or []:
            if value and value not in seen:
                merged.append(value)
                seen.add(value)
    return merged
