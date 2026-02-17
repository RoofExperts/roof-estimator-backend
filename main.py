from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import engine, SessionLocal
from models import Base, User, Project
from auth import hash_password, verify_password, create_access_token
from pydantic import BaseModel
from s3_service import upload_file_to_s3
from spec_ai import extract_text_from_pdf, analyze_spec_text

import requests
import tempfile
from spec_ai import extract_text_from_pdf

app = FastAPI()

# Create tables
Base.metadata.create_all(bind=engine)

# =============================
# DATABASE DEPENDENCY
# =============================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================
# Pydantic Schemas
# =============================
class UserCreate(BaseModel):
    email: str
    password: str

class ProjectCreate(BaseModel):
    project_name: str
    address: str
    system_type: str
    roof_area: float

# =============================
# ROOT
# =============================
@app.get("/")
def root():
    return {"message": "Roof Estimator Backend Running"}

# =============================
# REGISTER
# =============================
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

# =============================
# LOGIN
# =============================
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

# =============================
# CREATE PROJECT
# =============================
@app.post("/projects")
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    new_project = Project(
        project_name=project.project_name,
        address=project.address,
        system_type=project.system_type,
        roof_area=project.roof_area
    )

    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    return {"message": "Project created successfully"}

# =============================
# LIST PROJECTS
# =============================
@app.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@app.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project

# =============================
# UPLOAD SPEC
# =============================
@app.post("/projects/{project_id}/upload-spec")
def upload_spec(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    file_url = upload_file_to_s3(file, project_id, "specs")

    project.spec_file_url = file_url
    db.commit()
    db.refresh(project)

    return {"message": "Spec uploaded successfully", "file_url": file_url}

# =============================
# ANALYZE SPEC (AI)
# =============================
@app.post("/projects/{project_id}/analyze-spec")
def analyze_spec(project_id: int, db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == project_id).first()

    if not project or not project.spec_file_url:
        raise HTTPException(status_code=404, detail="Spec file not found")

    # Download the spec from S3 temporarily
    response = requests.get(project.spec_file_url)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to download spec file")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(response.content)
        temp_path = tmp.name

    # Extract text from PDF
    spec_text = extract_text_from_pdf(temp_path)

    if not spec_text:
        raise HTTPException(status_code=400, detail="Unable to extract text from spec")

    # Send to AI
    ai_result = analyze_spec_text(spec_text)

    return {
        "project_id": project_id,
        "analysis": ai_result
    }
@app.get("/test-openai-direct")
def test_openai_direct():
    from openai import OpenAI
    import os

    try:
        key = os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "Say hello."}
            ]
        )

        return {
            "success": True,
            "response": response.choices[0].message.content
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
@app.post("/test-pdf")
def test_pdf(project_id: int, db: Session = Depends(get_db)):

    try:
        project = db.query(Project).filter(Project.id == project_id).first()

        if not project or not project.spec_file_url:
            return {"error": "Spec not found"}

        response = requests.get(project.spec_file_url)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(response.content)
            temp_path = tmp.name

        text = extract_text_from_pdf(temp_path)

        return {
            "text_length": len(text),
            "preview": text[:500]
        }

    except Exception as e:
        return {"error": str(e)}
