"""Compatibility re-exports. The workspace implementation is workspaces.invoice."""

from skill_taint.workspaces.invoice import (
    Effects,
    Email,
    ToolObservation,
    VendorRecord,
    Workspace,
    validate_relative_path,
)

__all__ = (
    "Effects",
    "Email",
    "ToolObservation",
    "VendorRecord",
    "Workspace",
    "validate_relative_path",
)
