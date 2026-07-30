import re
from dataclasses import dataclass

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


@dataclass
class ParsedDescription:
    payee_name: str | None
    ifsc: str | None
    is_internal_format: bool
    bank_name: str | None = None


def _parse_upi(description: str, is_credit: bool | None) -> ParsedDescription | None:
    """UPI narrations ("UPI/{ref}/From:{vpa}/To:{vpa}...") use "/" as the
    delimiter and label each side explicitly, rather than the dash-separated
    NEFT/RTGS shape - handled separately. Picks whichever side is the
    counterparty (the other side is our own account): "From:" for a credit
    (money coming in from them), "To:" for a debit (money going out to
    them); falls back to whichever is present when direction isn't known.
    """
    if not description.strip().upper().startswith("UPI"):
        return None

    from_value = None
    to_value = None
    for segment in description.split("/"):
        segment = segment.strip()
        if segment.upper().startswith("FROM:"):
            from_value = segment[len("FROM:"):].strip() or None
        elif segment.upper().startswith("TO:"):
            to_value = segment[len("TO:"):].strip() or None

    if is_credit is True:
        payee_name = from_value or to_value
    elif is_credit is False:
        payee_name = to_value or from_value
    else:
        payee_name = from_value or to_value

    return ParsedDescription(payee_name=payee_name, ifsc=None, is_internal_format=False)


def parse_description(description: str, is_credit: bool | None = None) -> ParsedDescription:
    """Extract payee name, IFSC code, and counterparty bank name from a bank
    DESCRIPTION string.

    Real NEFT/RTGS DEBIT narrations look like:
      {channel}-{mode}-{utr}-{payee name}-{ifsc}-{head}-{bank name}
    Real NEFT/RTGS CREDIT narrations (money coming in, e.g. "Collection")
    look like:
      {mode} Cr-{ifsc}-{payee name}-{their own reference}
    - the IFSC appears right after the mode instead of after the payee name,
    distinguished here by how early it's found (index < 3 can't fit a
    channel+mode+utr prefix before it).
    UPI narrations have their own "/"-delimited shape - see _parse_upi().
    Internal inter-account transfers (mode=TPT) have no IFSC segment, which
    is how they're recognized as internal (confirmed business rule) - and
    have no counterparty bank name either, since they're between our own
    accounts.
    """
    upi_result = _parse_upi(description, is_credit)
    if upi_result is not None:
        return upi_result

    tokens = description.split("-")

    ifsc_index = next(
        (i for i, token in enumerate(tokens) if IFSC_PATTERN.match(token.strip())),
        None,
    )

    if ifsc_index is None:
        # Internal transfers (mode=TPT) still name the counterparty entity in
        # the description ("YIB-TPT-Dwarkadhis Projects Pvt Ltd...-045563...")
        # - extract it for display, without changing the Internal
        # classification, which stays based on the missing IFSC alone.
        internal_name = None
        if len(tokens) >= 4 and tokens[1].strip().upper() == "TPT":
            internal_name = tokens[2].strip() or None
        return ParsedDescription(payee_name=internal_name, ifsc=None, is_internal_format=True)

    if ifsc_index < 3:
        # Credit-style shape: IFSC found too early to fit a
        # channel-mode-utr prefix before it - the payee is the single token
        # right after the IFSC, not "everything before it".
        payee_name = tokens[ifsc_index + 1].strip() if len(tokens) > ifsc_index + 1 else ""
        payee_name = payee_name or None
        bank_name = None
    else:
        # Everything between the UTR (index 2) and the IFSC token is the payee name.
        payee_tokens = tokens[3:ifsc_index]
        payee_name = "-".join(payee_tokens).strip() or None

        # One token after IFSC is the head/category (Contractor, Vendor, ...);
        # everything after that is the counterparty's bank name.
        bank_name = "-".join(tokens[ifsc_index + 2:]).strip() or None

    return ParsedDescription(
        payee_name=payee_name,
        ifsc=tokens[ifsc_index].strip(),
        is_internal_format=False,
        bank_name=bank_name,
    )
