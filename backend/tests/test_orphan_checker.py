from unittest.mock import patch

from app.services import orphan_checker


def test_check_orphans_finds_code_missing_from_one_tab():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {
            "DepositWithdrawal": {"1", "2", "3"},
            "DepositWithdrawalDetails": {"1", "2", "3"},
            "LedgerDetails": {"1", "3"},  # 2 is missing here
        }[worksheet_name]

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert report["destination"] == "deposit_withdrawal"
    assert len(report["orphans"]) == 1
    orphan = report["orphans"][0]
    assert orphan["link_ref_code"] == "2"
    assert orphan["missing_from"] == ["LedgerDetails"]
    assert set(orphan["present_in"]) == {"DepositWithdrawal", "DepositWithdrawalDetails"}


def test_check_orphans_returns_empty_list_when_fully_consistent():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {"1", "2", "3"}

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert report["orphans"] == []


def test_check_orphans_sorts_numeric_codes_numerically():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "LedgerDetails":
            return set()
        return {"10", "2", "1"}

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert [o["link_ref_code"] for o in report["orphans"]] == ["1", "2", "10"]


def test_check_orphans_does_not_flag_code_missing_only_from_optional_adjustment_details():
    # A transaction with a blank Parent Account Head legitimately has no
    # AdjustmentDetails row (automation_engine._build_receipt_payment_rows) -
    # that must not be reported as an orphan.
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {
            "ReceiptPayment": {"1", "2"},
            "ReceiptPaymentDetail": {"1", "2"},
            "LedgerDetails": {"1", "2"},
            "AdjustmentDetails": {"1"},  # 2 is intentionally missing here
            "ImportTaxInfo": {"1", "2"},
        }[worksheet_name]

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("receipt_payment")

    assert report["orphans"] == []


def test_check_orphans_still_flags_code_missing_from_a_required_tab():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {
            "ReceiptPayment": {"1", "2"},
            "ReceiptPaymentDetail": {"1", "2"},
            "LedgerDetails": {"1"},  # 2 is missing here - a required tab
            "AdjustmentDetails": {"1"},
            "ImportTaxInfo": {"1", "2"},
        }[worksheet_name]

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("receipt_payment")

    assert len(report["orphans"]) == 1
    assert report["orphans"][0]["link_ref_code"] == "2"
    assert "LedgerDetails" in report["orphans"][0]["missing_from"]


def test_check_orphans_flags_a_stray_code_present_only_in_the_optional_tab():
    # A code that shows up in AdjustmentDetails but nowhere else is a real
    # orphan (e.g. a leftover row from a previous run), not an expected skip.
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {
            "ReceiptPayment": {"1"},
            "ReceiptPaymentDetail": {"1"},
            "LedgerDetails": {"1"},
            "AdjustmentDetails": {"1", "99"},
            "ImportTaxInfo": {"1"},
        }[worksheet_name]

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("receipt_payment")

    assert len(report["orphans"]) == 1
    assert report["orphans"][0]["link_ref_code"] == "99"


def test_check_all_orphans_covers_both_destinations():
    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        return_value=set(),
    ):
        reports = orphan_checker.check_all_orphans()

    destinations = {r["destination"] for r in reports}
    assert destinations == {"deposit_withdrawal", "receipt_payment"}
