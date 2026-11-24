"""Substitute $doc fields from the latest trusted vendor lookup.

There is no $email binder. Untrusted email text cannot flow into tool
arguments through this path. That is a limitation of the scripted plans,
not a general data-flow monitor.
"""

import re
from collections.abc import Mapping

from skill_integrity.errors import MissingDocBindingError, UnknownBindingError
from skill_integrity.workspace import VendorRecord

_DOC_TOKEN = re.compile(pattern=r"\$doc\.(account|amount|invoice_id)")


def bind_arguments(
    *,
    arguments: Mapping[str, str],
    vendor: VendorRecord | None,
) -> dict[str, str]:
    return {
        key: bind_value(value=value, vendor=vendor)
        for key, value in arguments.items()
    }


def bind_value(*, value: str, vendor: VendorRecord | None) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _DOC_TOKEN.finditer(string=value):
        if vendor is None:
            raise MissingDocBindingError(
                "argument uses $doc before search_docs has returned a record"
            )
        pieces.append(value[cursor:match.start()])
        field = match.group(1)
        if field == "account":
            pieces.append(vendor.account)
        elif field == "amount":
            pieces.append(vendor.amount)
        elif field == "invoice_id":
            pieces.append(vendor.invoice_id)
        else:
            raise UnknownBindingError(f"unknown $doc field {field}")
        cursor = match.end()
    pieces.append(value[cursor:])
    bound = "".join(pieces)
    if "$" in bound:
        raise UnknownBindingError(f"unresolved binding in {bound!r}")
    return bound
