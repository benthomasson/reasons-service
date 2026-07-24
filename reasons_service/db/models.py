"""SQLAlchemy models for reasons-service."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship

try:
    from pgvector.sqlalchemy import Vector

    _has_pgvector = True
except ImportError:
    _has_pgvector = False


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    email = Column(String, primary_key=True)
    role = Column(String, nullable=False, default="reader")
    display_name = Column(String)
    visible_tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Domain(Base):
    __tablename__ = "domains"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False)
    config = Column(JSON, default=dict)
    public = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    sources = relationship("Source", back_populates="domain", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="domain", cascade="all, delete-orphan")
    summaries = relationship("Summary", back_populates="domain", cascade="all, delete-orphan")
    nogoods = relationship("Nogood", back_populates="domain", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="domain", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="domain", cascade="all, delete-orphan")


entry_sources = Table(
    "entry_sources",
    Base.metadata,
    Column("entry_id", String, nullable=False),
    Column("entry_domain_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
    ForeignKeyConstraint(
        ["entry_id", "entry_domain_id"],
        ["entries.id", "entries.domain_id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("entry_id", "entry_domain_id", "source_id"),
)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("domain_id", "slug"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    url = Column(String)
    slug = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    word_count = Column(Integer)
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="sources")
    entries = relationship("Entry", secondary=entry_sources, back_populates="sources")
    summaries = relationship("Summary", secondary="summary_sources", back_populates="sources")


class Entry(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    topic = Column(String, nullable=False)
    title = Column(String)
    content = Column(Text, nullable=False)
    source_id = Column(Uuid(as_uuid=True), ForeignKey("sources.id"))
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="entries")
    sources = relationship("Source", secondary=entry_sources, back_populates="entries")


summary_sources = Table(
    "summary_sources",
    Base.metadata,
    Column("summary_id", String, nullable=False),
    Column("summary_domain_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
    ForeignKeyConstraint(
        ["summary_id", "summary_domain_id"],
        ["summaries.id", "summaries.domain_id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("summary_id", "summary_domain_id", "source_id"),
)


class Summary(Base):
    __tablename__ = "summaries"

    id = Column(String, primary_key=True)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    topic = Column(String, nullable=False)
    title = Column(String)
    content = Column(Text, nullable=False)
    source_id = Column(Uuid(as_uuid=True), ForeignKey("sources.id"))
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="summaries")
    sources = relationship("Source", secondary=summary_sources, back_populates="summaries")


class Nogood(Base):
    __tablename__ = "nogoods"

    id = Column(String, primary_key=True)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    description = Column(Text, nullable=False)
    resolution = Column(Text)
    claim_ids = Column(JSON)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True))

    domain = relationship("Domain", back_populates="nogoods")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    assessment_type = Column(String, nullable=False)
    input_data = Column(JSON)
    results = Column(JSON, nullable=False)
    score = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="assessments")


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_index"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    section = Column(String, default="")
    text = Column(Text, nullable=False)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("domain_id", "name"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    label = Column(String)
    description = Column(String)
    belief_count = Column(Integer, default=0)
    curated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="topics")


class McpClient(Base):
    __tablename__ = "mcp_clients"

    client_id = Column(String, primary_key=True)
    client_data = Column(JSON, nullable=False)
    is_open = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class McpAccessToken(Base):
    __tablename__ = "mcp_access_tokens"
    __table_args__ = (Index("ix_mcp_access_tokens_client_subject", "client_id", "subject"),)

    token = Column(String, primary_key=True)
    client_id = Column(String, nullable=False)
    scopes = Column(JSON, default=list)
    expires_at = Column(Integer)
    resource = Column(String)
    subject = Column(String)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class McpRefreshToken(Base):
    __tablename__ = "mcp_refresh_tokens"

    token = Column(String, primary_key=True)
    client_id = Column(String, nullable=False)
    scopes = Column(JSON, default=list)
    expires_at = Column(Integer)
    subject = Column(String)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


if _has_pgvector:

    class Embedding(Base):
        __tablename__ = "embeddings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
        source_table = Column(String, nullable=False)
        source_id = Column(String, nullable=False)
        label = Column(String)
        embedding = Column(Vector(384), nullable=False)
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

else:
    Embedding = None
