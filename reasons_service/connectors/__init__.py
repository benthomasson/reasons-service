"""Plugin system for external data connectors.

Connectors are discovered via Python entry points:

    [project.entry-points."reasons_service.connectors"]
    dataverse = "expert_dataverse:create_connector"

Each entry point should be a callable that returns a DataConnector instance.
"""

import abc
import asyncio
import importlib.metadata
import logging

logger = logging.getLogger(__name__)


class DataConnector(abc.ABC):
    """Base class for external data connectors."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier (e.g. 'dataverse')."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """One-line description for the LLM prompt."""
        ...

    @abc.abstractmethod
    async def query(self, question: str) -> str:
        """Query this data source. Returns a plain-text answer."""
        ...


class ConnectorRegistry:
    """Discovers and caches DataConnector plugins via entry points."""

    _instance: "ConnectorRegistry | None" = None

    def __init__(self):
        self._connectors: dict[str, DataConnector] = {}
        self._discovered = False

    @classmethod
    def get(cls) -> "ConnectorRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def discover(self) -> None:
        """Load all installed connector plugins."""
        if self._discovered:
            return
        for ep in importlib.metadata.entry_points(
            group="reasons_service.connectors",
        ):
            try:
                factory = ep.load()
                connector = factory()
                if not isinstance(connector, DataConnector):
                    logger.warning("Entry point %r returned %s, not DataConnector",
                                   ep.name, type(connector).__name__)
                    continue
                self._connectors[connector.name] = connector
                logger.info("Loaded connector: %s — %s", connector.name, connector.description)
            except Exception:
                logger.exception("Failed to load connector: %s", ep.name)
        self._discovered = True

    def list_connectors(self, allowed: list[str] | None = None) -> list[DataConnector]:
        """List available connectors, optionally filtered by allowed names."""
        self.discover()
        if allowed is None:
            return list(self._connectors.values())
        return [c for c in self._connectors.values() if c.name in allowed]

    def get_connector(self, name: str) -> DataConnector | None:
        self.discover()
        return self._connectors.get(name)


async def query_data(
    question: str,
    connector_name: str | None = None,
    allowed: list[str] | None = None,
) -> str:
    """Dispatch a query to a data connector.

    If connector_name is given, queries that specific connector.
    Otherwise queries all allowed connectors.
    """
    registry = ConnectorRegistry.get()

    if connector_name:
        connector = registry.get_connector(connector_name)
        if connector is None:
            available = [c.name for c in registry.list_connectors(allowed)]
            return f"Connector '{connector_name}' not found. Available: {available}"
        return await connector.query(question)

    connectors = registry.list_connectors(allowed)
    if not connectors:
        return "No data connectors available."

    if len(connectors) == 1:
        return await connectors[0].query(question)

    results = await asyncio.gather(
        *(c.query(question) for c in connectors),
        return_exceptions=True,
    )
    parts = []
    for conn, result in zip(connectors, results):
        if isinstance(result, Exception):
            parts.append(f"[{conn.name}] Error: {result}")
        else:
            parts.append(f"[{conn.name}]\n{result}")
    return "\n\n---\n\n".join(parts)
