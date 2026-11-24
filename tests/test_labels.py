import pytest

from skill_integrity.errors import EmptyJoinError, UnknownIntegrityLabelError
from skill_integrity.labels import Integrity, join, join_all, parse_integrity


def test_join_is_the_contaminated_upper_bound() -> None:
    pairs = (
        (Integrity.TRUSTED, Integrity.TRUSTED, Integrity.TRUSTED),
        (Integrity.TRUSTED, Integrity.UNTRUSTED, Integrity.UNTRUSTED),
        (Integrity.UNTRUSTED, Integrity.TRUSTED, Integrity.UNTRUSTED),
        (Integrity.UNTRUSTED, Integrity.UNTRUSTED, Integrity.UNTRUSTED),
    )
    for left, right, expected in pairs:
        assert join(left=left, right=right) is expected


def test_join_all_is_associative_on_the_two_point_lattice() -> None:
    labels = (Integrity.TRUSTED, Integrity.UNTRUSTED)
    for left in labels:
        for middle in labels:
            for right in labels:
                grouped_left = join(left=join(left=left, right=middle), right=right)
                grouped_right = join(left=left, right=join(left=middle, right=right))
                assert grouped_left is grouped_right
    assert join_all(labels=(Integrity.TRUSTED,)) is Integrity.TRUSTED
    assert join_all(
        labels=(Integrity.TRUSTED, Integrity.TRUSTED, Integrity.UNTRUSTED)
    ) is Integrity.UNTRUSTED


def test_empty_join_raises() -> None:
    with pytest.raises(EmptyJoinError):
        join_all(labels=())


def test_parse_integrity_accepts_only_canonical_spellings() -> None:
    assert parse_integrity(text="trusted") is Integrity.TRUSTED
    assert parse_integrity(text="untrusted") is Integrity.UNTRUSTED
    with pytest.raises(UnknownIntegrityLabelError):
        parse_integrity(text="Trusted")
    with pytest.raises(UnknownIntegrityLabelError):
        parse_integrity(text="low")
