from pathlib import Path
from config.loader import get_data_dir
from config.config import SandboxPolicy


class SandboxViolation(Exception):
    """Raised when a path access violates sandbox boundaries."""

    def __init__(self, path: Path, allowed: list[Path]):
        self.path = path
        self.allowed = allowed
        boundaries = ", ".join(str(p) for p in allowed)
        super().__init__(
            f"Sandbox violation: '{path}' is outside allowed boundaries [{boundaries}]"
        )


def validate_path(
    resolved_path: Path,
    cwd: Path,
    sandbox_config: SandboxPolicy,
) -> Path:
    """Validate that a resolved path is within sandbox boundaries.

    Always allows:
      - Anything under cwd
      - The app data dir (for memory, sessions, etc.)
      - Any paths in sandbox_config.allowed_paths

    Raises SandboxViolation if the path is outside all allowed boundaries.
    Returns the resolved path if valid.
    """
    if not sandbox_config.enabled:
        return resolved_path

    # Resolve symlinks to prevent escape
    try:
        real_path = resolved_path.resolve()
    except OSError:
        real_path = resolved_path

    real_cwd = cwd.resolve()

    # Always allow project cwd
    if _is_within(real_path, real_cwd):
        return resolved_path

    # Always allow app data dir (memory, sessions, config)
    data_dir = get_data_dir().resolve()
    if _is_within(real_path, data_dir):
        return resolved_path

    # Check explicitly allowed paths
    for allowed in sandbox_config.allowed_paths:
        real_allowed = allowed.resolve()
        if _is_within(real_path, real_allowed):
            return resolved_path

    raise SandboxViolation(
        path=resolved_path,
        allowed=[real_cwd] + [p.resolve() for p in sandbox_config.allowed_paths],
    )


def _is_within(path: Path, boundary: Path) -> bool:
    """Check if path is within boundary directory (or is the boundary itself)."""
    try:
        path.relative_to(boundary)
        return True
    except ValueError:
        return False
