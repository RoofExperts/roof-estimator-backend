from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON
from database import Base
import datetime


# =============================
# USER MODEL
# =============================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="estimator")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# =============================
# PROJECT MODEL
# =============================
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    # Basic Info
    user_id = Column(Integer, nullable=True)
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
# COMPANY SETTINGS MODEL
# =============================
class CompanySettings(Base):
    __tablename__ = "company_settings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="ROOF EXPERTS")
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

    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
