from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any

import yaml

from ite.config.loader import get_config_dir

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"


def _slugify(value: str) -> str:
    lowered = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "skill"


@dataclass
class SkillDefinition:
    identifier: str
    name: str
    description: str
    instructions: str
    directory: Path
    skill_file: Path
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.name} — {self.description}"

    def matches(self, reference: str) -> bool:
        query = str(reference or "").strip().lower()
        if not query:
            return False
        candidates = {self.identifier.lower(), self.name.strip().lower()}
        candidates.update(alias.lower() for alias in self.aliases)
        return query in candidates

    def prompt_block(self) -> str:
        return (
            f"## Skill: {self.name}\n"
            f"Source: {self.source}\n"
            f"Description: {self.description}\n\n"
            f"{self.instructions.strip()}"
        ).strip()


class SkillManager:
    def __init__(self, cwd: Path):
        self.cwd = Path(cwd).resolve()
        self._skills: dict[str, SkillDefinition] = {}

    def discover(self) -> list[SkillDefinition]:
        skills: dict[str, SkillDefinition] = {}
        for label, directory in self._discovery_roots():
            for skill in self._scan_directory(directory, source=label):
                skills[skill.identifier] = skill
        self._skills = skills
        return self.list_skills()

    def list_skills(self) -> list[SkillDefinition]:
        return sorted(self._skills.values(), key=lambda skill: skill.identifier)

    def get(self, reference: str) -> SkillDefinition | None:
        query = str(reference or "").strip()
        if not query:
            return None
        lowered = query.lower()
        if lowered in self._skills:
            return self._skills[lowered]
        for skill in self._skills.values():
            if skill.matches(query):
                return skill
        return None

    def summaries(self) -> list[dict[str, str]]:
        return [
            {
                "identifier": skill.identifier,
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
            }
            for skill in self.list_skills()
        ]

    def _discovery_roots(self) -> list[tuple[str, Path]]:
        home = Path.home()
        return [
            ("shared-global", home / ".agents" / "skills"),
            ("compat-claude-global", home / ".claude" / "skills"),
            ("local-global-override", get_config_dir() / "skills"),
            ("shared-project", self.cwd / ".agents" / "skills"),
            ("compat-claude-project", self.cwd / ".claude" / "skills"),
            ("local-project-override", self.cwd / ".ite" / "skills"),
        ]

    def _scan_directory(self, directory: Path, *, source: str) -> list[SkillDefinition]:
        if not directory.is_dir():
            return []
        discovered: list[SkillDefinition] = []
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            skill = self._load_skill(child, source=source)
            if skill is not None:
                discovered.append(skill)
        return discovered

    def _load_skill(self, directory: Path, *, source: str) -> SkillDefinition | None:
        skill_file = directory / SKILL_FILE_NAME
        if not skill_file.is_file():
            return None
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read skill file %s: %s", skill_file, exc)
            return None

        frontmatter, body = self._split_frontmatter(text)
        if frontmatter is None:
            logger.warning("Skipping skill without YAML frontmatter: %s", skill_file)
            return None
        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError as exc:
            logger.warning("Skipping skill with invalid frontmatter %s: %s", skill_file, exc)
            return None
        if not isinstance(metadata, dict):
            logger.warning("Skipping skill with non-object frontmatter: %s", skill_file)
            return None

        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        instructions = body.strip()
        if not name or not description or not instructions:
            logger.warning(
                "Skipping skill missing name, description, or instructions: %s",
                skill_file,
            )
            return None

        aliases = {_slugify(name), _slugify(directory.name), directory.name.strip().lower()}
        if isinstance(metadata.get("aliases"), list):
            aliases.update(_slugify(item) for item in metadata["aliases"] if str(item).strip())
            aliases.update(str(item).strip().lower() for item in metadata["aliases"] if str(item).strip())

        return SkillDefinition(
            identifier=_slugify(name),
            name=name,
            description=description,
            instructions=instructions,
            directory=directory,
            skill_file=skill_file,
            source=source,
            metadata=metadata,
            aliases=sorted(alias for alias in aliases if alias),
        )

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[str | None, str]:
        if not text.startswith("---\n"):
            return None, text
        closing = text.find("\n---", 4)
        if closing == -1:
            return None, text
        frontmatter = text[4:closing]
        body_start = closing + 4
        if body_start < len(text) and text[body_start] == "\n":
            body_start += 1
        return frontmatter, text[body_start:]
