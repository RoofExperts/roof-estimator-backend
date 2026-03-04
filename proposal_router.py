"""
Proposal Router - Generates and serves bid proposal PDFs.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import datetime
import io
import traceback

import json

from database import get_db
from models import Project, CompanySettings, Customer, SavedProposal
from conditions_models import RoofCondition, EstimateLineItem
from proposal_generator import generate_proposal_pdf
from admin_router import get_or_create_settings, _parse_json_list


proposal_router = APIRouter(prefix="/api/v1", tags=["proposals"])


# ── Request Models ────────────────────────────────────────────

class PreparedFor(BaseModel):
    company: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""


class LineItem(BaseModel):
    item: str = ""
    description: str = ""
    qty: str = ""
    unit: str = ""
    unit_price: str = ""
    total: str = ""


class WallPanelSection(BaseModel):
    title: str = ""
    description: str = ""
    items: List[LineItem] = []


class ProposalRequest(BaseModel):
    # Project overrides (auto-filled from project, but overridable)
    project_name: Optional[str] = None
    project_address: Optional[str] = None

    # Proposal meta
    proposal_number: str = ""
    proposal_date: Optional[str] = None
    valid_until: str = "30 days from date of proposal"

    # Prepared for
    prepared_for: PreparedFor = PreparedFor()

    # Page 1: Roofing System
    roofing_system_description: str = ""
    roofing_items: List[LineItem] = []
    roofing_metals: List[LineItem] = []
    roofing_total: str = ""
    roofing_exclusions: List[str] = []
    roofing_notes: List[str] = []

    # Page 2: Metal Roofing (optional)
    include_metal_roof: bool = False
    metal_roof_type: str = "Standing Seam Metal Roof"
    metal_roof_description: str = ""
    metal_roof_items: List[LineItem] = []
    metal_roof_total: str = ""
    metal_roof_exclusions: List[str] = []
    metal_roof_notes: List[str] = []

    # Page 3: Wall Panels (optional)
    include_wall_panels: bool = False
    wall_panel_sections: List[WallPanelSection] = []
    wall_panel_items: List[LineItem] = []
    wall_panel_total: str = ""
    wall_panel_exclusions: List[str] = []
    wall_panel_notes: List[str] = []

    # Page 4: Awnings (optional)
    include_awnings: bool = False
    awning_description: str = ""
    awning_items: List[LineItem] = []
    awning_total: str = ""
    awning_exclusions: List[str] = []
    awning_notes: List[str] = []

    # Grand total
    grand_total: str = ""

    # Terms & conditions
    terms: List[str] = []

    # Company info overrides (defaults used if empty)
    company_info: Optional[Dict[str, Any]] = None


# ── Company Info from DB ──────────────────────────────────────

def _get_company_info_dict(db: Session) -> dict:
    """Load company info from DB and return as a dict for the PDF generator."""
    settings = get_or_create_settings(db)
    return {
        "name": settings.name or "ROOF EXPERTS",
        "tagline": settings.tagline or "Commercial Roofing Specialists",
        "phone": settings.phone or "",
        "email": settings.email or "",
        "website": settings.website or "",
        "address": settings.address or "",
        "license": settings.license_info or "",
        "logo_url": settings.logo_url,
        "about_text": settings.about_text or "",
        "services": _parse_json_list(settings.services_json),
        "certifications": _parse_json_list(settings.certifications_json),
        "why_choose_us": _parse_json_list(settings.why_choose_us_json),
    }


def _get_default_terms(db: Session) -> list:
    """Load default terms from DB."""
    settings = get_or_create_settings(db)
    return _parse_json_list(settings.default_terms_json)


# ── Endpoints ─────────────────────────────────────────────────

@proposal_router.post("/projects/{project_id}/generate-proposal")
async def generate_proposal(project_id: int, request: ProposalRequest, db: Session = Depends(get_db)):
    """Generate a bid proposal PDF for a project."""

    # Look up project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Build the data dict for the PDF generator
    company_info = request.company_info or _get_company_info_dict(db)

    data = {
        "project_name": request.project_name or project.project_name,
        "project_address": request.project_address or project.address or "",
        "proposal_number": request.proposal_number or f"P-{project_id:04d}",
        "proposal_date": request.proposal_date or datetime.date.today().strftime("%B %d, %Y"),
        "valid_until": request.valid_until,

        "prepared_for": request.prepared_for.model_dump(),
        "company_info": company_info,

        # Page 1
        "roofing_system_description": request.roofing_system_description,
        "roofing_items": [item.model_dump() for item in request.roofing_items],
        "roofing_metals": [item.model_dump() for item in request.roofing_metals],
        "roofing_total": request.roofing_total,
        "roofing_exclusions": request.roofing_exclusions,
        "roofing_notes": request.roofing_notes,

        # Page 2
        "include_metal_roof": request.include_metal_roof,
        "metal_roof_type": request.metal_roof_type,
        "metal_roof_description": request.metal_roof_description,
        "metal_roof_items": [item.model_dump() for item in request.metal_roof_items],
        "metal_roof_total": request.metal_roof_total,
        "metal_roof_exclusions": request.metal_roof_exclusions,
        "metal_roof_notes": request.metal_roof_notes,

        # Page 3
        "include_wall_panels": request.include_wall_panels,
        "wall_panel_sections": [
            {
                "title": s.title,
                "description": s.description,
                "items": [i.model_dump() for i in s.items],
            }
            for s in request.wall_panel_sections
        ],
        "wall_panel_items": [item.model_dump() for item in request.wall_panel_items],
        "wall_panel_total": request.wall_panel_total,
        "wall_panel_exclusions": request.wall_panel_exclusions,
        "wall_panel_notes": request.wall_panel_notes,

        # Page 4
        "include_awnings": request.include_awnings,
        "awning_description": request.awning_description,
        "awning_items": [item.model_dump() for item in request.awning_items],
        "awning_total": request.awning_total,
        "awning_exclusions": request.awning_exclusions,
        "awning_notes": request.awning_notes,

        # Totals
        "grand_total": request.grand_total,
        "terms": request.terms if request.terms else _get_default_terms(db),
    }

    try:
        pdf_bytes = generate_proposal_pdf(data)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    # Return as downloadable PDF
    filename = f"Proposal_{data['proposal_number']}_{project.project_name.replace(' ', '_')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        }
    )


@proposal_router.get("/projects/{project_id}/proposal-defaults")
async def get_proposal_defaults(project_id: int, db: Session = Depends(get_db)):
    """
    Get default/pre-filled proposal data from existing project conditions.
    Frontend can use this to pre-populate the proposal form.
    """

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get conditions
    conditions = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id
    ).all()

    # Build a summary of conditions for the proposal
    condition_summary = []
    for c in conditions:
        condition_summary.append({
            "id": c.id,
            "type": c.condition_type,
            "description": c.description or "",
            "value": c.measurement_value,
            "unit": c.measurement_unit,
            "wind_zone": c.wind_zone,
        })

    # Get estimate if it exists
    line_items = db.query(EstimateLineItem).filter(
        EstimateLineItem.project_id == project_id
    ).all()

    estimate_items = []
    for li in line_items:
        estimate_items.append({
            "material_name": li.material_name,
            "material_category": li.material_category,
            "quantity": li.quantity,
            "unit": li.unit,
            "unit_cost": li.unit_cost,
            "total_cost": li.total_cost,
            "notes": li.notes,
        })

    return {
        "project_name": project.project_name,
        "project_address": project.address or "",
        "system_type": project.system_type or "",
        "roof_area": project.roof_area,
        "proposal_number": f"P-{project_id:04d}",
        "proposal_date": datetime.date.today().strftime("%B %d, %Y"),
        "conditions": condition_summary,
        "estimate_items": estimate_items,
        "company_info": _get_company_info_dict(db),
        "default_terms": _get_default_terms(db),
    }


# ── Saved Proposal Models ────────────────────────────────────

class SaveProposalRequest(BaseModel):
    proposal_name: Optional[str] = None
    customer_id: Optional[int] = None
    proposal_data: Dict[str, Any]  # Full form state as JSON


class SavedProposalResponse(BaseModel):
    id: int
    project_id: int
    customer_id: Optional[int]
    proposal_number: Optional[str]
    proposal_name: Optional[str]
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # Include customer info for display
    customer_company: Optional[str] = None

    class Config:
        from_attributes = True


class BatchProposalRequest(BaseModel):
    """Generate the same proposal for multiple customers."""
    customer_ids: List[int]
    proposal_data: Dict[str, Any]


# ── Save / Load Proposal Endpoints ───────────────────────────

@proposal_router.post("/projects/{project_id}/proposals")
async def save_proposal(project_id: int, request: SaveProposalRequest, db: Session = Depends(get_db)):
    """Save a proposal draft so it can be edited later."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate customer if provided
    if request.customer_id:
        customer = db.query(Customer).filter(Customer.id == request.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

    proposal_number = request.proposal_data.get("proposal_number", f"P-{project_id:04d}")

    saved = SavedProposal(
        project_id=project_id,
        customer_id=request.customer_id,
        proposal_number=proposal_number,
        proposal_name=request.proposal_name or f"Proposal for {project.project_name}",
        proposal_data=json.dumps(request.proposal_data),
        status="draft",
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)

    return {"id": saved.id, "message": "Proposal saved successfully"}


@proposal_router.put("/proposals/{proposal_id}")
async def update_saved_proposal(proposal_id: int, request: SaveProposalRequest, db: Session = Depends(get_db)):
    """Update an existing saved proposal."""
    saved = db.query(SavedProposal).filter(SavedProposal.id == proposal_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved proposal not found")

    if request.customer_id is not None:
        saved.customer_id = request.customer_id
    if request.proposal_name is not None:
        saved.proposal_name = request.proposal_name
    saved.proposal_data = json.dumps(request.proposal_data)
    saved.proposal_number = request.proposal_data.get("proposal_number", saved.proposal_number)

    db.commit()
    db.refresh(saved)

    return {"id": saved.id, "message": "Proposal updated successfully"}


@proposal_router.get("/projects/{project_id}/proposals")
async def list_saved_proposals(project_id: int, db: Session = Depends(get_db)):
    """List all saved proposals for a project."""
    proposals = db.query(SavedProposal).filter(
        SavedProposal.project_id == project_id
    ).order_by(SavedProposal.updated_at.desc()).all()

    result = []
    for p in proposals:
        customer_company = None
        if p.customer_id:
            customer = db.query(Customer).filter(Customer.id == p.customer_id).first()
            if customer:
                customer_company = customer.company_name

        result.append({
            "id": p.id,
            "project_id": p.project_id,
            "customer_id": p.customer_id,
            "proposal_number": p.proposal_number,
            "proposal_name": p.proposal_name,
            "status": p.status,
            "customer_company": customer_company,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        })

    return result


@proposal_router.get("/proposals/{proposal_id}")
async def get_saved_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Get a saved proposal with its full data."""
    saved = db.query(SavedProposal).filter(SavedProposal.id == proposal_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved proposal not found")

    customer_company = None
    if saved.customer_id:
        customer = db.query(Customer).filter(Customer.id == saved.customer_id).first()
        if customer:
            customer_company = customer.company_name

    return {
        "id": saved.id,
        "project_id": saved.project_id,
        "customer_id": saved.customer_id,
        "proposal_number": saved.proposal_number,
        "proposal_name": saved.proposal_name,
        "status": saved.status,
        "customer_company": customer_company,
        "proposal_data": json.loads(saved.proposal_data),
        "created_at": saved.created_at.isoformat(),
        "updated_at": saved.updated_at.isoformat(),
    }


@proposal_router.delete("/proposals/{proposal_id}")
async def delete_saved_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Delete a saved proposal."""
    saved = db.query(SavedProposal).filter(SavedProposal.id == proposal_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved proposal not found")
    db.delete(saved)
    db.commit()
    return {"message": "Proposal deleted successfully"}


@proposal_router.put("/proposals/{proposal_id}/status")
async def update_proposal_status(proposal_id: int, status: str, db: Session = Depends(get_db)):
    """Update proposal status (draft, sent, accepted, declined)."""
    saved = db.query(SavedProposal).filter(SavedProposal.id == proposal_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved proposal not found")
    if status not in ("draft", "sent", "accepted", "declined"):
        raise HTTPException(status_code=400, detail="Invalid status")
    saved.status = status
    db.commit()
    return {"message": f"Proposal status updated to {status}"}


# ── Batch / Multi-Customer Proposal Generation ───────────────

@proposal_router.post("/projects/{project_id}/generate-batch-proposals")
async def generate_batch_proposals(
    project_id: int, request: BatchProposalRequest, db: Session = Depends(get_db)
):
    """
    Generate the same proposal PDF for multiple customers.
    Returns a list of generated PDF download links (saved proposals).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_info = _get_company_info_dict(db)
    results = []

    for customer_id in request.customer_ids:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            results.append({"customer_id": customer_id, "error": "Customer not found"})
            continue

        # Clone proposal data and set this customer's info
        data = dict(request.proposal_data)
        data["prepared_for"] = {
            "company": customer.company_name,
            "contact_name": customer.contact_name or "",
            "contact_email": customer.contact_email or "",
            "contact_phone": customer.contact_phone or "",
        }
        data["project_name"] = data.get("project_name") or project.project_name
        data["project_address"] = data.get("project_address") or project.address or ""
        proposal_num = data.get("proposal_number", f"P-{project_id:04d}")
        data["proposal_number"] = proposal_num
        data["proposal_date"] = data.get("proposal_date") or datetime.date.today().strftime("%B %d, %Y")
        data["company_info"] = data.get("company_info") or company_info
        data["terms"] = data.get("terms") or _get_default_terms(db)

        # Save proposal to DB
        saved = SavedProposal(
            project_id=project_id,
            customer_id=customer_id,
            proposal_number=proposal_num,
            proposal_name=f"Proposal for {customer.company_name}",
            proposal_data=json.dumps(data),
            status="draft",
        )
        db.add(saved)
        db.commit()
        db.refresh(saved)

        results.append({
            "customer_id": customer_id,
            "customer_company": customer.company_name,
            "proposal_id": saved.id,
            "status": "created",
        })

    return {"proposals": results}


@proposal_router.get("/proposals/{proposal_id}/generate-pdf")
async def generate_saved_proposal_pdf(proposal_id: int, db: Session = Depends(get_db)):
    """Generate a PDF from a saved proposal."""
    saved = db.query(SavedProposal).filter(SavedProposal.id == proposal_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved proposal not found")

    project = db.query(Project).filter(Project.id == saved.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data = json.loads(saved.proposal_data)

    # Ensure company_info and terms are filled
    if not data.get("company_info"):
        data["company_info"] = _get_company_info_dict(db)
    if not data.get("terms"):
        data["terms"] = _get_default_terms(db)

    # Fill customer info if linked
    if saved.customer_id and not data.get("prepared_for", {}).get("company"):
        customer = db.query(Customer).filter(Customer.id == saved.customer_id).first()
        if customer:
            data["prepared_for"] = {
                "company": customer.company_name,
                "contact_name": customer.contact_name or "",
                "contact_email": customer.contact_email or "",
                "contact_phone": customer.contact_phone or "",
            }

    try:
        pdf_bytes = generate_proposal_pdf(data)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    filename = f"Proposal_{data.get('proposal_number', 'P-0001')}_{project.project_name.replace(' ', '_')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        }
    )
