import asyncio
import time
from types import SimpleNamespace

import pytest
import streamlit as st
import web_app
from services.context import ExecutionContext, use_context

DRAFT={'action':'BUY','symbol':'R_100','direction':'CALL','amount':'10.00','duration':5,'duration_unit':'t'}


def test_manager_only_proposes_and_stops_after_first_draft(monkeypatch):
    st.session_state.clear(); web_app.init_state()
    st.session_state.llm_provider='OpenAI'; st.session_state.llm_api_key='test-key'
    calls=[]
    msg=SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name='propose_trade_intent',arguments=__import__('json').dumps(DRAFT)),id='one')], content=None,model_dump=lambda **k: {'role':'assistant'})
    async def model(*a,**k): calls.append(1); return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    monkeypatch.setattr(web_app,'call_model',model)
    monkeypatch.setattr(web_app,'place_contract',lambda *a,**k: pytest.fail('Manager must not write'))
    result=web_app.run_hierarchical_trading_team('buy 10 USD CALL R_100')
    assert result.execution_report['draft']==DRAFT|{'contract_id':None}
    assert calls==[1]
    assert all(tool['function']['name']!='assign_task_to_execution_agent' for tool in web_app.MANAGER_TOOLS)


def test_duplicate_manager_draft_reuses_logical_intent(monkeypatch):
    st.session_state.clear(); web_app.init_state(); st.session_state.deriv_token='demo-token'
    def manager(*a,**k): return web_app.TeamRunResult('draft',[],execution_report={'draft':DRAFT})
    monkeypatch.setattr(web_app,'_run_hierarchical_trading_team',manager)
    first=web_app.run_hierarchical_trading_team('buy')
    st.session_state.confirm_next_trade=True
    second=web_app.run_hierarchical_trading_team('buy')
    assert first.execution_report['pending_trade']['intent_id']==second.execution_report['pending_trade']['intent_id']
    assert second.execution_report['reason']=='pending_human_confirmation'
    assert st.session_state.confirm_next_trade is False


def test_deadline_uses_monotonic_and_read_calls_cancel(monkeypatch):
    context=ExecutionContext('manager',.02)
    monkeypatch.setattr(time,'time',lambda:0)  # wall-clock jumps cannot extend the deadline
    async def slow(): await asyncio.sleep(1)
    start=time.monotonic()
    with use_context(context):
        result=web_app.call_deriv_tool('read',slow(),{})
    assert not result['ok']
    assert time.monotonic()-start<.2


def test_legacy_manager_execution_tool_is_rejected():
    assert web_app.manager_tool_dispatch('assign_task_to_execution_agent',DRAFT,[])['ok'] is False


def test_compatibility_planner_and_direct_dispatch_cannot_plan_writes(monkeypatch):
    st.session_state.clear(); web_app.init_state()
    async def forbidden(*args,**kwargs): raise AssertionError('trade intent must not use the read planner')
    monkeypatch.setattr(web_app,'call_read_model',forbidden)
    assert web_app.plan_with_openai_compatible('buy 10 USD CALL R_100','OpenAI') is None
    assert web_app.direct_tool_for_agent('execution')=='propose_trade_intent'
    args=web_app.direct_arguments('execution','买入 R_100 10 USD CALL 5分钟')
    result=web_app.manager_tool_dispatch('propose_trade_intent',args,[])
    assert result['status']=='DRAFT'
    args=web_app.direct_arguments('execution','买入 R_100 10 USD')
    assert web_app.manager_tool_dispatch('propose_trade_intent',args,[])['ok'] is False
