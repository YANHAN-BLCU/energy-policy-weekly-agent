"""Check the entire tracked tree, including forced additions of ignored assets."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOP = {"README.md", "SKILL.md", ".gitignore", ".gitattributes", "bootstrap.py", "run_weekly.py",
       "pyproject.toml", "requirements.txt", "requirements-browser.txt"}
EXAMPLES = {"examples/sources.example.json", "examples/mi_dictionary.example.json"}
DOCS = {"docs/ARCHITECTURE.md", "docs/HOST_PROTOCOL.md", "docs/LOCAL_DATA.md", "docs/MIGRATION.md"}
SKILLS = {"skills/policy-weekly-collector/SKILL.md"}
SECRET_PATTERNS = [r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
                   r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", r"sk-[A-Za-z0-9_-]{24,}"]


def allowed(name):
    path = PurePosixPath(name)
    if name in TOP | EXAMPLES | DOCS | SKILLS:
        return True
    return len(path.parts) == 2 and path.parts[0] in {"policy_agent", "scripts", "tests"} and path.suffix == ".py"


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name]
    if not names:
        raise SystemExit("没有跟踪文件；先在独立公开目录暂存代码，再检查")
    errors = []
    for name in names:
        if not allowed(name):
            errors.append("不允许公开的文件类型或路径：" + name)
            continue
        path = ROOT / name
        if path.is_symlink():
            errors.append("不允许发布符号链接：" + name)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            errors.append("文件不是可检查的 UTF-8 文本：" + name)
            continue
        if any(re.search(pattern, text) for pattern in SECRET_PATTERNS):
            errors.append("疑似凭证（内容不输出）：" + name)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"公开路径与凭证检查通过：{len(names)} 个跟踪文件。仍需人工审查代码中的业务数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
