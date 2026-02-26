"""פאנל הגדרות — שרת Flask לניהול הגדרות הבוט דרך ממשק ווב."""

import os
from functools import wraps
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

    # ── אימות — PANEL_TOKEN ──────────────────────────────────
    # אם PANEL_TOKEN מוגדר, כל בקשה ל-API חייבת לכלול את הטוקן
    # ב-header: Authorization: Bearer <token>
    # דף ה-HTML עצמו נגיש בלי טוקן — הוא שולח את הטוקן מ-localStorage
    panel_token = os.environ.get("PANEL_TOKEN", "").strip()
    if not panel_token:
        log.warning("PANEL_TOKEN לא מוגדר — הפאנל פתוח ללא אימות!")

    def require_auth(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not panel_token:
                return f(*args, **kwargs)
            auth = request.headers.get("Authorization", "")
            if auth == f"Bearer {panel_token}":
                return f(*args, **kwargs)
            return jsonify({"ok": False, "message": "אימות נדרש"}), 401
        return wrapper

    # ── דף ראשי (ללא אימות — ה-HTML עצמו לא מכיל מידע רגיש) ──
    @app.route("/")
    def index():
        return send_file(Path(__file__).parent / "panel.html")

    @app.route("/api/auth", methods=["POST"])
    def check_auth():
        """בדיקת תקינות טוקן. מחזיר ok=true אם הטוקן נכון או אם אין צורך באימות."""
        if not panel_token:
            return jsonify({"ok": True, "auth_required": False})
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {panel_token}":
            return jsonify({"ok": True, "auth_required": True})
        return jsonify({"ok": False, "auth_required": True}), 401

    # ── הגדרות כלליות ─────────────────────────────────────────

    # sentinel — מבדיל בין "אין ערך ב-DB" ל-"ערך ריק ב-DB"
    _NOT_SET = object()

    @app.route("/api/settings", methods=["GET"])
    @require_auth
    def get_settings():
        from classifier import _CLASSIFICATION_CRITERIA_DEFAULT

        criteria_db = get_config("classification_criteria")
        is_default = not bool(criteria_db.strip()) if criteria_db else True

        # quiet_hours — ערך ריק ב-DB = המשתמש ביטל דרך הפאנל → לא לחזור ל-env
        qh_db = get_config("quiet_hours", _NOT_SET)
        quiet_hours = qh_db if qh_db is not _NOT_SET else os.environ.get("QUIET_HOURS", "")

        # interval_minutes — אותו דפוס
        iv_db = get_config("interval_minutes", _NOT_SET)
        interval = iv_db if iv_db is not _NOT_SET else os.environ.get("INTERVAL_MINUTES", "10")
        # ברירת מחדל אם ריק
        if not interval.strip():
            interval = os.environ.get("INTERVAL_MINUTES", "10")

        return jsonify({
            "fb_email": get_config("fb_email") or os.environ.get("FB_EMAIL", ""),
            "fb_password": get_config("fb_password") or os.environ.get("FB_PASSWORD", ""),
            "classification_criteria": criteria_db or _CLASSIFICATION_CRITERIA_DEFAULT,
            "classification_criteria_default": _CLASSIFICATION_CRITERIA_DEFAULT,
            "criteria_is_default": is_default,
            "quiet_hours": quiet_hours,
            "interval_minutes": interval,
        })

    @app.route("/api/settings", methods=["PUT"])
    @require_auth
    def update_settings():
        data = request.get_json(force=True)
        allowed = ("fb_email", "fb_password", "classification_criteria",
                    "quiet_hours")
        for key in allowed:
            if key in data:
                set_config(key, str(data[key]).strip())
        return jsonify({"ok": True})

    # ── קבוצות ────────────────────────────────────────────────

    @app.route("/api/groups", methods=["GET"])
    @require_auth
    def list_groups():
        groups = get_db_groups()
        if groups is None:
            from scraper import DEFAULT_GROUPS
            return jsonify({"groups": DEFAULT_GROUPS, "source": "default"})
        return jsonify({"groups": groups, "source": "custom"})

    @app.route("/api/groups", methods=["POST"])
    @require_auth
    def create_group():
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"ok": False, "message": "URL ריק"}), 400
        ok, msg = add_group(url)
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/groups", methods=["DELETE"])
    @require_auth
    def delete_group():
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"ok": False, "message": "URL ריק"}), 400
        ok, msg = remove_group(url)
        return jsonify({"ok": ok, "message": msg})

    # ── מילות מפתח ────────────────────────────────────────────

    @app.route("/api/keywords/<kw_type>", methods=["GET"])
    @require_auth
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
    @require_auth
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
    @require_auth
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
