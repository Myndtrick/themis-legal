import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.model_config import Model, ModelAssignment, ProviderKey
from app.services.model_seed import seed_models, SEED_MODELS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_model_table_creation(db):
    models = db.query(Model).all()
    assert models == []


def test_seed_models_creates_13_models(db):
    seed_models(db)
    models = db.query(Model).all()
    assert len(models) == 13


def test_seed_models_creates_default_assignments(db):
    seed_models(db)
    assignments = db.query(ModelAssignment).all()
    assert len(assignments) >= 7


def test_seed_models_is_idempotent(db):
    seed_models(db)
    seed_models(db)
    models = db.query(Model).all()
    assert len(models) == 13


def test_model_capabilities_stored_as_json(db):
    seed_models(db)
    o3 = db.query(Model).filter(Model.id == "o3").first()
    assert "reasoning" in o3.capabilities_list


def test_assignment_references_valid_model(db):
    seed_models(db)
    assignment = db.query(ModelAssignment).filter(
        ModelAssignment.task == "issue_classification"
    ).first()
    model = db.query(Model).filter(Model.id == assignment.model_id).first()
    assert model is not None
