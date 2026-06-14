from vera.agent.factory import build_agent_loop


class _DummyLLM:
    pass


def test_build_agent_loop_discovers_run_ue_python():
    loop = build_agent_loop(llm_client=_DummyLLM())
    assert loop.registry.get("run_ue_python") is not None
    # the system prompt is not empty (it defines VERA's role)
    assert loop.system.strip() != ""
