"""GS1 GTIN-13 helpers.

Implements the real GS1 standard mod-10 check-digit algorithm so that the
marking codes minted for the supplier reference are *structurally valid*
GTIN-13 / EAN-13 barcodes, not arbitrary 13-digit strings.

The data identities are synthetic, but the encoding is genuine:

* GS1 prefixes ``460``-``469`` are the real EAEU (Russia / EAEU member
  states) country range. That is correct for this reference even though
  manufacturing is contracted to China: GTINs belong to the RU brand owner
  registered with GS1 RUS, regardless of where the goods are made — the
  own-brand kitchen-appliance importer legend (``docs/domain.md``).
* The 13th digit is computed with the published GS1 mod-10 weighting
  (odd positions weight 1, even positions weight 3, counting from the left
  over the 12 data digits).
"""

from __future__ import annotations

# Real GS1 country-code prefix range allocated to the EAEU (Russia and other
# member states). See GS1 prefix table 460-469.
EAEU_PREFIX_RANGE = range(460, 470)


def gtin13_check_digit(data12: str) -> int:
    """Return the GS1 mod-10 check digit for a 12-digit GTIN-13 payload."""
    if len(data12) != 12 or not data12.isdigit():
        raise ValueError(f"GTIN-13 payload must be exactly 12 digits, got {data12!r}")
    total = 0
    for index, char in enumerate(data12):
        weight = 3 if index % 2 == 1 else 1
        total += int(char) * weight
    return (10 - (total % 10)) % 10


def make_gtin13(prefix: int, item_reference: int) -> str:
    """Mint a valid GTIN-13 from a GS1 prefix and an item reference.

    ``prefix`` is a 3-digit GS1 country prefix; ``item_reference`` fills the
    remaining 9 payload digits (company prefix + item ref, zero-padded). The
    check digit is appended per the GS1 standard.
    """
    if prefix not in EAEU_PREFIX_RANGE:
        raise ValueError(f"prefix {prefix} is outside the EAEU range 460-469")
    if not 0 <= item_reference < 10**9:
        raise ValueError("item_reference must fit in 9 digits")
    payload = f"{prefix:03d}{item_reference:09d}"
    return payload + str(gtin13_check_digit(payload))


def is_valid_gtin13(gtin: str) -> bool:
    """True if ``gtin`` is 13 digits with a correct GS1 check digit."""
    if len(gtin) != 13 or not gtin.isdigit():
        return False
    return gtin13_check_digit(gtin[:12]) == int(gtin[12])
