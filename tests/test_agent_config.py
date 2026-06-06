from __future__ import annotations

import web_app


def test_prompt_registry_has_required_agents() -> None:
    prompts = web_app.load_agent_prompts()
    required = {
        "manager",
        "market",
        "strategy",
        "risk",
        "compliance",
        "chart",
        "execution",
        "report",
        "advisor.chief",
        "advisor.macro",
        "advisor.quant",
        "advisor.flow",
        "advisor.risk",
        "advisor.contrarian",
    }
    missing = required.difference(prompts)
    assert not missing
    assert all(prompts[key]["prompt"].strip() for key in required)


def test_advisor_specs_match_prompt_registry() -> None:
    prompts = web_app.load_agent_prompts()
    prompt_ids = {
        key.split(".", 1)[1]
        for key in prompts
        if key.startswith("advisor.") and key != "advisor.chief"
    }
    spec_ids = {item["id"] for item in web_app.advisor_specs()}
    assert prompt_ids.issubset(spec_ids)


def test_safe_agent_id_and_node_name() -> None:
    assert web_app.safe_agent_id("Breakout Master!") == "breakout_master"
    assert web_app.safe_agent_id("   ") == "custom"
    assert web_app.advisor_node_name("Breakout Master!") == "advisor_breakout_master"


def test_agent_ai_brief_is_disabled_outside_streamlit_runtime() -> None:
    report: dict[str, object] = {}
    events: list[web_app.AgentEvent] = []

    result = web_app.attach_agent_ai_brief(
        report,
        "market",
        task="检查 R_100",
        context={"symbol": "R_100"},
        events=events,
    )

    assert result["ai_enabled"] is False
    assert "ai_brief" not in result
    assert events == []
