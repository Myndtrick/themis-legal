"""SQLAlchemy models for multi-provider model configuration."""

import json
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from app.database import Base


class Model(Base):
    __tablename__ = "models"

    id = Column(String, primary_key=True)
    provider = Column(String, nullable=False)
    api_model_id = Column(String, nullable=False)
    label = Column(String, nullable=False)
    cost_tier = Column(String, nullable=False)
    capabilities = Column(Text, nullable=False, default='["chat"]')
    enabled = Column(Integer, default=1)

    @property
    def capabilities_list(self) -> list[str]:
        return json.loads(self.capabilities)

    @capabilities_list.setter
    def capabilities_list(self, value: list[str]):
        valid = {"chat", "ocr", "reasoning"}
        for cap in value:
            if cap not in valid:
                raise ValueError(f"Invalid capability: {cap}. Must be one of {valid}")
        self.capabilities = json.dumps(value)


class ModelAssignment(Base):
    __tablename__ = "model_assignments"

    task = Column(String, primary_key=True)
    model_id = Column(String, ForeignKey("models.id"), nullable=False)


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    provider = Column(String, primary_key=True)
    encrypted_key = Column(Text, nullable=False)
