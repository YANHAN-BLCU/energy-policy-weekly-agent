import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from policy_agent.paths import PACKAGE_ROOT
from policy_agent.taxonomy import validate_classification, validate_issuers, dictionary
from scripts.init_local_data import initialize


class LocalDataTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=".test-import-", dir=PACKAGE_ROOT))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.sources = json.loads((PACKAGE_ROOT / "examples/sources.example.json").read_text(encoding="utf-8"))
        self.vocabulary = json.loads((PACKAGE_ROOT / "examples/mi_dictionary.example.json").read_text(encoding="utf-8"))

    def test_import_creates_consistent_relocatable_local_assets(self):
        self.assertTrue(initialize(self.sources, self.vocabulary, root=self.root)["manifest_checked"])
        self.assertEqual(json.loads((self.root / "config/sources.json").read_text(encoding="utf-8")), self.sources)

    def test_import_does_not_overwrite_existing_assets(self):
        initialize(self.sources, self.vocabulary, root=self.root)
        original = (self.root / "policy_agent/data/mi_dictionary.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "已存在"):
            initialize(self.sources, self.vocabulary, root=self.root)
        self.assertEqual((self.root / "policy_agent/data/mi_dictionary.json").read_bytes(), original)

    def test_invalid_import_leaves_no_data_files(self):
        self.vocabulary["export_fields"].reverse()
        with self.assertRaises(ValueError):
            initialize(self.sources, self.vocabulary, root=self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_demo_cannot_enable_network_sources(self):
        self.sources["sources"][0]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "停用"):
            initialize(self.sources, self.vocabulary, root=self.root)

    def test_unknown_labels_and_issuers_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_classification("Other category", "Example Efficiency")
        with self.assertRaises(ValueError):
            validate_issuers({"body_text": "示例能源机构发布通知"}, [{"code": "UNKNOWN", "evidence_quote": "示例能源机构"}])

    def test_evidence_must_be_verbatim_and_office_not_parent(self):
        with self.assertRaises(ValueError):
            validate_issuers({"body_text": "示例能源机构发布通知"}, [{"code": "DEMO", "evidence_quote": "猜测的署名"}])
        with self.assertRaisesRegex(ValueError, "office"):
            validate_issuers({"body_text": "示例能源机构办公厅发布通知"}, [{"code": "DEMO", "evidence_quote": "示例能源机构"}])


if __name__ == "__main__":
    unittest.main()
