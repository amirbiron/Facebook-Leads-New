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
