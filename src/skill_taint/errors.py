"""Explicit failures. Callers do not substitute a default behavior."""


class SkillIntegrityError(Exception):
    """Base error for this prototype."""


class ConfigError(SkillIntegrityError):
    """Invalid combination of defense, backend, or endorsement settings."""


class MissingConfigError(SkillIntegrityError):
    """Required OpenAI-compatible settings were not provided."""

    def __init__(self, *, missing: tuple[str, ...]) -> None:
        if not missing:
            raise ValueError("MissingConfigError requires at least one missing item")
        self.missing = missing
        joined = ", ".join(missing)
        super().__init__(f"missing configuration: {joined}")


class UnknownIntegrityLabelError(SkillIntegrityError):
    """A label string is not in the integrity lattice."""


class EmptyJoinError(SkillIntegrityError):
    """Join was asked to combine an empty set of labels."""


class DuplicateSegmentError(SkillIntegrityError):
    """A trajectory already contains this segment id."""


class UnknownSegmentError(SkillIntegrityError):
    """A citation names a segment that is not in the trajectory."""


class UnknownToolError(SkillIntegrityError):
    """The tool name is not in the toy workspace."""


class InvalidArgumentError(SkillIntegrityError):
    """Tool arguments are missing, extra, empty, or the wrong type."""


class UnknownEmailError(SkillIntegrityError):
    """No email exists with this id."""


class UnknownInvoiceError(SkillIntegrityError):
    """The trusted vendor table has no row for this invoice."""


class UnknownSupplierError(SkillIntegrityError):
    """The trusted vendor registry has no row for this supplier."""


class UnsafePathError(SkillIntegrityError):
    """A path is absolute, escapes the workspace, or uses a disallowed root."""


class MissingPathError(SkillIntegrityError):
    """delete_file was asked to delete a path that is not present."""


class InvalidAddressError(SkillIntegrityError):
    """A recipient address is not in the required canonical form."""


class InvalidTransferError(SkillIntegrityError):
    """A transfer field failed validation."""


class WorkspaceSetupError(SkillIntegrityError):
    """The initial workspace is internally inconsistent."""


class MalformedSkillError(SkillIntegrityError):
    """A skill file or lesson body does not match the required format."""


class SkillConflictError(SkillIntegrityError):
    """An existing skill body would be rewritten with different metadata."""


class MalformedLessonError(SkillIntegrityError):
    """A reflection proposal is syntactically unusable."""


class UngroundedLessonError(SkillIntegrityError):
    """A lesson body is not a verbatim substring of the cited source."""


class UnknownLessonError(SkillIntegrityError):
    """The mock interpreter has no effect for this lesson text."""


class DuplicateLessonError(SkillIntegrityError):
    """The same lesson body was proposed twice in one reflection."""


class MissingDocBindingError(SkillIntegrityError):
    """A plan argument uses $doc before search_docs has returned a record."""


class UnknownBindingError(SkillIntegrityError):
    """An argument contains a $ token this binder does not define."""


class MissingSlotError(SkillIntegrityError):
    """A skill effect needs a task slot that was not defined."""


class PlannerStateError(SkillIntegrityError):
    """The planner was called out of order."""


class StepLimitError(SkillIntegrityError):
    """The episode exceeded the fixed tool-step budget."""


class ModelRequestError(SkillIntegrityError):
    """The OpenAI-compatible endpoint returned an error or a non-object body."""


class UnexpectedModelOutputError(SkillIntegrityError):
    """The model payload does not match the required response shape."""


class UnknownTaskError(SkillIntegrityError):
    """The scenario has no task with this id."""


class EvaluationError(SkillIntegrityError):
    """Scoring was given an incomplete or inconsistent run."""


class EmptyLengthError(SkillIntegrityError):
    """finish_reason was length and the visible content was empty."""


class ContentFiltered(SkillIntegrityError):
    """The provider returned finish_reason content_filter."""


class IncompleteModelCall(SkillIntegrityError):
    """A model call failed twice with the same request."""

    def __init__(self, *, reason: str) -> None:
        if reason == "":
            raise ValueError("incomplete reason is empty")
        self.reason = reason
        super().__init__(reason)


class UntrackedCostError(SkillIntegrityError):
    """A response did not include enough usage data to record a cost."""


class BudgetStop(SkillIntegrityError):
    """Cumulative spend reached the scheduling stop, so a new run was not started."""
