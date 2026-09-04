from unittest.mock import MagicMock, patch

from app.services import app_config_repository


def test_hash_and_verify_password_roundtrip():
    stored = app_config_repository._hash_password("correct-horse")
    assert app_config_repository.verify_password("correct-horse", stored)
    assert not app_config_repository.verify_password("wrong-password", stored)


def test_verify_password_rejects_malformed_hash():
    assert not app_config_repository.verify_password("anything", "not-a-valid-hash")


def test_get_password_hash_returns_none_when_no_row():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.get_password_hash() is None


def test_get_password_hash_returns_stored_hash():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"password_hash": "salt$digest"}
    ]

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.get_password_hash() == "salt$digest"


def test_set_password_upserts_a_hash():
    mock_client = MagicMock()

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        app_config_repository.set_password("new-password")

    mock_client.table.assert_called_with("app_config")
    upsert_payload = mock_client.table.return_value.upsert.call_args[0][0]
    assert upsert_payload["id"] == 1
    assert app_config_repository.verify_password("new-password", upsert_payload["password_hash"])


def test_seed_password_if_empty_noops_when_row_already_exists():
    with patch(
        "app.services.app_config_repository.get_password_hash", return_value="existing-hash"
    ), patch("app.services.app_config_repository.set_password") as mock_set:
        app_config_repository.seed_password_if_empty("legacy-password")

    mock_set.assert_not_called()


def test_seed_password_if_empty_seeds_when_no_row():
    with patch("app.services.app_config_repository.get_password_hash", return_value=None), patch(
        "app.services.app_config_repository.set_password"
    ) as mock_set:
        app_config_repository.seed_password_if_empty("legacy-password")

    mock_set.assert_called_once_with("legacy-password")


def test_has_active_reset_token_true_when_unexpired_unused_token_exists():
    mock_client = MagicMock()
    query = mock_client.table.return_value.select.return_value.is_.return_value.gt.return_value.limit.return_value
    query.execute.return_value.data = [{"id": 1}]

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.has_active_reset_token() is True


def test_has_active_reset_token_false_when_none_found():
    mock_client = MagicMock()
    query = mock_client.table.return_value.select.return_value.is_.return_value.gt.return_value.limit.return_value
    query.execute.return_value.data = []

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.has_active_reset_token() is False


def test_consume_reset_token_returns_false_when_not_found():
    mock_client = MagicMock()
    select_query = (
        mock_client.table.return_value.select.return_value.eq.return_value.is_.return_value.gt.return_value.limit.return_value
    )
    select_query.execute.return_value.data = []

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.consume_reset_token("some-token") is False


def test_consume_reset_token_marks_used_when_found():
    mock_client = MagicMock()
    select_query = (
        mock_client.table.return_value.select.return_value.eq.return_value.is_.return_value.gt.return_value.limit.return_value
    )
    select_query.execute.return_value.data = [{"id": 42}]
    update_query = mock_client.table.return_value.update.return_value.eq.return_value.is_.return_value
    update_query.execute.return_value.data = [{"id": 42}]

    with patch("app.services.app_config_repository.supabase_client.get_client", return_value=mock_client):
        assert app_config_repository.consume_reset_token("some-token") is True

    mock_client.table.return_value.update.assert_called_once()
