"""Package-local path guards used by every executable stage."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def local_path(value, label, must_exist=False):
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else PACKAGE_ROOT / path).resolve()
    try:
        path.relative_to(PACKAGE_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} 必须位于应用工作目录内：{PACKAGE_ROOT}") from exc
    if must_exist and not path.exists():
        raise ValueError(f"{label} 不存在：{path}")
    return path
