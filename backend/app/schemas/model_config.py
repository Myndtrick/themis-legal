from pydantic import BaseModel, ConfigDict


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    api_model_id: str
    label: str
    cost_tier: str
    capabilities: list[str]
    enabled: bool


class ModelUpdate(BaseModel):
    enabled: bool | None = None
    label: str | None = None


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task: str
    model_id: str


class AssignmentUpdate(BaseModel):
    task: str
    model_id: str
