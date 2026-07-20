"""Tests for the /ask endpoint error handling."""

from uuid import UUID

import pytest

from tests.conftest import VALID_DOMAIN_ID


# --- Happy path ---


def test_ask_returns_beliefs(client, mock_search):
    """Normal search with well-formed results."""
    mock_search.return_value = {
        "results": [
            {"truth_value": "IN", "id": "b1", "text": "EDA uses events"},
            {"truth_value": "OUT", "id": "b2", "text": "Deprecated feature"},
        ],
        "count": 2,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "What is EDA?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == "What is EDA?"
    assert body["count"] == 2
    assert len(body["beliefs"]) == 2
    assert "[IN] b1" in body["compact"]
    assert "[OUT] b2" in body["compact"]


def test_ask_empty_results(client, mock_search):
    """Search returns zero results."""
    mock_search.return_value = {"results": [], "count": 0}
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "nonexistent topic"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["beliefs"] == []
    assert body["count"] == 0
    assert body["compact"] == ""


def test_ask_single_result(client, mock_search):
    """Search returns exactly one result."""
    mock_search.return_value = {
        "results": [{"truth_value": "IN", "id": "only-one", "text": "Single belief"}],
        "count": 1,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "one result"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["compact"] == "[IN] only-one — Single belief"


# --- Error handling: search failures ---


def test_ask_search_exception_returns_500(client, mock_search):
    """rms_api.search raising returns 500 with generic detail."""
    mock_search.side_effect = Exception("connection refused")
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Search failed"


def test_ask_search_runtime_error(client, mock_search):
    """RuntimeError from search layer is caught."""
    mock_search.side_effect = RuntimeError("broken query")
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Search failed"


def test_ask_search_connection_error(client, mock_search):
    """ConnectionError (DB unreachable) is caught."""
    mock_search.side_effect = ConnectionError("DB unreachable")
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Search failed"


def test_ask_search_key_error(client, mock_search):
    """KeyError from search internals is caught."""
    mock_search.side_effect = KeyError("missing_column")
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Search failed"


def test_ask_error_does_not_leak_details(client, mock_search):
    """Exception message is NOT exposed in the API response."""
    mock_search.side_effect = Exception("postgresql://user:pass@host/db")
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert "postgresql" not in body["detail"]
    assert "user:pass" not in body["detail"]
    assert body["detail"] == "Search failed"


# --- Defensive key access (.get defaults) ---


def test_ask_missing_truth_value_defaults_to_unknown(client, mock_search):
    """Result without truth_value shows UNKNOWN in compact."""
    mock_search.return_value = {
        "results": [{"id": "b1", "text": "some belief"}],
        "count": 1,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 200
    assert "[UNKNOWN] b1" in resp.json()["compact"]


def test_ask_missing_id_defaults_to_placeholder(client, mock_search):
    """Result without id shows ? in compact."""
    mock_search.return_value = {
        "results": [{"truth_value": "IN", "text": "some belief"}],
        "count": 1,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 200
    assert "[IN] ?" in resp.json()["compact"]


def test_ask_missing_text_defaults_to_empty(client, mock_search):
    """Result without text shows empty after the dash."""
    mock_search.return_value = {
        "results": [{"truth_value": "IN", "id": "b1"}],
        "count": 1,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 200
    assert resp.json()["compact"] == "[IN] b1 — "


def test_ask_completely_empty_result_dict(client, mock_search):
    """Result dict with no keys at all still works."""
    mock_search.return_value = {
        "results": [{}],
        "count": 1,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 200
    assert resp.json()["compact"] == "[UNKNOWN] ? — "


def test_ask_mixed_complete_and_partial_results(client, mock_search):
    """Mix of well-formed and partial result dicts."""
    mock_search.return_value = {
        "results": [
            {"truth_value": "IN", "id": "b1", "text": "Good belief"},
            {"id": "b2"},
            {"truth_value": "OUT"},
        ],
        "count": 3,
    }
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 200
    lines = resp.json()["compact"].split("\n")
    assert lines[0] == "[IN] b1 — Good belief"
    assert lines[1] == "[UNKNOWN] b2 — "
    assert "[OUT] ?" in lines[2]


# --- Input validation ---


def test_ask_missing_question_field(client, mock_search):
    """POST without question field returns 422."""
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={},
    )
    assert resp.status_code == 422


def test_ask_invalid_domain_id(client, mock_search):
    """Non-UUID domain_id returns 422."""
    resp = client.post(
        "/api/domains/not-a-uuid/ask",
        json={"question": "test"},
    )
    assert resp.status_code == 422


def test_ask_empty_question(client, mock_search):
    """Empty string question is valid (no min-length constraint)."""
    mock_search.return_value = {"results": [], "count": 0}
    resp = client.post(
        f"/api/domains/{VALID_DOMAIN_ID}/ask",
        json={"question": ""},
    )
    assert resp.status_code == 200


# --- Logging ---


def test_ask_logs_exception_on_search_failure(client, mock_search, caplog):
    """Exception is logged server-side with domain_id."""
    mock_search.side_effect = Exception("db timeout")
    with caplog.at_level("ERROR", logger="reasons_service.api.ask"):
        resp = client.post(
            f"/api/domains/{VALID_DOMAIN_ID}/ask",
            json={"question": "anything"},
        )
    assert resp.status_code == 500
    assert "Search failed for domain" in caplog.text
    assert VALID_DOMAIN_ID in caplog.text
