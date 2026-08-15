#!/usr/bin/env python3
"""Plan or deploy the section 9 Notion data-source schema.

The default and `plan` modes are offline. Network writes require an explicit
`apply --execute` command, NOTION_TOKEN, and NOTION_PARENT_PAGE_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "notion_schema.json"
NOTION_VERSION = "2026-03-11"


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def create_property(prop: dict, ids: dict[str, str] | None = None) -> dict:
    kind = prop["type"]
    if kind == "relation":
        if ids is None:
            raise ValueError("relation properties are created in phase 2")
        relation = {"data_source_id": ids[prop["target"]]}
        relation[prop.get("relation_mode", "single_property")] = {}
        return {"relation": relation}
    if kind in {"status", "select", "multi_select"}:
        return {kind: {"options": [{"name": value} for value in prop.get("options", [])]}}
    return {kind: {}}


def build_plan(schema: dict, parent_page_id: str = "<PARENT_PAGE_ID>") -> dict:
    phase1 = []
    phase2 = []
    for database in schema["databases"]:
        plain = {
            name: create_property(prop)
            for name, prop in database["properties"].items()
            if prop["type"] != "relation"
        }
        phase1.append({
            "database_key": database["key"],
            "request": {
                "method": "POST", "path": "/v1/databases",
                "body": {
                    "parent": {"type": "page_id", "page_id": parent_page_id},
                    "title": [{"type": "text", "text": {"content": database["name"]}}],
                    "initial_data_source": {"properties": plain},
                },
            },
        })
        relations = {
            name: {"target": prop["target"], "relation_mode": prop.get("relation_mode", "single_property")}
            for name, prop in database["properties"].items() if prop["type"] == "relation"
        }
        phase2.append({"database_key": database["key"], "relations": relations})
    return {
        "notion_version": schema["notion_version"],
        "dry_run": True,
        "phase_1_create_databases_and_data_sources": phase1,
        "phase_2_patch_relations_after_resolving_data_source_ids": phase2,
        "phase_3_manual_views": {d["name"]: d["views"] for d in schema["databases"]},
        "phase_4_manual_templates": schema["templates"],
    }


class NotionClient:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            "https://api.notion.com" + path,
            data=json.dumps(body).encode(), method=method,
            headers={"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"Notion API {error.code} for {path}: {detail}") from error


def apply(schema: dict, parent: str, token: str) -> dict:
    client = NotionClient(token)
    ids: dict[str, str] = {}
    database_ids: dict[str, str] = {}
    # Phase 1 deliberately excludes relations: every target must exist first.
    for item in build_plan(schema, parent)["phase_1_create_databases_and_data_sources"]:
        result = client.request("POST", "/v1/databases", item["request"]["body"])
        key = item["database_key"]
        database_ids[key] = result["id"]
        ids[key] = result["data_sources"][0]["id"]
    # Phase 2 adds all relations using stable data-source IDs.
    for database in schema["databases"]:
        properties = {
            name: create_property(prop, ids)
            for name, prop in database["properties"].items() if prop["type"] == "relation"
        }
        if properties:
            client.request("PATCH", f"/v1/data_sources/{ids[database['key']]}", {"properties": properties})
    return {"database_ids": database_ids, "data_source_ids": ids,
            "manual_follow_up": "Create views/templates using docs/IMPLEMENTATION.md"}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="write a fully offline deployment plan")
    plan.add_argument("--output", type=Path)
    deploy = sub.add_parser("apply", help="create databases and properties")
    deploy.add_argument("--execute", action="store_true", help="required write safety gate")
    args = parser.parse_args()
    schema = load_schema()
    if args.command == "plan":
        result = build_plan(schema)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    if not args.execute:
        parser.error("apply is disabled without the explicit --execute safety gate")
    token = os.environ.get("NOTION_TOKEN")
    parent = os.environ.get("NOTION_PARENT_PAGE_ID")
    if not token or not parent:
        parser.error("NOTION_TOKEN and NOTION_PARENT_PAGE_ID are required")
    print(json.dumps(apply(schema, parent, token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
