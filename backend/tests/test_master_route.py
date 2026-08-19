import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services import master_repository

client = TestClient(app)


def test_get_head_options_returns_fixed_list_regardless_of_master(monkeypatch):
    # Deriving this list from Master used to leak raw Account Head noise
    # (e.g. bank account entries) into the dropdown whenever a row's Parent
    # Account Head was blank - now it's a fixed, accounts-team-provided
    # list, so Master's content must have zero effect on the response.
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "PNB CURRENT A/C - (4184002100014005)", "Parent Account Head": ""},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    response = client.get("/api/v1/master/heads")

    assert response.status_code == 200
    heads = response.json()["heads"]
    assert "PNB CURRENT A/C - (4184002100014005)" not in heads
    assert "Imprest" not in heads  # fixed list uses the accounts-team casing
    assert "IMPREST" in heads
    assert "CONTRACTOR" in heads
    assert "COLLECTION" in heads
    assert "BANK CHARGES" in heads
    assert heads == sorted(heads)


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
