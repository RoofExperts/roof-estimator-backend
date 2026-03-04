import hashlib
import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import datetime
import os

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

security = HTTPBearer()


# ============================================================================
# PASSWORD HASHING (bcrypt with SHA256 backward compat)
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password. Supports both bcrypt and legacy SHA256 hashes."""
    # Try bcrypt first (new format starts with $2b$)
    if hashed.startswith("$2b$") or hashed.startswith("$2a$"):
        return bcrypt.checkpw(password.encode(), hashed.encode())
    # Fall back to legacy SHA256
    return hashlib.sha256(password.encode()).hexdigest() == hashed


# ============================================================================
# JWT TOKEN
# ============================================================================

def create_access_token(data: dict) -> str:
    """Create JWT with user_id, org_id, role, email."""
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and validate a JWT token. Returns payload dict."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise JWTError("Missing subject")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ============================================================================
# FASTAPI DEPENDENCY: GET CURRENT USER
# ============================================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Extract authenticated user from JWT Bearer token.

    Returns dict with keys: sub (email), user_id, org_id, role
    Raises 401 if token is invalid or missing.
    """
    token = credentials.credentials
    payload = verify_token(token)
    return {
        "email": payload.get("sub"),
        "user_id": payload.get("user_id"),
        "org_id": payload.get("org_id"),
        "role": payload.get("role", "estimator"),
    }
