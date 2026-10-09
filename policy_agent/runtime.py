"""Keep environment changes process-local and writable runtime files package-local."""
import os
import tempfile
from .paths import PACKAGE_ROOT, local_path


def environment():
    env = os.environ.copy()
    # Inherited pip prefixes/targets and config files can redirect installs outside the venv.
    for key in tuple(env):
        if key.startswith("PIP_") or key in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"}:
            env.pop(key)
    runtime = local_path(PACKAGE_ROOT / ".runtime", "运行时目录")
    for folder in ("pip-cache", "tmp", "playwright-browsers", "cache", "config", "data"):
        local_path(runtime / folder, "运行时子目录").mkdir(parents=True, exist_ok=True)
    env.update({
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_USER": "0",
        "PIP_REQUIRE_VIRTUALENV": "1",
        "PIP_CACHE_DIR": str(runtime / "pip-cache"),
        "TMPDIR": str(runtime / "tmp"),
        "TEMP": str(runtime / "tmp"),
        "TMP": str(runtime / "tmp"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PLAYWRIGHT_BROWSERS_PATH": str(runtime / "playwright-browsers"),
        "XDG_CACHE_HOME": str(runtime / "cache"),
        "XDG_CONFIG_HOME": str(runtime / "config"),
        "XDG_DATA_HOME": str(runtime / "data"),
        "MPLCONFIGDIR": str(runtime / "config" / "matplotlib"),
    })
    return env


def configure():
    """Changes affect this process and its children, never system/user settings."""
    env = environment()
    for key in tuple(os.environ):
        if key.startswith("PIP_") or key in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"}:
            os.environ.pop(key)
    os.environ.update(env)
    tempfile.tempdir = env["TMPDIR"]
    return env
