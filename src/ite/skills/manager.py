from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any

import yaml

from ite.config.loader import get_config_dir
from ite.skills.trust import SkillTrustManager
from ite.utils.paths import is_binary_file

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"
REFERENCE_CONTENT_CHAR_LIMIT = 6000


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
    user_invocable: bool = False
    argument_hint: str | None = None
    reference_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: str | None = None
    author: str | None = None
    homepage: str | None = None
    trusted: bool = True
    requires_trust: bool = False

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
    def __init__(self, cwd: Path, trust_manager: SkillTrustManager | None = None):
        self.cwd = Path(cwd).resolve()
        self._skills: dict[str, SkillDefinition] = {}
        self._trust_manager = trust_manager or SkillTrustManager()

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
                "user_invocable": "true" if skill.user_invocable else "false",
                "argument_hint": skill.argument_hint or "",
                "references": str(len(skill.reference_files)),
                "trusted": "true" if skill.trusted else "false",
                "requires_trust": "true" if skill.requires_trust else "false",
                "version": skill.version or "",
                "author": skill.author or "",
                "homepage": skill.homepage or "",
            }
            for skill in self.list_skills()
        ]

    def _discovery_roots(self) -> list[tuple[str, Path]]:
        home = Path.home()
        return [
            ("shared-global", home / ".agents" / "skills"),
            ("compat-claude-global", home / ".claude" / "skills"),
            ("compat-codex-global", home / ".codex" / "skills"),
            ("compat-cursor-global", home / ".cursor" / "skills"),
            ("compat-gemini-global", home / ".gemini" / "skills"),
            ("compat-opencode-global", home / ".opencode" / "skills"),
            ("compat-kiro-global", home / ".kiro" / "skills"),
            ("compat-pi-global", home / ".pi" / "skills"),
            ("local-global-override", get_config_dir() / "skills"),
            ("shared-project", self.cwd / ".agents" / "skills"),
            ("compat-claude-project", self.cwd / ".claude" / "skills"),
            ("compat-codex-project", self.cwd / ".codex" / "skills"),
            ("compat-cursor-project", self.cwd / ".cursor" / "skills"),
            ("compat-gemini-project", self.cwd / ".gemini" / "skills"),
            ("compat-opencode-project", self.cwd / ".opencode" / "skills"),
            ("compat-kiro-project", self.cwd / ".kiro" / "skills"),
            ("compat-pi-project", self.cwd / ".pi" / "skills"),
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

        user_invocable = bool(metadata.get("user-invocable", metadata.get("user_invocable", False)))
        argument_hint = str(metadata.get("argument-hint") or metadata.get("argument_hint") or "").strip() or None
        reference_files = self._reference_files(directory)
        tags = [
            str(item).strip()
            for item in list(metadata.get("tags") or [])
            if str(item).strip()
        ] if isinstance(metadata.get("tags"), list) else []
        version = str(metadata.get("version") or "").strip() or None
        author = str(metadata.get("author") or "").strip() or None
        homepage = str(metadata.get("homepage") or metadata.get("url") or "").strip() or None
        requires_trust = self._requires_trust(source)
        trusted = (not requires_trust) or self._trust_manager.is_workspace_trusted(self.cwd)

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
            user_invocable=user_invocable,
            argument_hint=argument_hint,
            reference_files=reference_files,
            tags=tags,
            version=version,
            author=author,
            homepage=homepage,
            trusted=trusted,
            requires_trust=requires_trust,
        )

    @staticmethod
    def _requires_trust(source: str) -> bool:
        return source.endswith("-project") and source != "local-project-override"

    @staticmethod
    def _reference_files(directory: Path) -> list[str]:
        matches: list[str] = []
        for folder_name in ("reference", "references"):
            reference_dir = directory / folder_name
            if not reference_dir.is_dir():
                continue
            for path in sorted(reference_dir.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    matches.append(str(path.relative_to(directory)))
                except ValueError:
                    matches.append(str(path))
        return matches

    def load_reference_context(
        self,
        skill: SkillDefinition,
        *,
        max_chars: int = REFERENCE_CONTENT_CHAR_LIMIT,
        max_files: int = 4,
    ) -> list[dict[str, str]]:
        if max_chars <= 0 or max_files <= 0:
            return []

        selected = self._select_reference_files(skill)
        remaining = max_chars
        loaded: list[dict[str, str]] = []
        for relative_path in selected[:max_files]:
            target = skill.directory / relative_path
            if not target.is_file() or is_binary_file(target):
                continue
            try:
                content = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            content = content.strip()
            if not content:
                continue
            if len(content) > remaining:
                content = content[:remaining].rstrip() + "\n...[reference truncated]"
            loaded.append({"path": relative_path, "content": content})
            remaining -= len(content)
            if remaining <= 256:
                break
        return loaded

    @staticmethod
    def _select_reference_files(skill: SkillDefinition) -> list[str]:
        if not skill.reference_files:
            return []
        mentioned = []
        seen: set[str] = set()
        for match in re.findall(r"(?:reference|references)/[A-Za-z0-9_./-]+", skill.instructions):
            normalized = match.strip()
            if normalized in skill.reference_files and normalized not in seen:
                mentioned.append(normalized)
                seen.add(normalized)
        for path in skill.reference_files:
            if path not in seen:
                mentioned.append(path)
        return mentioned

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
