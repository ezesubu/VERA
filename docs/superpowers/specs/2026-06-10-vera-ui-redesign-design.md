# VERA UI Redesign — Diseño

**Fecha:** 2026-06-10
**Estado:** Aprobado por el usuario (brainstorming 2026-06-10, segunda iteración)
**Principio de diseño (del usuario):** "de lo simple y obvio a lo bello con amor" — construir primero lo que funciona evidente, pulir después con cuidado.

## Objetivo

Rediseñar la ventana de chat de VERA dentro del editor de Unreal: progreso de agentes en vivo, markdown con código, historial persistente e imágenes del viewport en el chat. Render completo en HTML (QWebEngine) — verificado por spike en el editor del usuario (UE 5.7.4, PySide6 6.11.1, render perfecto).

## Decisiones tomadas (con el usuario)

- **Render:** ventana completa en un `QWebEngineView` (header, chat, input — todo HTML). Python conserva solo el marco de ventana, el botón 🤖 de la toolbar y el parenting a Slate. El avance existente no se tira: misma ventana, mismo botón, interior nuevo.
- **Layout:** "C" — chips de estado de la crew en el header. **Copy profesional**: sin lemas ("Mission Control" etc. descartados). Header `VERA` + `● Online · UE 5.7` (estado real), chips solo nombre+estado, placeholder `"Type an instruction…"`, saludo `"Hi, I'm VERA. What are we building today?"`.
- **Progreso:** estilo "timeline" dentro de la burbuja de respuesta — una línea por acción de agente, expandible, queda como registro.
- **Protocolo:** streaming sobre el socket existente (9880). Múltiples líneas JSON + final.
- **Voz:** el botón 🎤 va junto a enviar (idle/grabando con pulso/transcripción en vivo en el input; revisar antes de enviar por defecto, toggle manos-libres). **Solo UI en esta iteración** — conectar Whisper/voice_agent es iteración aparte.

## Arquitectura

```
vera_ui.py (shell Python)                    vera_chat/ (HTML/JS/CSS)
┌────────────────────────┐  QWebChannel  ┌─────────────────────────┐
│ ventana + toolbar btn  │◀────────────▶│ header: VERA + chips    │
│ QWebEngineView         │   eventos     │ chat: burbujas+timeline │
│ hilo lector del stream │               │ input + mic + enviar    │
└───────────┬────────────┘               └─────────────────────────┘
            │ TCP 9880 (JSON por líneas, streaming)
┌───────────▼────────────┐
│ vera_server.py         │── blackboard.report_progress(agent,msg)
│ ManagerAgent + crew    │   (los agentes emiten en puntos clave)
└────────────────────────┘
```

### Componente 1: Protocolo streaming (`vera_server.py` + `blackboard.py`)

El server responde N líneas JSON terminadas por la final:

```json
{"type":"progress","agent":"Manager","msg":"routed to Architect"}
{"type":"progress","agent":"Python","msg":"executing step 2 of 3"}
{"type":"image","path":"E:/.../vera_abc.png"}
{"type":"final","status":"success","msg":"Done. Glass bridge…"}
```

- `Blackboard.report_progress(agent, msg)` → callback inyectable; el server lo conecta al socket del cliente activo. Sin cliente conectado: no-op (los agentes no se enteran).
- Eventos `error` para fallos (`{"type":"error","msg":"..."}`).
- El Manager emite en el ruteo; cada sub-agente en sus 1-3 puntos clave. Una línea de código por punto.
- Compatibilidad: `vera_command` del MCP server (terminal) lee el stream y devuelve solo la final (o el stream completo más adelante).

### Componente 2: UI HTML (`UE57/Content/Python/vera_chat/`)

- `index.html` + `chat.js` + `chat.css` — burbujas, timeline expandible, chips del header, thumbnails clickeables (clic abre el PNG con el visor del sistema vía Python).
- Markdown: `marked.js`; sintaxis: `highlight.js` — **vendorizados** en `vera_chat/vendor/` (sin CDN; el editor puede estar offline).
- Tema GitHub-dark del mockup final (`ui-final.html` de la sesión de brainstorming, persistido en `.superpowers/brainstorm/`).
- Python↔JS por `QWebChannel`: Python llama `addUserMessage`, `agentProgress`, `addImage`, `finalMessage`, `setStatus`; JS llama `sendCommand(text)`, `openImage(path)`.

### Componente 3: Shell Python (`vera_ui.py` modificado)

- Reemplaza el QScrollArea de burbujas por el QWebEngineView + QWebChannel.
- Hilo lector del stream: parsea líneas JSON y las encola; el tick de Qt existente las drena hacia JS (mismo patrón thread-safe actual).
- Historial: appendea cada evento a `UE57/Saved/VERA/chat_history.jsonl` (mismo schema que el protocolo — un solo formato); al abrir carga los últimos 50 mensajes.
- Fallback: si `QtWebEngineWidgets` no importa, usa la UI actual de burbujas (se conserva como `vera_ui_basic`/ruta legacy). Nunca una ventana muerta.

### Componente 4: Arranque (`init_unreal.py` modificado)

- Setea `Qt.AA_ShareOpenGLContexts` **antes** de cualquier QApplication (hoy el spike funcionó sin el flag; lo hacemos determinístico).

## Manejo de errores

- Backend caído → header `● Offline` + burbuja con acción (`python -m vera.core.vera_server`).
- Stream interrumpido a mitad de tarea → timeout del lector; la timeline marca el último agente como "interrumpido".
- Evento `error` → burbuja de error (rojo sobrio del tema).
- WebEngine ausente → fallback a UI básica + warning en el Output Log.

## Testing

- **Unit (sin Unreal):** streaming del server con cliente falso (patrón de los tests del bridge); `report_progress` con/sin cliente; round-trip del historial JSONL.
- **Visual (sin Unreal):** `vera_chat/dev.html` inyecta eventos falsos para desarrollar el look en un navegador normal.
- **Smoke en editor (con el usuario, que va testeando en vivo):** abrir ventana, comando real con timeline, verificar historial tras cerrar/reabrir, fallback forzado.

## Fuera de alcance

- Conectar Whisper/voice_agent al botón 🎤 (solo el botón y sus estados visuales).
- Agentes en paralelo (el backend es secuencial; los chips lo reflejan).
- Cambiar el LLM default del backend.
- Temas alternativos (neón) — el tema es uno, GitHub-dark.
