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


def test_agent_memory_appends_and_limits_context() -> None:
    state = {"agent_memory": {}}

    for index in range(3):
        web_app.append_agent_memory_to_state(
            state,
            "market",
            {"time": f"10:0{index}", "summary": f"memory {index}"},
            limit=2,
        )

    assert [item["summary"] for item in state["agent_memory"]["market"]] == ["memory 1", "memory 2"]


def test_ui_does_not_render_debug_code_blocks() -> None:
    source = web_app.Path(web_app.__file__).read_text(encoding="utf-8")

    assert "st.code(" not in source
    assert "st.json(" not in source


def test_init_state_can_prefill_local_environment_secrets(monkeypatch) -> None:
    monkeypatch.setenv("DERIV_API_TOKEN", "demo-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    web_app.st.session_state.clear()
    web_app.init_state()

    assert web_app.st.session_state.deriv_token == "demo-token"
    assert web_app.st.session_state.llm_provider == "DeepSeek"
    assert web_app.st.session_state.llm_api_key == "deepseek-key"
    assert web_app.st.session_state.llm_model == "deepseek-reasoner"
