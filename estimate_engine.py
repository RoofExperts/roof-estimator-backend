"""
Condition-Based Commercial Roofing Estimating Engine - Calculation Logic

This module provides the core calculation functions that:
1. Retrieve conditions for a project
2. Match material templates by condition type
3. Calculate quantities based on coverage rates and waste
4. Look up unit costs from the cost database
5. Generate estimate line items and summary reports
"""

from sqlalchemy.orm import Session
from conditions_models import RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem
from models import Project
from sqlalchemy import delete
from typing import Dict, List, Optional


# ============================================================================
# MAIN CALCULATION FUNCTION
# ============================================================================

def calculate_estimate(project_id: int, db: Session) -> Dict:
    """
    Calculate the complete estimate for a project based on conditions and material templates.
    
    Process:
    1. Retrieve all conditions for the project
    2. For each condition, find matching material templates by condition_type
    3. For each template, calculate: quantity = measurement_value * coverage_rate * (1 + waste_factor)
    4. Look up unit cost from cost database
    5. Create EstimateLineItem records (delete old ones first)
    6. Return success status and line item count
    
    Args:
        project_id: ID of the project to estimate
        db: SQLAlchemy session
        
    Returns:
        Dict with status, line_items_created, and total_cost
    """
    
    try:
        # Verify project exists
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"Project {project_id} not found"}
        
        # Delete existing estimate line items for this project
        db.query(EstimateLineItem).filter(EstimateLineItem.project_id == project_id).delete()
        db.commit()
        
        # Get all conditions for this project
        conditions = db.query(RoofCondition).filter(RoofCondition.project_id == project_id).all()
        
        if not conditions:
            return {
                "status": "success",
                "message": "No conditions found for this project",
                "line_items_created": 0,
                "total_cost": 0.0
            }
        
        line_items_created = 0
        total_cost = 0.0
        errors = []
        
        # Process each condition
        for condition in conditions:
            # Find material templates for this condition type
            templates = db.query(MaterialTemplate).filter(
                MaterialTemplate.condition_type == condition.condition_type,
                MaterialTemplate.is_active == True
            ).all()
            
            # Generate line items from templates
            for template in templates:
                # Calculate quantity with waste
                base_quantity = condition.measurement_value * template.coverage_rate
                quantity = base_quantity * (1 + template.waste_factor)
                
                # Look up cost from database
                cost_item = db.query(CostDatabaseItem).filter(
                    CostDatabaseItem.material_name == template.material_name,
                    CostDatabaseItem.unit == template.unit,
                    CostDatabaseItem.is_active == True
                ).first()
                
                if not cost_item:
                    errors.append(
                        f"No cost found for {template.material_name} ({template.unit}) "
                        f"in condition {condition.id}"
                    )
                    continue
                
                # Calculate total cost (material + optional labor)
                unit_cost = cost_item.unit_cost
                if cost_item.labor_cost_per_unit:
                    unit_cost += cost_item.labor_cost_per_unit
                
                item_total = quantity * unit_cost
                
                # Create line item
                line_item = EstimateLineItem(
                    project_id=project_id,
                    condition_id=condition.id,
                    material_name=template.material_name,
                    material_category=template.material_category,
                    quantity=quantity,
                    unit=template.unit,
                    unit_cost=unit_cost,
                    total_cost=item_total,
                    notes=f"From condition: {condition.description or condition.condition_type}"
                )
                
                db.add(line_item)
                line_items_created += 1
                total_cost += item_total
        
        db.commit()
        
        return {
            "status": "success",
            "line_items_created": line_items_created,
            "total_cost": round(total_cost, 2),
            "errors": errors if errors else None
        }
    
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Failed to calculate estimate: {str(e)}"
        }


# ============================================================================
# ESTIMATE SUMMARY FUNCTION
# ============================================================================

def get_estimate_summary(project_id: int, db: Session) -> Dict:
    """
    Generate a structured summary of the estimate for a project.
    
    Includes:
    - Conditions grouped with their line items
    - Subtotals per condition
    - Material and labor subtotals
    - Material category breakdown
    - Grand total
    
    Args:
        project_id: ID of the project
        db: SQLAlchemy session
        
    Returns:
        Dict with estimate summary structure
    """
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"Project {project_id} not found"}
        
        # Get all conditions with their line items
        conditions = db.query(RoofCondition).filter(
            RoofCondition.project_id == project_id
        ).all()
        
        if not conditions:
            return {
                "status": "success",
                "project_id": project_id,
                "project_name": project.project_name,
                "conditions": [],
                "summary": {
                    "material_subtotal": 0.0,
                    "labor_subtotal": 0.0,
                    "grand_total": 0.0,
                    "category_breakdown": {}
                }
            }
        
        # Build condition details
        conditions_detail = []
        material_total = 0.0
        labor_total = 0.0
        category_breakdown = {}
        
        for condition in conditions:
            # Get line items for this condition
            line_items = db.query(EstimateLineItem).filter(
                EstimateLineItem.condition_id == condition.id
            ).all()
            
            condition_subtotal = 0.0
            items = []
            
            for item in line_items:
                # Estimate material vs labor split
                cost_item = db.query(CostDatabaseItem).filter(
                    CostDatabaseItem.material_name == item.material_name,
                    CostDatabaseItem.unit == item.unit
                ).first()
                
                material_portion = item.total_cost
                labor_portion = 0.0
                
                if cost_item and cost_item.labor_cost_per_unit:
                    labor_portion = item.quantity * cost_item.labor_cost_per_unit
                    material_portion = item.total_cost - labor_portion
                
                # Track category breakdown
                category = item.material_category
                if category not in category_breakdown:
                    category_breakdown[category] = 0.0
                category_breakdown[category] += item.total_cost
                
                items.append({
                    "id": item.id,
                    "material_name": item.material_name,
                    "material_category": item.material_category,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_cost": item.unit_cost,
                    "total_cost": item.total_cost,
                    "material_portion": round(material_portion, 2),
                    "labor_portion": round(labor_portion, 2)
                })
                
                condition_subtotal += item.total_cost
                material_total += material_portion
                labor_total += labor_portion
            
            conditions_detail.append({
                "id": condition.id,
                "condition_type": condition.condition_type,
                "description": condition.description,
                "measurement_value": condition.measurement_value,
                "measurement_unit": condition.measurement_unit,
                "wind_zone": condition.wind_zone,
                "subtotal": round(condition_subtotal, 2),
                "line_items": items
            })
        
        grand_total = material_total + labor_total
        
        return {
            "status": "success",
            "project_id": project_id,
            "project_name": project.project_name,
            "conditions": conditions_detail,
            "summary": {
                "material_subtotal": round(material_total, 2),
                "labor_subtotal": round(labor_total, 2),
                "grand_total": round(grand_total, 2),
                "category_breakdown": {cat: round(cost, 2) for cat, cost in category_breakdown.items()}
            }
        }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to generate estimate summary: {str(e)}"
        }


# ============================================================================
# HELPER FUNCTION: GET AVAILABLE CONDITION TYPES
# ============================================================================

def get_available_condition_types(db: Session) -> List[str]:
    """
    Get all unique condition types that have active material templates.
    
    Args:
        db: SQLAlchemy session
        
    Returns:
        List of condition type strings
    """
    templates = db.query(MaterialTemplate.condition_type).filter(
        MaterialTemplate.is_active == True
    ).distinct().all()
    
    return [t[0] for t in templates]


# ============================================================================
# HELPER FUNCTION: GET MATERIALS FOR CONDITION TYPE
# ============================================================================

def get_materials_for_condition(condition_type: str, db: Session) -> List[Dict]:
    """
    Get all active material templates for a specific condition type.
    
    Args:
        condition_type: Type of condition (field, perimeter, etc.)
        db: SQLAlchemy session
        
    Returns:
        List of dicts with material template information
    """
    templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.condition_type == condition_type,
        MaterialTemplate.is_active == True
    ).all()
    
    return [
        {
            "id": t.id,
            "material_name": t.material_name,
            "material_category": t.material_category,
            "unit": t.unit,
            "coverage_rate": t.coverage_rate,
            "waste_factor": t.waste_factor
        }
        for t in templates
    ]
