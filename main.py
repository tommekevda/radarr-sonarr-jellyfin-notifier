from flask import Flask, jsonify

from logging_setup import configure_logging
from webhooks import webhooks_bp


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)
    app.register_blueprint(webhooks_bp)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
