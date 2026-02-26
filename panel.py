"""פאנל הגדרות — שרת Flask לניהול הגדרות הבוט דרך ממשק ווב."""

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from database import (
    init_db,
    get_config,
    set_config,
    add_group,
    remove_group,
    get_db_groups,
    add_keyword,
    remove_keyword,
    get_db_keywords,
)
from logger import get_logger

log = get_logger("Panel")

PANEL_PORT = int(os.environ.get("PANEL_PORT", "8501"))


def create_app() -> Flask:
    app = Flask(__name__)

    # ── דף ראשי ──────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_file(Path(__file__).parent / "panel.html")

    # ── הגדרות כלליות ─────────────────────────────────────────

    @app.route("/api/settings", methods=["GET"])
    def get_settings():
        from classifier import _CLASSIFICATION_CRITERIA_DEFAULT

        criteria_db = get_config("classification_criteria")
        return jsonify({
            "fb_email": get_config("fb_email") or os.environ.get("FB_EMAIL", ""),
            "fb_password": get_config("fb_password") or os.environ.get("FB_PASSWORD", ""),
            "classification_criteria": criteria_db or _CLASSIFICATION_CRITERIA_DEFAULT,
            "criteria_is_default": not bool(criteria_db.strip()) if criteria_db else True,
            "quiet_hours": get_config("quiet_hours") or os.environ.get("QUIET_HOURS", ""),
            "interval_minutes": get_config("interval_minutes") or os.environ.get("INTERVAL_MINUTES", "10"),
        })

    @app.route("/api/settings", methods=["PUT"])
    def update_settings():
        data = request.get_json(force=True)
        allowed = ("fb_email", "fb_password", "classification_criteria",
                    "quiet_hours", "interval_minutes")
        for key in allowed:
            if key in data:
                set_config(key, str(data[key]).strip())
        return jsonify({"ok": True})

    # ── קבוצות ────────────────────────────────────────────────

    @app.route("/api/groups", methods=["GET"])
    def list_groups():
        groups = get_db_groups()
        if groups is None:
            from scraper import DEFAULT_GROUPS
            return jsonify({"groups": DEFAULT_GROUPS, "source": "default"})
        return jsonify({"groups": groups, "source": "custom"})

    @app.route("/api/groups", methods=["POST"])
    def create_group():
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"ok": False, "message": "URL ריק"}), 400
        ok, msg = add_group(url)
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/groups", methods=["DELETE"])
    def delete_group():
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"ok": False, "message": "URL ריק"}), 400
        ok, msg = remove_group(url)
        return jsonify({"ok": ok, "message": msg})

    # ── מילות מפתח ────────────────────────────────────────────

    @app.route("/api/keywords/<kw_type>", methods=["GET"])
    def list_keywords(kw_type):
        if kw_type not in ("pre_filter", "block"):
            return jsonify({"ok": False, "message": "סוג לא תקין"}), 400

        kws = get_db_keywords(kw_type)
        if kws is None:
            # fallback לברירות מחדל
            if kw_type == "pre_filter":
                from main import _PRE_FILTER_KEYWORDS_DEFAULT
                return jsonify({"keywords": _PRE_FILTER_KEYWORDS_DEFAULT, "source": "default"})
            else:
                block_env = os.environ.get("BLOCK_KEYWORDS", "").strip()
                defaults = [w.strip().lower() for w in block_env.split(",") if w.strip()] if block_env else []
                return jsonify({"keywords": defaults, "source": "default"})
        return jsonify({"keywords": kws, "source": "custom"})

    @app.route("/api/keywords/<kw_type>", methods=["POST"])
    def create_keyword(kw_type):
        if kw_type not in ("pre_filter", "block"):
            return jsonify({"ok": False, "message": "סוג לא תקין"}), 400
        data = request.get_json(force=True)
        word = data.get("word", "").strip()
        if not word:
            return jsonify({"ok": False, "message": "מילה ריקה"}), 400
        ok, msg = add_keyword(word, kw_type)
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/keywords/<kw_type>", methods=["DELETE"])
    def delete_keyword(kw_type):
        if kw_type not in ("pre_filter", "block"):
            return jsonify({"ok": False, "message": "סוג לא תקין"}), 400
        data = request.get_json(force=True)
        word = data.get("word", "").strip()
        if not word:
            return jsonify({"ok": False, "message": "מילה ריקה"}), 400
        ok, msg = remove_keyword(word, kw_type)
        return jsonify({"ok": ok, "message": msg})

    return app


if __name__ == "__main__":
    init_db()
    app = create_app()
    log.info(f"פאנל הגדרות רץ על פורט {PANEL_PORT}")
    app.run(host="0.0.0.0", port=PANEL_PORT, debug=False)
