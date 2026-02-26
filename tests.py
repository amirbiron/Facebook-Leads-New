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

from notifier import clean_post_content, send_error_alert


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
# 4b. send_error_alert
# ──────────────────────────────────────────────────────────────


class TestSendErrorAlert:
    @patch("notifier.send_message")
    def test_sends_error_message(self, mock_send):
        mock_send.return_value = True
        result = send_error_alert("something broke")
        assert result is True
        mock_send.assert_called_once()
        call_text = mock_send.call_args[0][0]
        assert "⚠️" in call_text
        assert "something broke" in call_text

    @patch("notifier.send_message")
    def test_truncates_long_error(self, mock_send):
        mock_send.return_value = True
        long_error = "x" * 1000
        send_error_alert(long_error)
        call_text = mock_send.call_args[0][0]
        # הודעת השגיאה חתוכה ל-500 תווים מהשגיאה עצמה
        assert len(call_text) < 600

    @patch("notifier.send_message")
    def test_send_failure_returns_false(self, mock_send):
        mock_send.return_value = False
        result = send_error_alert("error")
        assert result is False


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
        """Build a mock OpenAI ChatCompletion response."""
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice])

    @patch("classifier.client")
    def test_relevant_post(self, mock_client):
        from classifier import classify_post

        mock_client.chat.completions.create.return_value = self._make_mock_response(
            '{"relevant": true, "reason": "עסק קטן מחפש מפתח"}'
        )
        result = classify_post("מחפש מפתח לבוט", "קבוצת פרילנסרים")
        assert result["relevant"] is True
        assert "reason" in result

    @patch("classifier.client")
    def test_not_relevant_post(self, mock_client):
        from classifier import classify_post

        mock_client.chat.completions.create.return_value = self._make_mock_response(
            '{"relevant": false, "reason": "שיתוף מאמר"}'
        )
        result = classify_post("מאמר מעניין על AI", "טכנולוגיה")
        assert result["relevant"] is False

    @patch("classifier.client")
    def test_markdown_wrapped_json(self, mock_client):
        from classifier import classify_post

        mock_client.chat.completions.create.return_value = self._make_mock_response(
            '```json\n{"relevant": true, "reason": "ליד"}\n```'
        )
        result = classify_post("צריך מתכנת", "קבוצה")
        assert result["relevant"] is True

    @patch("classifier.client")
    def test_empty_response(self, mock_client):
        from classifier import classify_post

        mock_client.chat.completions.create.return_value = self._make_mock_response("")
        result = classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False
        assert "ריקה" in result["reason"]

    @patch("classifier.client")
    def test_invalid_json(self, mock_client):
        from classifier import classify_post

        mock_client.chat.completions.create.return_value = self._make_mock_response(
            "this is not json"
        )
        result = classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False

    @patch("classifier.client")
    def test_api_error(self, mock_client):
        import openai
        from classifier import classify_post

        mock_client.chat.completions.create.side_effect = openai.APIStatusError(
            message="rate limit",
            response=MagicMock(status_code=429, headers={}),
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
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice])

    @patch("classifier.client")
    def test_batch_two_posts(self, mock_client):
        from classifier import classify_batch

        mock_client.chat.completions.create.return_value = self._make_mock_response(
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
        assert mock_client.chat.completions.create.call_count == 1

    @patch("classifier.client")
    def test_batch_empty_list(self, mock_client):
        from classifier import classify_batch

        results = classify_batch([])
        assert results == []
        mock_client.chat.completions.create.assert_not_called()

    @patch("classifier.client")
    def test_batch_splits_into_batches(self, mock_client):
        from classifier import classify_batch

        def side_effect(**kwargs):
            msgs = kwargs.get("messages", [])
            # הודעת user היא האחרונה ברשימת messages
            user_msg = msgs[-1].get("content", "") if msgs else ""
            count = user_msg.count("--- פוסט")
            items = [{"relevant": False, "reason": "לא רלוונטי"}] * count
            return self._make_mock_response(json.dumps(items))

        mock_client.chat.completions.create.side_effect = side_effect
        posts = [{"content": f"פוסט {i}", "group": "קבוצה"} for i in range(7)]
        results = classify_batch(posts, batch_size=3)
        assert len(results) == 7
        # 7 פוסטים בבאצ'ים של 3: 3 + 3 + 1 = 3 קריאות API
        assert mock_client.chat.completions.create.call_count == 3

    @patch("classifier.client")
    def test_batch_single_post_returns_dict(self, mock_client):
        """באצ' של פוסט בודד — API יכול להחזיר אובייקט במקום מערך."""
        from classifier import classify_batch

        mock_client.chat.completions.create.return_value = self._make_mock_response(
            '{"relevant": true, "reason": "ליד"}'
        )
        results = classify_batch([{"content": "צריך מתכנת", "group": "קבוצה"}])
        assert len(results) == 1
        assert results[0]["relevant"] is True

    @patch("classifier.client")
    def test_batch_markdown_wrapped(self, mock_client):
        from classifier import classify_batch

        mock_client.chat.completions.create.return_value = self._make_mock_response(
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
        mock_client.chat.completions.create.side_effect = [
            batch_response, single_response, single_response
        ]
        posts = [
            {"content": "פוסט 1", "group": "קבוצה"},
            {"content": "פוסט 2", "group": "קבוצה"},
        ]
        results = classify_batch(posts, batch_size=5)
        assert len(results) == 2
        # 1 batch + 2 fallback singles = 3 calls
        assert mock_client.chat.completions.create.call_count == 3

    @patch("classifier.client")
    def test_batch_fallback_on_api_error(self, mock_client):
        """אם API נופל בבאצ' — fallback לסיווג בודד פוסט-פוסט."""
        import openai
        from classifier import classify_batch

        single_ok = self._make_mock_response(
            '{"relevant": false, "reason": "fallback"}'
        )
        mock_client.chat.completions.create.side_effect = [
            openai.APIStatusError(
                message="server error",
                response=MagicMock(status_code=500, headers={}),
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
        mock_client.chat.completions.create.side_effect = [
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
# 6c. Auto-model-fallback
# ──────────────────────────────────────────────────────────────


class TestModelFallback:
    def _make_mock_response(self, text: str):
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice])

    def setup_method(self):
        """איפוס מודל פעיל לפני כל טסט."""
        import classifier
        classifier._active_model = None

    @patch("classifier.client")
    def test_deprecated_model_rotates_to_next(self, mock_client):
        """מודל deprecated → עובר למודל הבא ברשימה ומצליח."""
        import openai
        import classifier

        classifier._active_model = "gpt-4.1-nano"
        ok_response = self._make_mock_response(
            '{"relevant": true, "reason": "ליד"}'
        )
        mock_client.chat.completions.create.side_effect = [
            openai.NotFoundError(
                message="model not found",
                response=MagicMock(status_code=404, headers={}),
                body={"error": {"message": "model not found"}},
            ),
            ok_response,
        ]
        result = classifier.classify_post("צריך מפתח", "קבוצה")
        assert result["relevant"] is True
        assert classifier._active_model == "gpt-4o-mini"

    @patch("classifier.client")
    def test_all_models_exhausted(self, mock_client):
        """כל המודלים deprecated → מחזיר שגיאה."""
        import openai
        import classifier

        classifier._active_model = "gpt-5-nano"  # אחרון ברשימה
        mock_client.chat.completions.create.side_effect = openai.NotFoundError(
            message="model not found",
            response=MagicMock(status_code=404, headers={}),
            body={"error": {"message": "model not found"}},
        )
        result = classifier.classify_post("פוסט", "קבוצה")
        assert result["relevant"] is False
        assert "API" in result["reason"]

    def test_rotate_model_returns_next(self):
        import classifier

        next_m = classifier._rotate_model("gpt-4.1-nano")
        assert next_m == "gpt-4o-mini"

    def test_rotate_model_last_wraps_around(self):
        """כשהמודל האחרון ברשימה נכשל, עוטף מסביב לראשון."""
        import classifier

        result = classifier._rotate_model("gpt-5-nano")
        assert result == classifier._MODEL_PRIORITY[0]

    def test_is_model_deprecated_error_404(self):
        import openai
        import classifier

        err = openai.NotFoundError(
            message="model not found",
            response=MagicMock(status_code=404, headers={}),
            body={},
        )
        assert classifier._is_model_deprecated_error(err) is True

    def test_non_deprecated_error_not_detected(self):
        import openai
        import classifier

        err = openai.APIStatusError(
            message="rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body={},
        )
        assert classifier._is_model_deprecated_error(err) is False


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


# ──────────────────────────────────────────────────────────────
# 10. Health server
# ──────────────────────────────────────────────────────────────

import urllib.request

from main import _HealthHandler, start_health_server


class TestHealthServer:
    def test_returns_200_ok(self):
        """שרת healthcheck מחזיר 200 עם גוף 'ok'."""
        server = start_health_server(port=0)  # פורט 0 = OS בוחר פורט פנוי
        try:
            port = server.server_address[1]
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            assert resp.status == 200
            assert resp.read() == b"ok"
        finally:
            server.shutdown()

    def test_any_path_returns_200(self):
        """כל נתיב מחזיר 200 (לא רק /)."""
        server = start_health_server(port=0)
        try:
            port = server.server_address[1]
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz")
            assert resp.status == 200
        finally:
            server.shutdown()


# ──────────────────────────────────────────────────────────────
# 11. Database — get_config / set_config
# ──────────────────────────────────────────────────────────────


class TestConfigCRUD:
    def test_get_config_default(self, tmp_db):
        assert database.get_config("nonexistent") is None

    def test_get_config_custom_default(self, tmp_db):
        assert database.get_config("nonexistent", "fallback") == "fallback"

    def test_set_and_get_config(self, tmp_db):
        database.set_config("fb_email", "test@example.com")
        assert database.get_config("fb_email") == "test@example.com"

    def test_set_config_overwrites(self, tmp_db):
        database.set_config("interval", "10")
        database.set_config("interval", "20")
        assert database.get_config("interval") == "20"

    def test_set_config_does_not_break_feature_flags(self, tmp_db):
        """set_config לא צריך לשבור את _feature_was_configured."""
        database.set_config("custom_key", "value")
        database.add_group("https://m.facebook.com/groups/123")
        assert database._feature_was_configured("groups") is True
        assert database.get_config("custom_key") == "value"


# ──────────────────────────────────────────────────────────────
# 12. Panel API
# ──────────────────────────────────────────────────────────────

from panel import create_app


@pytest.fixture
def panel_client(tmp_db):
    """Flask test client עם DB זמני."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestPanelAPI:
    def test_get_settings(self, panel_client):
        resp = panel_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "fb_email" in data
        assert "classification_criteria" in data
        assert "interval_minutes" in data

    def test_put_settings(self, panel_client):
        resp = panel_client.put("/api/settings", json={
            "fb_email": "new@test.com",
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # ערכים נשמרו
        resp2 = panel_client.get("/api/settings")
        data = resp2.get_json()
        assert data["fb_email"] == "new@test.com"

    def test_put_quiet_hours(self, panel_client):
        resp = panel_client.put("/api/settings", json={"quiet_hours": "22:00-06:00"})
        assert resp.status_code == 200
        resp2 = panel_client.get("/api/settings")
        assert resp2.get_json()["quiet_hours"] == "22:00-06:00"

    def test_get_groups_default(self, panel_client):
        resp = panel_client.get("/api/groups")
        data = resp.get_json()
        assert data["source"] == "default"
        assert len(data["groups"]) > 0

    def test_add_and_list_groups(self, panel_client):
        resp = panel_client.post("/api/groups", json={"url": "https://facebook.com/groups/111"})
        assert resp.get_json()["ok"] is True
        resp2 = panel_client.get("/api/groups")
        data = resp2.get_json()
        assert data["source"] == "custom"
        assert any("111" in g["url"] for g in data["groups"])

    def test_delete_group(self, panel_client):
        panel_client.post("/api/groups", json={"url": "https://m.facebook.com/groups/222"})
        resp = panel_client.delete("/api/groups", json={"url": "https://m.facebook.com/groups/222"})
        assert resp.get_json()["ok"] is True

    def test_add_empty_group_rejected(self, panel_client):
        resp = panel_client.post("/api/groups", json={"url": ""})
        assert resp.status_code == 400

    def test_get_keywords_default(self, panel_client):
        resp = panel_client.get("/api/keywords/pre_filter")
        data = resp.get_json()
        assert data["source"] == "default"
        assert len(data["keywords"]) > 0

    def test_add_and_list_keywords(self, panel_client):
        resp = panel_client.post("/api/keywords/pre_filter", json={"word": "טסט"})
        assert resp.get_json()["ok"] is True
        resp2 = panel_client.get("/api/keywords/pre_filter")
        data = resp2.get_json()
        assert data["source"] == "custom"
        assert "טסט" in data["keywords"]

    def test_add_and_list_block_keywords(self, panel_client):
        """הוספת מילה חסומה דרך הפאנל — בדיקת זרימה מלאה."""
        resp = panel_client.post("/api/keywords/block", json={"word": "ספאם"})
        data = resp.get_json()
        assert data["ok"] is True
        assert resp.status_code == 200

        resp2 = panel_client.get("/api/keywords/block")
        data2 = resp2.get_json()
        assert data2["source"] == "custom"
        assert "ספאם" in data2["keywords"]

    def test_delete_keyword(self, panel_client):
        panel_client.post("/api/keywords/block", json={"word": "ספאם"})
        resp = panel_client.delete("/api/keywords/block", json={"word": "ספאם"})
        assert resp.get_json()["ok"] is True

    def test_invalid_keyword_type(self, panel_client):
        resp = panel_client.get("/api/keywords/invalid")
        assert resp.status_code == 400

    def test_add_empty_keyword_rejected(self, panel_client):
        resp = panel_client.post("/api/keywords/pre_filter", json={"word": ""})
        assert resp.status_code == 400

    def test_settings_include_default_criteria(self, panel_client):
        """API מחזיר גם את ברירת המחדל של קריטריוני הסיווג."""
        resp = panel_client.get("/api/settings")
        data = resp.get_json()
        assert "classification_criteria_default" in data
        assert len(data["classification_criteria_default"]) > 0

    def test_auth_not_required_when_no_token(self, panel_client):
        resp = panel_client.post("/api/auth")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["auth_required"] is False

    def test_cleared_quiet_hours_not_refilled_from_env(self, tmp_db, monkeypatch):
        """ערך ריק ב-DB (המשתמש ביטל) לא צריך לחזור ל-env var."""
        monkeypatch.setenv("QUIET_HOURS", "02:00-07:00")
        database.set_config("quiet_hours", "")
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/settings")
            data = resp.get_json()
            assert data["quiet_hours"] == ""


class TestPanelAuth:
    def test_auth_required_blocks_without_token(self, tmp_db, monkeypatch):
        """כשיש PANEL_TOKEN, בקשות ללא טוקן נחסמות."""
        monkeypatch.setenv("PANEL_TOKEN", "secret123")
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/settings")
            assert resp.status_code == 401

    def test_auth_passes_with_correct_token(self, tmp_db, monkeypatch):
        monkeypatch.setenv("PANEL_TOKEN", "secret123")
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/settings",
                              headers={"Authorization": "Bearer secret123"})
            assert resp.status_code == 200

    def test_html_page_accessible_without_token(self, tmp_db, monkeypatch):
        """דף ה-HTML נגיש גם בלי טוקן."""
        monkeypatch.setenv("PANEL_TOKEN", "secret123")
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────
# 13. Classifier — dynamic criteria loading
# ──────────────────────────────────────────────────────────────


class TestClassifierDynamicCriteria:
    def test_default_criteria(self, tmp_db):
        from classifier import _get_classification_criteria, _CLASSIFICATION_CRITERIA_DEFAULT
        result = _get_classification_criteria()
        assert result == _CLASSIFICATION_CRITERIA_DEFAULT

    def test_custom_criteria_from_db(self, tmp_db):
        from classifier import _get_classification_criteria
        database.set_config("classification_criteria", "קריטריונים מותאמים אישית")
        result = _get_classification_criteria()
        assert result == "קריטריונים מותאמים אישית"

    def test_empty_criteria_falls_back_to_default(self, tmp_db):
        from classifier import _get_classification_criteria, _CLASSIFICATION_CRITERIA_DEFAULT
        database.set_config("classification_criteria", "  ")
        result = _get_classification_criteria()
        assert result == _CLASSIFICATION_CRITERIA_DEFAULT

    def test_build_system_prompt_includes_json_instruction(self, tmp_db):
        from classifier import _build_system_prompt
        prompt = _build_system_prompt()
        assert "JSON" in prompt
        assert "relevant" in prompt

    def test_build_batch_prompt_includes_array_instruction(self, tmp_db):
        from classifier import _build_batch_system_prompt
        prompt = _build_batch_system_prompt()
        assert "מערך JSON" in prompt


# ──────────────────────────────────────────────────────────────
# 14. Main — dynamic settings loading
# ──────────────────────────────────────────────────────────────

from main import _load_interval_from_db, _load_quiet_hours_from_db


class TestDynamicSettings:
    def test_interval_from_env(self, tmp_db, monkeypatch):
        """interval נקרא ממשתנה סביבה בלבד, לא מ-DB."""
        monkeypatch.setattr("main.INTERVAL_MINUTES", 25)
        assert _load_interval_from_db() == 25

    def test_interval_zero_floored_to_one(self, tmp_db, monkeypatch):
        """ערך 0 מוחזר כ-1 — defense-in-depth מול לולאה צמודה."""
        monkeypatch.setattr("main.INTERVAL_MINUTES", 0)
        assert _load_interval_from_db() == 1

    def test_interval_ignores_stale_db_value(self, tmp_db, monkeypatch):
        """ערך ישן ב-DB לא דורס את env var."""
        database.set_config("interval_minutes", "99")
        monkeypatch.setattr("main.INTERVAL_MINUTES", 10)
        assert _load_interval_from_db() == 10

    def test_quiet_hours_from_db(self, tmp_db):
        database.set_config("quiet_hours", "22:00-06:00")
        result = _load_quiet_hours_from_db()
        assert result is not None
        assert result[0].hour == 22
        assert result[1].hour == 6

    def test_quiet_hours_empty_returns_none(self, tmp_db):
        database.set_config("quiet_hours", "")
        result = _load_quiet_hours_from_db()
        assert result is None

    def test_quiet_hours_invalid_returns_none(self, tmp_db):
        database.set_config("quiet_hours", "invalid")
        result = _load_quiet_hours_from_db()
        assert result is None

    def test_quiet_hours_empty_db_overrides_env(self, tmp_db, monkeypatch):
        """ערך ריק ב-DB צריך לבטל שעות שקטות גם אם QUIET_HOURS מוגדר ב-env."""
        monkeypatch.setattr("main.QUIET_HOURS", "02:00-07:00")
        database.set_config("quiet_hours", "")
        result = _load_quiet_hours_from_db()
        assert result is None


# ──────────────────────────────────────────────────────────────
# 15. Inline Keyboard — כפתורי תפריט
# ──────────────────────────────────────────────────────────────

from main import (
    _main_menu_buttons, _settings_menu_buttons, _back_to_menu_button,
    _build_status_text, _build_daily_report_text,
    _build_groups_text, _build_keywords_text, _build_blocked_text,
)


class TestMenuButtons:
    def test_main_menu_structure(self):
        """תפריט ראשי — 2 שורות, 2 כפתורים בכל שורה."""
        buttons = _main_menu_buttons()
        assert len(buttons) == 2
        assert len(buttons[0]) == 2
        assert len(buttons[1]) == 2

    def test_main_menu_callback_data(self):
        """כל כפתור בתפריט ראשי מכיל callback_data תקין."""
        buttons = _main_menu_buttons()
        expected = {"scan", "status", "daily_report", "settings"}
        actual = {btn["callback_data"] for row in buttons for btn in row}
        assert actual == expected

    def test_main_menu_buttons_have_text(self):
        """כל כפתור מכיל שדה text."""
        buttons = _main_menu_buttons()
        for row in buttons:
            for btn in row:
                assert "text" in btn
                assert len(btn["text"]) > 0

    def test_settings_menu_structure(self):
        """תפריט הגדרות — 2 שורות, 2 כפתורים בכל שורה."""
        buttons = _settings_menu_buttons()
        assert len(buttons) == 2
        assert len(buttons[0]) == 2
        assert len(buttons[1]) == 2

    def test_settings_menu_callback_data(self):
        buttons = _settings_menu_buttons()
        expected = {"groups", "keywords", "blocked", "menu"}
        actual = {btn["callback_data"] for row in buttons for btn in row}
        assert actual == expected

    def test_back_to_menu_button(self):
        """כפתור חזרה — שורה אחת, כפתור אחד."""
        buttons = _back_to_menu_button()
        assert len(buttons) == 1
        assert len(buttons[0]) == 1
        assert buttons[0][0]["callback_data"] == "menu"


class TestBuildStatusText:
    def test_contains_key_fields(self, tmp_db):
        shared = {
            "quiet": None,
            "scan_in_progress": False,
            "last_scan_started": None,
            "last_scan_finished": None,
        }
        text = _build_status_text(shared)
        assert "סטטוס בוט" in text
        assert "שעה מקומית" in text
        assert "סך נראו" in text

    def test_scan_in_progress(self, tmp_db):
        shared = {
            "quiet": None,
            "scan_in_progress": True,
            "last_scan_started": datetime(2026, 1, 1, 10, 0),
            "last_scan_finished": None,
        }
        text = _build_status_text(shared)
        assert "כן" in text


class TestBuildDailyReport:
    def test_contains_report_fields(self, tmp_db):
        shared = {
            "scan_in_progress": False,
            "last_scan_started": None,
            "last_scan_finished": None,
        }
        text = _build_daily_report_text(shared)
        assert "דו\"ח יומי" in text
        assert "פוסטים שנסרקו היום" in text
        assert "לידים שנשלחו היום" in text
        assert "סה\"כ כללי" in text


class TestBuildGroupsText:
    def test_no_groups(self):
        with patch("scraper.GROUPS", []):
            text = _build_groups_text()
            assert "אין קבוצות" in text

    def test_with_groups(self):
        fake = [{"name": "טסט", "url": "https://m.facebook.com/groups/123"}]
        with patch("scraper.GROUPS", fake):
            text = _build_groups_text()
            assert "טסט" in text
            assert "1." in text


class TestBuildKeywordsText:
    def test_empty_keywords(self):
        with patch("main.PRE_FILTER_KEYWORDS", []), patch("main.BLOCK_KEYWORDS", []):
            text = _build_keywords_text()
            assert "(ריק)" in text

    def test_with_keywords(self):
        with patch("main.PRE_FILTER_KEYWORDS", ["בוט", "אוטומציה"]), patch("main.BLOCK_KEYWORDS", ["ספאם"]):
            text = _build_keywords_text()
            assert "בוט" in text
            assert "אוטומציה" in text
            assert "ספאם" in text
            assert "מילים חסומות" in text


class TestBuildBlockedText:
    def test_empty_blocked(self):
        with patch("main.BLOCK_KEYWORDS", []):
            from main import _build_blocked_text
            text = _build_blocked_text()
            assert "(ריק)" in text

    def test_with_blocked(self):
        with patch("main.BLOCK_KEYWORDS", ["ספאם"]):
            from main import _build_blocked_text
            text = _build_blocked_text()
            assert "ספאם" in text


# ──────────────────────────────────────────────────────────────
# 16. Notifier — inline keyboard functions
# ──────────────────────────────────────────────────────────────

from notifier import send_message_with_buttons, edit_message_text, answer_callback_query


class TestSendMessageWithButtons:
    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_sends_with_reply_markup(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_post.return_value = mock_resp

        buttons = [[{"text": "כפתור", "callback_data": "test"}]]
        result = send_message_with_buttons("טקסט", buttons, chat_id=123)
        assert result is not None
        assert result["message_id"] == 42

        call_payload = mock_post.call_args[1]["json"]
        assert "reply_markup" in call_payload
        assert call_payload["reply_markup"]["inline_keyboard"] == buttons

    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_returns_none_on_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        result = send_message_with_buttons("טקסט", [[]], chat_id=123)
        assert result is None

    def test_no_token_returns_none(self, monkeypatch):
        monkeypatch.setattr("notifier.BOT_TOKEN", None)
        result = send_message_with_buttons("טקסט", [[]], chat_id=123)
        assert result is None


class TestEditMessageText:
    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_edits_message(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        buttons = [[{"text": "כפתור", "callback_data": "test"}]]
        result = edit_message_text(123, 42, "טקסט חדש", buttons)
        assert result is True

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["message_id"] == 42
        assert call_payload["text"] == "טקסט חדש"
        assert "reply_markup" in call_payload

    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_edit_without_buttons(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = edit_message_text(123, 42, "טקסט")
        assert result is True

        call_payload = mock_post.call_args[1]["json"]
        assert "reply_markup" not in call_payload

    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_returns_false_on_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        result = edit_message_text(123, 42, "טקסט")
        assert result is False


class TestAnswerCallbackQuery:
    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_answers_query(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = answer_callback_query("cb_123", "הודעה")
        assert result is True

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["callback_query_id"] == "cb_123"
        assert call_payload["text"] == "הודעה"

    @patch("notifier.BOT_TOKEN", "fake-token")
    @patch("notifier.requests.post")
    def test_answers_without_text(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        answer_callback_query("cb_123")
        call_payload = mock_post.call_args[1]["json"]
        assert "text" not in call_payload

    def test_no_token_returns_false(self, monkeypatch):
        monkeypatch.setattr("notifier.BOT_TOKEN", None)
        result = answer_callback_query("cb_123")
        assert result is False


# ──────────────────────────────────────────────────────────────
# 17. Panel — scan frequency removed
# ──────────────────────────────────────────────────────────────


class TestGetDailyStats:
    def test_daily_stats_filters_by_date(self, tmp_db):
        conn = database._get_conn()
        conn.execute("INSERT INTO seen_posts (post_id, group_name, seen_at) VALUES (?, ?, ?)",
                     ("p1", "g", "2026-02-26T10:00:00"))
        conn.execute("INSERT INTO seen_posts (post_id, group_name, seen_at) VALUES (?, ?, ?)",
                     ("p2", "g", "2026-02-25T10:00:00"))
        conn.execute("INSERT INTO sent_leads (post_id, group_name, content, reason, sent_at) VALUES (?, ?, ?, ?, ?)",
                     ("p1", "g", "c", "r", "2026-02-26T10:00:00"))
        conn.commit()
        stats = database.get_daily_stats("2026-02-26")
        assert stats["seen"] == 1
        assert stats["sent"] == 1

    def test_daily_stats_empty_day(self, tmp_db):
        stats = database.get_daily_stats("2026-02-26")
        assert stats["seen"] == 0
        assert stats["sent"] == 0


class TestPanelIntervalRemoved:
    def test_put_interval_ignored(self, panel_client):
        """interval_minutes כבר לא ניתן לעריכה מהפאנל."""
        resp = panel_client.put("/api/settings", json={"interval_minutes": "99"})
        assert resp.status_code == 200
        # ערך לא נשמר
        resp2 = panel_client.get("/api/settings")
        data = resp2.get_json()
        assert data["interval_minutes"] != "99"


# ──────────────────────────────────────────────────────────────
# 18. ensure_keywords_migrated — מיגרציית ברירות מחדל
# ──────────────────────────────────────────────────────────────


class TestEnsureKeywordsMigrated:
    def test_migrates_defaults_on_first_add(self, tmp_db):
        """הוספת מילה ראשונה צריכה להעביר ברירות מחדל ל-DB."""
        defaults = ["בוט", "אוטומציה", "סקריפט"]
        database.ensure_keywords_migrated("pre_filter", defaults)
        kws = database.get_db_keywords("pre_filter")
        assert set(kws) == {"בוט", "אוטומציה", "סקריפט"}

    def test_no_duplicate_on_second_call(self, tmp_db):
        """קריאה חוזרת לא מכפילה את המילים."""
        defaults = ["בוט", "אוטומציה"]
        database.ensure_keywords_migrated("pre_filter", defaults)
        database.ensure_keywords_migrated("pre_filter", defaults)
        kws = database.get_db_keywords("pre_filter")
        assert kws == ["בוט", "אוטומציה"]

    def test_add_after_migration_appends(self, tmp_db):
        """הוספת מילה חדשה אחרי מיגרציה — מצטרפת לברירות מחדל."""
        defaults = ["בוט", "אוטומציה"]
        database.ensure_keywords_migrated("pre_filter", defaults)
        database.add_keyword("חדשה", "pre_filter")
        kws = database.get_db_keywords("pre_filter")
        assert "חדשה" in kws
        assert "בוט" in kws
        assert "אוטומציה" in kws

    def test_empty_defaults_still_marks_configured(self, tmp_db):
        """ברירות מחדל ריקות — לא מוסיפות כלום אבל לא שוברות."""
        database.ensure_keywords_migrated("block", [])
        # רשימה ריקה לא מסמנת כמוגדר — _feature_was_configured נשאר False
        assert database.get_db_keywords("block") is None

    def test_does_not_overwrite_existing(self, tmp_db):
        """אם הסוג כבר הוגדר — לא דורסים."""
        database.add_keyword("קיימת", "pre_filter")
        database.ensure_keywords_migrated("pre_filter", ["חדשה1", "חדשה2"])
        kws = database.get_db_keywords("pre_filter")
        # רק המילה שהוספנו ידנית — ברירות מחדל לא נוספו
        assert kws == ["קיימת"]

    def test_panel_add_preserves_defaults(self, panel_client):
        """הוספת מילה בפאנל שומרת את ברירות המחדל."""
        # שלב 1: לפני הוספה — ברירות מחדל
        resp = panel_client.get("/api/keywords/pre_filter")
        data = resp.get_json()
        assert data["source"] == "default"
        default_count = len(data["keywords"])
        assert default_count > 0

        # שלב 2: הוספת מילה חדשה דרך הפאנל
        resp = panel_client.post("/api/keywords/pre_filter", json={"word": "מילה_חדשה_מאוד"})
        assert resp.get_json()["ok"] is True

        # שלב 3: בדיקה שכל ברירות המחדל + החדשה קיימות
        resp = panel_client.get("/api/keywords/pre_filter")
        data = resp.get_json()
        assert data["source"] == "custom"
        assert "מילה_חדשה_מאוד" in data["keywords"]
        # ברירות המחדל נשמרו + המילה החדשה
        assert len(data["keywords"]) == default_count + 1


# ──────────────────────────────────────────────────────────────
# 18.5. ensure_groups_migrated — מיגרציית ברירות מחדל לקבוצות
# ──────────────────────────────────────────────────────────────


class TestEnsureGroupsMigrated:
    def test_migrates_defaults_on_first_add(self, tmp_db):
        """הוספת קבוצה ראשונה צריכה להעביר ברירות מחדל ל-DB."""
        defaults = [
            {"name": "קבוצה1", "url": "https://m.facebook.com/groups/111"},
            {"name": "קבוצה2", "url": "https://m.facebook.com/groups/222"},
        ]
        database.ensure_groups_migrated(defaults)
        groups = database.get_db_groups()
        assert len(groups) == 2
        assert groups[0]["name"] == "קבוצה1"
        assert groups[1]["name"] == "קבוצה2"

    def test_no_duplicate_on_second_call(self, tmp_db):
        """קריאה חוזרת לא מכפילה את הקבוצות."""
        defaults = [{"name": "קבוצה1", "url": "https://m.facebook.com/groups/111"}]
        database.ensure_groups_migrated(defaults)
        database.ensure_groups_migrated(defaults)
        groups = database.get_db_groups()
        assert len(groups) == 1

    def test_add_after_migration_appends(self, tmp_db):
        """הוספת קבוצה חדשה אחרי מיגרציה — מצטרפת לברירות מחדל."""
        defaults = [{"name": "קבוצה1", "url": "https://m.facebook.com/groups/111"}]
        database.ensure_groups_migrated(defaults)
        database.add_group("https://m.facebook.com/groups/999")
        groups = database.get_db_groups()
        urls = [g["url"] for g in groups]
        assert "https://m.facebook.com/groups/111" in urls
        assert "https://m.facebook.com/groups/999" in urls

    def test_empty_defaults_no_mark(self, tmp_db):
        """ברירות מחדל ריקות — לא מסמנות כמוגדר."""
        database.ensure_groups_migrated([])
        assert database.get_db_groups() is None

    def test_does_not_overwrite_existing(self, tmp_db):
        """אם קבוצות כבר הוגדרו — לא דורסים."""
        database.add_group("https://m.facebook.com/groups/existing")
        database.ensure_groups_migrated([
            {"name": "חדשה", "url": "https://m.facebook.com/groups/new"},
        ])
        groups = database.get_db_groups()
        urls = [g["url"] for g in groups]
        assert "https://m.facebook.com/groups/existing" in urls
        assert "https://m.facebook.com/groups/new" not in urls

    def test_panel_add_preserves_defaults(self, panel_client):
        """הוספת קבוצה בפאנל שומרת את ברירות המחדל."""
        # שלב 1: לפני הוספה — ברירות מחדל
        resp = panel_client.get("/api/groups")
        data = resp.get_json()
        assert data["source"] == "default"
        default_count = len(data["groups"])
        assert default_count > 0

        # שלב 2: הוספת קבוצה חדשה דרך הפאנל
        resp = panel_client.post("/api/groups", json={"url": "https://m.facebook.com/groups/test_new_group_99999"})
        assert resp.get_json()["ok"] is True

        # שלב 3: בדיקה שכל ברירות המחדל + החדשה קיימות
        resp = panel_client.get("/api/groups")
        data = resp.get_json()
        assert data["source"] == "custom"
        urls = [g["url"] for g in data["groups"]]
        assert "https://m.facebook.com/groups/test_new_group_99999" in urls
        # ברירות המחדל נשמרו + הקבוצה החדשה
        assert len(data["groups"]) == default_count + 1


# ──────────────────────────────────────────────────────────────
# 19. update_group_name — עדכון שם קבוצה ב-DB
# ──────────────────────────────────────────────────────────────


class TestUpdateGroupName:
    def test_update_existing_group(self, tmp_db):
        """עדכון שם קבוצה קיימת ב-DB."""
        database.add_group("https://m.facebook.com/groups/12345")
        groups = database.get_db_groups()
        assert groups[0]["name"] == "12345"

        updated = database.update_group_name("https://m.facebook.com/groups/12345", "שם אמיתי")
        assert updated is True

        groups = database.get_db_groups()
        assert groups[0]["name"] == "שם אמיתי"

    def test_update_nonexistent_group(self, tmp_db):
        """עדכון קבוצה שלא קיימת מחזיר False."""
        updated = database.update_group_name("https://m.facebook.com/groups/99999", "שם")
        assert updated is False

    def test_update_preserves_url(self, tmp_db):
        """עדכון שם לא משנה את ה-URL."""
        database.add_group("https://m.facebook.com/groups/55555")
        database.update_group_name("https://m.facebook.com/groups/55555", "קבוצה חדשה")
        groups = database.get_db_groups()
        assert groups[0]["url"] == "https://m.facebook.com/groups/55555"
        assert groups[0]["name"] == "קבוצה חדשה"


# ──────────────────────────────────────────────────────────────
# 20. _to_desktop_url — המרת URL מובייל לדסקטופ
# ──────────────────────────────────────────────────────────────

from notifier import _to_desktop_url


class TestToDesktopUrl:
    def test_mobile_to_desktop(self):
        url = "https://m.facebook.com/groups/123/posts/456"
        assert _to_desktop_url(url) == "https://www.facebook.com/groups/123/posts/456"

    def test_already_desktop(self):
        url = "https://www.facebook.com/groups/123/posts/456"
        assert _to_desktop_url(url) == url

    def test_no_facebook(self):
        url = "https://example.com/test"
        assert _to_desktop_url(url) == url

    def test_group_url_converted(self):
        url = "https://m.facebook.com/groups/1684554685829832"
        assert _to_desktop_url(url) == "https://www.facebook.com/groups/1684554685829832"


# ──────────────────────────────────────────────────────────────
# 21. _is_post_url — זיהוי URL של פוסט ספציפי
# ──────────────────────────────────────────────────────────────

from scraper import _is_post_url


class TestIsPostUrl:
    def test_posts_pattern(self):
        assert _is_post_url("https://m.facebook.com/groups/123/posts/456") is True

    def test_permalink_pattern(self):
        assert _is_post_url("https://m.facebook.com/groups/123/permalink/456") is True

    def test_story_fbid_pattern(self):
        assert _is_post_url("https://m.facebook.com/story.php?story_fbid=123") is True

    def test_pfbid_pattern(self):
        assert _is_post_url("https://m.facebook.com/groups/123/posts/pfbidABC") is True

    def test_group_url_only(self):
        """URL של קבוצה בלבד — לא פוסט ספציפי."""
        assert _is_post_url("https://m.facebook.com/groups/123") is False

    def test_p_pattern(self):
        assert _is_post_url("https://m.facebook.com/p/something") is True

    def test_multi_permalinks(self):
        assert _is_post_url("https://m.facebook.com/groups/123/?multi_permalinks=456") is True
