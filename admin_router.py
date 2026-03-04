"""
Admin Router - Company settings management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import json
import datetime
import traceback

from database import get_db
from models import CompanySettings
from s3_service import upload_file_to_s3, s3_client, AWS_BUCKET_NAME


admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Request/Response Models ──────────────────────────────────

class CompanySettingsUpdate(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    license_info: Optional[str] = None
    about_text: Optional[str] = None
    services: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    why_choose_us: Optional[List[str]] = None
    default_terms: Optional[List[str]] = None


class CompanySettingsResponse(BaseModel):
    id: int
    name: str
    tagline: str
    phone: str
    email: str
    website: str
    address: str
    license_info: str
    logo_url: Optional[str]
    about_text: Optional[str]
    services: List[str]
    certifications: List[str]
    why_choose_us: List[str]
    default_terms: List[str]
    updated_at: Optional[str]


# ── Helper ───────────────────────────────────────────────────

def _parse_json_list(json_str: Optional[str]) -> list:
    """Safely parse a JSON string list, returning [] on failure."""
    if not json_str:
        return []
    try:
        result = json.loads(json_str)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _settings_to_response(settings: CompanySettings) -> dict:
    """Convert a CompanySettings DB row to a response dict."""
    return {
        "id": settings.id,
        "name": settings.name or "",
        "tagline": settings.tagline or "",
        "phone": settings.phone or "",
        "email": settings.email or "",
        "website": settings.website or "",
        "address": settings.address or "",
        "license_info": settings.license_info or "",
        "logo_url": settings.logo_url,
        "about_text": settings.about_text or "",
        "services": _parse_json_list(settings.services_json),
        "certifications": _parse_json_list(settings.certifications_json),
        "why_choose_us": _parse_json_list(settings.why_choose_us_json),
        "default_terms": _parse_json_list(settings.default_terms_json),
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def get_or_create_settings(db: Session) -> CompanySettings:
    """Get the single company settings row, creating it if it doesn't exist."""
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(
            name="ROOF EXPERTS",
            tagline="Commercial Roofing Specialists",
            phone="(713) 555-0100",
            email="Anthony@roofexperts.com",
            website="www.roofexperts.com",
            address="Houston, TX",
            license_info="Licensed & Insured | Commercial Roofing Contractor",
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


# ── Endpoints ────────────────────────────────────────────────

@admin_router.get("/health")
def admin_health():
    """Quick check that admin router is loaded."""
    return {"status": "ok", "router": "admin", "version": "1.1"}


@admin_router.get("/company")
def get_company_settings(db: Session = Depends(get_db)):
    """Get current company settings."""
    try:
        settings = get_or_create_settings(db)
        return _settings_to_response(settings)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {str(e)}")


@admin_router.put("/company")
def update_company_settings(updates: CompanySettingsUpdate, db: Session = Depends(get_db)):
    """Update company settings."""
    try:
        print(f"[ADMIN] PUT /company received: {updates}")
        settings = get_or_create_settings(db)

        # Update simple string fields
        for field in ["name", "tagline", "phone", "email", "website", "address", "license_info", "about_text"]:
            value = getattr(updates, field, None)
            if value is not None:
                setattr(settings, field, value)

        # Update JSON list fields
        if updates.services is not None:
            settings.services_json = json.dumps(updates.services)
        if updates.certifications is not None:
            settings.certifications_json = json.dumps(updates.certifications)
        if updates.why_choose_us is not None:
            settings.why_choose_us_json = json.dumps(updates.why_choose_us)
        if updates.default_terms is not None:
            settings.default_terms_json = json.dumps(updates.default_terms)

        settings.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(settings)
        print(f"[ADMIN] Settings saved successfully, id={settings.id}")

        return _settings_to_response(settings)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {str(e)}")


@admin_router.post("/company/logo")
def upload_company_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a company logo image to S3."""
    settings = get_or_create_settings(db)

    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp", "image/svg+xml"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: PNG, JPG, WebP, SVG")

    # Upload to S3 under company/logo/ path
    import uuid
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "png"
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    s3_key = f"company/logo/{unique_filename}"

    s3_client.upload_fileobj(
        file.file,
        AWS_BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": file.content_type}
    )

    logo_url = f"https://{AWS_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
    settings.logo_url = logo_url
    settings.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(settings)

    return {"message": "Logo uploaded successfully", "logo_url": logo_url}


@admin_router.delete("/company/logo")
def delete_company_logo(db: Session = Depends(get_db)):
    """Remove the company logo."""
    settings = get_or_create_settings(db)

    if settings.logo_url:
        # Try to delete from S3
        try:
            s3_key = settings.logo_url.split(".amazonaws.com/")[-1]
            s3_client.delete_object(Bucket=AWS_BUCKET_NAME, Key=s3_key)
        except Exception:
            pass  # Don't fail if S3 delete fails

    settings.logo_url = None
    settings.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {"message": "Logo removed successfully"}
