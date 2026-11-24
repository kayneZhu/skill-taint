"""Tool names, argument schemas, and the consequential-action set."""

from collections.abc import Mapping
from dataclasses import dataclass

from skill_integrity.errors import InvalidArgumentError, UnknownToolError


@dataclass(frozen=True, kw_only=True)
class PlannedToolCall:
    """A tool call the planner wants to make. It does not carry a trust label."""

    tool: str
    arguments: dict[str, str]

CONSEQUENTIAL_TOOLS = frozenset({"send_email", "transfer", "delete_file"})
NONCONSEQUENTIAL_TOOLS = frozenset({"read_email", "search_docs", "write_file"})
ALL_TOOLS = CONSEQUENTIAL_TOOLS | NONCONSEQUENTIAL_TOOLS

TOOL_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "read_email": ("email_id",),
    "search_docs": ("invoice_id",),
    "write_file": ("path", "content"),
    "send_email": ("to", "subject", "body"),
    "transfer": ("invoice_id", "account", "amount"),
    "delete_file": ("path",),
}


def require_arguments(*, tool: str, arguments: Mapping[str, object]) -> dict[str, str]:
    if tool not in TOOL_ARGUMENTS:
        raise UnknownToolError(f"unknown tool: {tool}")
    expected = TOOL_ARGUMENTS[tool]
    if set(arguments) != set(expected):
        raise InvalidArgumentError(
            f"{tool} arguments must be exactly {expected}, got {tuple(arguments)}"
        )
    canonical: dict[str, str] = {}
    for key in expected:
        value = arguments[key]
        if not isinstance(value, str):
            raise InvalidArgumentError(f"{tool} argument {key} must be a string")
        if value == "":
            raise InvalidArgumentError(f"{tool} argument {key} is empty")
        canonical[key] = value
    return canonical
