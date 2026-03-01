"""
FastAPI endpoints for the AI Vision Plan Reader.
"""
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import SessionLocal
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction
from conditions_models import RoofCondition
from s3_service import upload_file_to_s3
from vision_ai import run_plan_analysis_background, auto_create_conditions

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


@router.post("/projects/{project_id}/upload-plan")
def upload_plan(
    project_id: int,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Upload an architectural roof plan PDF for AI vision analysis."""
    allowed_types = [".pdf"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_types)}"
        )

    s3_key = upload_file_to_s3(file, project_id, "plans")

    plan_file = RoofPlanFile(
        project_id=project_id,
        file_name=file.filename,
        file_type=file_ext.replace(".", ""),
        s3_key=s3_key,
        upload_status="pending",
    )
    db.add(plan_file)
    db.commit()
    db.refresh(plan_file)

    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)
    file.file.seek(0)
    with open(temp_path, "wb") as f:
        f.write(file.file.read())

    if background_tasks:
        background_tasks.add_task(
            run_plan_analysis_background,
            project_id, plan_file.id, temp_path,
        )
    else:
        from vision_ai import run_plan_analysis
        run_plan_analysis(project_id, plan_file.id, temp_path, db)

    return {
        "message": "Plan uploaded. Analysis started in background.",
        "plan_file_id": plan_file.id,
        "status": plan_file.upload_status,
        "file_name": file.filename,
    }


@router.get("/projects/{project_id}/plan-files")
def list_plan_files(project_id: int, db: Session = Depends(get_db)):
    """List all uploaded plan files for a project."""
    return db.query(RoofPlanFile).filter(
        RoofPlanFile.project_id == project_id
    ).order_by(RoofPlanFile.created_at.desc()).all()


@router.get("/plan-files/{plan_file_id}")
def get_plan_file(plan_file_id: int, db: Session = Depends(get_db)):
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
            "id": plan_file.id, "project_id": plan_file.project_id,
            "file_name": plan_file.file_name, "file_type": plan_file.file_type,
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
def get_extractions(plan_file_id: int, db: Session = Depends(get_db)):
    """List all extracted measurements for a plan file."""
    return db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()


@router.put("/extractions/{extraction_id}")
def update_extraction(extraction_id: int, update: ExtractionUpdate, db: Session = Depends(get_db)):
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
            "measurement_value": extraction.measurement_value, "measurement_unit": extraction.measurement_unit}


@router.delete("/extractions/{extraction_id}")
def delete_extraction(extraction_id: int, db: Session = Depends(get_db)):
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
def regenerate_conditions(plan_file_id: int, db: Session = Depends(get_db)):
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
    return {"message": f"Regenerated {len(created_ids)} conditions", "conditions_created": len(created_ids),
            "condition_ids": created_ids}


@router.get("/plan-files/{plan_file_id}/status")
def check_analysis_status(plan_file_id: int, db: Session = Depends(get_db)):
    """Quick status check for plan analysis progress."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        raise HTTPException(status_code=404, detail="Plan file not found")
    extraction_count = db.query(VisionExtraction).filter(VisionExtraction.plan_file_id == plan_file_id).count()
    condition_count = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id, VisionExtraction.condition_id.isnot(None)).count()
    return {"plan_file_id": plan_file_id, "status": plan_file.upload_status,
            "page_count": plan_file.page_count, "detected_scale": plan_file.detected_scale,
            "extractions_count": extraction_count, "conditions_created": condition_count,
            "error_message": plan_file.error_message}
