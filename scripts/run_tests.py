"""Run synthetic tests against this directory, using the current local interpreter."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_agent.taxonomy import dictionary

if not dictionary().get("demo"):
    raise SystemExit("测试仅可使用虚构字典；在独立工作目录运行 init_local_data.py --demo")
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
