"""Tests del adaptador OpenAI→Anthropic (traducción en ambos sentidos)."""
import json

from tests.llm.fake_openai import FakeOpenAI, text_response, tool_response, tool_call
from vera.llm.openai_compat_client import OpenAICompatClient


def _client(scripted):
    fake = FakeOpenAI(scripted)
    return OpenAICompatClient("http://x/v1", "key", "m", client=fake), fake


# ---------- ENTRADA: respuesta OpenAI → bloques Anthropic ----------

def test_text_response_maps_to_end_turn():
    client, _ = _client([text_response("hola mundo")])
    with client.messages.stream(model="m", messages=[{"role": "user", "content": "hi"}]) as s:
        resp = s.get_final_message()
    assert resp.stop_reason == "end_turn"
    assert len(resp.content) == 1
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "hola mundo"


def test_tool_calls_map_to_tool_use_blocks():
    client, _ = _client([
        tool_response([tool_call("call_1", "echo", '{"x": 5}')])
    ])
    with client.messages.stream(model="m", messages=[{"role": "user", "content": "go"}]) as s:
        resp = s.get_final_message()
    assert resp.stop_reason == "tool_use"
    blocks = [b for b in resp.content if b.type == "tool_use"]
    assert len(blocks) == 1
    assert blocks[0].id == "call_1"
    assert blocks[0].name == "echo"
    assert blocks[0].input == {"x": 5}


def test_multiple_tool_calls_in_one_turn():
    client, _ = _client([
        tool_response([
            tool_call("c1", "a", '{"n": 1}'),
            tool_call("c2", "b", '{"n": 2}'),
        ])
    ])
    with client.messages.stream(model="m", messages=[]) as s:
        resp = s.get_final_message()
    tus = [b for b in resp.content if b.type == "tool_use"]
    assert [b.id for b in tus] == ["c1", "c2"]
    assert [b.name for b in tus] == ["a", "b"]
    assert [b.input for b in tus] == [{"n": 1}, {"n": 2}]


def test_text_plus_tool_call_includes_text_block():
    client, _ = _client([
        tool_response([tool_call("c1", "echo", "{}")], text="voy a usar echo")
    ])
    with client.messages.stream(model="m", messages=[]) as s:
        resp = s.get_final_message()
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "voy a usar echo"
    assert resp.content[1].type == "tool_use"


def test_empty_arguments_become_empty_dict():
    client, _ = _client([tool_response([tool_call("c1", "echo", "")])])
    with client.messages.stream(model="m", messages=[]) as s:
        resp = s.get_final_message()
    assert resp.content[0].input == {}


def test_response_blocks_are_reintrospectable_as_anthropic_history():
    """El loop re-mete resp.content en messages → debe re-traducirse sin error."""
    client, fake = _client([
        tool_response([tool_call("c1", "echo", '{"x": 1}')]),
        text_response("listo"),
    ])
    with client.messages.stream(model="m", messages=[]) as s:
        resp = s.get_final_message()
    # simular lo que hace el loop: appendea los OBJETOS bloque
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": resp.content},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "ok", "is_error": False}
        ]},
    ]
    with client.messages.stream(model="m", messages=history) as s:
        s.get_final_message()
    sent = fake.calls[1]["messages"]
    assistant = [m for m in sent if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"x": 1}
    tool_msg = [m for m in sent if m["role"] == "tool"][0]
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "ok"


# ---------- SALIDA: tools/mensajes/system Anthropic → OpenAI ----------

def test_tools_translated_to_openai_function_schema():
    client, fake = _client([text_response("ok")])
    tools = [{"name": "echo", "description": "echoes", "input_schema": {"type": "object"}}]
    with client.messages.stream(model="m", tools=tools, messages=[]) as s:
        s.get_final_message()
    sent_tools = fake.calls[0]["tools"]
    assert sent_tools[0]["type"] == "function"
    assert sent_tools[0]["function"]["name"] == "echo"
    assert sent_tools[0]["function"]["description"] == "echoes"
    assert sent_tools[0]["function"]["parameters"] == {"type": "object"}
    assert fake.calls[0]["tool_choice"] == "auto"


def test_system_becomes_first_system_message():
    client, fake = _client([text_response("ok")])
    with client.messages.stream(model="m", system="sos VERA",
                                messages=[{"role": "user", "content": "hi"}]) as s:
        s.get_final_message()
    sent = fake.calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "sos VERA"}
    assert sent[1] == {"role": "user", "content": "hi"}


def test_no_system_when_empty():
    client, fake = _client([text_response("ok")])
    with client.messages.stream(model="m", system="",
                                messages=[{"role": "user", "content": "hi"}]) as s:
        s.get_final_message()
    assert fake.calls[0]["messages"][0]["role"] == "user"


def test_assistant_block_list_with_tool_use_translated():
    client, fake = _client([text_response("ok")])
    from types import SimpleNamespace as NS
    assistant_blocks = [
        NS(type="text", text="pienso"),
        NS(type="tool_use", id="c1", name="echo", input={"x": 7}),
    ]
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": assistant_blocks},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "echo:7", "is_error": False}
        ]},
    ]
    with client.messages.stream(model="m", messages=history) as s:
        s.get_final_message()
    sent = fake.calls[0]["messages"]
    assistant = [m for m in sent if m["role"] == "assistant"][0]
    assert assistant["content"] == "pienso"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["type"] == "function"
    assert assistant["tool_calls"][0]["function"]["name"] == "echo"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"x": 7}
    tool_msg = [m for m in sent if m["role"] == "tool"][0]
    assert tool_msg["content"] == "echo:7"


def test_multiple_tool_results_become_separate_tool_messages():
    client, fake = _client([text_response("ok")])
    history = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "r1", "is_error": False},
            {"type": "tool_result", "tool_use_id": "c2", "content": "r2", "is_error": True},
        ]},
    ]
    with client.messages.stream(model="m", messages=history) as s:
        s.get_final_message()
    tool_msgs = [m for m in fake.calls[0]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0]["tool_call_id"] == "c1"
    assert tool_msgs[1]["tool_call_id"] == "c2"


def test_tool_result_with_block_list_content_is_stringified():
    """Algunas tools devuelven content como lista de bloques (texto+imagen)."""
    client, fake = _client([text_response("ok")])
    history = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1",
             "content": [{"type": "text", "text": "hola"}], "is_error": False},
        ]},
    ]
    with client.messages.stream(model="m", messages=history) as s:
        s.get_final_message()
    tool_msg = [m for m in fake.calls[0]["messages"] if m["role"] == "tool"][0]
    assert isinstance(tool_msg["content"], str)
    assert "hola" in tool_msg["content"]


def test_model_is_forwarded():
    client, fake = _client([text_response("ok")])
    with client.messages.stream(model="qwen-32b", messages=[]) as s:
        s.get_final_message()
    assert fake.calls[0]["model"] == "qwen-32b"


def test_thinking_kwarg_is_accepted_and_ignored():
    client, fake = _client([text_response("ok")])
    with client.messages.stream(model="m", max_tokens=16000,
                                thinking={"type": "adaptive"}, messages=[]) as s:
        list(s)  # iterar no debe romper aunque no haya eventos
        resp = s.get_final_message()
    assert resp.stop_reason == "end_turn"
    assert "thinking" not in fake.calls[0]


def test_max_tokens_forwarded_as_max_tokens():
    client, fake = _client([text_response("ok")])
    with client.messages.stream(model="m", max_tokens=16000, messages=[]) as s:
        s.get_final_message()
    assert fake.calls[0].get("max_tokens") == 16000
