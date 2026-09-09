"""
Realistic demo/test data for PropPilot — 20 fictional contacts spanning the
two ways a person enters the CRM (Case A: interested in a specific
property, via PropertyInterest; Case B: looking for a property, via
BuyerRequirement), plus the properties, roles, and locations/features they
reference. Everything belongs to one dedicated "State AI Demo Organization"
so it can be reset independently of anything else.

No fields are invented that don't exist on the current schema (see
app/models/) — no ai_score, no conversion_probability. Every contact also
gets a chronological Activity timeline (calls, WhatsApp, viewings, offers,
...) reflecting the same narrative already summarized in each entity's
`notes` field — the structured, queryable version of that history, which
is what future AI agents (Lead Intelligence, Follow-up, Sales Copilot) will
actually read instead of parsing free text. See the README's "Demo data"
section and the final report for more.

Usage:
    uv run python scripts/seed_demo_data.py            # create or update
    uv run python scripts/seed_demo_data.py --reset     # delete demo org (cascades), then exit
    uv run python scripts/seed_demo_data.py --reset --seed   # delete, then recreate fresh

Idempotent: every row's id is deterministic (uuid5 of a stable string key),
so re-running never creates duplicates — it updates existing rows in place.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# Run directly (`python scripts/seed_demo_data.py`), Python puts only this
# file's own directory on sys.path — not the repo root `app`/`scripts`
# packages live under. Add it so this works the same as `-m scripts.seed_demo_data`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.activity import Activity
from app.models.appointment import Appointment
from app.models.buyer_requirement import (
    BuyerRequirement,
    BuyerRequirementFeature,
    BuyerRequirementLocation,
)
from app.models.contact import Contact, ContactRole
from app.models.opportunity import Opportunity
from app.models.organization import Organization, User
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from app.models.task import Task

# ---------------------------------------------------------------------------
# Deterministic IDs
# ---------------------------------------------------------------------------

# Fixed, arbitrary namespace — never changes. Every demo row's id is
# uuid.uuid5(DEMO_NAMESPACE, "<stable-key>"), so the *same* key always
# produces the *same* id across runs, machines, and environments.
DEMO_NAMESPACE = uuid.UUID("6f2c9c2e-6b8e-4a7a-8c3a-2b7e6a1d9f00")

DEMO_ORG_KEY = "state-ai-demo-organization"
DEMO_ORG_NAME = "State AI Demo Organization"

# The local test login created earlier this session — re-pointed at the demo
# org (see the plan's "Decision I'm flagging" note) so it's actually visible
# in the frontend instead of sitting in a different, now-empty tenant.
EGR_TEST_USER_ID = uuid.UUID("faa9f262-15de-46be-9fe3-fe4e607d359e")


def det_id(key: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, key)


def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


def in_days(n: int) -> datetime:
    """Negative n gives a past (overdue) moment — used for the demo "overdue task" scenario."""
    return datetime.now(timezone.utc) + timedelta(days=n)


def upsert(session: Session, model_cls: type, id_: uuid.UUID, **fields: Any):
    """
    Create-if-missing, else update-in-place — never touches `created_at` on
    an existing row (an explicit `created_at` kwarg is only honored the
    first time a row is created). This is what makes the whole seed
    idempotent: re-running never inserts a duplicate, and doesn't drift an
    already-seeded row's creation timestamp on every run.
    """
    obj = session.get(model_cls, id_)
    if obj is None:
        obj = model_cls(id=id_, **fields)
        session.add(obj)
    else:
        for key, value in fields.items():
            if key == "created_at":
                continue
            setattr(obj, key, value)
    return obj


# ---------------------------------------------------------------------------
# Properties — the 5 named in the spec, plus enough additional inventory
# that every buyer requirement below has at least one plausible real match
# through GET /buyer-requirements/{id}/matches.
# ---------------------------------------------------------------------------

PROPERTIES: list[dict[str, Any]] = [
    {
        "key": "casa-valle-oriente",
        "title": "Casa Valle Oriente",
        "property_type": "house",
        "status": "active",
        "price": Decimal("5200000"),
        "city": "San Pedro Garza García",
        "state": "Nuevo León",
        "neighborhood": "Valle Oriente",
        "bedrooms": 3,
        "bathrooms": Decimal("2.5"),
        "construction_m2": Decimal("220"),
        "land_m2": Decimal("300"),
        "parking_spaces": 2,
        "description": "Casa de dos niveles en Valle Oriente, cerca de zona comercial y colegios.",
    },
    {
        "key": "departamento-del-valle",
        "title": "Departamento Del Valle",
        "property_type": "apartment",
        "status": "active",
        "price": Decimal("3400000"),
        "city": "San Pedro Garza García",
        "state": "Nuevo León",
        "neighborhood": "Del Valle",
        "bedrooms": 2,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("110"),
        "parking_spaces": 1,
        "description": "Departamento moderno en edificio con amenidades, a unos pasos de Del Valle.",
    },
    {
        "key": "casa-cumbres",
        "title": "Casa Cumbres",
        "property_type": "house",
        "status": "active",
        "price": Decimal("5800000"),
        "city": "Monterrey",
        "state": "Nuevo León",
        "neighborhood": "Cumbres",
        "bedrooms": 4,
        "bathrooms": Decimal("3"),
        "construction_m2": Decimal("260"),
        "land_m2": Decimal("350"),
        "parking_spaces": 2,
        "description": "Residencia familiar en Cumbres con jardín amplio y acabados de lujo.",
    },
    {
        "key": "casa-carretera-nacional",
        "title": "Casa Carretera Nacional",
        "property_type": "house",
        "status": "active",
        "price": Decimal("6400000"),
        "city": "Monterrey",
        "state": "Nuevo León",
        "neighborhood": "Carretera Nacional",
        "bedrooms": 3,
        "bathrooms": Decimal("3"),
        "construction_m2": Decimal("270"),
        "land_m2": Decimal("320"),
        "parking_spaces": 2,
        "description": "Casa de reciente construcción sobre Carretera Nacional, alta plusvalía.",
    },
    {
        "key": "casa-san-jeronimo",
        "title": "Casa San Jerónimo",
        "property_type": "house",
        "status": "active",
        "price": Decimal("4700000"),
        "city": "Monterrey",
        "state": "Nuevo León",
        "neighborhood": "San Jerónimo",
        "bedrooms": 3,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("200"),
        "land_m2": Decimal("250"),
        "parking_spaces": 2,
        "description": "Casa remodelada en San Jerónimo, lista para habitar.",
    },
    {
        "key": "casa-san-pedro-alejandro",
        "title": "Casa Valle Alto",
        "property_type": "house",
        "status": "active",
        "price": Decimal("4600000"),
        "city": "San Pedro Garza García",
        "state": "Nuevo León",
        "neighborhood": "Valle Oriente",
        "bedrooms": 3,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("190"),
        "land_m2": Decimal("220"),
        "parking_spaces": 2,
        "description": "Casa de un nivel en privada, ideal para primera compra en Valle Oriente.",
    },
    {
        "key": "depto-valle-oriente-diego",
        "title": "Departamento Vista Oriente",
        "property_type": "apartment",
        "status": "active",
        "price": Decimal("3600000"),
        "city": "San Pedro Garza García",
        "state": "Nuevo León",
        "neighborhood": "Valle Oriente",
        "bedrooms": 2,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("120"),
        "parking_spaces": 1,
        "description": "Departamento con vista panorámica, torre nueva en Valle Oriente.",
    },
    {
        "key": "depto-del-valle-gabriela",
        "title": "Departamento Plaza Valle",
        "property_type": "apartment",
        "status": "active",
        "price": Decimal("3300000"),
        "city": "San Pedro Garza García",
        "state": "Nuevo León",
        "neighborhood": "Del Valle",
        "bedrooms": 2,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("105"),
        "parking_spaces": 1,
        "description": "Departamento compacto y funcional a pasos de Plaza Del Valle.",
    },
    {
        "key": "depto-monterrey-ricardo",
        "title": "Departamento Centro MTY",
        "property_type": "apartment",
        "status": "active",
        "price": Decimal("2800000"),
        "city": "Monterrey",
        "state": "Nuevo León",
        "neighborhood": "Centro",
        "bedrooms": 2,
        "bathrooms": Decimal("1"),
        "construction_m2": Decimal("80"),
        "parking_spaces": 1,
        "description": "Departamento con potencial de renta en el centro de Monterrey.",
    },
    {
        "key": "local-san-nicolas-ricardo",
        "title": "Local Comercial San Nicolás",
        "property_type": "commercial",
        "status": "active",
        "price": Decimal("3200000"),
        "city": "San Nicolás de los Garza",
        "state": "Nuevo León",
        "neighborhood": "Anáhuac",
        "construction_m2": Decimal("150"),
        "parking_spaces": 3,
        "description": "Local comercial en avenida de alto tráfico, apto para inversión.",
    },
    {
        "key": "casa-cumbres-andres",
        "title": "Casa Cumbres Elite",
        "property_type": "house",
        "status": "active",
        "price": Decimal("5600000"),
        "city": "Monterrey",
        "state": "Nuevo León",
        "neighborhood": "Cumbres",
        "bedrooms": 4,
        "bathrooms": Decimal("3"),
        "construction_m2": Decimal("240"),
        "land_m2": Decimal("300"),
        "parking_spaces": 2,
        "description": "Casa familiar con jardín trasero, sección exclusiva de Cumbres.",
    },
    {
        "key": "terreno-apodaca-jorge",
        "title": "Terreno Residencial Apodaca",
        "property_type": "land",
        "status": "active",
        "price": Decimal("2600000"),
        "city": "Apodaca",
        "state": "Nuevo León",
        "neighborhood": "Fundadores",
        "land_m2": Decimal("300"),
        "description": "Terreno plano en fraccionamiento residencial, listo para construir.",
    },
    {
        "key": "casa-santa-catarina-sergio",
        "title": "Casa Valle Alto Santa Catarina",
        "property_type": "house",
        "status": "active",
        "price": Decimal("4200000"),
        "city": "Santa Catarina",
        "state": "Nuevo León",
        "neighborhood": "Valle Alto",
        "bedrooms": 3,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("200"),
        "land_m2": Decimal("250"),
        "parking_spaces": 2,
        "description": "Casa de reciente entrega en Santa Catarina, cerca de Carretera Saltillo.",
    },
    {
        "key": "casa-guadalupe-eduardo",
        "title": "Casa Contry Guadalupe",
        "property_type": "house",
        "status": "active",
        "price": Decimal("3500000"),
        "city": "Guadalupe",
        "state": "Nuevo León",
        "neighborhood": "Contry",
        "bedrooms": 3,
        "bathrooms": Decimal("2"),
        "construction_m2": Decimal("180"),
        "land_m2": Decimal("200"),
        "parking_spaces": 2,
        "description": "Casa familiar en Contry, zona consolidada con buen acceso.",
    },
]

# ---------------------------------------------------------------------------
# Contacts — 10 new leads + 10 existing leads, exactly as described in the
# brief. `source`/`preferred_contact_method` filled in with the closest
# existing enum value where the brief didn't specify one.
# ---------------------------------------------------------------------------

CONTACTS: list[dict[str, Any]] = [
    # --- 10 NEW LEADS ---
    {
        "key": "alejandro-torres", "first_name": "Alejandro", "last_name": "Torres",
        "source": "referral", "preferred_contact_method": "whatsapp", "days_ago": 2,
        "notes": "Busca casa en San Pedro Garza García o Valle Oriente, MXN 4M-5M. Prioridad alta.",
    },
    {
        "key": "sofia-martinez", "first_name": "Sofía", "last_name": "Martínez",
        "source": "facebook", "preferred_contact_method": "whatsapp", "days_ago": 1,
        "notes": "Vio Casa Valle Oriente en Facebook y pidió más información.",
    },
    {
        "key": "diego-ramirez", "first_name": "Diego", "last_name": "Ramírez",
        "source": "website", "preferred_contact_method": "whatsapp", "days_ago": 3,
        "notes": "Busca departamento en Valle Oriente o Del Valle, MXN 3M-4M.",
    },
    {
        "key": "fernanda-lopez", "first_name": "Fernanda", "last_name": "López",
        "source": "inmuebles24", "preferred_contact_method": "email", "days_ago": 3,
        "notes": "Preguntó precio y disponibilidad de Departamento Del Valle vía Inmuebles24.",
    },
    {
        "key": "ricardo-hernandez", "first_name": "Ricardo", "last_name": "Hernández",
        "source": "referral", "preferred_contact_method": "phone", "days_ago": 4,
        "notes": "Inversionista — busca departamento o local comercial para renta en Monterrey, San Nicolás o Guadalupe.",
    },
    {
        "key": "valeria-garcia", "first_name": "Valeria", "last_name": "García",
        "source": "instagram", "preferred_contact_method": "whatsapp", "days_ago": 1,
        "notes": "Preguntó precio y características de Casa Cumbres por Instagram.",
    },
    {
        "key": "andres-morales", "first_name": "Andrés", "last_name": "Morales",
        "source": "website", "preferred_contact_method": "whatsapp", "days_ago": 2,
        "notes": "Comprador familiar — busca casa en Cumbres o Carretera Nacional, prefiere jardín.",
    },
    {
        "key": "mariana-sanchez", "first_name": "Mariana", "last_name": "Sánchez",
        "source": "referral", "preferred_contact_method": "whatsapp", "days_ago": 4,
        "notes": "Referida por cliente anterior. Interesada en Casa Carretera Nacional, quiere agendar visita.",
    },
    {
        "key": "jorge-castillo", "first_name": "Jorge", "last_name": "Castillo",
        "source": "website", "preferred_contact_method": "phone", "days_ago": 5,
        "notes": "Busca terreno en Apodaca o Escobedo para construir casa residencial.",
    },
    {
        "key": "daniela-flores", "first_name": "Daniela", "last_name": "Flores",
        "source": "marketplace", "preferred_contact_method": "whatsapp", "days_ago": 2,
        "notes": "Preguntó opciones de financiamiento para Casa San Jerónimo vía Facebook Marketplace.",
    },
    # --- 10 EXISTING LEADS ---
    {
        "key": "carlos-mendoza", "first_name": "Carlos", "last_name": "Mendoza",
        "source": "website", "preferred_contact_method": "phone", "days_ago": 14,
        "notes": (
            "Contacto inicial hace 14 días. Recibió 3 recomendaciones de propiedades. "
            "Visitó 2 propiedades. Sin respuesta desde hace 5 días. Requiere seguimiento — "
            "candidato de alto valor."
        ),
    },
    {
        "key": "laura-gonzalez", "first_name": "Laura", "last_name": "González",
        "source": "referral", "preferred_contact_method": "whatsapp", "days_ago": 12,
        "notes": "Completó visita a Casa Valle Oriente, le gustó, preguntó por negociación. Posible oferta — lead caliente.",
    },
    {
        "key": "miguel-herrera", "first_name": "Miguel", "last_name": "Herrera",
        "source": "website", "preferred_contact_method": "whatsapp", "days_ago": 10,
        "notes": "Recibió varias recomendaciones de departamentos, ninguna coincidió bien. Necesita mejor matching.",
    },
    {
        "key": "paola-rodriguez", "first_name": "Paola", "last_name": "Rodríguez",
        "source": "inmuebles24", "preferred_contact_method": "whatsapp", "days_ago": 15,
        "notes": "Visitó Casa Cumbres, envió oferta informal. Vendedor está revisando — en negociación, alta prioridad.",
    },
    {
        "key": "fernando-vargas", "first_name": "Fernando", "last_name": "Vargas",
        "source": "referral", "preferred_contact_method": "phone", "days_ago": 11,
        "notes": "Visitó 3 propiedades en Carretera Nacional. Comprador altamente calificado, preaprobado.",
    },
    {
        "key": "gabriela-ortiz", "first_name": "Gabriela", "last_name": "Ortiz",
        "source": "inmuebles24", "preferred_contact_method": "whatsapp", "days_ago": 18,
        "notes": (
            "Contactó por Departamento Del Valle, lo visitó, decidió que no era para ella. "
            "Sigue buscando — ver requerimiento de compra activo."
        ),
    },
    {
        "key": "sergio-navarro", "first_name": "Sergio", "last_name": "Navarro",
        "source": "website", "preferred_contact_method": "whatsapp", "days_ago": 25,
        "notes": "Comprador activo. Actualizó su búsqueda — presupuesto y zonas cambiaron recientemente.",
    },
    {
        "key": "natalia-ramirez", "first_name": "Natalia", "last_name": "Ramírez",
        "source": "referral", "preferred_contact_method": "whatsapp", "days_ago": 9,
        "notes": "Primera visita completada a Casa Carretera Nacional, pidió segunda visita — ya agendada. Alta intención.",
    },
    {
        "key": "eduardo-jimenez", "first_name": "Eduardo", "last_name": "Jiménez",
        "source": "website", "preferred_contact_method": "email", "days_ago": 21,
        "notes": "Solo conversación inicial. Sin actividad desde hace 21 días — lead frío.",
    },
    {
        "key": "carolina-reyes", "first_name": "Carolina", "last_name": "Reyes",
        "source": "facebook", "preferred_contact_method": "whatsapp", "days_ago": 16,
        "notes": (
            "Contacto inicial, visita completada, seguimiento completado. Pidió precio final, "
            "está considerando hacer una oferta. Alta intención."
        ),
    },
]


def contact_email(key: str) -> str:
    return f"{key.replace('-', '.')}@example.com"


def contact_phone(seq: int) -> str:
    return f"+52 81 5500 {seq:04d}"


# ---------------------------------------------------------------------------
# Property interests — Case A (10)
# ---------------------------------------------------------------------------

PROPERTY_INTERESTS: list[dict[str, Any]] = [
    {
        "contact_key": "sofia-martinez", "property_key": "casa-valle-oriente", "status": "new",
        "source": "facebook", "first_contact_days_ago": 1, "last_contact_days_ago": 1,
        "notes": "Vio la propiedad en Facebook y solicitó información.",
    },
    {
        "contact_key": "fernanda-lopez", "property_key": "departamento-del-valle", "status": "contacted",
        "source": "inmuebles24", "first_contact_days_ago": 3, "last_contact_days_ago": 2,
        "notes": "Solicitó precio y disponibilidad.",
    },
    {
        "contact_key": "valeria-garcia", "property_key": "casa-cumbres", "status": "new",
        "source": "instagram", "first_contact_days_ago": 1, "last_contact_days_ago": 1,
        "notes": "Preguntó precio y características por Instagram.",
    },
    {
        "contact_key": "mariana-sanchez", "property_key": "casa-carretera-nacional", "status": "interested",
        "source": "referral", "first_contact_days_ago": 4, "last_contact_days_ago": 3,
        "notes": "Referida por cliente anterior. Quiere agendar una visita.",
    },
    {
        "contact_key": "daniela-flores", "property_key": "casa-san-jeronimo", "status": "new",
        "source": "marketplace", "first_contact_days_ago": 2, "last_contact_days_ago": 2,
        "notes": "Preguntó por opciones de financiamiento.",
    },
    {
        "contact_key": "laura-gonzalez", "property_key": "casa-valle-oriente", "status": "offer",
        "source": "referral", "first_contact_days_ago": 12, "last_contact_days_ago": 2,
        "notes": "Visita completada, le encantó la propiedad, preguntó por negociación. Posible oferta.",
    },
    {
        "contact_key": "paola-rodriguez", "property_key": "casa-cumbres", "status": "negotiation",
        "source": "inmuebles24", "first_contact_days_ago": 15, "last_contact_days_ago": 3,
        "notes": "Visitó la propiedad, envió oferta informal. El vendedor está revisando.",
    },
    {
        "contact_key": "gabriela-ortiz", "property_key": "departamento-del-valle", "status": "not_interested",
        "source": "inmuebles24", "first_contact_days_ago": 18, "last_contact_days_ago": 10,
        "notes": (
            "Visitó la propiedad pero decidió que no era para ella. Sigue interesada en comprar — "
            "ver el requerimiento de compra activo creado a partir de este rechazo."
        ),
    },
    {
        "contact_key": "natalia-ramirez", "property_key": "casa-carretera-nacional", "status": "viewing_scheduled",
        "source": "referral", "first_contact_days_ago": 9, "last_contact_days_ago": 1,
        "notes": "Primera visita completada. Pidió una segunda visita, ya agendada. Muy alta intención.",
    },
    {
        "contact_key": "carolina-reyes", "property_key": "casa-san-jeronimo", "status": "negotiation",
        "source": "facebook", "first_contact_days_ago": 16, "last_contact_days_ago": 2,
        "notes": "Visita y seguimiento completados. Pidió el precio final y está considerando una oferta.",
    },
]

# ---------------------------------------------------------------------------
# Buyer requirements — Case B. Sergio and Ricardo each get two rows (see
# the plan: superseded/updated requirements and multiple property types
# are represented as separate rows rather than schema changes).
# ---------------------------------------------------------------------------

BUYER_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "req_key": "alejandro-torres:1", "contact_key": "alejandro-torres",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("4000000"), "budget_max": Decimal("5000000"),
        "bedrooms_min": 3, "bathrooms_min": Decimal("2"), "construction_m2_min": Decimal("180"),
        "parking_spaces_min": 2, "timeline": "1_3_months", "financing_type": "mortgage",
        "preapproval_status": "in_process",
        "motivation": "Busca su primera casa familiar en zona premium.",
        "notes": "Prioridad alta — activamente buscando casa.",
        "days_ago": 2,
        "locations": ["San Pedro Garza García", "Valle Oriente"],
        "features": [],
    },
    {
        "req_key": "diego-ramirez:1", "contact_key": "diego-ramirez",
        "purpose": "buy", "status": "active", "property_type": "apartment",
        "budget_min": Decimal("3000000"), "budget_max": Decimal("4000000"),
        "bedrooms_min": 2, "bathrooms_min": Decimal("2"), "parking_spaces_min": 1,
        "timeline": "3_6_months", "financing_type": "mortgage",
        "notes": None, "days_ago": 3,
        "locations": ["Valle Oriente", "Del Valle"],
        "features": [],
    },
    {
        "req_key": "ricardo-hernandez:1", "contact_key": "ricardo-hernandez",
        "purpose": "invest", "status": "active", "property_type": "apartment",
        "budget_min": Decimal("2500000"), "budget_max": Decimal("4000000"),
        "timeline": "3_6_months",
        "motivation": "Oportunidad de renta/inversión.",
        "notes": "Requerimiento 1 de 2 — también busca local comercial (ver requerimiento aparte).",
        "days_ago": 4,
        "locations": ["Monterrey", "San Nicolás de los Garza", "Guadalupe"],
        "features": [],
    },
    {
        "req_key": "ricardo-hernandez:2", "contact_key": "ricardo-hernandez",
        "purpose": "invest", "status": "active", "property_type": "commercial",
        "budget_min": Decimal("2500000"), "budget_max": Decimal("4000000"),
        "timeline": "3_6_months",
        "motivation": "Oportunidad de renta/inversión — local comercial pequeño.",
        "notes": "Requerimiento 2 de 2 — también busca departamento (ver requerimiento aparte).",
        "days_ago": 4,
        "locations": ["Monterrey", "San Nicolás de los Garza", "Guadalupe"],
        "features": [],
    },
    {
        "req_key": "andres-morales:1", "contact_key": "andres-morales",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("5000000"), "budget_max": Decimal("6500000"),
        "bedrooms_min": 3, "bathrooms_min": Decimal("2"), "parking_spaces_min": 2,
        "timeline": "1_3_months", "financing_type": "mortgage", "preapproval_status": "preapproved",
        "notes": None, "days_ago": 2,
        "locations": ["Cumbres", "Carretera Nacional"],
        "features": [("garden", "preferred")],
    },
    {
        "req_key": "jorge-castillo:1", "contact_key": "jorge-castillo",
        "purpose": "buy", "status": "active", "property_type": "land",
        "budget_min": Decimal("2000000"), "budget_max": Decimal("3500000"),
        "timeline": "6_12_months",
        "motivation": "Construir propiedad residencial.",
        "notes": None, "days_ago": 5,
        "locations": ["Apodaca", "Escobedo"],
        "features": [],
    },
    {
        "req_key": "carlos-mendoza:1", "contact_key": "carlos-mendoza",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("4500000"), "budget_max": Decimal("5500000"),
        "bedrooms_min": 3, "bathrooms_min": Decimal("2"), "parking_spaces_min": 2,
        "notes": (
            "Contacto inicial hace 14 días. Recibió 3 recomendaciones, visitó 2 propiedades. "
            "Sin respuesta hace 5 días — requiere seguimiento."
        ),
        "days_ago": 14,
        "locations": ["San Pedro Garza García", "Santa Catarina"],
        "features": [],
    },
    {
        "req_key": "miguel-herrera:1", "contact_key": "miguel-herrera",
        "purpose": "buy", "status": "active", "property_type": "apartment",
        "budget_min": Decimal("3500000"), "budget_max": Decimal("4500000"),
        "notes": "Recibió varias recomendaciones que no coincidieron bien — necesita mejor matching.",
        "days_ago": 10,
        "locations": ["San Pedro Garza García", "Valle Oriente"],
        "features": [],
    },
    {
        "req_key": "fernando-vargas:1", "contact_key": "fernando-vargas",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("6000000"), "budget_max": Decimal("7000000"),
        "bedrooms_min": 3, "bathrooms_min": Decimal("3"), "construction_m2_min": Decimal("250"),
        "parking_spaces_min": 2, "financing_type": "mortgage", "preapproval_status": "preapproved",
        "notes": "Visitó 3 propiedades — comprador altamente calificado.",
        "days_ago": 11,
        "locations": ["Carretera Nacional"],
        "features": [],
    },
    {
        "req_key": "gabriela-ortiz:1", "contact_key": "gabriela-ortiz",
        "purpose": "buy", "status": "active", "property_type": "apartment",
        "budget_min": Decimal("3000000"), "budget_max": Decimal("4000000"),
        "bedrooms_min": 2, "bathrooms_min": Decimal("2"), "parking_spaces_min": 1,
        "notes": (
            "Creado a partir del rechazo de Departamento Del Valle (ver property interest). "
            "Sigue buscando algo similar en la misma zona."
        ),
        "days_ago": 10,
        "locations": ["Valle Oriente", "Del Valle"],
        "features": [],
    },
    {
        "req_key": "sergio-navarro:1", "contact_key": "sergio-navarro",
        "purpose": "buy", "status": "cancelled", "property_type": "house",
        "budget_min": Decimal("5000000"), "budget_max": Decimal("6000000"),
        "notes": "Reemplazado por un requerimiento actualizado (presupuesto y zonas cambiaron).",
        "days_ago": 25,
        "locations": ["San Pedro Garza García"],
        "features": [],
    },
    {
        "req_key": "sergio-navarro:2", "contact_key": "sergio-navarro",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("4000000"), "budget_max": Decimal("4500000"),
        "notes": "Requerimiento actualizado — reemplaza la búsqueda original en San Pedro.",
        "days_ago": 6,
        "locations": ["Santa Catarina", "Cumbres"],
        "features": [],
    },
    {
        "req_key": "eduardo-jimenez:1", "contact_key": "eduardo-jimenez",
        "purpose": "buy", "status": "active", "property_type": "house",
        "budget_min": Decimal("3000000"), "budget_max": Decimal("4000000"),
        "notes": "Solo conversación inicial. Sin actividad desde hace 21 días — lead frío.",
        "days_ago": 21,
        "locations": ["Monterrey", "Guadalupe"],
        "features": [],
    },
]

# Every contact in this dataset is buyer-side; Ricardo is additionally an
# investor, and Fernando is additionally a seller — see OPPORTUNITIES below,
# where he's both buying a new home and selling his current one (the exact
# "later sells their own property" scenario the Opportunity domain is meant
# to represent — see app/models/opportunity.py).
CONTACT_ROLES: dict[str, list[str]] = {c["key"]: ["buyer"] for c in CONTACTS}
CONTACT_ROLES["ricardo-hernandez"].append("investor")
CONTACT_ROLES["fernando-vargas"].append("seller")

# ---------------------------------------------------------------------------
# Opportunities — the actual sales processes an advisor is managing, on top
# of the buyer requirements/property interests above. Deliberately reuses
# existing contacts/properties/buyer requirements rather than inventing new
# ones (see app/models/opportunity.py: "no duplicated client information").
# Covers: an active buy search, negotiation, an offer, a viewing, a
# property-selected buy, an active sell listing, a won deal, a lost deal,
# and a contact with two opportunities over time (Gabriela: her rejected
# Del Valle opportunity is separate from her new active search — same
# transition already modeled by her buyer_requirement/property_interest
# pair; Fernando: buying a new home while also selling his current one).
#
# `closed_days_ago`, when present, backfills `closed_at` directly — seeding
# writes rows straight via SQLAlchemy (like every other entity in this
# script), not through OpportunityService, so the auto-stamping that
# service normally does on a real stage change has to be done by hand here.
# ---------------------------------------------------------------------------

OPPORTUNITIES: list[dict[str, Any]] = [
    {
        "key": "alejandro-torres:buy", "contact_key": "alejandro-torres", "opportunity_type": "buy",
        "buyer_requirement_key": "alejandro-torres:1", "stage": "search",
        "title": "Búsqueda de casa — Alejandro Torres",
        "expected_value": Decimal("4500000"), "probability": 40, "days_ago": 2,
    },
    {
        "key": "laura-gonzalez:buy", "contact_key": "laura-gonzalez", "opportunity_type": "buy",
        "property_key": "casa-valle-oriente", "stage": "negotiation",
        "title": "Negociación Casa Valle Oriente — Laura González",
        "expected_value": Decimal("5200000"), "probability": 65, "days_ago": 12,
    },
    {
        "key": "paola-rodriguez:buy", "contact_key": "paola-rodriguez", "opportunity_type": "buy",
        "property_key": "casa-cumbres", "stage": "offer",
        "title": "Oferta Casa Cumbres — Paola Rodríguez",
        "expected_value": Decimal("5700000"), "probability": 55, "days_ago": 15,
    },
    {
        "key": "natalia-ramirez:buy", "contact_key": "natalia-ramirez", "opportunity_type": "buy",
        "property_key": "casa-carretera-nacional", "stage": "showing",
        "title": "Visitas Casa Carretera Nacional — Natalia Ramírez",
        "expected_value": Decimal("6400000"), "probability": 50, "days_ago": 9,
    },
    {
        "key": "fernando-vargas:buy", "contact_key": "fernando-vargas", "opportunity_type": "buy",
        "buyer_requirement_key": "fernando-vargas:1", "property_key": "casa-carretera-nacional",
        "stage": "property_selected",
        "title": "Compra de casa nueva — Fernando Vargas",
        "expected_value": Decimal("6400000"), "probability": 60, "days_ago": 11,
    },
    {
        "key": "fernando-vargas:sell", "contact_key": "fernando-vargas", "opportunity_type": "sell",
        "property_key": "casa-cumbres-andres", "stage": "listing",
        "title": "Venta de propiedad actual — Fernando Vargas",
        "expected_value": Decimal("5600000"), "probability": 30, "days_ago": 6,
    },
    {
        "key": "carolina-reyes:buy", "contact_key": "carolina-reyes", "opportunity_type": "buy",
        "property_key": "casa-san-jeronimo", "stage": "negotiation",
        "title": "Negociación Casa San Jerónimo — Carolina Reyes",
        "expected_value": Decimal("4700000"), "probability": 60, "days_ago": 16,
    },
    {
        "key": "sergio-navarro:won", "contact_key": "sergio-navarro", "opportunity_type": "buy",
        "buyer_requirement_key": "sergio-navarro:2", "property_key": "casa-santa-catarina-sergio",
        "stage": "won", "closed_days_ago": 1,
        "title": "Compra cerrada — Sergio Navarro",
        "expected_value": Decimal("4200000"), "probability": 100, "days_ago": 6,
    },
    {
        "key": "gabriela-ortiz:lost", "contact_key": "gabriela-ortiz", "opportunity_type": "buy",
        "property_key": "departamento-del-valle", "stage": "lost",
        "lost_reason": "chose_another_property", "closed_days_ago": 10,
        "title": "Departamento Del Valle — no avanzó",
        "expected_value": Decimal("3300000"), "probability": 0, "days_ago": 18,
    },
    {
        "key": "gabriela-ortiz:buy", "contact_key": "gabriela-ortiz", "opportunity_type": "buy",
        "buyer_requirement_key": "gabriela-ortiz:1", "stage": "search",
        "title": "Nueva búsqueda — Gabriela Ortiz",
        "expected_value": Decimal("3500000"), "probability": 35, "days_ago": 10,
    },
    {
        "key": "carlos-mendoza:buy", "contact_key": "carlos-mendoza", "opportunity_type": "buy",
        "buyer_requirement_key": "carlos-mendoza:1", "stage": "qualification",
        "title": "Seguimiento pendiente — Carlos Mendoza",
        "expected_value": Decimal("5000000"), "probability": 30, "days_ago": 14,
    },
]

# ---------------------------------------------------------------------------
# Tasks — demo scenario: an overdue follow-up on Carlos's stalled opportunity
# (matches his existing notes/activities: "sin respuesta desde hace 5 días").
# ---------------------------------------------------------------------------

TASKS: list[dict[str, Any]] = [
    {
        "key": "carlos-mendoza:follow-up", "contact_key": "carlos-mendoza",
        "buyer_requirement_key": "carlos-mendoza:1", "opportunity_key": "carlos-mendoza:buy",
        "title": "Seguimiento — sin respuesta hace 5 días", "task_type": "follow_up",
        "priority": "high", "status": "pending", "due_in_days": -2,
        "description": "Cliente de alto valor sin respuesta — requiere seguimiento urgente.",
    },
]

# ---------------------------------------------------------------------------
# Appointments — demo scenario: Natalia's already-agreed second viewing
# (matches her existing activity: "pidió una segunda visita — ya agendada").
# ---------------------------------------------------------------------------

APPOINTMENTS: list[dict[str, Any]] = [
    {
        "key": "natalia-ramirez:second-viewing", "contact_key": "natalia-ramirez",
        "property_key": "casa-carretera-nacional", "opportunity_key": "natalia-ramirez:buy",
        "title": "Segunda visita — Casa Carretera Nacional", "appointment_type": "showing",
        "status": "confirmed", "start_in_days": 2, "duration_hours": 1,
        "description": "Segunda visita solicitada por la clienta.",
    },
]

# ---------------------------------------------------------------------------
# Activities — a chronological timeline per contact (oldest first), the
# structured version of the narrative already summarized in each contact's
# `notes`. Every one of the 20 gets at least one entry; the "existing
# leads" get richer, multi-step timelines matching their detailed
# scenarios. Inbound "chat" messages from Facebook/Instagram/Marketplace
# are logged as `whatsapp` (closest existing type to a customer-facing chat
# channel) rather than stretching `call`/`email` to fit or inventing a new
# type — flagged here rather than silently.
# ---------------------------------------------------------------------------

ACTIVITIES: dict[str, list[dict[str, Any]]] = {
    # --- 10 new leads ---
    "alejandro-torres": [
        {"days_ago": 2, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — busca casa en San Pedro Garza García o Valle Oriente."},
        {"days_ago": 1, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron recomendaciones de propiedades."},
        {"days_ago": 0, "activity_type": "follow_up", "direction": "outbound",
         "notes": "Seguimiento — cliente en proceso de preaprobación hipotecaria."},
    ],
    "sofia-martinez": [
        {"days_ago": 1, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-valle-oriente",
         "notes": "Vio la propiedad en Facebook y escribió pidiendo información."},
    ],
    "diego-ramirez": [
        {"days_ago": 3, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — busca departamento en Valle Oriente o Del Valle."},
        {"days_ago": 2, "activity_type": "email", "direction": "outbound",
         "notes": "Se enviaron opciones de departamentos disponibles."},
    ],
    "fernanda-lopez": [
        {"days_ago": 3, "activity_type": "email", "direction": "inbound", "property_key": "departamento-del-valle",
         "notes": "Preguntó precio y disponibilidad vía Inmuebles24."},
        {"days_ago": 2, "activity_type": "email", "direction": "outbound", "property_key": "departamento-del-valle",
         "notes": "Se envió información de precio y disponibilidad."},
    ],
    "ricardo-hernandez": [
        {"days_ago": 4, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — inversionista busca departamento o local comercial para renta."},
        {"days_ago": 3, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se compartieron opciones de inversión en Monterrey y San Nicolás."},
    ],
    "valeria-garcia": [
        {"days_ago": 1, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-cumbres",
         "notes": "Preguntó precio y características por Instagram."},
    ],
    "andres-morales": [
        {"days_ago": 2, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — comprador familiar busca casa con jardín."},
        {"days_ago": 1, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron opciones en Cumbres y Carretera Nacional."},
    ],
    "mariana-sanchez": [
        {"days_ago": 4, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-carretera-nacional",
         "notes": "Referida por cliente anterior, preguntó por la propiedad."},
        {"days_ago": 3, "activity_type": "call", "direction": "outbound", "property_key": "casa-carretera-nacional",
         "notes": "Se coordinó para agendar visita."},
    ],
    "jorge-castillo": [
        {"days_ago": 5, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — busca terreno en Apodaca o Escobedo para construir."},
        {"days_ago": 4, "activity_type": "email", "direction": "outbound",
         "notes": "Se enviaron opciones de terrenos disponibles."},
    ],
    "daniela-flores": [
        {"days_ago": 2, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-san-jeronimo",
         "notes": "Preguntó por opciones de financiamiento vía Facebook Marketplace."},
    ],
    # --- 10 existing leads ---
    "carlos-mendoza": [
        {"days_ago": 14, "activity_type": "call", "direction": "inbound", "notes": "Contacto inicial."},
        {"days_ago": 13, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron 3 recomendaciones de propiedades."},
        {"days_ago": 10, "activity_type": "property_viewing", "property_key": "casa-san-pedro-alejandro",
         "notes": "Visita a la primera propiedad recomendada, en San Pedro."},
        {"days_ago": 8, "activity_type": "property_viewing", "property_key": "casa-santa-catarina-sergio",
         "notes": "Visita a la segunda propiedad recomendada, en Santa Catarina."},
        {"days_ago": 5, "activity_type": "follow_up", "direction": "outbound",
         "notes": "Seguimiento enviado — sin respuesta desde entonces.", "opportunity_key": "carlos-mendoza:buy"},
    ],
    "laura-gonzalez": [
        {"days_ago": 12, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-valle-oriente",
         "notes": "Consulta inicial sobre la propiedad."},
        {"days_ago": 9, "activity_type": "property_viewing", "property_key": "casa-valle-oriente",
         "notes": "Visita a la propiedad — cliente muy interesada."},
        {"days_ago": 5, "activity_type": "note", "property_key": "casa-valle-oriente",
         "notes": "Cliente confirmó que le encantó la propiedad."},
        {"days_ago": 2, "activity_type": "negotiation", "direction": "outbound", "property_key": "casa-valle-oriente",
         "notes": "Preguntó por posibilidad de negociar el precio — posible oferta.",
         "opportunity_key": "laura-gonzalez:buy"},
    ],
    "miguel-herrera": [
        {"days_ago": 10, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — busca departamento en San Pedro o Valle Oriente."},
        {"days_ago": 7, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron las primeras recomendaciones."},
        {"days_ago": 4, "activity_type": "note",
         "notes": "Ninguna opción coincidió bien — se requieren mejores recomendaciones."},
    ],
    "paola-rodriguez": [
        {"days_ago": 15, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-cumbres",
         "notes": "Consulta inicial sobre la propiedad."},
        {"days_ago": 11, "activity_type": "property_viewing", "property_key": "casa-cumbres",
         "notes": "Visita a la propiedad.", "opportunity_key": "paola-rodriguez:buy"},
        {"days_ago": 6, "activity_type": "offer", "direction": "inbound", "property_key": "casa-cumbres",
         "notes": "Cliente envió una oferta informal.", "opportunity_key": "paola-rodriguez:buy"},
        {"days_ago": 3, "activity_type": "negotiation", "property_key": "casa-cumbres",
         "notes": "El vendedor está revisando la oferta.", "opportunity_key": "paola-rodriguez:buy"},
    ],
    "fernando-vargas": [
        {"days_ago": 11, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — comprador preaprobado busca casa en Carretera Nacional."},
        {"days_ago": 8, "activity_type": "property_viewing", "property_key": "casa-carretera-nacional",
         "notes": "Primera visita."},
        {"days_ago": 6, "activity_type": "property_viewing", "property_key": "casa-cumbres-andres",
         "notes": "Segunda visita, opción alterna en Cumbres."},
        {"days_ago": 4, "activity_type": "property_viewing", "property_key": "casa-san-jeronimo",
         "notes": "Tercera visita, opción alterna en San Jerónimo."},
        {"days_ago": 2, "activity_type": "follow_up", "direction": "outbound",
         "notes": "Muy interesado, evaluando opciones — comprador altamente calificado."},
    ],
    "gabriela-ortiz": [
        {"days_ago": 18, "activity_type": "whatsapp", "direction": "inbound", "property_key": "departamento-del-valle",
         "notes": "Consulta inicial sobre la propiedad."},
        {"days_ago": 14, "activity_type": "property_viewing", "property_key": "departamento-del-valle",
         "notes": "Visita a la propiedad."},
        {"days_ago": 10, "activity_type": "note", "property_key": "departamento-del-valle",
         "notes": "Cliente decidió que la propiedad no era para ella — no interesada.",
         "opportunity_key": "gabriela-ortiz:lost"},
        {"days_ago": 10, "activity_type": "follow_up", "direction": "outbound",
         "notes": "Cliente sigue buscando — se inicia búsqueda con nuevos criterios (ver requerimiento de compra).",
         "opportunity_key": "gabriela-ortiz:buy"},
    ],
    "sergio-navarro": [
        {"days_ago": 25, "activity_type": "call", "direction": "inbound",
         "notes": "Contacto inicial — busca casa en San Pedro, MXN 5M-6M."},
        {"days_ago": 20, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron opciones en San Pedro."},
        {"days_ago": 6, "activity_type": "note",
         "notes": "Cliente actualizó su búsqueda — presupuesto y zonas cambiaron a Santa Catarina y Cumbres, MXN 4M-4.5M."},
        {"days_ago": 4, "activity_type": "whatsapp", "direction": "outbound",
         "notes": "Se enviaron nuevas opciones según los criterios actualizados."},
    ],
    "natalia-ramirez": [
        {"days_ago": 9, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-carretera-nacional",
         "notes": "Consulta inicial sobre la propiedad."},
        {"days_ago": 5, "activity_type": "property_viewing", "property_key": "casa-carretera-nacional",
         "notes": "Primera visita completada.", "opportunity_key": "natalia-ramirez:buy"},
        {"days_ago": 1, "activity_type": "follow_up", "direction": "inbound", "property_key": "casa-carretera-nacional",
         "notes": "Cliente solicitó una segunda visita — ya agendada.", "opportunity_key": "natalia-ramirez:buy"},
    ],
    "eduardo-jimenez": [
        {"days_ago": 21, "activity_type": "call", "direction": "inbound",
         "notes": "Conversación inicial — busca casa en Monterrey o Guadalupe."},
    ],
    "carolina-reyes": [
        {"days_ago": 16, "activity_type": "whatsapp", "direction": "inbound", "property_key": "casa-san-jeronimo",
         "notes": "Consulta inicial sobre la propiedad vía Facebook."},
        {"days_ago": 12, "activity_type": "property_viewing", "property_key": "casa-san-jeronimo",
         "notes": "Visita a la propiedad."},
        {"days_ago": 7, "activity_type": "follow_up", "direction": "outbound", "property_key": "casa-san-jeronimo",
         "notes": "Seguimiento completado."},
        {"days_ago": 4, "activity_type": "note", "property_key": "casa-san-jeronimo",
         "notes": "Cliente pidió el precio final.", "opportunity_key": "carolina-reyes:buy"},
        {"days_ago": 2, "activity_type": "negotiation", "property_key": "casa-san-jeronimo",
         "notes": "Cliente está considerando hacer una oferta.", "opportunity_key": "carolina-reyes:buy"},
    ],
}


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------


def seed_organization(session: Session) -> tuple[Organization, uuid.UUID | None]:
    """Returns (organization, egr_user_id_or_None) — the latter is used as every demo Activity's `created_by_user_id`."""
    org_id = det_id(DEMO_ORG_KEY)
    org = upsert(session, Organization, org_id, name=DEMO_ORG_NAME)
    session.flush()

    # Re-point the local egr@proppilot.app test login at the demo org so
    # the seeded data is actually visible when logged in via the frontend —
    # see the plan's "Decision I'm flagging for your review". Upserted, not
    # just updated: users.organization_id -> organizations.id is
    # ON DELETE CASCADE, so `--reset` deletes this row along with the demo
    # org it pointed at. Without upserting it back, a reset+reseed would
    # silently leave egr linked to no organization at all.
    try:
        # A SAVEPOINT, not the outer transaction: on Postgres a failed
        # statement aborts the whole transaction until rolled back, which
        # would also discard the Organization insert flushed just above.
        # begin_nested() scopes that rollback to just this query.
        with session.begin_nested():
            auth_user_exists = session.execute(
                text("SELECT 1 FROM auth.users WHERE id = :id"), {"id": EGR_TEST_USER_ID}
            ).scalar()
    except Exception:
        # No `auth` schema at all (e.g. the SQLite test database, or a plain
        # Postgres without Supabase's auth schema) — not fatal, just means
        # there's nothing to link.
        auth_user_exists = False

    if auth_user_exists:
        upsert(session, User, EGR_TEST_USER_ID, organization_id=org_id, role="owner")
        creator_user_id = EGR_TEST_USER_ID
    else:
        print(f"Note: no auth.users row for {EGR_TEST_USER_ID} — skipping the egr test-login link.")
        creator_user_id = None

    return org, creator_user_id


def seed_properties(session: Session, org_id: uuid.UUID) -> dict[str, Property]:
    properties: dict[str, Property] = {}
    for p in PROPERTIES:
        fields = {k: v for k, v in p.items() if k != "key"}
        prop = upsert(session, Property, det_id(f"property:{p['key']}"), organization_id=org_id, **fields)
        properties[p["key"]] = prop
    session.flush()
    return properties


def seed_contacts(session: Session, org_id: uuid.UUID) -> dict[str, Contact]:
    contacts: dict[str, Contact] = {}
    for i, c in enumerate(CONTACTS, start=1):
        contact_id = det_id(f"contact:{c['key']}")
        contact = upsert(
            session,
            Contact,
            contact_id,
            organization_id=org_id,
            first_name=c["first_name"],
            last_name=c["last_name"],
            email=contact_email(c["key"]),
            phone=contact_phone(i),
            preferred_contact_method=c["preferred_contact_method"],
            source=c["source"],
            notes=c["notes"],
            created_at=days_ago(c["days_ago"]),
        )
        contacts[c["key"]] = contact
    session.flush()
    return contacts


def seed_contact_roles(session: Session, contacts: dict[str, Contact]) -> None:
    for contact_key, role_keys in CONTACT_ROLES.items():
        contact = contacts[contact_key]
        for role_key in role_keys:
            upsert(
                session,
                ContactRole,
                det_id(f"contact-role:{contact_key}:{role_key}"),
                contact_id=contact.id,
                role_key=role_key,
            )
    session.flush()


def seed_property_interests(
    session: Session, org_id: uuid.UUID, contacts: dict[str, Contact], properties: dict[str, Property]
) -> None:
    for pi in PROPERTY_INTERESTS:
        upsert(
            session,
            PropertyInterest,
            det_id(f"property-interest:{pi['contact_key']}:{pi['property_key']}"),
            organization_id=org_id,
            contact_id=contacts[pi["contact_key"]].id,
            property_id=properties[pi["property_key"]].id,
            status=pi["status"],
            source=pi["source"],
            notes=pi["notes"],
            first_contact_at=days_ago(pi["first_contact_days_ago"]),
            last_contact_at=days_ago(pi["last_contact_days_ago"]),
            created_at=days_ago(pi["first_contact_days_ago"]),
        )
    session.flush()


def seed_buyer_requirements(session: Session, org_id: uuid.UUID, contacts: dict[str, Contact]) -> None:
    for br in BUYER_REQUIREMENTS:
        requirement_id = det_id(f"buyer-requirement:{br['req_key']}")
        fields = {
            k: v
            for k, v in br.items()
            if k not in {"req_key", "contact_key", "days_ago", "locations", "features"}
        }
        requirement = upsert(
            session,
            BuyerRequirement,
            requirement_id,
            organization_id=org_id,
            contact_id=contacts[br["contact_key"]].id,
            created_at=days_ago(br["days_ago"]),
            **fields,
        )
        session.flush()

        for i, location_name in enumerate(br["locations"], start=1):
            # Areas outside Nuevo León's two biggest cities read as neighborhoods
            # of Monterrey/San Pedro here; everything else is stored as a city.
            is_city = location_name in {
                "San Pedro Garza García", "Monterrey", "Santa Catarina",
                "Apodaca", "Escobedo", "Guadalupe", "San Nicolás de los Garza",
            }
            upsert(
                session,
                BuyerRequirementLocation,
                det_id(f"buyer-requirement-location:{br['req_key']}:{location_name}"),
                buyer_requirement_id=requirement_id,
                city=location_name if is_city else None,
                neighborhood=None if is_city else location_name,
                priority=i,
            )

        for feature_key, classification in br["features"]:
            upsert(
                session,
                BuyerRequirementFeature,
                det_id(f"buyer-requirement-feature:{br['req_key']}:{feature_key}"),
                buyer_requirement_id=requirement_id,
                feature_key=feature_key,
                classification=classification,
            )
    session.flush()


def seed_activities(
    session: Session,
    org_id: uuid.UUID,
    contacts: dict[str, Contact],
    properties: dict[str, Property],
    opportunities: dict[str, Opportunity],
    created_by_user_id: uuid.UUID | None,
) -> None:
    for contact_key, entries in ACTIVITIES.items():
        contact = contacts[contact_key]
        for i, entry in enumerate(entries, start=1):
            property_key = entry.get("property_key")
            opportunity_key = entry.get("opportunity_key")
            upsert(
                session,
                Activity,
                det_id(f"activity:{contact_key}:{i}"),
                organization_id=org_id,
                contact_id=contact.id,
                property_id=properties[property_key].id if property_key else None,
                opportunity_id=opportunities[opportunity_key].id if opportunity_key else None,
                created_by_user_id=created_by_user_id,
                activity_type=entry["activity_type"],
                direction=entry.get("direction"),
                occurred_at=days_ago(entry["days_ago"]),
                notes=entry["notes"],
                created_at=days_ago(entry["days_ago"]),
            )
    session.flush()


def seed_opportunities(
    session: Session,
    org_id: uuid.UUID,
    contacts: dict[str, Contact],
    properties: dict[str, Property],
    owner_user_id: uuid.UUID | None,
) -> dict[str, Opportunity]:
    """
    Buyer requirement ids are resolved directly via det_id() rather than a
    returned dict — seed_buyer_requirements() doesn't build one (it has no
    other caller that needs it), and every id here is deterministic anyway,
    so there's nothing a lookup dict would add over recomputing the same id.
    """
    opportunities: dict[str, Opportunity] = {}
    for o in OPPORTUNITIES:
        opportunity_id = det_id(f"opportunity:{o['key']}")
        fields = {
            "organization_id": org_id,
            "contact_id": contacts[o["contact_key"]].id,
            "property_id": properties[o["property_key"]].id if o.get("property_key") else None,
            "buyer_requirement_id": (
                det_id(f"buyer-requirement:{o['buyer_requirement_key']}") if o.get("buyer_requirement_key") else None
            ),
            "opportunity_type": o["opportunity_type"],
            "stage": o["stage"],
            "title": o["title"],
            "expected_value": o.get("expected_value"),
            "probability": o.get("probability"),
            "lost_reason": o.get("lost_reason"),
            "owner_user_id": owner_user_id,
            "created_by_user_id": owner_user_id,
            "created_at": days_ago(o["days_ago"]),
        }
        if "closed_days_ago" in o:
            fields["closed_at"] = days_ago(o["closed_days_ago"])
        opportunities[o["key"]] = upsert(session, Opportunity, opportunity_id, **fields)
    session.flush()
    return opportunities


def seed_tasks(
    session: Session,
    org_id: uuid.UUID,
    contacts: dict[str, Contact],
    opportunities: dict[str, Opportunity],
    assignee_user_id: uuid.UUID | None,
) -> None:
    for t in TASKS:
        upsert(
            session,
            Task,
            det_id(f"task:{t['key']}"),
            organization_id=org_id,
            contact_id=contacts[t["contact_key"]].id if t.get("contact_key") else None,
            buyer_requirement_id=(
                det_id(f"buyer-requirement:{t['buyer_requirement_key']}") if t.get("buyer_requirement_key") else None
            ),
            opportunity_id=opportunities[t["opportunity_key"]].id if t.get("opportunity_key") else None,
            assigned_to_user_id=assignee_user_id,
            created_by_user_id=assignee_user_id,
            title=t["title"],
            description=t.get("description"),
            task_type=t["task_type"],
            status=t.get("status", "pending"),
            priority=t.get("priority", "medium"),
            due_at=in_days(t["due_in_days"]),
            created_at=days_ago(2),
        )
    session.flush()


def seed_appointments(
    session: Session,
    org_id: uuid.UUID,
    contacts: dict[str, Contact],
    properties: dict[str, Property],
    opportunities: dict[str, Opportunity],
    assignee_user_id: uuid.UUID | None,
) -> None:
    for a in APPOINTMENTS:
        start = in_days(a["start_in_days"])
        upsert(
            session,
            Appointment,
            det_id(f"appointment:{a['key']}"),
            organization_id=org_id,
            contact_id=contacts[a["contact_key"]].id if a.get("contact_key") else None,
            property_id=properties[a["property_key"]].id if a.get("property_key") else None,
            opportunity_id=opportunities[a["opportunity_key"]].id if a.get("opportunity_key") else None,
            assigned_to_user_id=assignee_user_id,
            created_by_user_id=assignee_user_id,
            title=a["title"],
            description=a.get("description"),
            appointment_type=a["appointment_type"],
            status=a.get("status", "scheduled"),
            start_at=start,
            end_at=start + timedelta(hours=a.get("duration_hours", 1)),
            created_at=days_ago(2),
        )
    session.flush()


def run_seed(session: Session) -> Organization:
    org, creator_user_id = seed_organization(session)
    properties = seed_properties(session, org.id)
    contacts = seed_contacts(session, org.id)
    seed_contact_roles(session, contacts)
    seed_property_interests(session, org.id, contacts, properties)
    seed_buyer_requirements(session, org.id, contacts)
    opportunities = seed_opportunities(session, org.id, contacts, properties, creator_user_id)
    seed_activities(session, org.id, contacts, properties, opportunities, creator_user_id)
    seed_tasks(session, org.id, contacts, opportunities, creator_user_id)
    seed_appointments(session, org.id, contacts, properties, opportunities, creator_user_id)
    session.commit()
    return org


def run_reset(session: Session) -> None:
    """
    Deletes the demo organization row. Every child table (contacts,
    properties, buyer_requirements, property_interests, opportunities,
    tasks, appointments, and in turn contact_roles/property_features/
    buyer_requirement_locations/buyer_requirement_features) has
    ondelete="CASCADE" back to organizations — see app/models/ — so this one
    statement removes the entire demo dataset without needing to touch
    every table by hand.
    """
    session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": det_id(DEMO_ORG_KEY)})
    session.commit()


def print_summary(session: Session, org: Organization) -> None:
    def count(table: str) -> int:
        return session.execute(
            text(f"SELECT count(*) FROM {table} WHERE organization_id = :org_id"), {"org_id": org.id}
        ).scalar()

    contact_roles_count = session.execute(
        text(
            "SELECT count(*) FROM contact_roles cr JOIN contacts c ON c.id = cr.contact_id "
            "WHERE c.organization_id = :org_id"
        ),
        {"org_id": org.id},
    ).scalar()

    print(f"Organization: {org.name} ({org.id})")
    print(f"  contacts:            {count('contacts')}")
    print(f"  contact_roles:       {contact_roles_count}")
    print(f"  properties:          {count('properties')}")
    print(f"  buyer_requirements:  {count('buyer_requirements')}")
    print(f"  property_interests:  {count('property_interests')}")
    print(f"  opportunities:       {count('opportunities')}")
    print(f"  activities:          {count('activities')}")
    print(f"  tasks:               {count('tasks')}")
    print(f"  appointments:        {count('appointments')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Delete the demo organization (cascades) first.")
    parser.add_argument(
        "--no-seed", action="store_true", help="With --reset, only delete — don't reseed afterward."
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if args.reset:
            run_reset(session)
            print(f"Deleted demo organization and everything under it (id={det_id(DEMO_ORG_KEY)}).")
            if args.no_seed:
                return
        org = run_seed(session)
        print_summary(session, org)
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
