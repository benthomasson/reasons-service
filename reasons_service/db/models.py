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


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    display_name = Column(String)
    type = Column(String, nullable=False, default="organization")
    public = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    members = relationship("TenantMember", back_populates="tenant", cascade="all, delete-orphan")
    domains = relationship("Domain", back_populates="tenant")


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_email"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_email = Column(String, ForeignKey("users.email", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, default="reader")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="members")
    user = relationship("User", back_populates="tenant_memberships")


class User(Base):
    __tablename__ = "users"

    email = Column(String, primary_key=True)
    role = Column(String, nullable=False, default="reader")
    display_name = Column(String)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    visible_tags = Column(JSON, default=list)
    writable_tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tenant_memberships = relationship("TenantMember", back_populates="user")


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    config = Column(JSON, default=dict)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    public = Column(Boolean, nullable=False, default=False, server_default="false")
    members_only = Column(Boolean, nullable=False, default=False, server_default="false")
    allowed_tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="domains")
    sources = relationship("Source", back_populates="domain", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="domain", cascade="all, delete-orphan")
    summaries = relationship("Summary", back_populates="domain", cascade="all, delete-orphan")
    nogoods = relationship("Nogood", back_populates="domain", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="domain", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="domain", cascade="all, delete-orphan")
    proposals = relationship("Proposal", back_populates="domain", cascade="all, delete-orphan")
    members = relationship("DomainMember", back_populates="domain", cascade="all, delete-orphan")


class DomainMember(Base):
    __tablename__ = "domain_members"
    __table_args__ = (UniqueConstraint("domain_id", "user_email"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    user_email = Column(String, ForeignKey("users.email", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, default="reader")
    visible_tags = Column(JSON, default=list)
    writable_tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="members")
    user = relationship("User")


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
    title = Column(String)
    description = Column(Text)
    author = Column(String)
    content_type = Column(String)
    added_by = Column(String)
    license = Column(String)

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


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    domain_id = Column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    proposal_type = Column(String, nullable=False)
    target_node_id = Column(String)
    proposed_text = Column(Text)
    proposed_tags = Column(JSON, default=list)
    rationale = Column(Text)
    proposed_by = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    snapshot_json = Column(JSON)
    impact_json = Column(JSON)
    result_json = Column(JSON)
    review_notes = Column(Text)
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="proposals")


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


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_domain_id", "domain_id"),
        Index("ix_audit_log_actor", "actor"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_resource_type", "resource_type"),
        Index("ix_audit_log_timestamp", "timestamp"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String)
    domain_id = Column(Uuid(as_uuid=True))
    before_state = Column(JSON)
    after_state = Column(JSON)
    metadata_ = Column("metadata", JSON)


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
