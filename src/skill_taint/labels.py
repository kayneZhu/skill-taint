"""Two-point integrity lattice.

Trusted (T) is below untrusted (U): T ⊑ U. Join is the least upper bound, so
any combination that includes U is U. This is the integrity lattice used by
Fides (Costa et al., arXiv:2505.23643). High integrity is T. Writing a lesson
derived from U into a skill that later episodes load as instructions is an
implicit endorsement of U up to the instruction channel.
"""

from collections.abc import Sequence
from enum import Enum

from skill_taint.errors import EmptyJoinError, UnknownIntegrityLabelError


class Integrity(Enum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"

    def __str__(self) -> str:
        return self.value


_RANK = {
    Integrity.TRUSTED: 0,
    Integrity.UNTRUSTED: 1,
}


def parse_integrity(*, text: str) -> Integrity:
    for label in Integrity:
        if text == label.value:
            return label
    raise UnknownIntegrityLabelError(f"unknown integrity label: {text!r}")


def join(*, left: Integrity, right: Integrity) -> Integrity:
    if _RANK[left] >= _RANK[right]:
        return left
    return right


def join_all(*, labels: Sequence[Integrity]) -> Integrity:
    if not labels:
        raise EmptyJoinError("join_all requires at least one label")
    result = labels[0]
    for label in labels[1:]:
        result = join(left=result, right=label)
    return result
