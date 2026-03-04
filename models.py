from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime


# =============================
# ORGANIZATION MODEL (TENANT)
# =============================
class Organization(Base):
    """Represents a roofing company / tenant in the SaaS platform."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    members = relationship("OrganizationMember", back_populates="organization")
    settings = relationship("CompanySettings", back_populates="organization", uselist=False)


# =============================
# ORGANIZATION MEMBER MODEL
# =============================
class OrganizationMember(Base):
    """Links users to organizations with role-based access."""
    __tablename__ = "organization_members"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="estimator",
                  comment="owner, admin, estimator")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")


# =============================
# USER INVITE MODEL
# =============================
class UserInvite(Base):
    """Pending invitations for users to join an organization."""
    __tablename__ = "user_invites"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False, default="estimator")
    token = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# =============================
# USER MODEL
# =============================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="estimator")  # Legacy — role is now per-org in OrganizationMember
    current_org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    memberships = relationship("OrganizationMember", back_populates="user")


# =============================
# PROJECT MODEL
# =============================
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    # Tenant isolation
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    # Basic Info
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    system_type = Column(String, nullable=True)
    roof_area = Column(Float, nullable=True)

    # Files
    spec_file_url = Column(String, nullable=True)

    # AI Analysis Tracking
    analysis_status = Column(String, default="not_started")
    analysis_result = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# =============================
# COMPANY SETTINGS MODEL (per-org)
# =============================
class CompanySettings(Base):
    __tablename__ = "company_settings"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, unique=True, index=True)
    name = Column(String, nullable=False, default="My Roofing Company")
    tagline = Column(String, default="Commercial Roofing Specialists")
    phone = Column(String, default="")
    email = Column(String, default="")
    website = Column(String, default="")
    address = Column(String, default="")
    license_info = Column(String, default="")
    logo_url = Column(String, nullable=True)

    # Page 5 / About content
    about_text = Column(Text, nullable=True)
    services_json = Column(Text, nullable=True)          # JSON string list
    certifications_json = Column(Text, nullable=True)     # JSON string list
    why_choose_us_json = Column(Text, nullable=True)      # JSON string list

    # Default terms & conditions
    default_terms_json = Column(Text, nullable=True)      # JSON string list

    # Per-proposal-type defaults (JSON dict of {type: {terms:[], exclusions:[], notes:[]}})
    proposal_type_defaults_json = Column(Text, nullable=True)

    # Brand colors (hex values)
    primary_color = Column(String, default="#1e40af")
    secondary_color = Column(String, default="#475569")
    accent_color = Column(String, default="#059669")

    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="settings")


# =============================
# CUSTOMER MODEL
# =============================
class Customer(Base):
    """Master customer database for reusable client information."""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    company_name = Column(String, nullable=False, index=True)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


# =============================
# SAVED PROPOSAL MODEL
# =============================
class SavedProposal(Base):
    """Persisted proposal data so proposals can be edited and regenerated."""
    __tablename__ = "saved_proposals"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    proposal_number = Column(String, nullable=True)
    proposal_name = Column(String, nullable=True)
    proposal_data = Column(Text, nullable=False)  # JSON blob of full proposal form state
    status = Column(String, default="draft")  # draft, sent, accepted, declined
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
