"""
Admin Router - Company settings management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict
import json
import datetime
import traceback

from database import get_db
from models import CompanySettings
from conditions_models import SystemTemplateCondition
from s3_service import upload_file_to_s3, s3_client, AWS_BUCKET_NAME
from auth import get_current_user


admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Request/Response Models ──────────────────────────────────

class ProposalTypeDefaults(BaseModel):
    terms: Optional[List[str]] = None
    exclusions: Optional[List[str]] = None
    notes: Optional[List[str]] = None


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
    proposal_type_defaults: Optional[Dict[str, ProposalTypeDefaults]] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    # Estimate rate settings
    markup_percent: Optional[float] = None
    tax_rate: Optional[float] = None
    labor_rate_per_square: Optional[float] = None
    default_waste_factor: Optional[float] = None


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
    proposal_type_defaults: Dict
    primary_color: str
    secondary_color: str
    accent_color: str
    markup_percent: float
    tax_rate: float
    labor_rate_per_square: float
    default_waste_factor: float
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


def _parse_json_dict(json_str: Optional[str]) -> dict:
    """Safely parse a JSON string dict, returning {} on failure."""
    if not json_str:
        return {}
    try:
        result = json.loads(json_str)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


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
        "proposal_type_defaults": _parse_json_dict(settings.proposal_type_defaults_json),
        "primary_color": settings.primary_color or "#1e40af",
        "secondary_color": settings.secondary_color or "#475569",
        "accent_color": settings.accent_color or "#059669",
        "markup_percent": settings.markup_percent if settings.markup_percent is not None else 25.0,
        "tax_rate": settings.tax_rate if settings.tax_rate is not None else 8.25,
        "labor_rate_per_square": settings.labor_rate_per_square if settings.labor_rate_per_square is not None else 85.0,
        "default_waste_factor": settings.default_waste_factor if settings.default_waste_factor is not None else 10.0,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def get_or_create_settings(db: Session, org_id: Optional[str] = None) -> CompanySettings:
    """Get the single company settings row, creating it if it doesn't exist."""
    if org_id:
        settings = db.query(CompanySettings).filter(CompanySettings.org_id == org_id).first()
    else:
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
            org_id=org_id,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


# ── Endpoints ────────────────────────────────────────────────

@admin_router.get("/health")
def admin_health(current_user: dict = Depends(get_current_user)):
    """Quick check that admin router is loaded."""
    return {"status": "ok", "router": "admin", "version": "1.1"}


@admin_router.get("/company")
def get_company_settings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get current company settings."""
    try:
        settings = get_or_create_settings(db, current_user["org_id"])
        return _settings_to_response(settings)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {str(e)}")


@admin_router.put("/company")
def update_company_settings(updates: CompanySettingsUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update company settings."""
    try:
        print(f"[ADMIN] PUT /company received: {updates}")
        settings = get_or_create_settings(db, current_user["org_id"])

        # Update simple string fields
        for field in ["name", "tagline", "phone", "email", "website", "address", "license_info", "about_text",
                      "primary_color", "secondary_color", "accent_color",
                      "markup_percent", "tax_rate", "labor_rate_per_square", "default_waste_factor"]:
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
        if updates.proposal_type_defaults is not None:
            # Convert Pydantic models to dicts
            ptd = {}
            for key, val in updates.proposal_type_defaults.items():
                ptd[key] = val.model_dump(exclude_none=True) if hasattr(val, 'model_dump') else val
            settings.proposal_type_defaults_json = json.dumps(ptd)

        settings.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(settings)
        print(f"[ADMIN] Settings saved successfully, id={settings.id}")

        return _settings_to_response(settings)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {str(e)}")


@admin_router.post("/company/logo")
def upload_company_logo(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Upload a company logo image to S3."""
    settings = get_or_create_settings(db, current_user["org_id"])

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
def delete_company_logo(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Remove the company logo."""
    settings = get_or_create_settings(db, current_user["org_id"])

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


# ============================================================================
# SYSTEM TEMPLATE MANAGEMENT
# ============================================================================

class SystemTemplateConditionCreate(BaseModel):
    condition_type: str
    description: Optional[str] = None
    measurement_unit: str = "sqft"
    flashing_height: Optional[float] = None
    fastener_spacing: Optional[int] = None
    sort_order: Optional[int] = None


class SystemTemplateConditionUpdate(BaseModel):
    condition_type: Optional[str] = None
    description: Optional[str] = None
    measurement_unit: Optional[str] = None
    flashing_height: Optional[float] = None
    fastener_spacing: Optional[int] = None
    sort_order: Optional[int] = None


class SystemTemplateReorder(BaseModel):
    condition_ids: List[int]


def _ensure_org_template(system_type: str, org_id: int, db: Session):
    """
    Lazy clone: if the org has no custom template for this system type,
    clone the global defaults into org-specific rows. Returns the org rows.
    """
    org_rows = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.org_id == org_id,
        SystemTemplateCondition.system_type == system_type,
    ).order_by(SystemTemplateCondition.sort_order).all()

    if org_rows:
        return org_rows

    # Clone from global
    global_rows = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.org_id == None,
        SystemTemplateCondition.is_global == True,
        SystemTemplateCondition.system_type == system_type,
        SystemTemplateCondition.is_active == True,
    ).order_by(SystemTemplateCondition.sort_order).all()

    cloned = []
    for g in global_rows:
        row = SystemTemplateCondition(
            org_id=org_id,
            system_type=system_type,
            condition_type=g.condition_type,
            description=g.description,
            measurement_unit=g.measurement_unit,
            flashing_height=g.flashing_height,
            fastener_spacing=g.fastener_spacing,
            sort_order=g.sort_order,
            is_global=False,
            is_active=True,
        )
        db.add(row)
        cloned.append(row)

    db.flush()
    return cloned


def _template_row_to_dict(row: SystemTemplateCondition) -> dict:
    return {
        "id": row.id,
        "condition_type": row.condition_type,
        "description": row.description,
        "measurement_unit": row.measurement_unit,
        "flashing_height": row.flashing_height,
        "fastener_spacing": row.fastener_spacing,
        "sort_order": row.sort_order,
        "is_global": row.is_global,
        "is_active": row.is_active,
    }


@admin_router.get("/system-templates/{system_type}")
def get_system_template(
    system_type: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get the system template for a given type. Returns org-specific if exists, else global defaults."""
    org_id = current_user["org_id"]

    # Check for org-specific template first
    org_rows = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.org_id == org_id,
        SystemTemplateCondition.system_type == system_type,
        SystemTemplateCondition.is_active == True,
    ).order_by(SystemTemplateCondition.sort_order).all()

    if org_rows:
        return {
            "system_type": system_type,
            "is_custom": True,
            "conditions": [_template_row_to_dict(r) for r in org_rows],
        }

    # Fall back to global
    global_rows = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.org_id == None,
        SystemTemplateCondition.is_global == True,
        SystemTemplateCondition.system_type == system_type,
        SystemTemplateCondition.is_active == True,
    ).order_by(SystemTemplateCondition.sort_order).all()

    return {
        "system_type": system_type,
        "is_custom": False,
        "conditions": [_template_row_to_dict(r) for r in global_rows],
    }


@admin_router.post("/system-templates/{system_type}/conditions")
def add_template_condition(
    system_type: str,
    body: SystemTemplateConditionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add a condition to the org's system template. Auto-clones global on first edit."""
    org_id = current_user["org_id"]
    org_rows = _ensure_org_template(system_type, org_id, db)

    # Check for duplicate condition_type
    existing_types = {r.condition_type for r in org_rows}
    if body.condition_type in existing_types:
        raise HTTPException(status_code=400, detail=f"Condition '{body.condition_type}' already exists in template")

    # Determine sort_order
    max_sort = max((r.sort_order for r in org_rows), default=0)
    sort_order = body.sort_order if body.sort_order is not None else max_sort + 1

    row = SystemTemplateCondition(
        org_id=org_id,
        system_type=system_type,
        condition_type=body.condition_type,
        description=body.description or body.condition_type.replace("_", " ").title(),
        measurement_unit=body.measurement_unit,
        flashing_height=body.flashing_height,
        fastener_spacing=body.fastener_spacing,
        sort_order=sort_order,
        is_global=False,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return _template_row_to_dict(row)


@admin_router.put("/system-templates/{system_type}/conditions/{condition_id}")
def update_template_condition(
    system_type: str,
    condition_id: int,
    body: SystemTemplateConditionUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update a condition in the org's system template."""
    org_id = current_user["org_id"]

    row = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.id == condition_id,
        SystemTemplateCondition.org_id == org_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template condition not found")

    for field in ["condition_type", "description", "measurement_unit", "flashing_height", "fastener_spacing", "sort_order"]:
        value = getattr(body, field, None)
        if value is not None:
            setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _template_row_to_dict(row)


@admin_router.delete("/system-templates/{system_type}/conditions/{condition_id}")
def delete_template_condition(
    system_type: str,
    condition_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Remove a condition from the org's system template."""
    org_id = current_user["org_id"]

    row = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.id == condition_id,
        SystemTemplateCondition.org_id == org_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template condition not found")

    db.delete(row)
    db.commit()
    return {"message": f"Removed '{row.condition_type}' from {system_type} template"}


@admin_router.put("/system-templates/{system_type}/reorder")
def reorder_template_conditions(
    system_type: str,
    body: SystemTemplateReorder,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Bulk reorder conditions in the org's system template."""
    org_id = current_user["org_id"]

    for idx, cond_id in enumerate(body.condition_ids):
        row = db.query(SystemTemplateCondition).filter(
            SystemTemplateCondition.id == cond_id,
            SystemTemplateCondition.org_id == org_id,
        ).first()
        if row:
            row.sort_order = idx + 1

    db.commit()
    return {"message": "Reorder complete"}


@admin_router.post("/system-templates/{system_type}/reset")
def reset_template_to_defaults(
    system_type: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete all org-specific template conditions, reverting to global defaults."""
    org_id = current_user["org_id"]

    deleted = db.query(SystemTemplateCondition).filter(
        SystemTemplateCondition.org_id == org_id,
        SystemTemplateCondition.system_type == system_type,
    ).delete()

    db.commit()
    return {"message": f"Reset {system_type} template to defaults. Removed {deleted} custom conditions."}
