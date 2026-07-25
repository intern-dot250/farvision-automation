import re
from dataclasses import dataclass

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


@dataclass
class ParsedDescription:
    payee_name: str | None
    ifsc: str | None
    is_internal_format: bool


def parse_description(description: str) -> ParsedDescription:
    """Extract payee name and IFSC code from a bank DESCRIPTION string.

    Real NEFT/RTGS narrations look like:
      {channel}-{mode}-{utr}-{payee name}-{ifsc}-{bank name}
    Internal inter-account transfers (mode=TPT) have no IFSC segment, which
    is how they're recognized as internal (confirmed business rule).
    """
    tokens = description.split("-")

    ifsc_index = next(
        (i for i, token in enumerate(tokens) if IFSC_PATTERN.match(token.strip())),
        None,
    )

    if ifsc_index is None:
        return ParsedDescription(payee_name=None, ifsc=None, is_internal_format=True)

    # Everything between the UTR (index 2) and the IFSC token is the payee name.
    payee_tokens = tokens[3:ifsc_index]
    payee_name = "-".join(payee_tokens).strip() or None

    return ParsedDescription(
        payee_name=payee_name,
        ifsc=tokens[ifsc_index].strip(),
        is_internal_format=False,
    )
