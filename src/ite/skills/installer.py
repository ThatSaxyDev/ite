from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

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
GITHUB_SHORTHAND_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?(?:\.git)?$"
)


@dataclass
class SkillInstallResult:
    source: Path
    destination: Path
    installed_skill_names: list[str]
    detected_root: str


def install_skills_from_source(
    source: Path | str,
    destination_root: Path,
) -> SkillInstallResult:
    source_text = str(source).strip()
    resolved_dest = Path(destination_root).expanduser().resolve()
    with _materialize_install_source(source_text) as materialized_source:
        skill_directories, detected_root = _detect_skill_directories(materialized_source)
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
        source=Path(source_text).expanduser(),
        destination=resolved_dest,
        installed_skill_names=sorted(installed),
        detected_root=detected_root,
    )


@contextmanager
def _materialize_install_source(source: str):
    raw = str(source or "").strip()
    candidate = Path(raw).expanduser()
    if candidate.exists():
        yield candidate.resolve()
        return

    remote_url = _remote_url_for_reference(raw)
    if remote_url is None:
        raise FileNotFoundError(f"Skill source not found: {candidate}")

    with tempfile.TemporaryDirectory(prefix="ite-skills-") as temp_dir:
        checkout = Path(temp_dir) / "source"
        _clone_skill_repo(remote_url, checkout)
        yield checkout.resolve()


def _remote_url_for_reference(source: str) -> str | None:
    raw = str(source or "").strip()
    if not raw:
        return None
    if raw.startswith(("https://", "http://", "ssh://", "git@", "file://")):
        return raw
    if GITHUB_SHORTHAND_RE.match(raw):
        suffix = raw if raw.endswith(".git") else f"{raw}.git"
        return f"https://github.com/{suffix}"
    return None


def _clone_skill_repo(source: str, destination: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", source, str(destination)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Git is not installed or not in PATH. Please install Git from https://git-scm.com/downloads"
        )
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(
        f"Failed to clone skill source {source}: {detail or f'git exited with status {result.returncode}'}"
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
