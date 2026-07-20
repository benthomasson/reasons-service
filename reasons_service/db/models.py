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


class Project(Base):
    __tablename__ = "projects"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False, unique=True)
    domain = Column(String, nullable=False)
    config = Column(JSON, default=dict)
    public = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="project", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="project", cascade="all, delete-orphan")
    nogoods = relationship("Nogood", back_populates="project", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="project", cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="project", cascade="all, delete-orphan")


entry_sources = Table(
    "entry_sources",
    Base.metadata,
    Column("entry_id", String, nullable=False),
    Column("entry_project_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
    ForeignKeyConstraint(
        ["entry_id", "entry_project_id"],
        ["entries.id", "entries.project_id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("entry_id", "entry_project_id", "source_id"),
)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("project_id", "slug"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(String)
    slug = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    word_count = Column(Integer)
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="sources")
    entries = relationship("Entry", secondary=entry_sources, back_populates="sources")


class Entry(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    topic = Column(String, nullable=False)
    title = Column(String)
    content = Column(Text, nullable=False)
    source_id = Column(Uuid(as_uuid=True), ForeignKey("sources.id"))
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="entries")
    sources = relationship("Source", secondary=entry_sources, back_populates="entries")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    text = Column(Text, nullable=False)
    status = Column(String, default="IN")
    source = Column(String)
    source_hash = Column(String)
    review_status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="claims")


class Nogood(Base):
    __tablename__ = "nogoods"

    id = Column(String, primary_key=True)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    description = Column(Text, nullable=False)
    resolution = Column(Text)
    claim_ids = Column(JSON)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True))

    project = relationship("Project", back_populates="nogoods")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    assessment_type = Column(String, nullable=False)
    input_data = Column(JSON)
    results = Column(JSON, nullable=False)
    score = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="assessments")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    graph_name = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)
    status = Column(String, default="running")
    progress = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True))
    error = Column(Text)

    project = relationship("Project", back_populates="pipeline_runs")


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_index"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    section = Column(String, default="")
    text = Column(Text, nullable=False)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    label = Column(String)
    description = Column(String)
    belief_count = Column(Integer, default=0)
    curated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="topics")


if _has_pgvector:

    class Embedding(Base):
        __tablename__ = "embeddings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        project_id = Column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
        source_table = Column(String, nullable=False)
        source_id = Column(String, nullable=False)
        label = Column(String)
        embedding = Column(Vector(384), nullable=False)
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

else:
    Embedding = None
