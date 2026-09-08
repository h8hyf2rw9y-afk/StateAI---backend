from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for every *Read schema — lets Pydantic build a response directly from a SQLAlchemy ORM object."""

    model_config = ConfigDict(from_attributes=True)
