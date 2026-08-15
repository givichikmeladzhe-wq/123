import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/notion_schema.json").read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_has_exactly_the_required_databases(self):
        self.assertEqual([d["name"] for d in SCHEMA["databases"]], [
            "Projects", "Tasks / Backlog", "Decisions", "Open Questions", "Agents",
            "Agent Brain / Prompt Versions", "Operating Manual", "Changes",
            "Source Events", "Approvals", "Briefings",
        ])

    def test_common_properties_and_stable_id_are_everywhere(self):
        common = {"Name", "Entity ID", "State Version", "Source Events", "Last Change",
                  "Last Command ID", "Audit Status", "Created", "Created By",
                  "Last Edited", "Last Edited By"}
        for database in SCHEMA["databases"]:
            self.assertTrue(common <= database["properties"].keys(), database["name"])
            self.assertTrue(database["properties"]["Entity ID"]["required"])

    def test_relation_targets_exist(self):
        keys = {d["key"] for d in SCHEMA["databases"]}
        for database in SCHEMA["databases"]:
            for name, prop in database["properties"].items():
                if prop["type"] == "relation":
                    self.assertIn(prop["target"], keys, f"{database['name']}.{name}")

    def test_required_views_match_request(self):
        expected = {
            "Projects": 4, "Tasks / Backlog": 8, "Decisions": 5, "Open Questions": 4,
            "Agents": 4, "Agent Brain / Prompt Versions": 6, "Operating Manual": 5,
            "Changes": 4, "Source Events": 5, "Approvals": 4, "Briefings": 6,
        }
        self.assertEqual({d["name"]: len(d["views"]) for d in SCHEMA["databases"]}, expected)

    def test_plan_is_offline_and_has_two_api_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plan.json"
            subprocess.run(["python3", str(ROOT / "scripts/deploy_notion.py"), "plan",
                            "--output", str(output)], check=True)
            plan = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["notion_version"], "2026-03-11")
        self.assertEqual(len(plan["phase_1_create_databases_and_data_sources"]), 11)
        for item in plan["phase_1_create_databases_and_data_sources"]:
            properties = item["request"]["body"]["initial_data_source"]["properties"]
            self.assertNotIn("relation", {v.keys().__iter__().__next__() for v in properties.values()})


if __name__ == "__main__":
    unittest.main()
