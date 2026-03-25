from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

SUPPORTED_PACK_ROOTS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".cursor/skills",
    ".gemini/skills",
    ".opencode/skills",
    ".kiro/skills",
    ".pi/skills",
)


@dataclass
class SkillInstallResult:
    source: Path
    destination: Path
    installed_skill_names: list[str]
    detected_root: str


def install_skills_from_source(
    source: Path,
    destination_root: Path,
) -> SkillInstallResult:
    resolved_source = Path(source).expanduser().resolve()
    resolved_dest = Path(destination_root).expanduser().resolve()
    if not resolved_source.exists():
        raise FileNotFoundError(f"Skill source not found: {resolved_source}")

    skill_directories, detected_root = _detect_skill_directories(resolved_source)
    if not skill_directories:
        raise ValueError(
            "No skills found. Expected a skill directory with SKILL.md or a universal pack containing */skills/<name>/SKILL.md."
        )

    resolved_dest.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for skill_dir in skill_directories:
        target = resolved_dest / skill_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            skill_dir,
            target,
            ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"),
        )
        installed.append(skill_dir.name)

    return SkillInstallResult(
        source=resolved_source,
        destination=resolved_dest,
        installed_skill_names=sorted(installed),
        detected_root=detected_root,
    )


def _detect_skill_directories(source: Path) -> tuple[list[Path], str]:
    if (source / "SKILL.md").is_file():
        return [source], "direct-skill"

    for root in SUPPORTED_PACK_ROOTS:
        candidate = source / root
        dirs = _skill_directories_under(candidate)
        if dirs:
            return dirs, root

    dirs = _skill_directories_under(source)
    if dirs:
        return dirs, "direct-folder"

    return [], "none"


def _skill_directories_under(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    )
