from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Feature(Base):
    """
    Catalog shared by both buyer_requirement_features and property_features
    (e.g. "pool", "garden", "home_office") — one place to add a new
    feature, no migration, no hardcoded boolean columns.
    """

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
