"""Tests for the FTS abstraction layer (reasons_service.db.search)."""

from unittest.mock import patch

import pytest

from reasons_service.db.search import (
    _ALLOWED_TEXT_EXPRS,
    _get_terms,
    _validate_text_expr,
    fts_clause,
    plainto_fts_clause,
)


# --- _validate_text_expr ---


class TestValidateTextExpr:
    def test_allowed_expressions_pass(self):
        for expr in _ALLOWED_TEXT_EXPRS:
            _validate_text_expr(expr)  # should not raise

    def test_unknown_expression_raises(self):
        with pytest.raises(ValueError, match="Disallowed text_expr"):
            _validate_text_expr("id; DROP TABLE nodes --")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _validate_text_expr("")

    def test_partial_match_raises(self):
        with pytest.raises(ValueError):
            _validate_text_expr("text AND 1=1")


# --- _get_terms ---


class TestGetTerms:
    def test_extracts_meaningful_words(self):
        terms = _get_terms("What is access control?")
        assert "access" in terms
        assert "control" in terms
        # Stop words removed
        assert "what" not in terms
        assert "is" not in terms

    def test_single_letter_words_excluded(self):
        terms = _get_terms("I a b see")
        # "i", "a" are stop words; "b" is single char; "see" survives
        assert "see" in terms
        assert "b" not in terms

    def test_fallback_when_all_stop_words(self):
        # If all words are stop words, falls back to all words > 1 char
        terms = _get_terms("is the")
        assert terms == ["is", "the"]

    def test_empty_string(self):
        assert _get_terms("") == []

    def test_preserves_order(self):
        terms = _get_terms("pipeline delivery risks")
        assert terms == ["pipeline", "delivery", "risks"]

    def test_lowercases_terms(self):
        terms = _get_terms("Pipeline RISKS")
        assert terms == ["pipeline", "risks"]


# --- fts_clause (OR semantics) ---


@patch("reasons_service.db.search.settings")
class TestFtsClauseSQLite:
    def test_single_term(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = fts_clause("text", "pipeline")
        assert "LIKE :q0" in where
        assert params["q0"] == "%pipeline%"
        assert order == ""

    def test_multiple_terms_or(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = fts_clause("text", "pipeline delivery risks")
        assert " OR " in where
        assert "LIKE :q0" in where
        assert "LIKE :q1" in where
        assert "LIKE :q2" in where
        assert params["q0"] == "%pipeline%"
        assert params["q1"] == "%delivery%"
        assert params["q2"] == "%risks%"

    def test_stop_words_filtered(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = fts_clause("text", "what is the pipeline")
        # Only "pipeline" survives stop word filtering
        assert "q0" in params
        assert "q1" not in params
        assert params["q0"] == "%pipeline%"

    def test_all_stop_words_returns_false(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = fts_clause("text", "a")
        assert where == "1=0"
        assert params == {}

    def test_disallowed_text_expr_raises(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        with pytest.raises(ValueError, match="Disallowed"):
            fts_clause("'; DROP TABLE --", "test")

    def test_uses_lower(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, _, _ = fts_clause("c.text", "test")
        assert "lower(c.text)" in where


@patch("reasons_service.db.search.settings")
class TestFtsClausePostgreSQL:
    def test_uses_tsvector(self, mock_settings):
        mock_settings.db_backend = "postgresql"
        where, order, params = fts_clause("text", "pipeline delivery")
        assert "to_tsvector" in where
        assert "to_tsquery" in where
        assert "ts_rank_cd" in order
        assert "|" in params["q"]  # OR query

    def test_terms_joined_with_pipe(self, mock_settings):
        mock_settings.db_backend = "postgresql"
        _, _, params = fts_clause("text", "pipeline delivery risks")
        assert params["q"] == "pipeline | delivery | risks"

    def test_has_ranking(self, mock_settings):
        mock_settings.db_backend = "postgresql"
        _, order, _ = fts_clause("text", "test")
        assert order != ""
        assert "DESC" in order


# --- plainto_fts_clause (AND semantics) ---


@patch("reasons_service.db.search.settings")
class TestPlaintoFtsClauseSQLite:
    def test_single_term(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = plainto_fts_clause("text", "pipeline")
        assert "LIKE :q0" in where
        assert params["q0"] == "%pipeline%"
        assert order == ""

    def test_multiple_terms_and(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = plainto_fts_clause("text", "access control")
        assert " AND " in where
        assert " OR " not in where
        assert params["q0"] == "%access%"
        assert params["q1"] == "%control%"

    def test_all_stop_words_returns_false(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        where, order, params = plainto_fts_clause("text", "a")
        assert where == "1=0"
        assert params == {}

    def test_disallowed_text_expr_raises(self, mock_settings):
        mock_settings.db_backend = "sqlite"
        with pytest.raises(ValueError, match="Disallowed"):
            plainto_fts_clause("user_input", "test")


@patch("reasons_service.db.search.settings")
class TestPlaintoFtsClausePostgreSQL:
    def test_uses_plainto_tsquery(self, mock_settings):
        mock_settings.db_backend = "postgresql"
        where, order, params = plainto_fts_clause("text", "access control")
        assert "plainto_tsquery" in where
        assert params["q"] == "access control"
        assert order == ""

    def test_no_ranking(self, mock_settings):
        mock_settings.db_backend = "postgresql"
        _, order, _ = plainto_fts_clause("text", "test")
        assert order == ""
