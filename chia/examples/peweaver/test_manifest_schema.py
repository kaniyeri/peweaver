import json
import unittest
from pathlib import Path

try:
    from .manifest_schema import ManifestValidationError, validate_manifest
except ImportError:
    from manifest_schema import ManifestValidationError, validate_manifest


ROOT = Path(__file__).parent


class ManifestSchemaTests(unittest.TestCase):
    def test_existing_benchmarks_have_valid_contracts(self):
        for path in sorted((ROOT / "benchmarks").glob("*/manifest.json")):
            with self.subTest(path=path):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIs(validate_manifest(data, path=str(path)), data)

    def test_invalid_contract_reports_structured_errors(self):
        with self.assertRaises(ManifestValidationError) as caught:
            validate_manifest({"name": "broken", "schema_version": 1, "contract": {}})
        self.assertGreaterEqual(len(caught.exception.errors), 6)
        self.assertEqual(caught.exception.as_dict()["error"], "manifest_validation")

    def test_parallel_group_must_reference_mode_components(self):
        data = json.loads((ROOT / "testdata/equivalent.json").read_text(encoding="utf-8"))
        data["contract"]["task_modes"][0]["parallel_groups"] = [["not_a_component"]]
        with self.assertRaises(ManifestValidationError) as caught:
            validate_manifest(data)
        self.assertTrue(any("unknown components" in error for error in caught.exception.errors))

    def test_schema_version_is_required(self):
        data = json.loads((ROOT / "testdata/equivalent.json").read_text(encoding="utf-8"))
        del data["schema_version"]
        with self.assertRaises(ManifestValidationError) as caught:
            validate_manifest(data)
        self.assertTrue(any("schema_version" in error for error in caught.exception.errors))


if __name__ == "__main__":
    unittest.main()
