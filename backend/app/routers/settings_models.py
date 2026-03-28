"""Settings endpoints for model configuration and assignments."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_config import Model, ModelAssignment
from app.schemas.model_config import ModelOut, ModelUpdate, AssignmentOut, AssignmentUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

TASK_REQUIRED_CAPABILITY = {
    "issue_classification": "chat",
    "law_mapping": "chat",
    "fast_general": "chat",
    "article_selection": "chat",
    "answer_generation": "chat",
    "diff_summary": "chat",
    "ocr": "ocr",
}


@router.get("/models", response_model=list[ModelOut])
def list_models(db: Session = Depends(get_db)):
    models = db.query(Model).all()
    return [
        ModelOut(
            id=m.id, provider=m.provider, api_model_id=m.api_model_id,
            label=m.label, cost_tier=m.cost_tier,
            capabilities=m.capabilities_list, enabled=bool(m.enabled),
        )
        for m in models
    ]


@router.put("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, update: ModelUpdate, db: Session = Depends(get_db)):
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if update.enabled is not None:
        model.enabled = int(update.enabled)
    if update.label is not None:
        model.label = update.label
    db.commit()
    db.refresh(model)
    return ModelOut(
        id=model.id, provider=model.provider, api_model_id=model.api_model_id,
        label=model.label, cost_tier=model.cost_tier,
        capabilities=model.capabilities_list, enabled=bool(model.enabled),
    )


@router.get("/model-assignments", response_model=list[AssignmentOut])
def list_assignments(db: Session = Depends(get_db)):
    return db.query(ModelAssignment).all()


@router.put("/model-assignments", response_model=AssignmentOut)
def update_assignment(update: AssignmentUpdate, db: Session = Depends(get_db)):
    required_cap = TASK_REQUIRED_CAPABILITY.get(update.task)
    if required_cap:
        model = db.query(Model).filter(Model.id == update.model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        if required_cap not in model.capabilities_list:
            raise HTTPException(
                status_code=422,
                detail=f"Model '{model.label}' does not have required capability '{required_cap}' for task '{update.task}'",
            )

    assignment = db.query(ModelAssignment).filter(ModelAssignment.task == update.task).first()
    if assignment:
        assignment.model_id = update.model_id
    else:
        db.add(ModelAssignment(task=update.task, model_id=update.model_id))
    db.commit()
    return db.query(ModelAssignment).filter(ModelAssignment.task == update.task).first()
