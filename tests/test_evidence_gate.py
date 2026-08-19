from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_resume_evidence import validate


ROOT = Path(__file__).resolve().parents[1]


def test_committed_resume_evidence_passes_recalculation_gate() -> None:
    errors = validate(
        ROOT / "docs/resume-evidence.json",
        ROOT / "docs/evidence/runtime-evidence.json",
    )
    assert errors == []


def test_tampered_exact_count_fails_gate(tmp_path: Path) -> None:
    runtime = json.loads(
        (ROOT / "docs/evidence/runtime-evidence.json").read_text(encoding="utf-8")
    )
    runtime["graph"]["advisor_parallel_role_count"] = 500
    tampered = tmp_path / "runtime-tampered.json"
    tampered.write_text(json.dumps(runtime), encoding="utf-8")
    errors = validate(ROOT / "docs/resume-evidence.json", tampered)
    assert "advisor role count/list mismatch" in errors


def test_tampered_schema_hash_fails_gate(tmp_path: Path) -> None:
    runtime = json.loads(
        (ROOT / "docs/evidence/runtime-evidence.json").read_text(encoding="utf-8")
    )
    runtime["mcp"]["schema_sha256"] = "0" * 64
    tampered = tmp_path / "runtime-tampered.json"
    tampered.write_text(json.dumps(runtime), encoding="utf-8")
    errors = validate(ROOT / "docs/resume-evidence.json", tampered)
    assert "recorded MCP schema hash does not match runtime enumeration" in errors


def test_tampered_mcp_tool_count_fails_gate(tmp_path: Path) -> None:
    runtime = json.loads(
        (ROOT / "docs/evidence/runtime-evidence.json").read_text(encoding="utf-8")
    )
    runtime["mcp"]["tool_count"] = 600
    tampered = tmp_path / "runtime-tampered.json"
    tampered.write_text(json.dumps(runtime), encoding="utf-8")
    errors = validate(ROOT / "docs/resume-evidence.json", tampered)
    assert "recorded FastMCP tool count is not exactly 6" in errors


def test_unlabelled_fixture_fails_gate(tmp_path: Path) -> None:
    runtime = json.loads(
        (ROOT / "docs/evidence/runtime-evidence.json").read_text(encoding="utf-8")
    )
    runtime["decision_budget"]["fixture"] = False
    tampered = tmp_path / "runtime-tampered.json"
    tampered.write_text(json.dumps(runtime), encoding="utf-8")
    errors = validate(ROOT / "docs/resume-evidence.json", tampered)
    assert "offline benchmark must be labelled fixture" in errors
