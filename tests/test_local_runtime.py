import os
import unittest
from unittest.mock import patch

from policy_agent.paths import PACKAGE_ROOT, local_path
from policy_agent.runtime import environment


class LocalRuntimeTests(unittest.TestCase):
    def test_inherited_settings_cannot_redirect_installations_or_browsers(self):
        inherited = {
            "PIP_TARGET": str(PACKAGE_ROOT.parent / "external-packages"),
            "PIP_PREFIX": str(PACKAGE_ROOT.parent / "external-prefix"),
            "PIP_CONFIG_FILE": "global-pip.ini",
            "PIP_USER": "1",
            "PYTHONPATH": "external-libraries",
            "PYTHONUSERBASE": "external-user-base",
            "PLAYWRIGHT_BROWSERS_PATH": "external-browsers",
            "TEMP": "external-temp",
        }
        with patch.dict(os.environ, inherited):
            env = environment()
            self.assertEqual(os.environ["PIP_TARGET"], inherited["PIP_TARGET"])
        self.assertNotIn("PIP_TARGET", env)
        self.assertNotIn("PIP_PREFIX", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONUSERBASE", env)
        self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual(env["PIP_USER"], "0")
        self.assertEqual(env["PIP_REQUIRE_VIRTUALENV"], "1")
        for key in ("PIP_CACHE_DIR", "TMP", "TEMP", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH",
                    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            self.assertEqual(local_path(env[key], key), PACKAGE_ROOT / ".runtime" / {
                "PIP_CACHE_DIR": "pip-cache", "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp",
                "PLAYWRIGHT_BROWSERS_PATH": "playwright-browsers", "XDG_CACHE_HOME": "cache",
                "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
            }[key])


if __name__ == "__main__":
    unittest.main()
