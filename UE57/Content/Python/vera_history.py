"""Historial del chat de VERA — JSONL append-only, mismo schema que el protocolo.
Stdlib only (corre en el Python embebido de Unreal)."""
import json
import os


def append_event(path, event):
    """Appendea un evento como línea JSON. Crea el directorio si falta."""
    path = os.fspath(path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_recent(path, n=200):
    """Últimos n eventos. Líneas corruptas se saltan (el historial nunca
    impide abrir la ventana)."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events[-n:]
