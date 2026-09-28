"""Flask app for the Sentinel demo dashboard (module G).

Run it with:
    python -m dashboard.app --provider fixture --port 5000
    python -m dashboard.app --provider file --file /path/to/state.json --port 5000

See dashboard/README.md for the finale click sequence and CONTRACTS.md for
the state schema this module serves.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Sequence

from flask import Flask, jsonify, request, send_from_directory

from dashboard.state_provider import FileProvider, FixtureProvider, StateProvider

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

DEMO_ACTIONS = ("outage", "restore", "reset_mcu", "replay_soh", "force_soc")


def create_app(provider: StateProvider) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["PROVIDER"] = provider

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/state")
    def api_state():
        _st = provider.get_state()
        if 'meta' not in _st:
            _st = dict(_st); _st['meta'] = {'source': 'fixture (scripted demo)', 'age_s': 0.0, 'stale': False, 'override_ack': None}
        return jsonify(_st)
    def _unused_api_state():
        return jsonify(provider.get_state())

    @app.post("/api/override")
    def api_override():
        data = request.get_json(silent=True) or {}
        channel = data.get("channel")
        minutes = data.get("minutes", 30)

        if not channel or not isinstance(channel, str):
            return jsonify(error="channel is required and must be a string"), 400
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return jsonify(error="minutes must be numeric"), 400
        if not (0 < minutes <= 60):
            return jsonify(error="minutes must be between 0 and 60"), 400

        try:
            provider.override(channel, minutes)
        except (ValueError, NotImplementedError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(provider.get_state())

    @app.post("/api/label")
    def api_label():
        data = request.get_json(silent=True) or {}
        cluster_id = data.get("cluster_id")
        name = data.get("name")

        if not cluster_id or not isinstance(cluster_id, str):
            return jsonify(error="cluster_id is required and must be a string"), 400
        if not name or not isinstance(name, str):
            return jsonify(error="name is required and must be a string"), 400

        try:
            provider.label(cluster_id, name)
        except (ValueError, NotImplementedError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(provider.get_state())

    @app.post("/api/verify_log")
    def api_verify_log():
        try:
            result = provider.verify_log()
        except NotImplementedError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(result)

    @app.post("/api/demo/<action>")
    def api_demo(action: str):
        if not isinstance(provider, FixtureProvider):
            return jsonify(error="demo endpoints require --provider fixture"), 400
        if action not in DEMO_ACTIONS:
            return jsonify(error=f"unknown demo action: {action}"), 404

        data = request.get_json(silent=True) or {}
        try:
            if action == "outage":
                provider.demo_outage()
            elif action == "restore":
                provider.demo_restore()
            elif action == "reset_mcu":
                provider.demo_reset_mcu()
            elif action == "replay_soh":
                provider.demo_replay_soh()
            elif action == "force_soc":
                if "soc" not in data:
                    return jsonify(error="soc is required (0.0-1.0)"), 400
                soc = float(data["soc"])
                provider.demo_force_soc(soc)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        return jsonify(provider.get_state())

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify(error="not found"), 404

    return app


def _build_provider(args: argparse.Namespace) -> StateProvider:
    if args.provider == "file":
        if not args.file:
            raise SystemExit("--file is required when --provider file")
        return FileProvider(Path(args.file))
    return FixtureProvider()


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="V-Guard Sentinel demo dashboard")
    parser.add_argument("--provider", choices=["fixture", "file"], default="fixture")
    parser.add_argument("--file", default=None, help="path to a JSON state file (provider=file)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)

    provider = _build_provider(args)
    app = create_app(provider)
    logger.info("Sentinel dashboard starting: provider=%s host=%s port=%s", args.provider, args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
