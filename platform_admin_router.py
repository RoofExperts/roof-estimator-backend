"""
Platform Admin Router — Super admin endpoints for managing the entire SaaS platform.

Only accessible by users with is_superadmin=True.
Provides: org listing, org management, usage stats, and impersonation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from pydantic import BaseModel
from database import get_db
from models import Organization, OrganizationMember, User, Project, Customer, CompanySettings, SavedProposal
from conditions_models import MaterialTemplate, CostDatabaseItem
from auth import get_current_user, create_access_token, hash_password
import datetime

router = APIRouter(prefix="/api/v1/platform", tags=["Platform Admin"])


# ============================================================================
# SUPERADMIN GUARD
# ============================================================================

async def require_superadmin(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dependency that requires the current user to be a superadmin."""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user or not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin access required")
    return current_user


# ============================================================================
# SCHEMAS
# ============================================================================

class OrgUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class UserUpdate(BaseModel):
    is_superadmin: Optional[bool] = None
    email: Optional[str] = None

class CreateSuperadminRequest(BaseModel):
    user_email: str


# ============================================================================
# DASHBOARD / USAGE STATS
# ============================================================================

@router.get("/dashboard")
def platform_dashboard(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Get platform-wide usage statistics."""
    total_orgs = db.query(func.count(Organization.id)).scalar()
    total_users = db.query(func.count(User.id)).scalar()
    total_projects = db.query(func.count(Project.id)).scalar()
    total_customers = db.query(func.count(Customer.id)).scalar()
    total_proposals = db.query(func.count(SavedProposal.id)).scalar()

    # Recent signups (last 30 days)
    thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
    recent_orgs = db.query(func.count(Organization.id)).filter(
        Organization.created_at >= thirty_days_ago
    ).scalar()
    recent_users = db.query(func.count(User.id)).filter(
        User.created_at >= thirty_days_ago
    ).scalar()
    recent_projects = db.query(func.count(Project.id)).filter(
        Project.created_at >= thirty_days_ago
    ).scalar()

    # Orgs by size (member count)
    org_sizes = db.query(
        OrganizationMember.org_id,
        func.count(OrganizationMember.id).label("member_count")
    ).group_by(OrganizationMember.org_id).all()

    avg_team_size = sum(s.member_count for s in org_sizes) / max(len(org_sizes), 1)

    return {
        "totals": {
            "organizations": total_orgs,
            "users": total_users,
            "projects": total_projects,
            "customers": total_customers,
            "proposals": total_proposals,
        },
        "last_30_days": {
            "new_organizations": recent_orgs,
            "new_users": recent_users,
            "new_projects": recent_projects,
        },
        "averages": {
            "team_size": round(avg_team_size, 1),
        }
    }


# ============================================================================
# ORGANIZATION MANAGEMENT
# ============================================================================

@router.get("/organizations")
def list_organizations(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """List all organizations with member and project counts."""
    query = db.query(Organization)

    if search:
        query = query.filter(Organization.name.ilike(f"%{search}%"))

    total = query.count()
    orgs = query.order_by(Organization.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for org in orgs:
        member_count = db.query(func.count(OrganizationMember.id)).filter(
            OrganizationMember.org_id == org.id
        ).scalar()
        project_count = db.query(func.count(Project.id)).filter(
            Project.org_id == org.id
        ).scalar()
        customer_count = db.query(func.count(Customer.id)).filter(
            Customer.org_id == org.id
        ).scalar()

        # Get owner email
        owner_member = db.query(OrganizationMember).filter(
            OrganizationMember.org_id == org.id,
            OrganizationMember.role == "owner"
        ).first()
        owner_email = ""
        if owner_member:
            owner_user = db.query(User).filter(User.id == owner_member.user_id).first()
            owner_email = owner_user.email if owner_user else ""

        # Get company settings
        settings = db.query(CompanySettings).filter(CompanySettings.org_id == org.id).first()

        result.append({
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "owner_email": owner_email,
            "member_count": member_count,
            "project_count": project_count,
            "customer_count": customer_count,
            "logo_url": settings.logo_url if settings else None,
            "created_at": str(org.created_at),
        })

    return {"organizations": result, "total": total}


@router.get("/organizations/{org_id}")
def get_organization_detail(
    org_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Get detailed info about a specific organization."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Members
    members = db.query(OrganizationMember).filter(OrganizationMember.org_id == org_id).all()
    member_list = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        project_count = db.query(func.count(Project.id)).filter(
            Project.org_id == org_id, Project.user_id == m.user_id
        ).scalar()
        member_list.append({
            "id": m.id,
            "user_id": m.user_id,
            "email": u.email if u else "",
            "role": m.role,
            "project_count": project_count,
            "created_at": str(m.created_at),
        })

    # Usage stats
    project_count = db.query(func.count(Project.id)).filter(Project.org_id == org_id).scalar()
    customer_count = db.query(func.count(Customer.id)).filter(Customer.org_id == org_id).scalar()
    proposal_count = db.query(func.count(SavedProposal.id)).filter(SavedProposal.org_id == org_id).scalar()
    template_count = db.query(func.count(MaterialTemplate.id)).filter(
        MaterialTemplate.org_id == org_id
    ).scalar()

    # Company settings
    settings = db.query(CompanySettings).filter(CompanySettings.org_id == org_id).first()

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "created_at": str(org.created_at),
        "members": member_list,
        "usage": {
            "projects": project_count,
            "customers": customer_count,
            "proposals": proposal_count,
            "material_templates": template_count,
        },
        "settings": {
            "company_name": settings.name if settings else "",
            "email": settings.email if settings else "",
            "phone": settings.phone if settings else "",
            "logo_url": settings.logo_url if settings else None,
        } if settings else None,
    }


@router.put("/organizations/{org_id}")
def update_organization(
    org_id: int,
    data: OrgUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Update organization details (name, active status)."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if data.name is not None:
        org.name = data.name
    db.commit()
    return {"message": "Organization updated", "id": org.id, "name": org.name}


@router.delete("/organizations/{org_id}")
def deactivate_organization(
    org_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Soft-deactivate an org by removing all member access (doesn't delete data)."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Remove all memberships (soft deactivate)
    members = db.query(OrganizationMember).filter(OrganizationMember.org_id == org_id).all()
    for m in members:
        user = db.query(User).filter(User.id == m.user_id).first()
        if user and user.current_org_id == org_id:
            user.current_org_id = None
        db.delete(m)

    db.commit()
    return {"message": f"Organization '{org.name}' deactivated. {len(members)} members removed."}


class MergeOrgsRequest(BaseModel):
    source_org_id: int
    target_org_id: int


@router.post("/organizations/merge")
def merge_organizations(
    data: MergeOrgsRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """
    Merge source org INTO target org.
    Moves all projects, customers, proposals, members, templates, and cost items.
    Then deletes the source org's membership records and settings.
    """
    source = db.query(Organization).filter(Organization.id == data.source_org_id).first()
    target = db.query(Organization).filter(Organization.id == data.target_org_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source organization not found")
    if not target:
        raise HTTPException(status_code=404, detail="Target organization not found")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot merge an organization into itself")

    results = {"source": source.name, "target": target.name, "moved": {}}

    # 1. Move projects
    from sqlalchemy import update
    count = db.query(Project).filter(Project.org_id == source.id).update(
        {Project.org_id: target.id}, synchronize_session=False
    )
    results["moved"]["projects"] = count

    # 2. Move customers
    count = db.query(Customer).filter(Customer.org_id == source.id).update(
        {Customer.org_id: target.id}, synchronize_session=False
    )
    results["moved"]["customers"] = count

    # 3. Move saved proposals
    count = db.query(SavedProposal).filter(SavedProposal.org_id == source.id).update(
        {SavedProposal.org_id: target.id}, synchronize_session=False
    )
    results["moved"]["proposals"] = count

    # 4. Move org-specific material templates (not global ones)
    count = db.query(MaterialTemplate).filter(
        MaterialTemplate.org_id == source.id,
        MaterialTemplate.is_global == False
    ).update({MaterialTemplate.org_id: target.id}, synchronize_session=False)
    results["moved"]["material_templates"] = count

    # 5. Move org-specific cost database items
    count = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.org_id == source.id,
        CostDatabaseItem.is_global == False
    ).update({CostDatabaseItem.org_id: target.id}, synchronize_session=False)
    results["moved"]["cost_items"] = count

    # 6. Move members (avoid duplicates)
    source_members = db.query(OrganizationMember).filter(
        OrganizationMember.org_id == source.id
    ).all()
    members_moved = 0
    for m in source_members:
        # Check if user is already a member of target org
        existing = db.query(OrganizationMember).filter(
            OrganizationMember.org_id == target.id,
            OrganizationMember.user_id == m.user_id
        ).first()
        if existing:
            # User already in target — just delete source membership
            db.delete(m)
        else:
            # Move membership to target org
            m.org_id = target.id
            members_moved += 1
        # Update user's current_org_id
        user = db.query(User).filter(User.id == m.user_id).first()
        if user and user.current_org_id == source.id:
            user.current_org_id = target.id
    results["moved"]["members"] = members_moved

    # 7. Delete source org settings
    source_settings = db.query(CompanySettings).filter(
        CompanySettings.org_id == source.id
    ).all()
    for s in source_settings:
        db.delete(s)

    # 8. Delete the source org itself
    db.delete(source)
    db.commit()

    results["message"] = f"Merged '{source.name}' into '{target.name}' successfully"
    return results


# ============================================================================
# USER MANAGEMENT
# ============================================================================

@router.get("/users")
def list_all_users(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """List all users across the platform."""
    query = db.query(User)
    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for u in users:
        orgs = db.query(OrganizationMember).filter(OrganizationMember.user_id == u.id).all()
        org_names = []
        for m in orgs:
            org = db.query(Organization).filter(Organization.id == m.org_id).first()
            if org:
                org_names.append({"id": org.id, "name": org.name, "role": m.role})

        result.append({
            "id": u.id,
            "email": u.email,
            "is_superadmin": u.is_superadmin or False,
            "current_org_id": u.current_org_id,
            "organizations": org_names,
            "created_at": str(u.created_at),
        })

    return {"users": result, "total": total}


@router.post("/users/make-superadmin")
def make_superadmin(
    data: CreateSuperadminRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Grant superadmin privileges to a user."""
    user = db.query(User).filter(User.email == data.user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_superadmin = True
    db.commit()
    return {"message": f"{user.email} is now a superadmin"}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """Reset a user's password to a temporary one."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    import secrets
    temp_password = secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp_password)
    db.commit()
    return {
        "message": f"Password reset for {user.email}",
        "temporary_password": temp_password,
        "note": "Share this securely with the user. They should change it on next login."
    }


# ============================================================================
# IMPERSONATION
# ============================================================================

@router.post("/impersonate/{org_id}")
def impersonate_org(
    org_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_superadmin),
):
    """
    Generate a token that lets the superadmin act as an owner of the target org.
    The token is scoped to the target org but the user remains the superadmin.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Create a token scoped to the target org with owner role
    token = create_access_token({
        "sub": admin["email"],
        "user_id": admin["user_id"],
        "org_id": org_id,
        "role": "owner",
        "impersonating": True,
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "org_id": org_id,
        "org_name": org.name,
        "note": "You are now impersonating this organization as owner."
    }
