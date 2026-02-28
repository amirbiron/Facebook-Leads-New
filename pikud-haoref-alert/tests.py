"""טסטים למוניטור פיקוד העורף."""
import os
import sys
import pytest

# מגדיר env לפני import
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")

from monitor import matches_filter, ALERT_CITIES, POSITIVE_PHRASES
from scraper import _parse_messages, _extract_msg_id
from database import init_db, is_seen, mark_seen, is_alert_sent, save_alert, cleanup_old, DB_PATH


# ═══════════════════════════════════════════════════════
# סינון הודעות — matches_filter
# ═══════════════════════════════════════════════════════

class TestMatchesFilter:
    """בדיקות whitelist: עיר + ביטוי חיובי = התראה."""

    def test_city_and_positive_phrase(self):
        """עיר + ביטוי חיובי → True."""
        text = "תושבי תל אביב - ניתן לצאת מהמרחב המוגן ולהמשיך בשגרה"
        match, reason = matches_filter(text)
        assert match is True
        assert "תל אביב" in reason

    def test_city_only_no_positive(self):
        """עיר בלי ביטוי חיובי → False (אזעקה רגילה, לא מעניינת)."""
        text = "ירי רקטות לעבר תל אביב — היכנסו למרחב מוגן"
        match, _ = matches_filter(text)
        assert match is False

    def test_positive_only_no_city(self):
        """ביטוי חיובי בלי עיר רלוונטית → False."""
        text = "תושבי באר שבע - ניתן לצאת מהמרחב המוגן"
        match, _ = matches_filter(text)
        assert match is False

    def test_no_match_at_all(self):
        """הודעה כללית ללא עיר וללא ביטוי → False."""
        text = "עדכון שגרתי מפיקוד העורף"
        match, _ = matches_filter(text)
        assert match is False

    def test_negative_phrase_overrides(self):
        """ביטוי שלילי גובר — גם אם יש עיר + חיובי."""
        text = "תושבי תל אביב - ניתן לצאת מהמרחב המוגן אך יש להישאר במרחב המוגן עד להודעה נוספת"
        match, _ = matches_filter(text)
        assert match is False

    def test_alternative_positive_phrasing(self):
        """ביטוי חיובי חלופי — ניתן לצאת מהמקלט."""
        text = "תל אביב - ניתן לצאת מהמקלט"
        match, reason = matches_filter(text)
        assert match is True

    def test_case_insensitive_city(self):
        """שם עיר case-insensitive (רלוונטי אם יש ערים באנגלית)."""
        text = "תל אביב — ניתן לצאת מהמרחב המוגן"
        match, _ = matches_filter(text)
        assert match is True

    def test_empty_text(self):
        """טקסט ריק → False."""
        match, _ = matches_filter("")
        assert match is False

    def test_leave_shelter_variant(self):
        """ניתן לעזוב את המרחב המוגן — ניסוח אלטרנטיבי."""
        text = "תל אביב — ניתן לעזוב את המרחב המוגן"
        match, _ = matches_filter(text)
        assert match is True


# ═══════════════════════════════════════════════════════
# פירוש HTML — scraper
# ═══════════════════════════════════════════════════════

# HTML מינימלי שמדמה את מבנה t.me/s/
_SAMPLE_HTML = """
<div class="tgme_widget_message" data-post="PikudHaOref_all/12345">
  <div class="tgme_widget_message_text">
    תושבי תל אביב — ניתן לצאת מהמרחב המוגן
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/PikudHaOref_all/12345">
    <time datetime="2026-02-28T14:30:00+02:00">14:30</time>
  </a>
</div>
<div class="tgme_widget_message" data-post="PikudHaOref_all/12344">
  <div class="tgme_widget_message_text">
    ירי רקטות לעבר אשדוד — היכנסו למרחב מוגן
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/PikudHaOref_all/12344">
    <time datetime="2026-02-28T14:25:00+02:00">14:25</time>
  </a>
</div>
"""

_MSG_NO_TEXT_HTML = """
<div class="tgme_widget_message" data-post="PikudHaOref_all/99999">
  <div class="tgme_widget_message_photo"></div>
</div>
"""


class TestParseMessages:
    def test_parse_two_messages(self):
        msgs = _parse_messages(_SAMPLE_HTML)
        assert len(msgs) == 2

    def test_message_id_extracted(self):
        msgs = _parse_messages(_SAMPLE_HTML)
        assert msgs[0]["id"] == "12345"
        assert msgs[1]["id"] == "12344"

    def test_message_text(self):
        msgs = _parse_messages(_SAMPLE_HTML)
        assert "תל אביב" in msgs[0]["text"]
        assert "אשדוד" in msgs[1]["text"]

    def test_message_date(self):
        msgs = _parse_messages(_SAMPLE_HTML)
        assert "2026-02-28" in msgs[0]["date"]

    def test_empty_html(self):
        msgs = _parse_messages("")
        assert msgs == []

    def test_no_text_skipped(self):
        """הודעה ללא טקסט (תמונה בלבד) — מדלגים."""
        msgs = _parse_messages(_MSG_NO_TEXT_HTML)
        assert msgs == []

    def test_fallback_id_from_link(self):
        """מחלץ ID מ-href כשאין data-post."""
        html = """
        <div class="tgme_widget_message">
          <div class="tgme_widget_message_text">test</div>
          <a class="tgme_widget_message_date" href="https://t.me/PikudHaOref_all/77777">
            <time datetime="2026-02-28T10:00:00+02:00">10:00</time>
          </a>
        </div>
        """
        msgs = _parse_messages(html)
        assert len(msgs) == 1
        assert msgs[0]["id"] == "77777"


# ═══════════════════════════════════════════════════════
# Database — dedup
# ═══════════════════════════════════════════════════════

class TestDatabase:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """DB זמני לכל טסט."""
        import database
        db_path = tmp_path / "test.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        # מנקה thread-local connection אם קיים
        if hasattr(database._local, "conn"):
            del database._local.conn
        init_db()

    def test_mark_and_check_seen(self):
        mark_seen("123", "test_channel")
        assert is_seen("123") is True
        assert is_seen("999") is False

    def test_save_and_check_alert(self):
        save_alert("123", "test_channel", "test content")
        assert is_alert_sent("123") is True
        assert is_alert_sent("999") is False

    def test_duplicate_mark_seen_no_error(self):
        """INSERT OR IGNORE — לא זורק שגיאה על כפילות."""
        mark_seen("123", "test_channel")
        mark_seen("123", "test_channel")
        assert is_seen("123") is True

    def test_cleanup_keeps_recent(self):
        mark_seen("recent", "ch")
        cleanup_old(days=14)
        assert is_seen("recent") is True


# ═══════════════════════════════════════════════════════
# אינטגרציה — פיפליין מלא (ללא רשת)
# ═══════════════════════════════════════════════════════

class TestIntegration:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        import database
        db_path = tmp_path / "test.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        if hasattr(database._local, "conn"):
            del database._local.conn
        init_db()

    def test_full_pipeline(self):
        """HTML → parse → filter → dedup → should alert."""
        msgs = _parse_messages(_SAMPLE_HTML)
        assert len(msgs) == 2

        alerts = []
        for msg in msgs:
            if is_seen(msg["id"]):
                continue
            mark_seen(msg["id"], "test")
            match, reason = matches_filter(msg["text"])
            if match and not is_alert_sent(msg["id"]):
                alerts.append((msg, reason))
                save_alert(msg["id"], "test", msg["text"])

        # רק ההודעה עם "תל אביב" + "ניתן לצאת" עוברת
        assert len(alerts) == 1
        assert "12345" == alerts[0][0]["id"]

    def test_dedup_prevents_second_alert(self):
        """הודעה שכבר נשלחה לא נשלחת שוב."""
        msgs = _parse_messages(_SAMPLE_HTML)

        # סבב ראשון
        for msg in msgs:
            mark_seen(msg["id"], "test")
            match, reason = matches_filter(msg["text"])
            if match:
                save_alert(msg["id"], "test", msg["text"])

        # סבב שני — אותן הודעות
        alerts = []
        for msg in msgs:
            if is_seen(msg["id"]):
                continue  # כבר נראו → מדלגים
            alerts.append(msg)

        assert len(alerts) == 0
