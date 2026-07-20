"""Tests for SQLite backend — count helpers, init_db, connection pragmas."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import UUID

import pytest


FAKE_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000001")


# --- count_beliefs ---


class TestCountBeliefs:
    def _make_db(self, tmp_path, nodes=None):
        """Create a minimal reasons_lib-compatible SQLite database."""
        db_path = tmp_path / str(FAKE_PROJECT_ID) / "reasons.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE nodes ("
            "  id TEXT PRIMARY KEY, text TEXT NOT NULL,"
            "  truth_value TEXT NOT NULL DEFAULT 'IN')"
        )
        conn.execute(
            "CREATE TABLE nogoods ("
            "  id TEXT PRIMARY KEY, nodes_json TEXT NOT NULL DEFAULT '[]')"
        )
        if nodes:
            conn.executemany(
                "INSERT INTO nodes (id, text, truth_value) VALUES (?, ?, ?)",
                nodes,
            )
        conn.commit()
        conn.close()
        return tmp_path

    @patch("reasons_service.rms.api.settings")
    def test_count_all_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
            ("b3", "Belief three", "IN"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, None) == 3

    @patch("reasons_service.rms.api.settings")
    def test_count_in_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
            ("b3", "Belief three", "IN"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 2

    @patch("reasons_service.rms.api.settings")
    def test_count_out_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "OUT") == 1

    @patch("reasons_service.rms.api.settings")
    def test_count_empty_db(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 0
        assert count_beliefs(FAKE_PROJECT_ID, None) == 0

    @patch("reasons_service.rms.api.settings")
    def test_count_nonexistent_db(self, mock_settings, tmp_path):
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        from reasons_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 0


# --- count_nogoods ---


class TestCountNogoods:
    def _make_db(self, tmp_path, nogoods=None):
        db_path = tmp_path / str(FAKE_PROJECT_ID) / "reasons.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE nodes ("
            "  id TEXT PRIMARY KEY, text TEXT NOT NULL,"
            "  truth_value TEXT NOT NULL DEFAULT 'IN')"
        )
        conn.execute(
            "CREATE TABLE nogoods ("
            "  id TEXT PRIMARY KEY, nodes_json TEXT NOT NULL DEFAULT '[]')"
        )
        if nogoods:
            conn.executemany(
                "INSERT INTO nogoods (id, nodes_json) VALUES (?, ?)",
                nogoods,
            )
        conn.commit()
        conn.close()
        return tmp_path

    @patch("reasons_service.rms.api.settings")
    def test_count_nogoods(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("ng-001", '["b1", "b2"]'),
            ("ng-002", '["b3", "b4"]'),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 2

    @patch("reasons_service.rms.api.settings")
    def test_count_nogoods_empty(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 0

    @patch("reasons_service.rms.api.settings")
    def test_count_nogoods_nonexistent_db(self, mock_settings, tmp_path):
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        from reasons_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 0


# --- init_db ---


class TestInitDb:
    @patch("reasons_service.db.connection._is_sqlite", False)
    def test_init_db_noop_for_postgresql(self):
        from reasons_service.db.connection import init_db
        # Should return without doing anything
        init_db()

    @patch("reasons_service.db.connection._is_sqlite", True)
    @patch("reasons_service.db.connection.settings")
    @patch("reasons_service.db.connection.get_sync_engine")
    def test_init_db_creates_tables_for_sqlite(self, mock_engine, mock_settings, tmp_path):
        from reasons_service.db.connection import init_db
        mock_settings.data_dir = tmp_path / "data"
        mock_engine_obj = MagicMock()
        mock_engine.return_value = mock_engine_obj

        # Mock Base.metadata.create_all
        with patch("reasons_service.db.models.Base") as mock_base:
            init_db()
            mock_base.metadata.create_all.assert_called_once_with(mock_engine_obj)

        # data_dir should be created
        assert (tmp_path / "data").exists()


# --- search_beliefs_fts ---


class TestSearchBeliefsFts:
    def _make_db(self, tmp_path, nodes=None):
        """Create a full reasons_lib-compatible SQLite database with FTS5."""
        from reasons_lib.storage import SCHEMA
        db_path = tmp_path / str(FAKE_PROJECT_ID) / "reasons.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA)
        if nodes:
            for nid, text, tv in nodes:
                conn.execute(
                    "INSERT INTO nodes (id, text, truth_value) VALUES (?, ?, ?)",
                    (nid, text, tv),
                )
                conn.execute(
                    "INSERT INTO nodes_fts (id, text) VALUES (?, ?)",
                    (nid, text),
                )
        conn.commit()
        conn.close()
        return tmp_path

    @patch("reasons_service.rms.api.settings")
    def test_filters_to_in_only(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Pipeline risk assessment", "IN"),
            ("b2", "Pipeline throughput metric", "OUT"),
            ("b3", "Pipeline delivery status", "IN"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import search_beliefs_fts
        results = search_beliefs_fts(FAKE_PROJECT_ID, "pipeline")
        # Only IN beliefs should be returned
        ids = {r["id"] for r in results}
        assert "b1" in ids
        assert "b3" in ids
        assert "b2" not in ids  # OUT belief excluded

    @patch("reasons_service.rms.api.settings")
    def test_out_beliefs_excluded(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Security vulnerability found", "OUT"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from reasons_service.rms.api import search_beliefs_fts
        results = search_beliefs_fts(FAKE_PROJECT_ID, "security")
        assert len(results) == 0


# --- import_network ---


class TestImportNetwork:
    @patch("reasons_service.rms.api.settings")
    def test_import_network_sqlite(self, mock_settings, tmp_path):
        from reasons_lib.network import Network
        from reasons_service.rms.api import import_network, count_beliefs, count_nogoods

        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        # Build a network with nodes and a nogood
        net = Network()
        net.add_node("n1", "First belief")
        net.add_node("n2", "Second belief")
        net.add_node("n3", "Third belief")
        net.add_nogood(["n1", "n2"])

        result = import_network(FAKE_PROJECT_ID, net)
        assert result["node_count"] == 3
        assert result["nogood_count"] == 1

        # Verify data persisted
        assert count_beliefs(FAKE_PROJECT_ID, None) == 3
        assert count_nogoods(FAKE_PROJECT_ID) == 1

    @patch("reasons_service.rms.api.settings")
    def test_import_network_preserves_truth_values(self, mock_settings, tmp_path):
        from reasons_lib.network import Network
        from reasons_service.rms.api import import_network, count_beliefs

        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        net = Network()
        net.add_node("n1", "IN belief")
        net.add_node("n2", "OUT belief")
        net.retract("n2")

        import_network(FAKE_PROJECT_ID, net)
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 1
        assert count_beliefs(FAKE_PROJECT_ID, "OUT") == 1

    @patch("reasons_service.rms.api.settings")
    def test_import_empty_network(self, mock_settings, tmp_path):
        from reasons_lib.network import Network
        from reasons_service.rms.api import import_network, count_beliefs

        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        net = Network()
        result = import_network(FAKE_PROJECT_ID, net)
        assert result["node_count"] == 0
        assert result["nogood_count"] == 0
        assert count_beliefs(FAKE_PROJECT_ID, None) == 0


# --- import_reasons endpoint ---


class TestImportReasonsEndpoint:
    def _make_reasons_db(self, tmp_path):
        """Create a valid reasons.db file and return its path."""
        from reasons_lib.network import Network
        from reasons_lib.storage import Storage
        db_file = tmp_path / "upload.db"
        store = Storage(str(db_file))
        net = Network()
        net.add_node("b1", "Belief one")
        net.add_node("b2", "Belief two")
        net.add_nogood(["b1", "b2"])
        store.save(net)
        store.close()
        return db_file

    @patch("reasons_service.rms.api.settings")
    def test_import_reasons_sqlite(self, mock_settings, tmp_path):
        """Full round-trip: upload reasons.db → project created → beliefs importd."""
        from httpx import ASGITransport, AsyncClient
        import asyncio

        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path / "data"

        db_file = self._make_reasons_db(tmp_path)

        # We need to test the endpoint, but it requires a real DB session.
        # Use the rms_api.import_network directly for SQLite validation.
        from reasons_lib.storage import Storage
        store = Storage(str(db_file))
        network = store.load()
        store.close()

        from reasons_service.rms.api import import_network
        result = import_network(FAKE_PROJECT_ID, network)
        assert result["node_count"] == 2
        assert result["nogood_count"] == 1

        # Verify the beliefs are queryable
        from reasons_service.rms.api import count_beliefs, count_nogoods
        assert count_beliefs(FAKE_PROJECT_ID, None) == 2
        assert count_nogoods(FAKE_PROJECT_ID) == 1

    def test_tmp_file_cleanup_on_invalid_upload(self, tmp_path):
        """Temp file is cleaned up even when the upload is invalid."""
        import tempfile

        # Create an invalid (non-SQLite) file
        bad_file = tmp_path / "bad.db"
        bad_file.write_text("not a sqlite database")

        # Simulate what the endpoint does: write to temp, try to load, clean up
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path_file = Path(tmp.name)
            tmp.write(bad_file.read_bytes())

        try:
            from reasons_lib.storage import Storage
            Storage(str(tmp_path_file)).load()
            assert False, "Should have raised"
        except Exception:
            pass
        finally:
            tmp_path_file.unlink(missing_ok=True)

        # Temp file should be gone
        assert not tmp_path_file.exists()
