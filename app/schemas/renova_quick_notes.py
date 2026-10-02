from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class RenovaQuickNotesRequest(BaseModel):
    """A client-redacted call note. Full NSS, credit and phone values never belong here."""

    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class RenovaQuickNotesExtraction(BaseModel):
    """Non-sensitive fields the model may propose for the editable Renova form."""

    owner_name: str | None = Field(default=None, max_length=200)
    street_address: str | None = Field(default=None, max_length=300)
    neighborhood: str | None = Field(default=None, max_length=300)
    municipality: str | None = Field(default=None, max_length=300)
    postal_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    dwelling_type: Literal["house", "apartment"] | None = None
    is_duplex: bool | None = None
    floors: int | None = Field(default=None, ge=0, le=100)
    bathrooms: str | None = Field(default=None, pattern=r"^\d{1,2}(?:\.5)?$")
    bedrooms: int | None = Field(default=None, ge=0, le=100)
    property_tax_debt: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    property_tax_debt_unit: Literal["mxn", "years"] | None = None
    other_debt: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    water_debt: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    electricity_debt: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    gas_debt: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    owner_expected_amount: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    market_value: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    final_offer: str | None = Field(default=None, pattern=r"^\d+(?:\.\d{1,2})?$")
    sale_reason: str | None = Field(default=None, max_length=5000)
