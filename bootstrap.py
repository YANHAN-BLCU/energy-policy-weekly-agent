"""Create the package-local Python environment and optional browser runtime."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse
import json
import os
import subprocess
import venv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy_agent.paths import local_path
from policy_agent.runtime import configure

PACKAGE_ROOT = Path(__file__).resolve().parent
VENV_DIR = PACKAGE_ROOT / ".venv"
RUNTIME_DIR = PACKAGE_ROOT / ".runtime"


def local_python():
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command, env):
    print("$", " ".join(map(str, command)), flush=True)
    subprocess.run(command, check=True, cwd=PACKAGE_ROOT, env=env)


def main(argv=None):
    parser = argparse.ArgumentParser(description="仅在应用目录创建 Python 与可选浏览器运行环境")
    parser.add_argument("--browser", action="store_true", help="在应用目录安装 Playwright 和 Chromium")
    args = parser.parse_args(argv)
    env = configure()
    local_path(VENV_DIR, "虚拟环境目录")
    if not VENV_DIR.exists():
        venv.EnvBuilder(with_pip=True, clear=False, system_site_packages=False).create(VENV_DIR)
    python = local_python()
    configuration = (VENV_DIR / "pyvenv.cfg").read_text(encoding="utf-8")
    if "include-system-site-packages = false" not in configuration.lower():
        raise ValueError("包内 .venv 必须关闭全局 site-packages，请重建此本地环境")
    requirements = PACKAGE_ROOT / ("requirements-browser.txt" if args.browser else "requirements.txt")
    run([str(python), "-I", "-X", "utf8", "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "-r", str(requirements)], env)
    if args.browser:
        run([str(python), "-I", "-X", "utf8", "-m", "playwright", "install", "chromium"], env)
    print(json.dumps({"python": str(python), "runtime": str(RUNTIME_DIR), "browser": args.browser}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
