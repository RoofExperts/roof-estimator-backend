"""
Condition-Based Commercial Roofing Estimating Engine - FastAPI Routes

This module provides all API endpoints for:
- Managing roof conditions (CRUD)
- Managing material templates (CRUD)
- Managing the cost database (CRUD)
- Calculating estimates
- Retrieving estimate summaries
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pydantic import BaseModel
import datetime
import csv
import io

from database import SessionLocal
from auth import get_current_user
from conditions_models import (
    RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem
)
from models import SavedEstimate
from estimate_engine import calculate_estimate, get_estimate_summary
from estimate_engine import get_available_condition_types, get_materials_for_condition
from condition_builder import smart_build_conditions
from takeoff_engine import generate_takeoff


# ============================================================================
# DEPENDENCY: GET DATABASE SESSION
# ============================================================================

def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class RoofConditionCreate(BaseModel):
    """Schema for creating a roof condition."""
    condition_type: str
    description: Optional[str] = None
    measurement_value: float
    measurement_unit: str = "sqft"
    wind_zone: Optional[str] = None


class RoofConditionUpdate(BaseModel):
    """Schema for updating a roof condition."""
    condition_type: Optional[str] = None
    description: Optional[str] = None
    measurement_value: Optional[float] = None
    measurement_unit: Optional[str] = None
    wind_zone: Optional[str] = None


class RoofConditionResponse(BaseModel):
    """Schema for roof condition response."""
    id: int
    project_id: int
    condition_type: str
    description: Optional[str]
    measurement_value: float
    measurement_unit: str
    wind_zone: Optional[str]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class MaterialTemplateCreate(BaseModel):
    """Schema for creating a material template."""
    system_type: str = "common"
    condition_type: str
    material_name: str
    material_category: str
    unit: str
    coverage_rate: float
    waste_factor: float = 0.10
    is_active: bool = True


class MaterialTemplateUpdate(BaseModel):
    """Schema for updating a material template."""
    coverage_rate: Optional[float] = None
    waste_factor: Optional[float] = None
    is_active: Optional[bool] = None


class MaterialTemplateResponse(BaseModel):
    """Schema for material template response."""
    id: int
    system_type: str
    condition_type: str
    material_name: str
    material_category: str
    unit: str
    coverage_rate: float
    waste_factor: float
    is_active: bool
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class CostDatabaseItemCreate(BaseModel):
    """Schema for creating a cost database item."""
    material_name: str
    manufacturer: Optional[str] = None
    material_category: str
    unit: str
    unit_cost: float
    labor_cost_per_unit: Optional[float] = None
    is_active: bool = True


class CostDatabaseItemUpdate(BaseModel):
    """Schema for updating a cost database item."""
    unit_cost: Optional[float] = None
    labor_cost_per_unit: Optional[float] = None
    is_active: Optional[bool] = None


class CostDatabaseItemResponse(BaseModel):
    """Schema for cost database item response."""
    id: int
    material_name: str
    manufacturer: Optional[str]
    material_category: str
    unit: str
    unit_cost: float
    labor_cost_per_unit: Optional[float]
    last_updated: datetime.datetime
    is_active: bool

    class Config:
        from_attributes = True


class EstimateLineItemResponse(BaseModel):
    """Schema for estimate line item response."""
    id: int
    project_id: int
    condition_id: int
    material_name: str
    material_category: str
    quantity: float
    unit: str
    unit_cost: float
    total_cost: float
    notes: Optional[str]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


# ============================================================================
# CREATE ROUTER
# ============================================================================

router = APIRouter(prefix="/api/v1", tags=["roofing-estimate"])


# ============================================================================
# ROOF CONDITION ENDPOINTS
# ============================================================================

@router.post("/projects/{project_id}/conditions", response_model=RoofConditionResponse)
def create_condition(
    project_id: int,
    condition: RoofConditionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add a new roof condition to a project."""
    roof_condition = RoofCondition(
        project_id=project_id,
        condition_type=condition.condition_type,
        description=condition.description,
        measurement_value=condition.measurement_value,
        measurement_unit=condition.measurement_unit,
        wind_zone=condition.wind_zone
    )
    db.add(roof_condition)
    db.commit()
    db.refresh(roof_condition)
    return roof_condition


@router.get("/projects/{project_id}/conditions", response_model=List[RoofConditionResponse])
def list_conditions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all conditions for a project."""
    conditions = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id
    ).all()
    return conditions


@router.get("/conditions/{condition_id}", response_model=RoofConditionResponse)
def get_condition(
    condition_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific roof condition by ID."""
    condition = db.query(RoofCondition).filter(
        RoofCondition.id == condition_id
    ).first()
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")
    return condition


@router.put("/conditions/{condition_id}", response_model=RoofConditionResponse)
def update_condition(
    condition_id: int,
    condition: RoofConditionUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update an existing roof condition."""
    db_condition = db.query(RoofCondition).filter(
        RoofCondition.id == condition_id
    ).first()
    if not db_condition:
        raise HTTPException(status_code=404, detail="Condition not found")
    
    if condition.condition_type is not None:
        db_condition.condition_type = condition.condition_type
    if condition.description is not None:
        db_condition.description = condition.description
    if condition.measurement_value is not None:
        db_condition.measurement_value = condition.measurement_value
    if condition.measurement_unit is not None:
        db_condition.measurement_unit = condition.measurement_unit
    if condition.wind_zone is not None:
        db_condition.wind_zone = condition.wind_zone
    
    db.commit()
    db.refresh(db_condition)
    return db_condition


@router.delete("/conditions/{condition_id}")
def delete_condition(
    condition_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a roof condition. Also deletes associated line items."""
    db_condition = db.query(RoofCondition).filter(
        RoofCondition.id == condition_id
    ).first()
    if not db_condition:
        raise HTTPException(status_code=404, detail="Condition not found")
    
    db.query(EstimateLineItem).filter(
        EstimateLineItem.condition_id == condition_id
    ).delete()
    
    db.delete(db_condition)
    db.commit()
    return {"message": "Condition deleted successfully"}


# ============================================================================
# ESTIMATE CALCULATION ENDPOINTS
# ============================================================================

@router.post("/projects/{project_id}/calculate-estimate")
def calculate_project_estimate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Calculate the complete estimate for a project."""
    result = calculate_estimate(project_id, db)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("/projects/{project_id}/estimate")
def get_project_estimate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get the full estimate summary for a project."""
    result = get_estimate_summary(project_id, db)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ============================================================================
# MATERIAL TEMPLATE ENDPOINTS
# ============================================================================

@router.post("/material-templates", response_model=MaterialTemplateResponse)
def create_material_template(
    template: MaterialTemplateCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new material template."""
    db_template = MaterialTemplate(
        system_type=template.system_type,
        condition_type=template.condition_type,
        material_name=template.material_name,
        material_category=template.material_category,
        unit=template.unit,
        coverage_rate=template.coverage_rate,
        waste_factor=template.waste_factor,
        is_active=template.is_active,
        org_id=current_user["org_id"]
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


@router.get("/material-templates", response_model=List[MaterialTemplateResponse])
def list_material_templates(
    condition_type: Optional[str] = Query(None),
    system_type: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List material templates with optional filtering by condition_type and system_type."""
    query = db.query(MaterialTemplate).filter(
        MaterialTemplate.is_active == is_active,
        or_(MaterialTemplate.org_id == current_user["org_id"], MaterialTemplate.is_global == True)
    )
    if condition_type:
        query = query.filter(MaterialTemplate.condition_type == condition_type)
    if system_type:
        query = query.filter(or_(
            MaterialTemplate.system_type == system_type,
            MaterialTemplate.system_type == "common"
        ))
    return query.all()


@router.get("/material-templates/{template_id}", response_model=MaterialTemplateResponse)
def get_material_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific material template by ID."""
    template = db.query(MaterialTemplate).filter(MaterialTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/material-templates/{template_id}", response_model=MaterialTemplateResponse)
def update_material_template(
    template_id: int,
    template: MaterialTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update an existing material template."""
    db_template = db.query(MaterialTemplate).filter(
        MaterialTemplate.id == template_id,
        MaterialTemplate.org_id == current_user["org_id"]
    ).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.coverage_rate is not None:
        db_template.coverage_rate = template.coverage_rate
    if template.waste_factor is not None:
        db_template.waste_factor = template.waste_factor
    if template.is_active is not None:
        db_template.is_active = template.is_active
    db.commit()
    db.refresh(db_template)
    return db_template


@router.delete("/material-templates/{template_id}")
def delete_material_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a material template (soft delete)."""
    db_template = db.query(MaterialTemplate).filter(
        MaterialTemplate.id == template_id,
        MaterialTemplate.org_id == current_user["org_id"]
    ).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    db_template.is_active = False
    db.commit()
    return {"message": "Template deleted successfully"}


# ============================================================================
# COST DATABASE ENDPOINTS
# ============================================================================

@router.post("/cost-database", response_model=CostDatabaseItemResponse)
def create_cost_item(
    item: CostDatabaseItemCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add a new item to the cost database."""
    db_item = CostDatabaseItem(
        material_name=item.material_name,
        manufacturer=item.manufacturer,
        material_category=item.material_category,
        unit=item.unit,
        unit_cost=item.unit_cost,
        labor_cost_per_unit=item.labor_cost_per_unit,
        is_active=item.is_active,
        org_id=current_user["org_id"]
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/cost-database", response_model=List[CostDatabaseItemResponse])
def list_cost_items(
    material_category: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List cost database items with optional filtering."""
    query = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.is_active == is_active,
        or_(CostDatabaseItem.org_id == current_user["org_id"], CostDatabaseItem.is_global == True)
    )
    if material_category:
        query = query.filter(CostDatabaseItem.material_category == material_category)
    return query.order_by(CostDatabaseItem.material_name).all()


@router.post("/cost-database/upload-pricing")
def upload_pricing_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload vendor pricing from CSV or Excel file.

    Expected columns:
    - material_name (required): Name of material to match
    - unit_cost (required): Cost per unit
    - labor_cost_per_unit (optional): Labor cost per unit
    - manufacturer (optional): Manufacturer name

    Matches materials by case-insensitive partial match of material_name.
    Returns summary of matched/unmatched items and update counts.
    """
    try:
        # Read file content
        content = file.file.read()
        filename = file.filename.lower()

        rows = []

        # Parse CSV or Excel
        if filename.endswith('.csv'):
            # Parse CSV
            text_content = content.decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(text_content))
            rows = list(csv_reader)
        elif filename.endswith(('.xlsx', '.xls')):
            # Parse Excel
            try:
                import openpyxl
            except ImportError:
                raise HTTPException(
                    status_code=400,
                    detail="Excel support requires openpyxl. Please upload a CSV file instead or install openpyxl."
                )

            from openpyxl import load_workbook
            workbook = load_workbook(io.BytesIO(content))
            worksheet = workbook.active

            # Get headers from first row
            headers = []
            for cell in worksheet[1]:
                headers.append(cell.value)

            # Read data rows
            for row in worksheet.iter_rows(min_row=2, values_only=False):
                row_data = {}
                for idx, cell in enumerate(row):
                    if idx < len(headers):
                        row_data[headers[idx]] = cell.value
                rows.append(row_data)
        else:
            raise HTTPException(
                status_code=400,
                detail="File must be CSV or Excel (.csv, .xlsx, .xls)"
            )

        if not rows:
            raise HTTPException(status_code=400, detail="File is empty")

        # Process rows
        matched = 0
        updated = 0
        unmatched_items = []

        for row in rows:
            if not row:
                continue

            # Extract required fields
            material_name = row.get('material_name') or row.get('Material Name')
            unit_cost = row.get('unit_cost') or row.get('Unit Cost')

            if not material_name or unit_cost is None:
                continue

            # Convert unit_cost to float
            try:
                unit_cost = float(unit_cost)
            except (ValueError, TypeError):
                unmatched_items.append(str(material_name))
                continue

            # Get optional fields
            labor_cost_per_unit = row.get('labor_cost_per_unit') or row.get('Labor Cost Per Unit')
            if labor_cost_per_unit is not None:
                try:
                    labor_cost_per_unit = float(labor_cost_per_unit)
                except (ValueError, TypeError):
                    labor_cost_per_unit = None

            # Find matching CostDatabaseItem by case-insensitive partial match
            matching_item = db.query(CostDatabaseItem).filter(
                CostDatabaseItem.material_name.ilike(f'%{material_name}%'),
                CostDatabaseItem.org_id == current_user["org_id"]
            ).first()

            if matching_item:
                matched += 1
                # Update the item
                matching_item.unit_cost = unit_cost
                if labor_cost_per_unit is not None:
                    matching_item.labor_cost_per_unit = labor_cost_per_unit
                matching_item.last_updated = datetime.datetime.utcnow()
                updated += 1
            else:
                unmatched_items.append(str(material_name))

        db.commit()

        return {
            "total_rows": len(rows),
            "matched": matched,
            "updated": updated,
            "unmatched_items": unmatched_items
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


@router.get("/cost-database/{item_id}", response_model=CostDatabaseItemResponse)
def get_cost_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific cost database item by ID."""
    item = db.query(CostDatabaseItem).filter(CostDatabaseItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cost item not found")
    return item


@router.put("/cost-database/{item_id}", response_model=CostDatabaseItemResponse)
def update_cost_item(
    item_id: int,
    item: CostDatabaseItemUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update an existing cost database item."""
    db_item = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.id == item_id,
        CostDatabaseItem.org_id == current_user["org_id"]
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cost item not found")
    if item.unit_cost is not None:
        db_item.unit_cost = item.unit_cost
    if item.labor_cost_per_unit is not None:
        db_item.labor_cost_per_unit = item.labor_cost_per_unit
    if item.is_active is not None:
        db_item.is_active = item.is_active
    db_item.last_updated = datetime.datetime.utcnow()
    db.commit()
    db.refresh(db_item)
    return db_item


@router.delete("/cost-database/{item_id}")
def delete_cost_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a cost database item (soft delete)."""
    db_item = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.id == item_id,
        CostDatabaseItem.org_id == current_user["org_id"]
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cost item not found")
    db_item.is_active = False
    db_item.last_updated = datetime.datetime.utcnow()
    db.commit()
    return {"message": "Cost item deleted successfully"}


# ============================================================================
# REFERENCE DATA ENDPOINTS
# ============================================================================

@router.get("/reference/condition-types")
def get_condition_types(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get all available condition types that have active material templates."""
    types = get_available_condition_types(db)
    return {"condition_types": types}


@router.get("/reference/condition-types/{condition_type}/materials")
def get_condition_materials(
    condition_type: str,
    system_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get all materials available for a specific condition type, optionally filtered by system."""
    materials = get_materials_for_condition(condition_type, db, system_type=system_type)
    return {"condition_type": condition_type, "system_type": system_type, "materials": materials}


# ============================================================================
# SMART BUILD ENDPOINT
# ============================================================================

@router.post("/projects/{project_id}/smart-build-conditions")
def smart_build(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Intelligently build conditions from spec analysis + plan extractions.

    This endpoint:
    1. Reads the project's spec analysis to determine system type (TPO/EPDM/PVC)
    2. Sets project.system_type automatically
    3. Reads all plan extractions (from AI vision)
    4. Creates conditions with spec-enriched descriptions
    5. Auto-estimates perimeter if not found in plans
    6. Returns the full build result

    Call this AFTER both spec analysis and plan analysis are complete.
    """
    result = smart_build_conditions(project_id, db)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ============================================================================
# TAKEOFF ENDPOINT
# ============================================================================

@router.get("/projects/{project_id}/takeoff")
def get_takeoff(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a professional material takeoff from conditions + spec data.

    Returns structured data matching a 4-tab spreadsheet:
    1. Project Summary - system specs, area, cost totals
    2. Flat Roof Materials - membrane, insulation, fasteners, wall flashing
    3. Roof Related Metals - drainage, gutters, coping
    4. Labor & General Conditions - crew labor, equipment, permits

    Each line item has: description, qty, unit, unit_cost, extended_cost
    """
    result = generate_takeoff(project_id, db)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ============================================================================
# SAVED ESTIMATES — PERSIST & LOAD TAKEOFF DATA
# ============================================================================

class SaveEstimateRequest(BaseModel):
    estimate_data: dict


@router.post("/projects/{project_id}/save-estimate")
def save_estimate(
    project_id: int,
    body: SaveEstimateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Save (or update) the takeoff/estimate for a project.
    Upserts — one saved estimate per project (latest version wins).
    """
    import json
    org_id = current_user["org_id"]
    data = body.estimate_data

    # Extract key summary fields for quick access
    grand_total = None
    system_type = None
    roof_area_sf = None
    summary = data.get("summary", {})
    if summary:
        cost_summary = summary.get("cost_summary", {})
        grand_total = cost_summary.get("grand_total")
        system_type = summary.get("system_type")
        roof_area_sf = summary.get("roof_area_sf")

    # Check for existing saved estimate
    existing = db.query(SavedEstimate).filter(
        SavedEstimate.project_id == project_id,
        SavedEstimate.org_id == org_id,
    ).first()

    if existing:
        existing.estimate_data = json.dumps(data)
        existing.grand_total = grand_total
        existing.system_type = system_type
        existing.roof_area_sf = roof_area_sf
        existing.version = (existing.version or 1) + 1
        existing.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return {
            "message": "Estimate updated",
            "id": existing.id,
            "version": existing.version,
            "grand_total": existing.grand_total,
        }
    else:
        saved = SavedEstimate(
            org_id=org_id,
            project_id=project_id,
            version=1,
            estimate_data=json.dumps(data),
            grand_total=grand_total,
            system_type=system_type,
            roof_area_sf=roof_area_sf,
            created_by=current_user["user_id"],
        )
        db.add(saved)
        db.commit()
        db.refresh(saved)
        return {
            "message": "Estimate saved",
            "id": saved.id,
            "version": saved.version,
            "grand_total": saved.grand_total,
        }


@router.get("/projects/{project_id}/saved-estimate")
def get_saved_estimate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Load the saved estimate for a project (if any)."""
    import json
    org_id = current_user["org_id"]

    saved = db.query(SavedEstimate).filter(
        SavedEstimate.project_id == project_id,
        SavedEstimate.org_id == org_id,
    ).first()

    if not saved:
        return {"saved": False}

    return {
        "saved": True,
        "id": saved.id,
        "version": saved.version,
        "grand_total": saved.grand_total,
        "system_type": saved.system_type,
        "roof_area_sf": saved.roof_area_sf,
        "updated_at": str(saved.updated_at),
        "estimate_data": json.loads(saved.estimate_data),
    }
