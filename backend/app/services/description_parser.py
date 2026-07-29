import re
from dataclasses import dataclass

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


@dataclass
class ParsedDescription:
    payee_name: str | None
    ifsc: str | None
    is_internal_format: bool
    bank_name: str | None = None


def parse_description(description: str) -> ParsedDescription:
    """Extract payee name, IFSC code, and counterparty bank name from a bank
    DESCRIPTION string.

    Real NEFT/RTGS narrations look like:
      {channel}-{mode}-{utr}-{payee name}-{ifsc}-{head}-{bank name}
    Internal inter-account transfers (mode=TPT) have no IFSC segment, which
    is how they're recognized as internal (confirmed business rule) - and
    have no counterparty bank name either, since they're between our own
    accounts.
    """
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
