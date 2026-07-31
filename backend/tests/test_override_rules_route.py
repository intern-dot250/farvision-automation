from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE_RULE = {
    "id": 1,
    "description_keyword": "Ravi Vats",
    "head": "Imprest",
    "sheet_name": "YES AH IDW 2457",
    "account_head": "Ravi Vats(555)",
    "is_active": True,
    "created_at": "2026-07-31T00:00:00Z",
    "updated_at": "2026-07-31T00:00:00Z",
}


def test_list_rules_returns_all_rules():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.order.return_value.execute.return_value.data = [SAMPLE_RULE]

    with patch("app.services.override_rules_repository.supabase_client.get_client", return_value=mock_client):
        response = client.get("/api/v1/override-rules")

    assert response.status_code == 200
    assert response.json() == [SAMPLE_RULE]


def test_create_rule_inserts_and_returns_row():
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [SAMPLE_RULE]

    with patch("app.services.override_rules_repository.supabase_client.get_client", return_value=mock_client):
        response = client.post(
            "/api/v1/override-rules",
            json={
                "description_keyword": "Ravi Vats",
                "head": "Imprest",
                "sheet_name": "YES AH IDW 2457",
                "account_head": "Ravi Vats(555)",
                "is_active": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == SAMPLE_RULE
    insert_args = mock_client.table.return_value.insert.call_args[0][0]
    assert insert_args["description_keyword"] == "Ravi Vats"


def test_update_rule_returns_updated_row():
    updated = {**SAMPLE_RULE, "account_head": "New Account Head"}
    mock_client = MagicMock()
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [updated]

    with patch("app.services.override_rules_repository.supabase_client.get_client", return_value=mock_client):
        response = client.put(
            "/api/v1/override-rules/1",
            json={
                "description_keyword": "Ravi Vats",
                "head": "Imprest",
                "sheet_name": "YES AH IDW 2457",
                "account_head": "New Account Head",
                "is_active": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["account_head"] == "New Account Head"


def test_toggle_rule_sets_is_active():
    toggled = {**SAMPLE_RULE, "is_active": False}
    mock_client = MagicMock()
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [toggled]

    with patch("app.services.override_rules_repository.supabase_client.get_client", return_value=mock_client):
        response = client.patch("/api/v1/override-rules/1/toggle", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    update_args = mock_client.table.return_value.update.call_args[0][0]
    assert update_args["is_active"] is False


def test_delete_rule_calls_delete():
    mock_client = MagicMock()

    with patch("app.services.override_rules_repository.supabase_client.get_client", return_value=mock_client):
        response = client.delete("/api/v1/override-rules/1")

    assert response.status_code == 204
    mock_client.table.return_value.delete.return_value.eq.assert_called_with("id", 1)


def test_create_rule_rejects_blank_keyword():
    response = client.post(
        "/api/v1/override-rules",
        json={
            "description_keyword": "",
            "head": "Imprest",
            "sheet_name": "YES AH IDW 2457",
            "account_head": "Ravi Vats(555)",
            "is_active": True,
        },
    )

    assert response.status_code == 422
