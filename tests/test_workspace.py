import pytest

from skill_taint.binding import bind_arguments
from skill_taint.errors import (
    InvalidAddressError,
    InvalidTransferError,
    MissingDocBindingError,
    MissingPathError,
    UnknownBindingError,
    UnknownEmailError,
    UnknownInvoiceError,
    UnsafePathError,
)
from skill_taint.labels import Integrity
from skill_taint.lessons import ATTACK_LESSON
from skill_taint.scenarios import fresh_workspace
from skill_taint.workspace import VendorRecord


def test_email_is_untrusted_and_vendor_lookup_is_trusted() -> None:
    workspace = fresh_workspace()
    email = workspace.execute(
        tool="read_email",
        arguments={"email_id": "poison-1"},
        episode_id="poison",
    )
    assert email.label is Integrity.UNTRUSTED
    assert ATTACK_LESSON in email.content
    docs = workspace.execute(
        tool="search_docs",
        arguments={"invoice_id": "INV-100"},
        episode_id="pay-inv-100",
    )
    assert docs.label is Integrity.TRUSTED
    assert docs.content == "INV-100 account=acme-operating-4401 amount=1200"
    assert workspace.last_vendor is not None
    assert workspace.last_vendor.account == "acme-operating-4401"


def test_missing_records_and_unsafe_paths_raise() -> None:
    workspace = fresh_workspace()
    with pytest.raises(UnknownEmailError):
        workspace.execute(
            tool="read_email",
            arguments={"email_id": "missing"},
            episode_id="poison",
        )
    with pytest.raises(UnknownInvoiceError):
        workspace.execute(
            tool="search_docs",
            arguments={"invoice_id": "INV-404"},
            episode_id="pay-inv-100",
        )
    for path in ("../tmp/x.txt", "/tmp/x.txt", "notes/../tmp/x.txt", "etc/passwd", "notes"):
        with pytest.raises(UnsafePathError):
            workspace.execute(
                tool="write_file",
                arguments={"path": path, "content": "x"},
                episode_id="poison",
            )
    with pytest.raises(MissingPathError):
        workspace.execute(
            tool="delete_file",
            arguments={"path": "tmp/missing.txt"},
            episode_id="delete-scratch",
        )


def test_consequential_arguments_are_not_normalized() -> None:
    workspace = fresh_workspace()
    with pytest.raises(InvalidAddressError):
        workspace.execute(
            tool="send_email",
            arguments={"to": "Audit@Example.com", "subject": "s", "body": "b"},
            episode_id="pay-inv-100",
        )
    with pytest.raises(InvalidTransferError):
        workspace.execute(
            tool="transfer",
            arguments={"invoice_id": "INV-100", "account": "acme-operating-4401", "amount": "012"},
            episode_id="pay-inv-100",
        )
    assert workspace.effects_for(episode_id="pay-inv-100").sends == ()
    assert workspace.effects_for(episode_id="pay-inv-100").transfers == ()


def test_doc_binding_uses_only_the_trusted_vendor_record() -> None:
    vendor = VendorRecord(invoice_id="INV-100", account="acme-operating-4401", amount="1200")
    bound = bind_arguments(
        arguments={"account": "$doc.account", "line": "account: $doc.account\n"},
        vendor=vendor,
    )
    assert bound["account"] == "acme-operating-4401"
    assert bound["line"] == "account: acme-operating-4401\n"
    with pytest.raises(MissingDocBindingError):
        bind_arguments(arguments={"account": "$doc.account"}, vendor=None)
    with pytest.raises(UnknownBindingError):
        bind_arguments(arguments={"body": "$email.body"}, vendor=vendor)


def test_begin_episode_drops_the_previous_vendor_lookup() -> None:
    workspace = fresh_workspace()
    workspace.execute(
        tool="search_docs",
        arguments={"invoice_id": "INV-100"},
        episode_id="pay-inv-100",
    )
    workspace.begin_episode()
    assert workspace.last_vendor is None
