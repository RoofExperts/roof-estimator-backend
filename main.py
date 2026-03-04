from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from database import engine, SessionLocal
from models import Base, User, Project, Organization, OrganizationMember, CompanySettings, UserInvite
from auth import hash_password, verify_password, create_access_token, get_current_user
from pydantic import BaseModel
from s3_service import upload_file_to_s3, s3_client, AWS_BUCKET_NAME
from spec_ai import analyze_spec_text_from_pdf
from seed_data import clone_seed_for_org

# Phase 1: Condition-based estimating engine
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
import secrets
import datetime
import re

# Create tables
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database with seed data on startup."""
    from migrations import run_migrations
    run_migrations(engine)

    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="Roof Estimator API",
    description="Multi-tenant commercial roofing estimation SaaS",
    version="3.0.0",
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


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class UserRegister(BaseModel):
    email: str
    password: str
    company_name: str | None = None  # Optional — creates org if provided

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

class InviteCreate(BaseModel):
    email: str
    role: str = "estimator"

class AcceptInviteRequest(BaseModel):
    token: str
    password: str | None = None  # Required if user doesn't exist yet


# ============================================================================
# HELPERS
# ============================================================================

def slugify(name: str) -> str:
    """Create URL-safe slug from org name."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    return slug[:50]


def get_user_org_role(user: User, db: Session) -> tuple:
    """Get user's current org and role. Returns (org_id, role)."""
    if user.current_org_id:
        member = db.query(OrganizationMember).filter(
            OrganizationMember.org_id == user.current_org_id,
            OrganizationMember.user_id == user.id
        ).first()
        if member:
            return user.current_org_id, member.role

    # Fall back to first org membership
    member = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == user.id
    ).first()
    if member:
        user.current_org_id = member.org_id
        db.commit()
        return member.org_id, member.role

    return None, "estimator"


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================

@app.get("/")
def root():
    return {"message": "Roof Estimator API v3.0.0 (Multi-Tenant)", "status": "running"}


@app.post("/register")
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register a new user and create their organization."""
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user with bcrypt
    new_user = User(email=user_data.email, password_hash=hash_password(user_data.password))
    db.add(new_user)
    db.flush()

    # Create organization
    org_name = user_data.company_name or f"{user_data.email.split('@')[0]}'s Company"
    org = Organization(name=org_name, slug=slugify(org_name))
    db.add(org)
    db.flush()

    # Create membership (owner)
    member = OrganizationMember(org_id=org.id, user_id=new_user.id, role="owner")
    db.add(member)

    # Set current org
    new_user.current_org_id = org.id

    # Create default company settings for this org
    settings = CompanySettings(org_id=org.id, name=org_name)
    db.add(settings)

    db.commit()

    # Clone seed data for the new org
    clone_seed_for_org(org.id, db)
    db.commit()

    # Issue JWT with org context
    token = create_access_token({
        "sub": new_user.email,
        "user_id": new_user.id,
        "org_id": org.id,
        "role": "owner"
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": new_user.id,
        "org_id": org.id,
        "org_name": org.name,
        "role": "owner"
    }


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Upgrade legacy SHA256 hash to bcrypt on successful login
    if not user.password_hash.startswith("$2b$"):
        user.password_hash = hash_password(form_data.password)

    org_id, role = get_user_org_role(user, db)

    # If user has no org (legacy user), create one
    if not org_id:
        org = Organization(name=f"{user.email.split('@')[0]}'s Company")
        db.add(org)
        db.flush()
        member = OrganizationMember(org_id=org.id, user_id=user.id, role="owner")
        db.add(member)
        user.current_org_id = org.id
        settings = CompanySettings(org_id=org.id, name=org.name)
        db.add(settings)
        db.commit()
        clone_seed_for_org(org.id, db)
        db.commit()
        org_id, role = org.id, "owner"

    db.commit()

    # Get org name
    org = db.query(Organization).filter(Organization.id == org_id).first()

    token = create_access_token({
        "sub": user.email,
        "user_id": user.id,
        "org_id": org_id,
        "role": role
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "org_id": org_id,
        "org_name": org.name if org else "",
        "role": role
    }


# ============================================================================
# ORGANIZATION / TEAM ENDPOINTS
# ============================================================================

@app.get("/api/v1/org")
def get_current_org(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get current organization details."""
    org = db.query(Organization).filter(Organization.id == current_user["org_id"]).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    members = db.query(OrganizationMember).filter(
        OrganizationMember.org_id == org.id
    ).all()

    member_list = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        member_list.append({
            "id": m.id,
            "user_id": m.user_id,
            "email": u.email if u else "",
            "role": m.role,
            "created_at": str(m.created_at)
        })

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "members": member_list,
        "created_at": str(org.created_at)
    }


@app.put("/api/v1/org")
def update_org(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update organization name (owner/admin only)."""
    if current_user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners and admins can update the organization")
    org = db.query(Organization).filter(Organization.id == current_user["org_id"]).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if "name" in data:
        org.name = data["name"]
        org.slug = slugify(data["name"])
    db.commit()
    return {"message": "Organization updated", "name": org.name}


@app.post("/api/v1/org/invite")
def invite_member(
    invite: InviteCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Invite a user to the organization (owner/admin only)."""
    if current_user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners and admins can invite members")

    # Check if already a member
    existing_user = db.query(User).filter(User.email == invite.email).first()
    if existing_user:
        existing_member = db.query(OrganizationMember).filter(
            OrganizationMember.org_id == current_user["org_id"],
            OrganizationMember.user_id == existing_user.id
        ).first()
        if existing_member:
            raise HTTPException(status_code=400, detail="User is already a member of this organization")

    # Create invite token
    token = secrets.token_urlsafe(32)
    invite_record = UserInvite(
        org_id=current_user["org_id"],
        email=invite.email,
        role=invite.role,
        token=token,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7)
    )
    db.add(invite_record)
    db.commit()

    return {
        "message": f"Invite created for {invite.email}",
        "invite_token": token,
        "expires_in": "7 days"
    }


@app.post("/accept-invite")
def accept_invite(data: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Accept an organization invite."""
    invite = db.query(UserInvite).filter(UserInvite.token == data.token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite token")
    if invite.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite has expired")

    # Find or create user
    user = db.query(User).filter(User.email == invite.email).first()
    if not user:
        if not data.password:
            raise HTTPException(status_code=400, detail="Password required for new users")
        user = User(email=invite.email, password_hash=hash_password(data.password))
        db.add(user)
        db.flush()

    # Add to org
    existing_member = db.query(OrganizationMember).filter(
        OrganizationMember.org_id == invite.org_id,
        OrganizationMember.user_id == user.id
    ).first()
    if not existing_member:
        member = OrganizationMember(org_id=invite.org_id, user_id=user.id, role=invite.role)
        db.add(member)

    user.current_org_id = invite.org_id

    # Delete invite
    db.delete(invite)
    db.commit()

    org = db.query(Organization).filter(Organization.id == invite.org_id).first()

    token = create_access_token({
        "sub": user.email,
        "user_id": user.id,
        "org_id": invite.org_id,
        "role": invite.role
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "org_id": invite.org_id,
        "org_name": org.name if org else "",
        "role": invite.role
    }


@app.get("/api/v1/org/members")
def list_members(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all members of the current organization."""
    members = db.query(OrganizationMember).filter(
        OrganizationMember.org_id == current_user["org_id"]
    ).all()

    result = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        result.append({
            "id": m.id,
            "user_id": m.user_id,
            "email": u.email if u else "",
            "role": m.role,
            "created_at": str(m.created_at)
        })
    return result


@app.delete("/api/v1/org/members/{member_id}")
def remove_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Remove a member from the organization (owner only)."""
    if current_user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can remove members")

    member = db.query(OrganizationMember).filter(
        OrganizationMember.id == member_id,
        OrganizationMember.org_id == current_user["org_id"]
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the owner")

    db.delete(member)
    db.commit()
    return {"message": "Member removed"}


@app.get("/api/v1/org/invites")
def list_invites(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List pending invites for the current organization."""
    invites = db.query(UserInvite).filter(
        UserInvite.org_id == current_user["org_id"]
    ).all()
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role": inv.role,
            "expires_at": str(inv.expires_at),
            "token": inv.token
        }
        for inv in invites
    ]


# ============================================================================
# PROJECT ENDPOINTS (tenant-scoped)
# ============================================================================

@app.post("/projects")
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    new_project = Project(
        org_id=current_user["org_id"],
        user_id=current_user["user_id"],
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
def list_projects(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    projects = db.query(Project).filter(
        Project.org_id == current_user["org_id"]
    ).order_by(Project.created_at.desc()).all()
    return [{"id": p.id, "project_name": p.project_name, "address": p.address,
             "system_type": p.system_type, "roof_area": p.roof_area,
             "spec_file_url": p.spec_file_url, "analysis_status": p.analysis_status,
             "analysis_result": p.analysis_result} for p in projects]


@app.get("/projects/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": project.id, "project_name": project.project_name, "address": project.address,
            "system_type": project.system_type, "roof_area": project.roof_area,
            "spec_file_url": project.spec_file_url, "analysis_status": project.analysis_status,
            "analysis_result": project.analysis_result}


@app.put("/projects/{project_id}")
def update_project(
    project_id: int,
    updates: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
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
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.query(EstimateLineItem).filter(EstimateLineItem.project_id == project_id).delete()
    plan_file_ids = [p.id for p in db.query(RoofPlanFile).filter(RoofPlanFile.project_id == project_id).all()]
    if plan_file_ids:
        db.query(VisionExtraction).filter(VisionExtraction.plan_file_id.in_(plan_file_ids)).delete(synchronize_session='fetch')
        db.query(PlanPageAnalysis).filter(PlanPageAnalysis.plan_file_id.in_(plan_file_ids)).delete(synchronize_session='fetch')
    db.query(RoofPlanFile).filter(RoofPlanFile.project_id == project_id).delete()
    db.query(RoofCondition).filter(RoofCondition.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    return {"message": "Project and all related data deleted successfully"}


# ============================================================================
# SPEC UPLOAD & ANALYSIS (tenant-scoped)
# ============================================================================

@app.post("/projects/{project_id}/upload-spec")
def upload_spec(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    file_url = upload_file_to_s3(file, project_id, "specs")
    project.spec_file_url = file_url
    project.analysis_status = "not_started"
    db.commit()
    db.refresh(project)
    return {"message": "Spec uploaded successfully", "file_url": file_url}


def run_spec_analysis(project_id: int):
    db = SessionLocal()
    temp_path = None
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or not project.spec_file_url:
            return
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
def analyze_spec(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
    if not project or not project.spec_file_url:
        raise HTTPException(status_code=404, detail="Spec file not found")
    if project.analysis_status == "processing":
        return {"status": "already_processing"}
    project.analysis_status = "processing"
    db.commit()
    background_tasks.add_task(run_spec_analysis, project_id)
    return {"project_id": project_id, "status": "processing"}


# ============================================================================
# PDF PROXY ENDPOINTS (tenant-scoped)
# ============================================================================

@app.get("/projects/{project_id}/spec-file")
def proxy_spec_file(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.org_id == current_user["org_id"]
    ).first()
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
def proxy_plan_file(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
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
