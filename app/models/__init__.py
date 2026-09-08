"""
Import every model module here so Alembic's autogenerate (which inspects
Base.metadata) and SQLAlchemy's mapper configuration see the whole schema,
not just whichever model happened to be imported first.
"""

from app.models.base import Base  # noqa: F401
from app.models.external import auth_users  # noqa: F401
from app.models.organization import Organization, User  # noqa: F401
from app.models.contact import Contact, Role, ContactRole  # noqa: F401
from app.models.feature import Feature  # noqa: F401
from app.models.property import Property, PropertyFeature  # noqa: F401
from app.models.buyer_requirement import (  # noqa: F401
    BuyerRequirement,
    BuyerRequirementLocation,
    BuyerRequirementFeature,
)
from app.models.property_interest import PropertyInterest  # noqa: F401

__all__ = [
    "Base",
    "auth_users",
    "Organization",
    "User",
    "Contact",
    "Role",
    "ContactRole",
    "Feature",
    "Property",
    "PropertyFeature",
    "BuyerRequirement",
    "BuyerRequirementLocation",
    "BuyerRequirementFeature",
    "PropertyInterest",
]
