from pathlib import Path

from vera.tools.mcp_server import tail_log


def test_tail_log_returns_last_n_lines(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_text("\n".join(f"linea {i}" for i in range(200)), encoding="utf-8")
    out = tail_log(log, lines=5)
    assert out.splitlines() == ["linea 195", "linea 196", "linea 197", "linea 198", "linea 199"]


def test_tail_log_missing_file_returns_message(tmp_path):
    out = tail_log(tmp_path / "no_existe.log", lines=10)
    assert "No existe el log" in out


def test_tail_log_tolerates_bad_encoding(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_bytes(b"ok\n\xff\xfe rotas\nfin\n")
    out = tail_log(log, lines=10)
    assert "fin" in out


def test_tail_log_zero_or_negative_lines_returns_empty(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_text("a\nb\nc\n", encoding="utf-8")
    assert tail_log(log, lines=0) == ""
    assert tail_log(log, lines=-5) == ""
