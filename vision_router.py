"""
FastAPI endpoints for the AI Vision Plan Reader.
"""

import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from auth import get_current_user
from database import SessionLocal
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction, PlanMarkup
from conditions_models import RoofCondition, EstimateLineItem, ConditionMaterial
from s3_service import upload_file_to_s3, upload_path_to_s3, download_file_from_s3
from vision_ai import run_plan_analysis_background, auto_create_conditions

# Max time an analysis can be "processing" before we consider it stuck
# Base timeout + per-page allowance (large PDFs need more time for GPT-4o calls)
ANALYSIS_TIMEOUT_BASE_MINUTES = 15
ANALYSIS_TIMEOUT_PER_PAGE_MINUTES = 1.5  # ~90 sec per page for classify + extract

router = APIRouter(prefix="/api/v1", tags=["vision-plan-reader"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ExtractionUpdate(BaseModel):
    measurement_value: Optional[float] = None
    measurement_unit: Optional[str] = None
    notes: Optional[str] = None


class MarkupItem(BaseModel):
    page_number: int
    markup_type: str
    data_json: str
    distance_ft: Optional[float] = None
    label: Optional[str] = None


class SaveMarkupsRequest(BaseModel):
    markups: List[MarkupItem]


def _split_pdf_to_pages(file_path: str) -> list:
    """Split a multi-page PDF into individual single-page PDFs.

    Returns a list of dicts: [{"page_number": 1, "path": "/tmp/.../page_1.pdf"}, ...]
    Uses PyMuPDF (fitz) which is already installed for page conversion.
    """
    import fitz
    doc = fitz.open(file_path)
    page_count = len(doc)
    pages = []

    if page_count <= 1:
        # Single page — no splitting needed
        doc.close()
        return [{"page_number": 1, "path": file_path}]

    temp_dir = tempfile.mkdtemp()
    for page_num in range(page_count):
        single_doc = fitz.open()  # New empty PDF
        single_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        page_path = os.path.join(temp_dir, f"page_{page_num + 1}.pdf")
        single_doc.save(page_path)
        single_doc.close()
        pages.append({"page_number": page_num + 1, "path": page_path})

    doc.close()
    return pages


@router.post("/projects/{project_id}/upload-plan")
def upload_plan(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload an architectural roof plan PDF for AI vision analysis.

    Multi-page PDFs are automatically split into individual single-page
    plan files so each page gets its own scale setting and fast viewer.
    """
    allowed_types = [".pdf"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_types)}"
        )

    # Save uploaded file to temp location for splitting
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)
    file.file.seek(0)
    with open(temp_path, "wb") as f:
        f.write(file.file.read())

    # Split into individual pages
    try:
        page_files = _split_pdf_to_pages(temp_path)
    except Exception as split_err:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDF: {str(split_err)[:200]}"
        )

    base_name = os.path.splitext(file.filename)[0]
    total_pages = len(page_files)
    created_plans = []

    for page_info in page_files:
        page_num = page_info["page_number"]
        page_path = page_info["path"]

        # Name: "A300 Roof Plan - Page 1 of 5" (or just the original name for single-page)
        if total_pages == 1:
            display_name = file.filename
        else:
            display_name = f"{base_name} - Page {page_num} of {total_pages}.pdf"

        # Upload this single page to S3
        s3_key = upload_path_to_s3(page_path, project_id, "plans")

        plan_file = RoofPlanFile(
            project_id=project_id,
            file_name=display_name,
            file_type="pdf",
            s3_key=s3_key,
            upload_status="pending",
            page_count=1,  # Each split file is always 1 page
        )
        db.add(plan_file)
        db.commit()
        db.refresh(plan_file)

        # Start analysis in background thread for each page
        thread = threading.Thread(
            target=run_plan_analysis_background,
            args=(project_id, plan_file.id, page_path),
            daemon=False,
        )
        thread.start()

        created_plans.append({
            "plan_file_id": plan_file.id,
            "file_name": display_name,
            "page_number": page_num,
            "status": "pending",
        })

    return {
        "message": f"Plan uploaded and split into {total_pages} page(s). Analysis started.",
        "total_pages": total_pages,
        "plan_files": created_plans,
    }


@router.post("/plan-files/{plan_file_id}/reanalyze")
def reanalyze_plan(
    plan_file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Re-run AI analysis on an existing plan file.

    Downloads the PDF from S3, clears previous analysis results,
    and re-runs the full vision analysis pipeline.
    """
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    # Clear existing extractions and their linked conditions
    extractions = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()

    # Collect condition IDs to delete, then null out FK references first
    condition_ids_to_delete = set()
    for ext in extractions:
        if ext.condition_id:
            condition_ids_to_delete.add(ext.condition_id)
            ext.condition_id = None
    db.flush()  # Null out FKs before deleting

    # Now safe to delete conditions (no more FK references)
    for cid in condition_ids_to_delete:
        # Delete condition materials and estimate line items first (FK children)
        db.query(ConditionMaterial).filter(ConditionMaterial.condition_id == cid).delete()
        db.query(EstimateLineItem).filter(
            EstimateLineItem.condition_id == cid
        ).delete()
        cond = db.query(RoofCondition).filter(RoofCondition.id == cid).first()
        if cond:
            db.delete(cond)

    # Delete the extractions
    for ext in extractions:
        db.delete(ext)

    # Clear existing page analyses
    db.query(PlanPageAnalysis).filter(
        PlanPageAnalysis.plan_file_id == plan_file_id
    ).delete()

    # Reset plan file status
    plan_file.upload_status = "pending"
    plan_file.detected_scale = None
    plan_file.scale_confidence = None
    plan_file.error_message = None
    db.commit()

    # Download file from S3 to temp location
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, plan_file.file_name)
    with open(temp_path, "wb") as f:
        download_file_from_s3(plan_file.s3_key, f)

    project_id = plan_file.project_id

    thread = threading.Thread(
        target=run_plan_analysis_background,
        args=(project_id, plan_file.id, temp_path),
        daemon=False,
    )
    thread.start()

    return {
        "message": "Re-analysis started in background.",
        "plan_file_id": plan_file.id,
        "status": "pending",
    }


@router.get("/projects/{project_id}/plan-files")
def list_plan_files(project_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """List all uploaded plan files for a project."""
    plans = db.query(RoofPlanFile).filter(
        RoofPlanFile.project_id == project_id
    ).order_by(RoofPlanFile.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "project_id": p.project_id,
            "file_name": p.file_name,
            "file_type": p.file_type,
            "upload_status": p.upload_status,
            "page_count": p.page_count,
            "detected_scale": p.detected_scale,
            "scale_confidence": p.scale_confidence,
            "manual_scale": p.manual_scale,
            "manual_scale_ratio": p.manual_scale_ratio,
            "error_message": p.error_message,
            "created_at": str(p.created_at) if p.created_at else None,
        }
        for p in plans
    ]


@router.get("/plan-files/{plan_file_id}")
def get_plan_file(plan_file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get plan file details including pages and extractions."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    pages = db.query(PlanPageAnalysis).filter(
        PlanPageAnalysis.plan_file_id == plan_file_id
    ).order_by(PlanPageAnalysis.page_number).all()

    extractions = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()

    return {
        "plan_file": {
            "id": plan_file.id,
            "project_id": plan_file.project_id,
            "file_name": plan_file.file_name,
            "file_type": plan_file.file_type,
            "upload_status": plan_file.upload_status,
            "page_count": plan_file.page_count,
            "detected_scale": plan_file.detected_scale,
            "scale_confidence": plan_file.scale_confidence,
            "error_message": plan_file.error_message,
        },
        "pages": [{"id": p.id, "page_number": p.page_number, "page_type": p.page_type,
                    "is_roof_relevant": p.is_roof_relevant, "processing_status": p.processing_status}
                   for p in pages],
        "extractions": [{"id": e.id, "extraction_type": e.extraction_type,
                         "measurement_value": e.measurement_value, "measurement_unit": e.measurement_unit,
                         "confidence_score": e.confidence_score, "source_description": e.source_description,
                         "location_on_plan": e.location_on_plan, "notes": e.notes,
                         "condition_id": e.condition_id} for e in extractions],
    }


@router.get("/plan-files/{plan_file_id}/extractions")
def get_extractions(plan_file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """List all extracted measurements for a plan file."""
    return db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()


@router.put("/extractions/{extraction_id}")
def update_extraction(extraction_id: int, update: ExtractionUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Edit an extracted measurement. User can override AI-detected values."""
    extraction = db.query(VisionExtraction).filter(VisionExtraction.id == extraction_id).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    if update.measurement_value is not None:
        extraction.measurement_value = update.measurement_value
    if update.measurement_unit is not None:
        extraction.measurement_unit = update.measurement_unit
    if update.notes is not None:
        extraction.notes = update.notes

    # Also update linked condition if it exists
    if extraction.condition_id:
        condition = db.query(RoofCondition).filter(RoofCondition.id == extraction.condition_id).first()
        if condition:
            if update.measurement_value is not None:
                condition.measurement_value = update.measurement_value
            if update.measurement_unit is not None:
                condition.measurement_unit = update.measurement_unit

    db.commit()
    db.refresh(extraction)

    return {"message": "Extraction updated", "extraction_id": extraction.id,
            "measurement_value": extraction.measurement_value,
            "measurement_unit": extraction.measurement_unit}


@router.delete("/extractions/{extraction_id}")
def delete_extraction(extraction_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Delete an extraction and its linked condition."""
    extraction = db.query(VisionExtraction).filter(VisionExtraction.id == extraction_id).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    if extraction.condition_id:
        condition = db.query(RoofCondition).filter(RoofCondition.id == extraction.condition_id).first()
        if condition:
            db.delete(condition)

    db.delete(extraction)
    db.commit()
    return {"message": "Extraction and linked condition deleted", "extraction_id": extraction_id}


@router.post("/plan-files/{plan_file_id}/regenerate-conditions")
def regenerate_conditions(plan_file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Re-create conditions from current extractions after edits."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    extractions = db.query(VisionExtraction).filter(VisionExtraction.plan_file_id == plan_file_id).all()
    for ext in extractions:
        if ext.condition_id:
            old_cond = db.query(RoofCondition).filter(RoofCondition.id == ext.condition_id).first()
            if old_cond:
                db.delete(old_cond)
            ext.condition_id = None
    db.commit()

    created_ids = auto_create_conditions(plan_file.project_id, plan_file_id, db)
    return {"message": f"Regenerated {len(created_ids)} conditions",
            "conditions_created": len(created_ids),
            "condition_ids": created_ids}


@router.get("/plan-files/{plan_file_id}/status")
def check_analysis_status(plan_file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Quick status check for plan analysis progress.

    Auto-detects stuck analyses: if status has been 'processing' for longer
    than ANALYSIS_TIMEOUT_MINUTES, automatically resets to 'failed'.
    """
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    # Auto-detect stuck analysis (covers both "processing" and "pending" states)
    if plan_file.upload_status in ("processing", "pending"):
        # Use updated_at if available, fall back to created_at
        check_time = plan_file.updated_at or plan_file.created_at
        if check_time:
            now = datetime.now(timezone.utc)
            if check_time.tzinfo is None:
                check_time = check_time.replace(tzinfo=timezone.utc)
            elapsed = now - check_time
            # Scale timeout based on page count (large PDFs need more time)
            page_count = plan_file.page_count or 10  # assume 10 if unknown
            timeout_mins = ANALYSIS_TIMEOUT_BASE_MINUTES + (page_count * ANALYSIS_TIMEOUT_PER_PAGE_MINUTES)
            if plan_file.upload_status == "pending":
                timeout_mins += 2  # extra grace for pending
            if elapsed > timedelta(minutes=timeout_mins):
                old_status = plan_file.upload_status
                plan_file.upload_status = "failed"
                plan_file.error_message = f"Analysis timed out (was '{old_status}' for {elapsed.total_seconds() / 60:.0f} min). Click Re-Analyze to try again."
                db.commit()
                print(f"[Vision] Auto-reset stuck analysis for plan_file {plan_file_id} (was {old_status} for {elapsed})")

    extraction_count = db.query(VisionExtraction).filter(VisionExtraction.plan_file_id == plan_file_id).count()
    condition_count = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id, VisionExtraction.condition_id.isnot(None)).count()

    # Separate progress messages (during processing) from real errors (on failure)
    error_msg = plan_file.error_message
    progress_msg = None
    if plan_file.upload_status == "processing" and error_msg and not error_msg.startswith("Analysis timed out"):
        progress_msg = error_msg
        error_msg = None

    return {"plan_file_id": plan_file_id, "status": plan_file.upload_status,
            "page_count": plan_file.page_count, "detected_scale": plan_file.detected_scale,
            "extractions_count": extraction_count, "conditions_created": condition_count,
            "error_message": error_msg, "progress_message": progress_msg}


@router.get("/plan-files/{plan_file_id}/debug")
def debug_plan_file(
    plan_file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Debug endpoint: shows all raw analysis data for a plan file."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    pages = db.query(PlanPageAnalysis).filter(
        PlanPageAnalysis.plan_file_id == plan_file_id
    ).order_by(PlanPageAnalysis.page_number).all()

    extractions = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()

    return {
        "plan_file": {
            "id": plan_file.id,
            "file_name": plan_file.file_name,
            "upload_status": plan_file.upload_status,
            "page_count": plan_file.page_count,
            "detected_scale": plan_file.detected_scale,
            "scale_confidence": plan_file.scale_confidence,
            "manual_scale": plan_file.manual_scale,
            "manual_scale_ratio": plan_file.manual_scale_ratio,
            "error_message": plan_file.error_message,
            "s3_key": plan_file.s3_key,
        },
        "pages": [
            {
                "page_number": p.page_number,
                "page_type": p.page_type,
                "is_roof_relevant": p.is_roof_relevant,
                "processing_status": p.processing_status,
                "analysis_json": p.analysis_json,
            }
            for p in pages
        ],
        "extractions": [
            {
                "id": e.id,
                "page_number": e.page_number,
                "extraction_type": e.extraction_type,
                "measurement_value": e.measurement_value,
                "measurement_unit": e.measurement_unit,
                "confidence_score": e.confidence_score,
                "source_description": e.source_description,
                "notes": e.notes,
            }
            for e in extractions
        ],
    }


@router.get("/vision-version")
def vision_version():
    """Returns the deployed code version for verification."""
    return {"version": "v13-debug-diagnostics", "commit": "pending"}


@router.get("/vision-health")
def vision_health_check(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Diagnostic endpoint to check if the vision analysis pipeline is configured correctly."""
    import importlib
    checks = {}

    # Check OpenAI API key
    openai_key = os.getenv("OPENAI_API_KEY")
    checks["openai_api_key"] = "set" if openai_key else "MISSING"

    # Check required libraries
    for lib_name in ["fitz", "PIL", "openai"]:
        try:
            importlib.import_module(lib_name)
            checks[f"lib_{lib_name}"] = "ok"
        except ImportError:
            checks[f"lib_{lib_name}"] = "MISSING"

    # Check S3 config
    checks["aws_bucket"] = "set" if os.getenv("AWS_BUCKET_NAME") else "MISSING"
    checks["aws_region"] = "set" if os.getenv("AWS_REGION") else "MISSING"
    checks["aws_access_key"] = "set" if os.getenv("AWS_ACCESS_KEY_ID") else "MISSING"

    # Check for stuck plan files
    from sqlalchemy import func
    stuck_processing = db.query(RoofPlanFile).filter(RoofPlanFile.upload_status == "processing").count()
    stuck_pending = db.query(RoofPlanFile).filter(RoofPlanFile.upload_status == "pending").count()
    total_plans = db.query(RoofPlanFile).count()
    completed_plans = db.query(RoofPlanFile).filter(RoofPlanFile.upload_status == "completed").count()
    failed_plans = db.query(RoofPlanFile).filter(RoofPlanFile.upload_status == "failed").count()

    # Check material templates
    from conditions_models import MaterialTemplate
    global_templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.is_global == True,
        MaterialTemplate.sort_order > 0
    ).count()

    checks["plans_total"] = total_plans
    checks["plans_completed"] = completed_plans
    checks["plans_failed"] = failed_plans
    checks["plans_stuck_processing"] = stuck_processing
    checks["plans_stuck_pending"] = stuck_pending
    checks["global_templates_with_sort_order"] = global_templates

    all_ok = (
        checks["openai_api_key"] == "set" and
        checks["lib_fitz"] == "ok" and
        checks["lib_PIL"] == "ok" and
        checks["lib_openai"] == "ok" and
        checks["aws_bucket"] == "set"
    )

    return {"status": "healthy" if all_ok else "issues_found", "checks": checks}


@router.post("/plan-files/{plan_file_id}/reset-status")
def reset_analysis_status(plan_file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Manually reset a stuck plan file analysis status.

    Use this when an analysis is stuck in 'processing' state and won't complete.
    Resets the status to 'failed' so the user can re-analyze.
    """
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    old_status = plan_file.upload_status
    plan_file.upload_status = "failed"
    plan_file.error_message = f"Analysis manually reset (was: {old_status}). Click Re-Analyze to try again."
    db.commit()

    return {
        "message": f"Status reset from '{old_status}' to 'failed'",
        "plan_file_id": plan_file_id,
        "previous_status": old_status,
        "new_status": "failed",
    }


# Common architectural scales for the dropdown
COMMON_SCALES = [
    {"label": "1/16\" = 1'-0\"", "notation": "1/16 inch = 1 foot", "ratio": 192},
    {"label": "3/32\" = 1'-0\"", "notation": "3/32 inch = 1 foot", "ratio": 128},
    {"label": "1/8\" = 1'-0\"", "notation": "1/8 inch = 1 foot", "ratio": 96},
    {"label": "3/16\" = 1'-0\"", "notation": "3/16 inch = 1 foot", "ratio": 64},
    {"label": "1/4\" = 1'-0\"", "notation": "1/4 inch = 1 foot", "ratio": 48},
    {"label": "3/8\" = 1'-0\"", "notation": "3/8 inch = 1 foot", "ratio": 32},
    {"label": "1/2\" = 1'-0\"", "notation": "1/2 inch = 1 foot", "ratio": 24},
    {"label": "3/4\" = 1'-0\"", "notation": "3/4 inch = 1 foot", "ratio": 16},
    {"label": "1\" = 1'-0\"", "notation": "1 inch = 1 foot", "ratio": 12},
]


class ScaleOverrideRequest(BaseModel):
    scale_notation: Optional[str] = None  # e.g., "3/16 inch = 1 foot"
    scale_ratio: Optional[float] = None   # e.g., 64
    clear: Optional[bool] = False         # Set True to remove manual override


@router.put("/plan-files/{plan_file_id}/scale")
def set_plan_scale(
    plan_file_id: int,
    body: ScaleOverrideRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Set or clear a manual scale override for a plan file.
    When set, this overrides the AI-detected scale for all measurements.
    """
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    if body.clear:
        plan_file.manual_scale = None
        plan_file.manual_scale_ratio = None
        db.commit()
        return {"message": "Manual scale cleared", "plan_file_id": plan_file_id,
                "manual_scale": None, "detected_scale": plan_file.detected_scale}

    if not body.scale_notation and not body.scale_ratio:
        raise HTTPException(status_code=400, detail="Provide scale_notation and/or scale_ratio")

    plan_file.manual_scale = body.scale_notation
    plan_file.manual_scale_ratio = body.scale_ratio
    db.commit()

    return {
        "message": "Manual scale set",
        "plan_file_id": plan_file_id,
        "manual_scale": plan_file.manual_scale,
        "manual_scale_ratio": plan_file.manual_scale_ratio,
        "detected_scale": plan_file.detected_scale,
    }


@router.get("/common-scales")
def get_common_scales():
    """Return the list of common architectural scales for the UI dropdown."""
    return COMMON_SCALES


@router.delete("/plan-files/{plan_file_id}")
def delete_plan_file(
    plan_file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a plan file and all its associated data (extractions, pages, markups, linked conditions)."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    # Delete linked conditions (via extractions)
    extractions = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()
    condition_ids_to_delete = set()
    for ext in extractions:
        if ext.condition_id:
            condition_ids_to_delete.add(ext.condition_id)
            ext.condition_id = None
    db.flush()

    for cid in condition_ids_to_delete:
        db.query(ConditionMaterial).filter(ConditionMaterial.condition_id == cid).delete()
        db.query(EstimateLineItem).filter(EstimateLineItem.condition_id == cid).delete()
        cond = db.query(RoofCondition).filter(RoofCondition.id == cid).first()
        if cond:
            db.delete(cond)

    # Delete extractions, page analyses, markups
    for ext in extractions:
        db.delete(ext)
    db.query(PlanPageAnalysis).filter(PlanPageAnalysis.plan_file_id == plan_file_id).delete()
    db.query(PlanMarkup).filter(PlanMarkup.plan_file_id == plan_file_id).delete()

    # Try to delete S3 file (non-fatal if it fails)
    try:
        from s3_service import delete_file_from_s3
        delete_file_from_s3(plan_file.s3_key)
    except Exception:
        pass  # S3 cleanup is best-effort

    db.delete(plan_file)
    db.commit()

    return {"message": "Plan file deleted", "plan_file_id": plan_file_id}


# ============================================================================
# PLAN MARKUPS / MEASUREMENTS
# ============================================================================

@router.post("/plan-files/{plan_file_id}/markups")
def save_markups(
    plan_file_id: int,
    data: SaveMarkupsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save user-drawn markups and measurements for a plan file."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")

    created = []
    for item in data.markups:
        markup = PlanMarkup(
            plan_file_id=plan_file_id,
            page_number=item.page_number,
            markup_type=item.markup_type,
            data_json=item.data_json,
            distance_ft=item.distance_ft,
            label=item.label,
            created_by=current_user["user_id"],
        )
        db.add(markup)
        db.flush()
        created.append(markup.id)

    db.commit()
    return {"message": f"Saved {len(created)} markups", "markup_ids": created}


@router.get("/plan-files/{plan_file_id}/markups")
def get_markups(
    plan_file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get all markups for a plan file."""
    markups = db.query(PlanMarkup).filter(
        PlanMarkup.plan_file_id == plan_file_id
    ).order_by(PlanMarkup.page_number, PlanMarkup.created_at).all()

    return [
        {
            "id": m.id,
            "page_number": m.page_number,
            "markup_type": m.markup_type,
            "data_json": m.data_json,
            "distance_ft": m.distance_ft,
            "label": m.label,
            "created_by": m.created_by,
            "created_at": str(m.created_at),
        }
        for m in markups
    ]


@router.delete("/markups/{markup_id}")
def delete_markup(
    markup_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a specific markup."""
    markup = db.query(PlanMarkup).filter(PlanMarkup.id == markup_id).first()
    if not markup:
        raise HTTPException(status_code=404, detail="Markup not found")
    db.delete(markup)
    db.commit()
    return {"message": "Markup deleted", "id": markup_id}
