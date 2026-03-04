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

from database import get_db
from models import Project
from conditions_models import RoofCondition, EstimateLineItem
from proposal_generator import generate_proposal_pdf


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


# ── Default Company Info ──────────────────────────────────────

DEFAULT_COMPANY_INFO = {
    "name": "ROOF EXPERTS",
    "tagline": "Commercial Roofing Specialists",
    "phone": "(713) 555-0100",
    "email": "Anthony@roofexperts.com",
    "website": "www.roofexperts.com",
    "address": "Houston, TX",
    "license": "Licensed & Insured | Commercial Roofing Contractor",
}


# ── Endpoints ─────────────────────────────────────────────────

@proposal_router.post("/projects/{project_id}/generate-proposal")
async def generate_proposal(project_id: int, request: ProposalRequest, db: Session = Depends(get_db)):
    """Generate a bid proposal PDF for a project."""

    # Look up project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Build the data dict for the PDF generator
    company_info = request.company_info or DEFAULT_COMPANY_INFO

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
        "terms": request.terms if request.terms else [],
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
        "company_info": DEFAULT_COMPANY_INFO,
    }
