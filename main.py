from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from database import engine, SessionLocal
from models import Base, User, Project
from auth import hash_password, verify_password, create_access_token
from pydantic import BaseModel
from s3_service import upload_file_to_s3
from spec_ai import extract_text_from_pdf, analyze_spec_text

# Phase 1: Condition-based estimating engine
from conditions_models import RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem
from conditions_router import router as conditions_router
from seed_data import seed_database

# Phase 2: AI Vision Plan Reader
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction
from vision_router import router as vision_router

import requests
import tempfile
import json

# Create tables
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database with seed data on startup."""
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Commercial Roofing Estimating API",
    description="AI-powered roofing specification analysis, condition-based estimating, and vision plan reading",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend access
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

# Include routers
app.include_router(conditions_router)
app.include_router(vision_router)


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


@app.get("/")
def root():
    return {"message": "Roof Estimator Backend Running"}


@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(
        email=user.email,
        password_hash=hash_password(user.password)
    )
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
    return db.query(Project).all()

@app.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


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
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or not project.spec_file_url:
            return
        response = requests.get(project.spec_file_url)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(response.content)
            temp_path = tmp.name
        spec_text = extract_text_from_pdf(temp_path)
        result = analyze_spec_text(spec_text)
        project.analysis_result = json.dumps(result)
        project.analysis_status = "complete"
        db.commit()
    except Exception as e:
        project.analysis_status = "failed"
        db.commit()
    finally:
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
