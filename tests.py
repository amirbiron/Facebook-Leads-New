"""Unit tests for Facebook-Leads-New — issue #28."""

import json
import re
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# 1. passes_keyword_filter
# ──────────────────────────────────────────────────────────────

from main import passes_keyword_filter


class TestPassesKeywordFilter:
    def test_matching_keyword(self):
        assert passes_keyword_filter("אני צריך בוט לטלגרם") is True

    def test_no_match(self):
        assert passes_keyword_filter("שלום לכולם, מה קורה?") is False

    def test_case_insensitive(self):
        assert passes_keyword_filter("אוטומציה") is True

    def test_empty_string(self):
        assert passes_keyword_filter("") is False

    def test_keyword_as_substring(self):
        # "מתכנת" appears inside a longer word — should still match
        assert passes_keyword_filter("אני מתכנתת מנוסה") is True

    def test_multiple_keywords(self):
        assert passes_keyword_filter("פיתוח בוט אוטומציה") is True

    def test_empty_list_passes_all(self):
        """רשימת מילות מפתח ריקה = אין סינון מוקדם, הכל עובר."""
        with patch("main.PRE_FILTER_KEYWORDS", []):
            assert passes_keyword_filter("כל טקסט שהוא") is True


# ──────────────────────────────────────────────────────────────
# 2. is_blocked
# ──────────────────────────────────────────────────────────────

from main import is_blocked


class TestIsBlocked:
    def test_no_block_keywords(self):
        with patch("main.BLOCK_KEYWORDS", []):
            assert is_blocked("כל טקסט שהוא") is False

    def test_blocked_word_present(self):
        with patch("main.BLOCK_KEYWORDS", ["ספאם", "פרסום"]):
            assert is_blocked("זה ספאם מלא") is True

    def test_blocked_word_absent(self):
        with patch("main.BLOCK_KEYWORDS", ["ספאם"]):
            assert is_blocked("פוסט רגיל לגמרי") is False

    def test_case_insensitive(self):
        with patch("main.BLOCK_KEYWORDS", ["spam"]):
            assert is_blocked("This is SPAM") is True


# ──────────────────────────────────────────────────────────────
# 3. _parse_quiet_hours / _is_quiet_now
# ──────────────────────────────────────────────────────────────

from main import _parse_quiet_hours, _is_quiet_now


class TestParseQuietHours:
    def test_standard_format(self):
        result = _parse_quiet_hours("22:00-06:00")
        assert result == (time(22, 0), time(6, 0))

    def test_short_format(self):
        result = _parse_quiet_hours("2-7")
        assert result == (time(2, 0), time(7, 0))

    def test_empty_string(self):
        assert _parse_quiet_hours("") is None

    def test_none_input(self):
        assert _parse_quiet_hours(None) is None

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            _parse_quiet_hours("invalid")

    def test_whitespace(self):
        result = _parse_quiet_hours("  02:00 - 07:00  ")
        assert result == (time(2, 0), time(7, 0))


class TestIsQuietNow:
    def test_within_quiet_hours(self):
        quiet = (time(22, 0), time(6, 0))
        now = datetime(2026, 1, 1, 23, 30)
        assert _is_quiet_now(now, quiet) is True

    def test_outside_quiet_hours(self):
        quiet = (time(22, 0), time(6, 0))
        now = datetime(2026, 1, 1, 12, 0)
        assert _is_quiet_now(now, quiet) is False

    def test_before_midnight_wrap(self):
        quiet = (time(22, 0), time(6, 0))
        now = datetime(2026, 1, 1, 5, 59)
        assert _is_quiet_now(now, quiet) is True

    def test_at_end_boundary(self):
        quiet = (time(22, 0), time(6, 0))
        now = datetime(2026, 1, 1, 6, 0)
        assert _is_quiet_now(now, quiet) is False

    def test_same_start_end(self):
        quiet = (time(0, 0), time(0, 0))
        now = datetime(2026, 1, 1, 15, 0)
        assert _is_quiet_now(now, quiet) is True

    def test_no_midnight_wrap(self):
        quiet = (time(2, 0), time(7, 0))
        now = datetime(2026, 1, 1, 3, 0)
        assert _is_quiet_now(now, quiet) is True

    def test_no_midnight_wrap_outside(self):
        quiet = (time(2, 0), time(7, 0))
        now = datetime(2026, 1, 1, 8, 0)
        assert _is_quiet_now(now, quiet) is False


# ──────────────────────────────────────────────────────────────
# 4. clean_post_content
# ──────────────────────────────────────────────────────────────

from notifier import clean_post_content


class TestCleanPostContent:
    def test_removes_private_use_unicode(self):
        text = "שלום \uE000\uE001 עולם"
        assert "\uE000" not in clean_post_content(text)

    def test_removes_like_count_lines(self):
        text = "פוסט מעניין\n42\nתגובה"
        result = clean_post_content(text)
        assert "42" not in result

    def test_removes_hebrew_commenter_lines(self):
        text = "תוכן\nו-עוד 5 אחרי\nסוף"
        result = clean_post_content(text)
        assert "ו-עוד" not in result

    def test_collapses_excess_newlines(self):
        text = "שורה 1\n\n\n\n\nשורה 2"
        result = clean_post_content(text)
        assert "\n\n\n" not in result

    def test_strips_whitespace(self):
        assert clean_post_content("  שלום  ") == "שלום"

    def test_normal_text_unchanged(self):
        text = "מחפש מפתח לבניית בוט"
        assert clean_post_content(text) == text


# ──────────────────────────────────────────────────────────────
# 5. extract_post_id
# ──────────────────────────────────────────────────────────────

from scraper import extract_post_id


class TestExtractPostId:
    def test_posts_pattern(self):
        assert extract_post_id("https://facebook.com/groups/123/posts/456789") == "456789"

    def test_story_fbid_pattern(self):
        assert extract_post_id("https://facebook.com/story.php?story_fbid=123456&id=789") == "123456"

    def test_permalink_pattern(self):
        assert extract_post_id("https://facebook.com/groups/123/permalink/999888") == "999888"

    def test_pfbid_pattern(self):
        url = "https://facebook.com/groups/123/posts/pfbidABCdef123"
        result = extract_post_id(url)
        assert result == "ABCdef123"

    def test_fallback_last_20_chars(self):
        url = "https://facebook.com/some/unknown/format"
        result = extract_post_id(url)
        assert result == url[-20:]

    def test_short_url_fallback(self):
        url = "https://fb.com/x"
        result = extract_post_id(url)
        assert result == url[-20:]


# ──────────────────────────────────────────────────────────────
# 6. classify_post (mocked API)
# ──────────────────────────────────────────────────────────────


class TestClassifyPost:
    def _make_mock_response(self, text: str):
        """Build a mock Anthropic message response."""
        content_block = SimpleNamespace(text=text)
        return SimpleNamespace(content=[content_block], stop_reason="end_turn")

    @patch("classifier.client")
    def test_relevant_post(self, mock_client):
        from classifier import classify_post

        mock_client.messages.create.return_value = self._make_mock_response(
            '{"relevant": true, "reason": "עסק קטן מחפש מפתח"}'
        )
        result = classify_post("מחפש מפתח לבוט", "קבוצת פרילנסרים")
        assert result["relevant"] is True
        assert "reason" in result

    @patch("classifier.client")
    def test_not_relevant_post(self, mock_client):
        from classifier import classify_post

        mock_client.messages.create.return_value = self._make_mock_response(
            '{"relevant": false, "reason": "שיתוף מאמר"}'
        )
        result = classify_post("מאמר מעניין על AI", "טכנולוגיה")
        assert result["relevant"] is False

    @patch("classifier.client")
    def test_markdown_wrapped_json(self, mock_client):
        from classifier import classify_post

        mock_client.messages.create.return_value = self._make_mock_response(
            '```json\n{"relevant": true, "reason": "ליד"}\n```'
        )
        result = classify_post("צריך מתכנת", "קבוצה")
        assert result["relevant"] is True

    @patch("classifier.client")
    def test_empty_response(self, mock_client):
        from classifier import classify_post

        mock_client.messages.create.return_value = self._make_mock_response("")
        result = classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False
        assert "ריקה" in result["reason"]

    @patch("classifier.client")
    def test_invalid_json(self, mock_client):
        from classifier import classify_post

        mock_client.messages.create.return_value = self._make_mock_response(
            "this is not json"
        )
        result = classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False

    @patch("classifier.client")
    def test_api_error(self, mock_client):
        import anthropic
        from classifier import classify_post

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_client.messages.create.side_effect = anthropic.APIStatusError(
            message="rate limit",
            response=mock_response,
            body={"error": {"message": "rate limit"}},
        )
        result = classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False
        assert "API" in result["reason"]


# ──────────────────────────────────────────────────────────────
# 6b. classify_batch (mocked API)
# ──────────────────────────────────────────────────────────────


class TestClassifyBatch:
    def _make_mock_response(self, text: str):
        content_block = SimpleNamespace(text=text)
        return SimpleNamespace(content=[content_block], stop_reason="end_turn")

    @patch("classifier.client")
    def test_batch_two_posts(self, mock_client):
        from classifier import classify_batch

        mock_client.messages.create.return_value = self._make_mock_response(
            '[{"relevant": true, "reason": "מחפש מפתח"}, {"relevant": false, "reason": "שיתוף מאמר"}]'
        )
        posts = [
            {"content": "מחפש מפתח לבוט", "group": "קבוצה1"},
            {"content": "מאמר מעניין", "group": "קבוצה2"},
        ]
        results = classify_batch(posts, batch_size=5)
        assert len(results) == 2
        assert results[0]["relevant"] is True
        assert results[1]["relevant"] is False
        # נשלחה בקשה אחת בלבד (לא 2)
        assert mock_client.messages.create.call_count == 1

    @patch("classifier.client")
    def test_batch_empty_list(self, mock_client):
        from classifier import classify_batch

        results = classify_batch([])
        assert results == []
        mock_client.messages.create.assert_not_called()

    @patch("classifier.client")
    def test_batch_splits_into_batches(self, mock_client):
        from classifier import classify_batch

        def side_effect(**kwargs):
            msg = kwargs.get("messages", [{}])[0].get("content", "")
            count = msg.count("--- פוסט")
            items = [{"relevant": False, "reason": "לא רלוונטי"}] * count
            return self._make_mock_response(json.dumps(items))

        mock_client.messages.create.side_effect = side_effect
        posts = [{"content": f"פוסט {i}", "group": "קבוצה"} for i in range(7)]
        results = classify_batch(posts, batch_size=3)
        assert len(results) == 7
        # 7 פוסטים בבאצ'ים של 3: 3 + 3 + 1 = 3 קריאות API
        assert mock_client.messages.create.call_count == 3

    @patch("classifier.client")
    def test_batch_single_post_returns_dict(self, mock_client):
        """באצ' של פוסט בודד — API יכול להחזיר אובייקט במקום מערך."""
        from classifier import classify_batch

        mock_client.messages.create.return_value = self._make_mock_response(
            '{"relevant": true, "reason": "ליד"}'
        )
        results = classify_batch([{"content": "צריך מתכנת", "group": "קבוצה"}])
        assert len(results) == 1
        assert results[0]["relevant"] is True

    @patch("classifier.client")
    def test_batch_markdown_wrapped(self, mock_client):
        from classifier import classify_batch

        mock_client.messages.create.return_value = self._make_mock_response(
            '```json\n[{"relevant": true, "reason": "ליד"}]\n```'
        )
        results = classify_batch([{"content": "צריך בוט", "group": "קבוצה"}])
        assert len(results) == 1
        assert results[0]["relevant"] is True

    @patch("classifier.client")
    def test_batch_fallback_on_length_mismatch(self, mock_client):
        """אם API מחזיר מערך בגודל שונה — fallback לסיווג בודד."""
        from classifier import classify_batch

        # קריאה ראשונה (batch) — מחזיר מערך בגודל שגוי
        batch_response = self._make_mock_response(
            '[{"relevant": true, "reason": "ליד"}]'  # מערך של 1 במקום 2
        )
        # קריאות fallback בודדות
        single_response = self._make_mock_response(
            '{"relevant": false, "reason": "לא רלוונטי"}'
        )
        mock_client.messages.create.side_effect = [
            batch_response, single_response, single_response
        ]
        posts = [
            {"content": "פוסט 1", "group": "קבוצה"},
            {"content": "פוסט 2", "group": "קבוצה"},
        ]
        results = classify_batch(posts, batch_size=5)
        assert len(results) == 2
        # 1 batch + 2 fallback singles = 3 calls
        assert mock_client.messages.create.call_count == 3

    @patch("classifier.client")
    def test_batch_fallback_on_api_error(self, mock_client):
        """אם API נופל בבאצ' — fallback לסיווג בודד פוסט-פוסט."""
        import anthropic
        from classifier import classify_batch

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.headers = {}

        single_ok = self._make_mock_response(
            '{"relevant": false, "reason": "fallback"}'
        )
        mock_client.messages.create.side_effect = [
            anthropic.APIStatusError(
                message="server error",
                response=error_response,
                body={"error": {"message": "server error"}},
            ),
            single_ok,
            single_ok,
        ]
        posts = [
            {"content": "פוסט 1", "group": "קבוצה"},
            {"content": "פוסט 2", "group": "קבוצה"},
        ]
        results = classify_batch(posts, batch_size=5)
        assert len(results) == 2
        assert all(r["relevant"] is False for r in results)

    @patch("classifier.client")
    def test_batch_fallback_on_null_element(self, mock_client):
        """אם אלמנט במערך הוא null — fallback בודד ללא תוצאות חלקיות."""
        from classifier import classify_batch

        # batch מחזיר מערך שבו אלמנט הוא None (לא dict)
        batch_response = self._make_mock_response(
            '[{"relevant": true, "reason": "ליד"}, null]'
        )
        single_ok = self._make_mock_response(
            '{"relevant": false, "reason": "fallback"}'
        )
        mock_client.messages.create.side_effect = [
            batch_response, single_ok, single_ok
        ]
        posts = [
            {"content": "פוסט 1", "group": "קבוצה"},
            {"content": "פוסט 2", "group": "קבוצה"},
        ]
        results = classify_batch(posts, batch_size=5)
        # חייבים לקבל בדיוק 2 תוצאות — לא יותר
        assert len(results) == 2


# ──────────────────────────────────────────────────────────────
# 7. Database — Groups CRUD
# ──────────────────────────────────────────────────────────────

import sqlite3
import tempfile
from pathlib import Path

import database


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """יוצר DB זמני לבדיקות."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    # ניקוי חיבור thread-local קיים כדי שייפתח מחדש עם הנתיב החדש
    if hasattr(database._local, "conn"):
        del database._local.conn
    database.init_db()
    yield db_path
    if hasattr(database._local, "conn"):
        del database._local.conn


class TestGroupsCRUD:
    def test_add_group(self, tmp_db):
        ok, msg = database.add_group("https://www.facebook.com/groups/12345")
        assert ok is True
        assert "נוספה" in msg

    def test_add_group_duplicate(self, tmp_db):
        database.add_group("https://m.facebook.com/groups/12345")
        ok, msg = database.add_group("https://m.facebook.com/groups/12345")
        assert ok is False
        assert "כבר קיימת" in msg

    def test_remove_group(self, tmp_db):
        database.add_group("https://m.facebook.com/groups/99999")
        ok, msg = database.remove_group("https://m.facebook.com/groups/99999")
        assert ok is True
        assert "הוסרה" in msg

    def test_remove_group_not_found(self, tmp_db):
        ok, msg = database.remove_group("https://m.facebook.com/groups/nonexistent")
        assert ok is False
        assert "לא נמצאה" in msg

    def test_get_db_groups(self, tmp_db):
        database.add_group("https://m.facebook.com/groups/111")
        database.add_group("https://m.facebook.com/groups/222")
        groups = database.get_db_groups()
        assert len(groups) == 2
        assert groups[0]["name"] == "111"
        assert "m.facebook.com" in groups[0]["url"]

    def test_url_normalization(self, tmp_db):
        database.add_group("https://www.facebook.com/groups/55555/")
        groups = database.get_db_groups()
        assert "m.facebook.com" in groups[0]["url"]
        assert not groups[0]["url"].endswith("/")

    def test_url_normalization_schemeless(self, tmp_db):
        """URL בלי סכמה עם דומיין לא צריך לקבל כפילות prefix."""
        database.add_group("www.facebook.com/groups/77777")
        groups = database.get_db_groups()
        assert groups[0]["url"] == "https://m.facebook.com/groups/77777"

    def test_url_normalization_bare_id(self, tmp_db):
        """מזהה קבוצה בלבד — מקבל prefix מלא."""
        database.add_group("12345")
        groups = database.get_db_groups()
        assert groups[0]["url"] == "https://m.facebook.com/groups/12345"

    def test_url_normalization_bare_domain_with_scheme(self, tmp_db):
        """facebook.com (ללא www) עם סכמה צריך להיות m.facebook.com."""
        database.add_group("https://facebook.com/groups/88888")
        groups = database.get_db_groups()
        assert groups[0]["url"] == "https://m.facebook.com/groups/88888"

    def test_url_normalization_bare_domain_without_scheme(self, tmp_db):
        """facebook.com (ללא www) בלי סכמה צריך להיות m.facebook.com."""
        database.add_group("facebook.com/groups/99999")
        groups = database.get_db_groups()
        assert groups[0]["url"] == "https://m.facebook.com/groups/99999"

    def test_never_configured_returns_none(self, tmp_db):
        assert database.get_db_groups() is None

    def test_add_then_remove_all_returns_empty_list(self, tmp_db):
        database.add_group("https://m.facebook.com/groups/111")
        database.remove_group("https://m.facebook.com/groups/111")
        groups = database.get_db_groups()
        assert groups == []


# ──────────────────────────────────────────────────────────────
# 8. Database — Keywords CRUD
# ──────────────────────────────────────────────────────────────


class TestKeywordsCRUD:
    def test_add_pre_filter_keyword(self, tmp_db):
        ok, msg = database.add_keyword("חדש", "pre_filter")
        assert ok is True
        assert "מילת מפתח" in msg

    def test_add_block_keyword(self, tmp_db):
        ok, msg = database.add_keyword("ספאם", "block")
        assert ok is True
        assert "מילה חסומה" in msg

    def test_add_duplicate_keyword(self, tmp_db):
        database.add_keyword("בוט", "pre_filter")
        ok, msg = database.add_keyword("בוט", "pre_filter")
        assert ok is False
        assert "כבר קיימת" in msg

    def test_same_word_different_types(self, tmp_db):
        ok1, _ = database.add_keyword("מילה", "pre_filter")
        ok2, _ = database.add_keyword("מילה", "block")
        assert ok1 is True
        assert ok2 is True

    def test_remove_keyword(self, tmp_db):
        database.add_keyword("למחוק", "block")
        ok, msg = database.remove_keyword("למחוק", "block")
        assert ok is True
        assert "הוסרה" in msg

    def test_remove_keyword_not_found(self, tmp_db):
        ok, msg = database.remove_keyword("אין", "block")
        assert ok is False
        assert "לא נמצאה" in msg

    def test_get_db_keywords(self, tmp_db):
        database.add_keyword("בוט", "pre_filter")
        database.add_keyword("סקריפט", "pre_filter")
        database.add_keyword("ספאם", "block")
        pf = database.get_db_keywords("pre_filter")
        bl = database.get_db_keywords("block")
        assert pf == ["בוט", "סקריפט"]
        assert bl == ["ספאם"]

    def test_empty_word_rejected(self, tmp_db):
        ok, msg = database.add_keyword("", "pre_filter")
        assert ok is False
        assert "ריקה" in msg

    def test_keyword_lowercased(self, tmp_db):
        database.add_keyword("SPAM", "block")
        kws = database.get_db_keywords("block")
        assert kws == ["spam"]

    def test_never_configured_returns_none(self, tmp_db):
        assert database.get_db_keywords("pre_filter") is None
        assert database.get_db_keywords("block") is None

    def test_add_then_remove_all_returns_empty_list(self, tmp_db):
        database.add_keyword("בוט", "pre_filter")
        database.remove_keyword("בוט", "pre_filter")
        kws = database.get_db_keywords("pre_filter")
        assert kws == []

    def test_cross_type_does_not_affect_other_type(self, tmp_db):
        """הוספת block לא צריכה לגרום ל-pre_filter להחזיר [] במקום None."""
        database.add_keyword("ספאם", "block")
        # block הוגדר — אבל pre_filter מעולם לא, אז צריך להחזיר None
        assert database.get_db_keywords("pre_filter") is None
        assert database.get_db_keywords("block") == ["ספאם"]

    def test_cross_type_independent_empty(self, tmp_db):
        """רוקנים סוג אחד — הסוג השני לא מושפע."""
        database.add_keyword("בוט", "pre_filter")
        database.add_keyword("ספאם", "block")
        database.remove_keyword("בוט", "pre_filter")
        # pre_filter רוקן בכוונה → []
        assert database.get_db_keywords("pre_filter") == []
        # block עדיין פעיל
        assert database.get_db_keywords("block") == ["ספאם"]


# ──────────────────────────────────────────────────────────────
# 9. reload_keywords
# ──────────────────────────────────────────────────────────────


class TestReloadKeywords:
    def test_reload_from_db(self, tmp_db):
        from main import reload_keywords
        database.add_keyword("חדשה", "pre_filter")
        database.add_keyword("חסימה", "block")
        reload_keywords()
        from main import PRE_FILTER_KEYWORDS, BLOCK_KEYWORDS
        assert "חדשה" in PRE_FILTER_KEYWORDS
        assert "חסימה" in BLOCK_KEYWORDS

    def test_fallback_to_defaults_when_never_configured(self, tmp_db):
        from main import reload_keywords, _PRE_FILTER_KEYWORDS_DEFAULT
        reload_keywords()
        from main import PRE_FILTER_KEYWORDS
        assert PRE_FILTER_KEYWORDS == _PRE_FILTER_KEYWORDS_DEFAULT

    def test_empty_list_when_all_removed(self, tmp_db):
        """הוספה ומחיקה של כל המילות מפתח צריכה להחזיר רשימה ריקה, לא defaults."""
        from main import reload_keywords
        database.add_keyword("זמני", "pre_filter")
        database.remove_keyword("זמני", "pre_filter")
        reload_keywords()
        from main import PRE_FILTER_KEYWORDS
        assert PRE_FILTER_KEYWORDS == []

    def test_block_keyword_does_not_kill_pre_filter_defaults(self, tmp_db):
        """הוספת block בלבד לא צריכה לרוקן את pre_filter — fallback ל-defaults."""
        from main import reload_keywords, _PRE_FILTER_KEYWORDS_DEFAULT
        database.add_keyword("ספאם", "block")
        reload_keywords()
        from main import PRE_FILTER_KEYWORDS, BLOCK_KEYWORDS
        assert PRE_FILTER_KEYWORDS == _PRE_FILTER_KEYWORDS_DEFAULT
        assert BLOCK_KEYWORDS == ["ספאם"]
