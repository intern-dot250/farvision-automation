import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services import master_repository

client = TestClient(app)


def test_get_head_options_derives_from_master(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "Mukesh Kumar", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
            {"Account Head": "Goel Electricals", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    response = client.get("/api/v1/master/heads")

    assert response.status_code == 200
    heads = response.json()["heads"]
    assert "Contractor" in heads
    assert "SUNDRY CREDITORS - OTHER" in heads
    assert "Internal" in heads


def test_get_account_head_options_returns_distinct_values(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "Ravi Vats(555)"},
            {"Account Head": "S S Paints"},
            {"Account Head": "Ravi Vats(555)"},
            {"Account Head": ""},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    response = client.get("/api/v1/master/account-heads")

    assert response.status_code == 200
    assert response.json()["account_heads"] == ["Ravi Vats(555)", "S S Paints"]
