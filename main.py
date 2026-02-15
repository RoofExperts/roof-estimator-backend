from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import engine, SessionLocal
from models import Base, User, Project
from auth import hash_password, verify_password, create_access_token
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm

app = FastAPI()

Base.metadata.create_all(bind=engine)

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
    system_type: str
    roof_area: float


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
    return {"access_token": token, "token_type": "bearer"}


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
