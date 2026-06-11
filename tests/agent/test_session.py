from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.session import MAX_HISTORY_MESSAGES, AgentSession
from tests.agent.fakes import FakeClient, _Resp, _Text


def test_el_historial_sobrevive_entre_comandos():
    loop_client = FakeClient([
        _Resp("end_turn", [_Text("cubo creado")]),
        _Resp("end_turn", [_Text("ahora es rojo")]),
    ])
    s = AgentSession(AgentLoop(ToolRegistry(), loop_client))
    s.run("creá un cubo")
    s.run("hacelo rojo")
    # la segunda request debe llevar el turno anterior completo
    msgs = loop_client.messages.calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "creá un cubo"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[2] == {"role": "user", "content": "hacelo rojo"}


def test_inject_agrega_un_turno_proactivo():
    client = FakeClient([_Resp("end_turn", [_Text("arreglado")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    out = s.inject("Error de compilación en el log: arreglalo si es seguro.")
    assert out["status"] == "success"
    assert s.messages[0]["role"] == "user"


def test_trim_corta_en_turno_user_de_texto_plano():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    # historial sintético más largo que el máximo, con pares tool_use/tool_result
    for i in range(MAX_HISTORY_MESSAGES):
        s.messages.append({"role": "user", "content": f"comando {i}"})
        s.messages.append({"role": "assistant", "content": [{"type": "tool_use"}]})
        s.messages.append({"role": "user", "content": [{"type": "tool_result"}]})
        s.messages.append({"role": "assistant", "content": [{"type": "text"}]})
    s.run("último comando")
    assert len(s.messages) <= MAX_HISTORY_MESSAGES + 2  # +turno nuevo y respuesta
    # nunca arrancar el historial en medio de un par tool_use/tool_result
    assert s.messages[0]["role"] == "user"
    assert isinstance(s.messages[0]["content"], str)
