"""In-memory email, vendor-file, and local-file workspace.

Emails are untrusted observations. The vendor table is trusted configuration.
Skill files are not stored here; they live in SkillLibrary.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from skill_integrity.errors import (
    InvalidAddressError,
    InvalidTransferError,
    MissingPathError,
    UnknownEmailError,
    UnknownInvoiceError,
    UnknownToolError,
    UnsafePathError,
    WorkspaceSetupError,
)
from skill_integrity.labels import Integrity
from skill_integrity.tools import require_arguments

_ALLOWED_ROOTS = frozenset({"notes", "invoices", "tmp"})
_INVOICE_ID = re.compile(pattern=r"INV-[0-9]+")
_ACCOUNT = re.compile(pattern=r"[a-z0-9-]+")
_AMOUNT = re.compile(pattern=r"[1-9][0-9]*")
_ADDRESS = re.compile(pattern=r"[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}")


@dataclass(frozen=True, kw_only=True)
class Email:
    email_id: str
    sender: str
    subject: str
    body: str


@dataclass(frozen=True, kw_only=True)
class VendorRecord:
    invoice_id: str
    account: str
    amount: str


@dataclass(frozen=True, kw_only=True)
class ToolObservation:
    content: str
    label: Integrity


@dataclass(frozen=True, kw_only=True)
class Effects:
    sends: tuple[str, ...]
    transfers: tuple[tuple[str, str, str], ...]
    writes: tuple[tuple[str, str], ...]
    deletes: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class _Send:
    to: str
    subject: str
    body: str
    episode_id: str


@dataclass(frozen=True, kw_only=True)
class _Transfer:
    invoice_id: str
    account: str
    amount: str
    episode_id: str


@dataclass(frozen=True, kw_only=True)
class _Write:
    path: str
    content: str
    episode_id: str


@dataclass(frozen=True, kw_only=True)
class _Delete:
    path: str
    episode_id: str


def validate_relative_path(*, path: str) -> None:
    if path.startswith("/") or path.startswith("\\") or "\\" in path:
        raise UnsafePathError(f"path must be relative: {path}")
    parts = path.split("/")
    if "" in parts or "." in parts or ".." in parts:
        raise UnsafePathError(f"path is not a normalized relative path: {path}")
    if len(parts) < 2 or parts[0] not in _ALLOWED_ROOTS:
        raise UnsafePathError(f"path root is not allowed: {path}")


class Workspace:
    def __init__(
        self,
        *,
        emails: Mapping[str, Email],
        vendors: Mapping[str, VendorRecord],
        files: Mapping[str, str],
    ) -> None:
        self._emails: dict[str, Email] = {}
        for email_id, email in emails.items():
            if not isinstance(email, Email):
                raise WorkspaceSetupError(f"email {email_id} is not an Email")
            if email.email_id != email_id:
                raise WorkspaceSetupError(f"email key {email_id} does not match record")
            self._emails[email_id] = email
        self._vendors: dict[str, VendorRecord] = {}
        for invoice_id, record in vendors.items():
            if not isinstance(record, VendorRecord):
                raise WorkspaceSetupError(f"vendor {invoice_id} is not a VendorRecord")
            if record.invoice_id != invoice_id:
                raise WorkspaceSetupError(f"vendor key {invoice_id} does not match record")
            _require_invoice(invoice_id=record.invoice_id)
            _require_account(account=record.account)
            _require_amount(amount=record.amount)
            self._vendors[invoice_id] = record
        self._files: dict[str, str] = {}
        for path, content in files.items():
            validate_relative_path(path=path)
            if not isinstance(content, str):
                raise WorkspaceSetupError(f"file {path} content is not a string")
            self._files[path] = content
        self.last_vendor: VendorRecord | None = None
        self._sends: list[_Send] = []
        self._transfers: list[_Transfer] = []
        self._writes: list[_Write] = []
        self._deletes: list[_Delete] = []

    def begin_episode(self) -> None:
        """Drop the previous episode's vendor lookup so $doc cannot leak across tasks."""
        self.last_vendor = None

    def execute(
        self,
        *,
        tool: str,
        arguments: Mapping[str, str],
        episode_id: str,
    ) -> ToolObservation:
        checked = require_arguments(tool=tool, arguments=arguments)
        if tool == "read_email":
            return self._read_email(email_id=checked["email_id"])
        if tool == "search_docs":
            return self._search_docs(invoice_id=checked["invoice_id"])
        if tool == "write_file":
            return self._write_file(
                path=checked["path"],
                content=checked["content"],
                episode_id=episode_id,
            )
        if tool == "send_email":
            return self._send_email(
                to=checked["to"],
                subject=checked["subject"],
                body=checked["body"],
                episode_id=episode_id,
            )
        if tool == "transfer":
            return self._transfer(
                invoice_id=checked["invoice_id"],
                account=checked["account"],
                amount=checked["amount"],
                episode_id=episode_id,
            )
        if tool == "delete_file":
            return self._delete_file(path=checked["path"], episode_id=episode_id)
        raise UnknownToolError(f"unknown tool: {tool}")

    def effects_for(self, *, episode_id: str) -> Effects:
        return Effects(
            sends=tuple(
                record.to for record in self._sends if record.episode_id == episode_id
            ),
            transfers=tuple(
                (record.invoice_id, record.account, record.amount)
                for record in self._transfers
                if record.episode_id == episode_id
            ),
            writes=tuple(
                (record.path, record.content)
                for record in self._writes
                if record.episode_id == episode_id
            ),
            deletes=tuple(
                record.path for record in self._deletes if record.episode_id == episode_id
            ),
        )

    def _read_email(self, *, email_id: str) -> ToolObservation:
        if email_id not in self._emails:
            raise UnknownEmailError(f"unknown email {email_id}")
        email = self._emails[email_id]
        content = f"From: {email.sender}\nSubject: {email.subject}\n\n{email.body}"
        return ToolObservation(content=content, label=Integrity.UNTRUSTED)

    def _search_docs(self, *, invoice_id: str) -> ToolObservation:
        _require_invoice(invoice_id=invoice_id)
        if invoice_id not in self._vendors:
            raise UnknownInvoiceError(f"unknown invoice {invoice_id}")
        record = self._vendors[invoice_id]
        self.last_vendor = record
        content = (
            f"{record.invoice_id} account={record.account} amount={record.amount}"
        )
        return ToolObservation(content=content, label=Integrity.TRUSTED)

    def _write_file(self, *, path: str, content: str, episode_id: str) -> ToolObservation:
        validate_relative_path(path=path)
        self._files[path] = content
        self._writes.append(_Write(path=path, content=content, episode_id=episode_id))
        return ToolObservation(content=f"wrote {path}", label=Integrity.TRUSTED)

    def _send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        episode_id: str,
    ) -> ToolObservation:
        if _ADDRESS.fullmatch(string=to) is None:
            raise InvalidAddressError(f"recipient is not a canonical address: {to}")
        self._sends.append(_Send(to=to, subject=subject, body=body, episode_id=episode_id))
        return ToolObservation(content=f"sent to {to}", label=Integrity.TRUSTED)

    def _transfer(
        self,
        *,
        invoice_id: str,
        account: str,
        amount: str,
        episode_id: str,
    ) -> ToolObservation:
        _require_invoice(invoice_id=invoice_id)
        _require_account(account=account)
        _require_amount(amount=amount)
        self._transfers.append(
            _Transfer(
                invoice_id=invoice_id,
                account=account,
                amount=amount,
                episode_id=episode_id,
            )
        )
        return ToolObservation(
            content=f"transferred {amount} to {account} for {invoice_id}",
            label=Integrity.TRUSTED,
        )

    def _delete_file(self, *, path: str, episode_id: str) -> ToolObservation:
        validate_relative_path(path=path)
        if path not in self._files:
            raise MissingPathError(f"cannot delete missing path {path}")
        del self._files[path]
        self._deletes.append(_Delete(path=path, episode_id=episode_id))
        return ToolObservation(content=f"deleted {path}", label=Integrity.TRUSTED)


def _require_invoice(*, invoice_id: str) -> None:
    if _INVOICE_ID.fullmatch(string=invoice_id) is None:
        raise InvalidTransferError(f"invalid invoice id {invoice_id}")


def _require_account(*, account: str) -> None:
    if _ACCOUNT.fullmatch(string=account) is None:
        raise InvalidTransferError(f"invalid account {account}")


def _require_amount(*, amount: str) -> None:
    if _AMOUNT.fullmatch(string=amount) is None:
        raise InvalidTransferError(f"invalid amount {amount}")
