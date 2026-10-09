"""Launch only the environment inside this application directory."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
# Isolated mode omits the script directory; only this application's code is added.
sys.path.insert(0, str(ROOT))
from policy_agent.paths import local_path
from policy_agent.runtime import configure


def main():
    env = configure()
    venv_dir = local_path(ROOT / ".venv", "虚拟环境目录", must_exist=True)
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise ValueError("应用缺少本地解释器，请先执行 bootstrap.py")
    configuration = (venv_dir / "pyvenv.cfg").read_text(encoding="utf-8")
    if "include-system-site-packages = false" not in configuration.lower():
        raise ValueError("应用环境不能启用全局 site-packages")
    if Path(sys.prefix).resolve() != venv_dir or not sys.flags.isolated or not sys.flags.utf8_mode:
        return subprocess.call([str(python), "-I", "-B", "-X", "utf8", str(ROOT / "run_weekly.py"), *sys.argv[1:]], cwd=ROOT, env=env)
    from policy_agent.cli import main as run_stage
    return run_stage()

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
