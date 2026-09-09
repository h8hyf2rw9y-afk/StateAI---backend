"""
The global feature catalog: GET /features, its response shape, and the
active/inactive default filtering. See app/api/routes/features.py.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.seed_data import FEATURE_SEEDS
from app.models.feature import Feature


def test_list_features_returns_active_features_by_default(client: TestClient):
    response = client.get("/api/v1/features")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(FEATURE_SEEDS)
    assert all(f["is_active"] for f in body)
    assert {f["key"] for f in body} == {seed["key"] for seed in FEATURE_SEEDS}


def test_feature_response_matches_schema_conventions(client: TestClient):
    body = client.get("/api/v1/features").json()
    garden = next(f for f in body if f["key"] == "garden")
    assert garden == {
        "key": "garden",
        "label": "Garden",
        "category": "exterior",
        "is_active": True,
        "created_at": garden["created_at"],
        "updated_at": garden["updated_at"],
    }
    assert garden["created_at"] is not None
    assert garden["updated_at"] is not None


def test_inactive_features_are_not_returned_by_default(client: TestClient, db_session: Session):
    feature = db_session.get(Feature, "pet_friendly")
    feature.is_active = False
    db_session.commit()

    default_response = client.get("/api/v1/features")
    assert default_response.status_code == 200
    assert "pet_friendly" not in {f["key"] for f in default_response.json()}
    assert len(default_response.json()) == len(FEATURE_SEEDS) - 1

    inactive_response = client.get("/api/v1/features", params={"active": "false"})
    assert inactive_response.status_code == 200
    assert {f["key"] for f in inactive_response.json()} == {"pet_friendly"}
