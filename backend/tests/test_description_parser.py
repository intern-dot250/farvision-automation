from app.services.description_parser import parse_description


def test_parses_neft_description_with_ifsc_and_payee():
    result = parse_description(
        "YIB-NEFT-YESME62030018559-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA"
    )

    assert result.payee_name == "Rakiba BIBI"
    assert result.ifsc == "SBIN0007204"
    assert result.is_internal_format is False
    assert result.bank_name == "STATE BANK OF INDIA"


def test_parses_payee_name_with_multiple_words():
    result = parse_description(
        "YIB-NEFT-YESME62030016702-Awesome Paint Planners Pvt Ltd-ICIC0003254-Vendor-ICICI BANK LIMITED"
    )

    assert result.payee_name == "Awesome Paint Planners Pvt Ltd"
    assert result.ifsc == "ICIC0003254"
    assert result.bank_name == "ICICI BANK LIMITED"


def test_internal_transfer_has_no_ifsc():
    result = parse_description(
        "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
    )

    assert result.is_internal_format is True
    assert result.ifsc is None
    assert result.bank_name is None


def test_internal_transfer_still_extracts_entity_name():
    result = parse_description(
        "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
    )

    assert result.is_internal_format is True
    assert result.payee_name == "DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR"


def test_internal_transfer_with_no_tpt_marker_has_no_payee_name():
    # Not the "{channel}-TPT-{name}-{account}" shape - don't guess a name.
    result = parse_description("IMPS/NA/XXXX0091/RRN:616698356024/PC38978 11144658468")

    assert result.is_internal_format is True
    assert result.payee_name is None
