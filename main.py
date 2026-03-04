from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from database import engine, SessionLocal
from models import Base, User, Project
from auth import hash_password, verify_password, create_access_token
from pydantic import BaseModel
from s3_service import upload_file_to_s3, s3_client, AWS_BUCKET_NAME
from spec_ai import analyze_spec_text_from_pdf



# Phase 1: Condition-based estimating engineh
from conditions_models import RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem
from conditions_router import router as conditions_router
from seed_data import seed_database

# Phase 2: AI Vision Plan Reader
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction
from vision_router import router as vision_router
from proposal_router import proposal_router
from admin_router import admin_router
from customer_router import customer_router

import requests
import tempfile
import json
import io
import os

# Create tables
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database with seed data on startup."""
    db = SessionLocal()
    try:
        seed_database(db)
        # Seed default company settings if none exist
        from admin_router import get_or_create_settings
        get_or_create_settings(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="Roof Estimator API",
    description="Commercial roofing estimation system with AI-powered plan reading",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://roofing-estimator-frontend.onrender.com",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Debug: Return actual error details for 500 errors
import traceback
from starlette.requests import Request

@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"[ERROR] {request.url}: {exc}\n{tb}")
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": tb[-2000:]}
    )

# Include routers
app.include_router(conditions_router)
app.include_router(vision_router)
app.include_router(proposal_router)
app.include_router(admin_router)
app.include_router(customer_router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class UserCreate(BaseModel):
    email: str
    password: str

class ProjectCreate(BaseModel):
    project_name: str
    address: str
    system_type: str | None = None
    roof_area: float | None = None

class ProjectUpdate(BaseModel):
    project_name: str | None = None
    address: str | None = None
    system_type: str | None = None
    roof_area: float | None = None


@app.get("/")
def root():
    return {"message": "Roof Estimator API v2.0.0", "status": "running"}


@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(email=user.email, password_hash=hash_password(user.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully"}


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.email})
    return {
        "access_token": token,
        "token_type": "bearer"
    }


@app.post("/projects")
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    new_project = Project(
        project_name=project.project_name,
        address=project.address,
        system_type=project.system_type,
        roof_area=project.roof_area,
        analysis_status="not_started"
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return {"message": "Project created successfully", "project_id": new_project.id}


@app.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return [{"id": p.id, "project_name": p.project_name, "address": p.address,
             "system_type": p.system_type, "roof_area": p.roof_area,
             "spec_file_url": p.spec_file_url, "analysis_status": p.analysis_status,
             "analysis_result": p.analysis_result} for p in projects]


@app.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": project.id, "project_name": project.project_name, "address": project.address,
            "system_type": project.system_type, "roof_area": project.roof_area,
            "spec_file_url": project.spec_file_url, "analysis_status": project.analysis_status,
            "analysis_result": project.analysis_result}


@app.put("/projects/{project_id}")
def update_project(project_id: int, updates: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    update_data = updates.dict(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return {"message": "Project updated successfully", "project_id": project.id}


@app.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete all related records in correct order to respect FK constraints
    # 1. EstimateLineItems (FK to projects + conditions)
    db.query(EstimateLineItem).filter(EstimateLineItem.project_id == project_id).delete()

    # 2. Get plan file IDs for this project
    plan_file_ids = [p.id for p in db.query(RoofPlanFile).filter(RoofPlanFile.project_id == project_id).all()]

    if plan_file_ids:
        # 3. VisionExtractions (FK to plan_files)
        db.query(VisionExtraction).filter(VisionExtraction.plan_file_id.in_(plan_file_ids)).delete(synchronize_session='fetch')
        # 4. PlanPageAnalysis (FK to plan_files)
        db.query(PlanPageAnalysis).filter(PlanPageAnalysis.plan_file_id.in_(plan_file_ids)).delete(synchronize_session='fetch')

    # 5. RoofPlanFiles (FK to projects)
    db.query(RoofPlanFile).filter(RoofPlanFile.project_id == project_id).delete()

    # 6. RoofConditions (FK to projects)
    db.query(RoofCondition).filter(RoofCondition.project_id == project_id).delete()

    # 7. Finally delete the project
    db.delete(project)
    db.commit()
    return {"message": "Project and all related data deleted successfully"}


@app.post("/projects/{project_id}/upload-spec")
def upload_spec(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    file_url = upload_file_to_s3(file, project_id, "specs")
    project.spec_file_url = file_url
    project.analysis_status = "not_started"
    db.commit()
    db.refresh(project)
    return {
        "message": "Spec uploaded successfully",
        "file_url": file_url
    }


def run_spec_analysis(project_id: int):
    db = SessionLocal()
    temp_path = None
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or not project.spec_file_url:
            return
        # Use boto3 to stream download from private S3 bucket (memory-efficient)
        from urllib.parse import urlparse
        parsed = urlparse(project.spec_file_url)
        s3_key = parsed.path.lstrip("/")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            s3_client.download_fileobj(AWS_BUCKET_NAME, s3_key, tmp)
            temp_path = tmp.name
        result = analyze_spec_text_from_pdf(temp_path)
        project.analysis_result = json.dumps(result)
        project.analysis_status = "complete"
        db.commit()
    except Exception as e:
        project.analysis_status = "failed"
        db.commit()
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        db.close()


@app.post("/projects/{project_id}/analyze-spec")
def analyze_spec(project_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.spec_file_url:
        raise HTTPException(status_code=404, detail="Spec file not found")
    if project.analysis_status == "processing":
        return {"status": "already_processing"}
    project.analysis_status = "processing"
    db.commit()
    background_tasks.add_task(run_spec_analysis, project_id)
    return {
        "project_id": project_id,
        "status": "processing"
    }


# PDF Proxy endpoints - serve PDFs through backend to avoid S3 CORS issues
@app.get("/projects/{project_id}/spec-file")
def proxy_spec_file(project_id: int, db: Session = Depends(get_db)):
    """Proxy the spec PDF file from S3 to avoid CORS issues."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.spec_file_url:
        raise HTTPException(status_code=404, detail="Spec file not found")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(project.spec_file_url)
        s3_key = parsed.path.lstrip("/")
        s3_obj = s3_client.get_object(Bucket=AWS_BUCKET_NAME, Key=s3_key)
        return StreamingResponse(
            s3_obj["Body"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=spec_{project_id}.pdf",
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch PDF: {str(e)}")


@app.get("/plans/{plan_id}/file")
def proxy_plan_file(plan_id: int, db: Session = Depends(get_db)):
    """Proxy plan PDF file from S3 to avoid CORS issues."""
    plan = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_id).first()
    if not plan or not plan.s3_key:
        raise HTTPException(status_code=404, detail="Plan file not found")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(plan.s3_key)
        s3_key = parsed.path.lstrip("/")
        s3_obj = s3_client.get_object(Bucket=AWS_BUCKET_NAME, Key=s3_key)
        return StreamingResponse(
            s3_obj["Body"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=plan_{plan_id}.pdf",
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch PDF: {str(e)}")
