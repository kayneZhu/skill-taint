"""On-disk skill library. Markdown with a strict four-field frontmatter.

The library stores the label it is given. It does not infer trust from the
prose. Callers that reflect must run assign_label first. A second write of the
same body with different metadata raises; it does not upgrade or downgrade
the stored label.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from skill_integrity.errors import MalformedSkillError, SkillConflictError
from skill_integrity.labels import Integrity, parse_integrity

_TOKEN = re.compile(pattern=r"[a-z0-9_:-]+")
_HEADER_KEYS = ("id", "label", "derived_from", "episode")


@dataclass(frozen=True, kw_only=True)
class Skill:
    skill_id: str
    label: Integrity
    body: str
    derived_from: tuple[str, ...]
    episode_id: str


def skill_id_for(*, body: str) -> str:
    digest = hashlib.sha256(string=body.encode("utf-8")).hexdigest()
    return f"skill-{digest[:12]}"


def require_token(*, value: str, field: str) -> None:
    if _TOKEN.fullmatch(string=value) is None:
        raise MalformedSkillError(f"invalid {field}: {value!r}")


class SkillLibrary:
    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise MalformedSkillError(f"skill root is not a directory: {root}")

    def store_lesson(
        self,
        *,
        body: str,
        label: Integrity,
        derived_from: tuple[str, ...],
        episode_id: str,
    ) -> Skill:
        _require_body(body=body)
        if not isinstance(label, Integrity):
            raise MalformedSkillError("label must be an Integrity value")
        if not derived_from:
            raise MalformedSkillError("derived_from is empty")
        require_token(value=episode_id, field="episode")
        seen: set[str] = set()
        for segment_id in derived_from:
            require_token(value=segment_id, field="derived_from")
            if segment_id in seen:
                raise MalformedSkillError(f"duplicate citation {segment_id}")
            seen.add(segment_id)
        skill = Skill(
            skill_id=skill_id_for(body=body),
            label=label,
            body=body,
            derived_from=derived_from,
            episode_id=episode_id,
        )
        path = self._path(skill_id=skill.skill_id)
        if path.exists():
            existing = read_skill(path=path)
            if existing != skill:
                raise SkillConflictError(
                    f"skill {skill.skill_id} already stores a different lesson or label"
                )
            return existing
        write_skill(path=path, skill=skill)
        return read_skill(path=path)

    def all(self) -> tuple[Skill, ...]:
        paths = [path for path in self._root.iterdir()]
        paths.sort(key=_path_name)
        skills: list[Skill] = []
        for path in paths:
            if path.name.startswith("."):
                raise MalformedSkillError(f"unexpected hidden file {path.name}")
            if path.suffix != ".md" or not path.is_file():
                raise MalformedSkillError(f"unexpected skill entry {path.name}")
            skills.append(read_skill(path=path))
        return tuple(skills)

    def instruction_channel(self, *, quarantine_untrusted: bool) -> tuple[Skill, ...]:
        skills = self.all()
        if not quarantine_untrusted:
            return skills
        return tuple(skill for skill in skills if skill.label is Integrity.TRUSTED)

    def _path(self, *, skill_id: str) -> Path:
        require_token(value=skill_id, field="skill id")
        return self._root / f"{skill_id}.md"


def write_skill(*, path: Path, skill: Skill) -> None:
    derived = ",".join(skill.derived_from)
    text = (
        "---\n"
        f"id: {skill.skill_id}\n"
        f"label: {skill.label.value}\n"
        f"derived_from: {derived}\n"
        f"episode: {skill.episode_id}\n"
        "---\n"
        f"{skill.body}\n"
    )
    path.write_text(data=text, encoding="utf-8")


def read_skill(*, path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise MalformedSkillError(f"{path.name} is missing frontmatter")
    rest = text[len("---\n"):]
    marker = "\n---\n"
    index = rest.find(marker)
    if index == -1:
        raise MalformedSkillError(f"{path.name} is missing the closing frontmatter marker")
    header = rest[:index]
    body_plus = rest[index + len(marker):]
    if not body_plus.endswith("\n"):
        raise MalformedSkillError(f"{path.name} must end with a newline")
    body = body_plus[:-1]
    _require_body(body=body)
    fields = _parse_header(header=header, filename=path.name)
    if fields["id"] != path.stem:
        raise MalformedSkillError(f"{path.name} id does not match the filename")
    if fields["id"] != skill_id_for(body=body):
        raise MalformedSkillError(f"{path.name} id does not match the body hash")
    derived_from = tuple(fields["derived_from"].split(","))
    if not derived_from or "" in derived_from:
        raise MalformedSkillError(f"{path.name} has an empty citation")
    for segment_id in derived_from:
        require_token(value=segment_id, field="derived_from")
    episode_id = fields["episode"]
    require_token(value=episode_id, field="episode")
    return Skill(
        skill_id=fields["id"],
        label=parse_integrity(text=fields["label"]),
        body=body,
        derived_from=derived_from,
        episode_id=episode_id,
    )


def _require_body(*, body: str) -> None:
    if body == "" or body.strip() != body or "\n" in body:
        raise MalformedSkillError("lesson body must be a single non-empty line")


def _parse_header(*, header: str, filename: str) -> dict[str, str]:
    lines = header.split("\n")
    if tuple(line.split(sep=": ", maxsplit=1)[0] for line in lines) != _HEADER_KEYS:
        raise MalformedSkillError(f"{filename} header keys must be {_HEADER_KEYS} in order")
    fields: dict[str, str] = {}
    for line in lines:
        key, value = line.split(sep=": ", maxsplit=1)
        if value == "":
            raise MalformedSkillError(f"{filename} has an empty {key}")
        fields[key] = value
    return fields


def _path_name(path: Path) -> str:
    return path.name
