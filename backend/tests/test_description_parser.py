from app.services.description_parser import parse_description


def test_parses_neft_description_with_ifsc_and_payee():
    result = parse_description(
        "YIB-NEFT-YESME62030018559-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA"
    )

    assert result.payee_name == "Rakiba BIBI"
    assert result.ifsc == "SBIN0007204"
    assert result.is_internal_format is False


def test_parses_payee_name_with_multiple_words():
    result = parse_description(
        "YIB-NEFT-YESME62030016702-Awesome Paint Planners Pvt Ltd-ICIC0003254-Vendor-ICICI BANK LIMITED"
    )

    assert result.payee_name == "Awesome Paint Planners Pvt Ltd"
    assert result.ifsc == "ICIC0003254"


def test_internal_transfer_has_no_ifsc():
    result = parse_description(
        "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
    )

    assert result.is_internal_format is True
    assert result.payee_name is None
    assert result.ifsc is None
