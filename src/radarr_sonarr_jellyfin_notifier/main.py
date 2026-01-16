import os

from flask import Flask, jsonify

from .logging_setup import configure_logging
from .webhooks import webhooks_bp


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)
    app.register_blueprint(webhooks_bp)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


def _get_port() -> int:
    raw = os.getenv("JELLYFIN_NOTIFIER_PORT") or os.getenv("PORT") or "5001"
    try:
        return int(raw)
    except ValueError:
        return 5001


def main() -> None:
    port = _get_port()
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
