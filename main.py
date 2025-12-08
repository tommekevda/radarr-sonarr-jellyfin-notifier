from flask import Flask, jsonify, request
import requests

app = Flask(__name__)


@app.route("/radarr-webhook", methods=["POST"])
def handle_radarr_event():
    data = request.json
    print("Received event from Radarr:", data.get("eventType"))

    # Read custom headers from Radarr
    jellyfin_url = request.headers.get("X-Jellyfin-Url")
    jellyfin_api_key = request.headers.get("X-Jellyfin-Api-Key")

    if not jellyfin_url or not jellyfin_api_key:
        return "Missing Jellyfin headers", 400

    headers = {"X-Emby-Token": jellyfin_api_key}
    refresh_url = f"{jellyfin_url}/Library/Refresh"
    response = requests.post(refresh_url, headers=headers)

    if response.status_code == 204:
        return "Triggered Jellyfin refresh", 200
    else:
        return f"Failed to trigger Jellyfin ({response.status_code})", 500


@app.route("/sonarr-webhook", methods=["POST"])
def handle_sonarr_event():
    data = request.json
    print("Received event from Sonarr:", data.get("eventType"))

    # Read custom headers from Sonarr
    jellyfin_url = request.headers.get("X-Jellyfin-Url")
    jellyfin_api_key = request.headers.get("X-Jellyfin-Api-Key")

    if not jellyfin_url or not jellyfin_api_key:
        return "Missing Jellyfin headers", 400

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
