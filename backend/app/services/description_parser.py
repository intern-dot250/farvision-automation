import re
from dataclasses import dataclass

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


@dataclass
class ParsedDescription:
    payee_name: str | None
    ifsc: str | None
    is_internal_format: bool
    bank_name: str | None = None
    counterparty_account: str | None = None  # destination account number embedded in a TPT-shaped internal-transfer narration


def _parse_slash_delimited(description: str) -> ParsedDescription | None:
    """Handle IMPS-style slash-delimited narrations and similar formats.

    UPI narrations ("UPI/{ref}/From:{vpa}/To:{vpa}/...") use "/" as
    delimiter and explicitly label each side - handled separately below
    because direction matters.

    IMPS narrations ("IMPS/{payee name}/{account info}/RRN:{ref}/...")
    use "/" but don't label From/To - the second segment is the payee name.
    """
    tokens = [t.strip() for t in description.split("/") if t.strip()]
    if not tokens:
        return None

    first = tokens[0].upper()

    if first.startswith("UPI"):
        return None  # handled by _parse_upi()

    if first == "IMPS" and len(tokens) >= 2:
        # IMPS/{payee name}/{account or ref}/RRN:{...}/...
        payee_candidate = tokens[1].strip() or None
        # "NA" is a placeholder meaning unknown, not an actual payee name.
        # Some banks append tracking codes (e.g. "NAXXXQ675") — treat any
        # "NA"-prefixed token as unknown.
        if payee_candidate and payee_candidate.upper().startswith("NA"):
            payee_candidate = None
        # When the payee slot is blank (NA placeholder), the bank name
        # further along in the narration is a usable fallback for Master
        # matching (e.g. "IMPS/NAXXXQ675/.../BANK OF MAHARAS/D").
        bank_name = None
        if payee_candidate is None:
            # Skip reference-number tokens (RRN:/{ref}, PC:/{ref}) and bare
            # digit/alphanumeric codes; the first multi-word token is the
            # bank name (e.g. "BANK OF MAHARAS").
            for t in tokens[2:]:
                t = t.strip()
                if not t or t.isdigit():
                    continue
                if IFSC_PATTERN.match(t):
                    continue
                if t.startswith(("RRN", "PC")):
                    continue
                if " " in t and len(t) > 3:
                    bank_name = t
                    break
        return ParsedDescription(
            payee_name=payee_candidate, ifsc=None,
            is_internal_format=False, bank_name=bank_name,
        )

    return None


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
    IMPS narrations use "/" too but don't label From/To - the second segment
    is the payee name. See _parse_slash_delimited().
    Internal inter-account transfers (mode=TPT) have no IFSC segment, which
    is how they're recognized as internal (confirmed business rule) - and
    have no counterparty bank name either, since they're between our own
    accounts.
    """
    upi_result = _parse_upi(description, is_credit)
    if upi_result is not None:
        return upi_result

    slash_result = _parse_slash_delimited(description)
    if slash_result is not None:
        return slash_result

    tokens = description.split("-")

    ifsc_index = next(
        (i for i, token in enumerate(tokens) if IFSC_PATTERN.match(token.strip())),
        None,
    )

    if ifsc_index is None:
        # Internal transfers (mode=TPT) have no IFSC and are explicitly
        # marked with TPT in the description. Other no-IFSC descriptions
        # (bank charges, plain payee names, etc.) are NOT internal - they
        # just don't have parseable structure, so return them as-is so the
        # classifier's fallback payee extraction can try.
        if len(tokens) >= 4 and tokens[1].strip().upper() == "TPT":
            internal_name = tokens[2].strip() or None
            # The last token is often the counterparty's full account number
            # (e.g. "...-tfr-045563400002477") - only treat it as one when
            # it's a bare digit string, so unrelated trailing text elsewhere
            # doesn't get misread as an account number.
            last_token = tokens[-1].strip()
            counterparty_account = last_token if last_token.isdigit() else None
            return ParsedDescription(
                payee_name=internal_name, ifsc=None, is_internal_format=True,
                counterparty_account=counterparty_account,
            )
        return ParsedDescription(payee_name=None, ifsc=None, is_internal_format=False)

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
