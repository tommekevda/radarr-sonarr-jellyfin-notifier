# Release Notes

## 1.1.1 - 2026-04-18
- Fixed: GitHub Actions Docker manifest publishing now handles newline-delimited tag output from `docker/metadata-action` without shell parsing failures.
- Changed: README now notes how to pin the published Docker image to `1.1.1` instead of following `latest`.
- Changed: Project version metadata updated to `1.1.1`.

## 1.1.0 - 2026-03-31
- Added: Request-level `refresh_profile` support for Radarr and Sonarr webhooks.
- Added: `X-Jellyfin-Refresh-Profile` header support and `refresh_profile` POST/body fallback with header precedence.
- Added: Refresh profile modes `auto`, `fast`, `missing`, `full`, and `replace`.
- Added: Queue merging now keeps the strongest pending refresh profile when multiple webhook events are buffered together.
- Changed: Non-default metadata-oriented refresh profiles now target libraries through item refresh calls so Jellyfin metadata/image refresh parameters can be applied consistently.
- Changed: README now documents refresh profiles, request precedence, and recommended single-webhook usage.
- Changed: Project version metadata updated to `1.1.0`.

## 1.0.3 - 2026-01-25
- Added: RELEASE_NOTES.md to track releases.
- Added: Common GitHub badges to README.
- Changed: docker-compose uses `image` for the GHCR reference.
- Changed: README docker-compose example matches the compose file.

## v1.0.1 - 2026-01-25
- Changed: Docker CI workflow now builds and pushes images.
- Changed: Version metadata updates (README, compose files, pyproject, uv.lock).

## 1.0.0 - 2026-01-16
- Changed: Documentation/metadata updates (same commit as 0.3.0 tag).

## 0.3.0 - 2026-01-16
- Changed: Documentation/metadata updates.

## 0.2.3 - 2026-01-16
- Added: Environment variables in docker-compose files.

## 0.2.2 - 2026-01-16
- Added: tmpfs mount for `/tmp` in compose.
- Added: Buffering for rapid incoming webhook requests.
- Added: Expanded test coverage.
- Changed: Documentation and docker-compose cleanup.

## 0.2.1 - 2025-12-11
- Changed: README update.
