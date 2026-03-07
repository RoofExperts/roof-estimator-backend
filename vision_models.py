"""
Database models for the AI Vision Plan Reader.
Tracks uploaded plan files, per-page analysis, and extracted measurements.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class RoofPlanFile(Base):
    """Tracks an uploaded architectural roof plan PDF."""
    __tablename__ = "roof_plan_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    file_name = Column(String(500), nullable=False)
    file_type = Column(String(10), default="pdf")
    s3_key = Column(String(1000), nullable=True)
    upload_status = Column(String(50), default="pending")
    page_count = Column(Integer, nullable=True)
    detected_scale = Column(String(200), nullable=True)
    scale_confidence = Column(Float, nullable=True)
    manual_scale = Column(String(200), nullable=True)  # User override: "3/16 inch = 1 foot"
    manual_scale_ratio = Column(Float, nullable=True)  # User override: 64 for 3/16"=1'-0"
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pages = relationship("PlanPageAnalysis", back_populates="plan_file", cascade="all, delete-orphan")
    extractions = relationship("VisionExtraction", back_populates="plan_file", cascade="all, delete-orphan")


class PlanPageAnalysis(Base):
    """Stores per-page vision analysis results."""
    __tablename__ = "plan_page_analysis"

    id = Column(Integer, primary_key=True, index=True)
    plan_file_id = Column(Integer, ForeignKey("roof_plan_files.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    page_type = Column(String(50), default="unknown")
    is_roof_relevant = Column(Boolean, default=False)
    analysis_json = Column(Text, nullable=True)
    page_image_s3_key = Column(String(1000), nullable=True)
    processing_status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    plan_file = relationship("RoofPlanFile", back_populates="pages")


class VisionExtraction(Base):
    """Individual measurement extracted from a roof plan by GPT-4o vision."""
    __tablename__ = "vision_extractions"

    id = Column(Integer, primary_key=True, index=True)
    plan_file_id = Column(Integer, ForeignKey("roof_plan_files.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=True)
    extraction_type = Column(String(50), nullable=False)
    measurement_value = Column(Float, nullable=False)
    measurement_unit = Column(String(20), nullable=False)
    confidence_score = Column(Float, default=0.5)
    source_description = Column(String(500), nullable=True)
    location_on_plan = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    condition_id = Column(Integer, ForeignKey("roof_conditions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    plan_file = relationship("RoofPlanFile", back_populates="extractions")


class PlanMarkup(Base):
    """User annotations and measurements drawn on the plan viewer."""
    __tablename__ = "plan_markups"

    id = Column(Integer, primary_key=True, index=True)
    plan_file_id = Column(Integer, ForeignKey("roof_plan_files.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    markup_type = Column(String(20), nullable=False)  # measurement, line, rect, circle, arrow, freehand, text
    data_json = Column(Text, nullable=False)  # JSON blob with coordinates, color, etc.
    distance_ft = Column(Float, nullable=True)  # only for measurement type
    label = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    plan_file = relationship("RoofPlanFile")
