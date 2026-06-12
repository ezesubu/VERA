TEnemos # VERA: Master Plan (Road to Fab v1.0)
![img.png](img.png)eS
Este es el plan de acción autónomo para llevar a VERA de un script de Python a un Plugin nativo y profesional en la tienda de Epic Games (Fab). 

## 🟢 FASE 1: Interfaz Nativa (C++ Slate UI) [COMPLETADO]
*Objetivo: Integrar el chat de VERA directamente en el Editor de Unreal.*
1. [x] Generar andamiaje del módulo C++ (`VERAModule.h/cpp`).
2. [x] Construir layout de Slate: Caja de historial (ScrollBox), Caja de entrada de texto (EditableTextBox), y Botón de envío.
3. [x] Integrar lógica de UI: Al presionar "Send" o "Enter", capturar el texto y limpiar la caja.

## 🟡 FASE 2: Puente de Comunicación (Sockets C++) [COMPLETADO]
*Objetivo: Conectar el Frontend (UI en Unreal) con el Backend (El Crew de VERA en Python).*
1. [x] Implementar cliente TCP/Sockets en C++ (`FSocket`).
2. [x] Enviar comandos del usuario desde la UI de Slate hacia el puerto de VERA.
3. [x] Recibir respuestas de la IA y pintarlas en el historial del chat.

## 🟠 FASE 3: Auto-Arranque Silencioso [COMPLETADO]
*Objetivo: Cero configuración para el usuario final.*
1. [x] Cuando el usuario abre el plugin, C++ debe invocar silenciosamente `python_agent.py` para levantar el backend de VERA en segundo plano.
2. [x] Asegurar que el proceso muera limpiamente al cerrar el Unreal Editor.

## 🔴 FASE 4: Pulido y Empaquetado [COMPLETADO]
*Objetivo: Listos para vender en Fab.*
1. [x] Crear un logo 128x128 para el plugin (`Resources/Icon128.png`).
2. [x] Compilación final con `PackageVERA.py` (C++ empaquetado exitosamente para UE 5.4 - 5.7).
3. [ ] Expandir recetas (Ej: "Generar iluminación exterior automática").

## 🟣 FASE 5: Auditoría y Optimización Autónoma [COMPLETADO]
*Objetivo: Que VERA no solo reciba órdenes, sino que critique proactivamente tu proyecto para que corra a 60FPS.*
1. [x] **Scene Performance Analyzer:** Crear un script autónomo que escanee el nivel en tiempo real para encontrar luces costosas, mallas dinámicas innecesarias y dar consejos de optimización de GPU.
2. [x] **Auto-Linter de Convenciones:** Un robot que escanee todo tu `Content Browser` y renombre automáticamente assets mal nombrados (Ej: cambiar "casa" por "SM_Casa" según las reglas de Epic).
3. [x] **QA Playtester Bots:** Agente autónomo que inicia Play-In-Editor (PIE) para probar el juego y leer los errores rojos.

## 🔵 FASE 6: Fusión Multi-Modal (Voz y Visión Artística) [VISIÓN FUTURA]
*Objetivo: Eliminar el teclado. Que hables con tu motor gráfico.*
1. [ ] **Comandos de Voz (Whisper):** Integrar STT (Speech-to-Text) local para que presiones un botón en Slate y simplemente le dictes órdenes a VERA con tu micrófono ("VERA, haz que sea de noche").
2. [ ] **Crítico de Arte (Gemini Vision):** Permitir que VERA tome capturas del *Viewport* y critique la composición, teoría del color y la iluminación de tu escena, ajustando el Post-Process Volume por ti.

## ⚫ FASE 7: Ingeniería Autónoma (Blueprints & Bug Fixing) [VISIÓN FUTURA]
*Objetivo: Un agente hardcore que programe nodos visuales y arregle tus errores.*
1. [x] **Generador de Blueprints (Graph API):** Usar Python para crear, enlazar y compilar nodos de Blueprint dinámicamente. Pídele a VERA "crea una puerta que se abra al acercarse" y el agente dibujará el Blueprint.
2. [ ] **Auto-Fixer de Errores (The GER Loop):** Un watcher que lee el Output Log de Unreal en tiempo real. Si detecta texto rojo (errores de compilación o excepciones), VERA lo lee, entiende por qué se rompió tu código/Blueprint, y aplica la corrección sin que tú hagas nada.

---

# 🚀 VISIÓN VERA AAA: EL AGENTE TÉCNICO AUTÓNOMO
*Añadido el 10/06/2026. Objetivos a largo plazo para evolucionar VERA de un "chat" a un Lead Engineer.*

1. **Memoria del Proyecto (COMPLETADA)**: Base vectorial local, índice de assets, historial de cambios. (Mini Perforce).
2. **Comprensión Total del Proyecto (COMPLETADA)**: Analizador global de FPS, Tick, World Partition, Lumen (`analyzer_agent.py`).
3. **Generador de Sistemas Completos (COMPLETADA)**: `ArchitectAgent` que genera Blueprints, Data Assets, UI y Save Systems juntos.
4. **Auto-Fixer Real (COMPLETADA)**: GER Loop avanzado para leer CPP, stack trace y recompilar sin intervención.
5. **Arquitecto de Rendimiento (COMPLETADA)**: Ajuste automático de Luces, LODs, HLODs, Nanite y Streaming para llegar a 60 FPS (`performance_architect.py`).
6. **Multiplayer Engineer (COMPLETADA)**: Detector de lógica no replicada, RPC faltantes y validación de Authority (`network_linter.py`).
7. **Integración Git (PENDIENTE)**: Control de versiones autónomo (crear ramas, revertir, explicar diffs).
8. **Director Técnico de Arte (COMPLETADA)**: Gemini Vision criticando composición, contraste y storytelling.
9. **Constructor de Juegos Completo (COMPLETADA)**: El santo grial ("Haz un Extraction Shooter").
10. **Modo Productor / PM (COMPLETADA)**: Análisis del estado del proyecto para detectar features faltantes (`pm_agent.py`).

## Animaciones (roadmap)

- **Fase 1 (implementada 2026-06-12):** tools `inspect_actor_animability` (read-only)
  y `animate_actor` (destructiva: animate/spawn). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase1-design.md`.
- **Fase 2 (pendiente):** percepción de animación — `isolate_and_capture` con entorno
  neutro (patrón S.A.M) para que el art_critic juzgue animaciones.
- **Fase 3 (pendiente, condicional):** Sequencer / Control Rig / retargeting, solo si
  las fases 1-2 se validan en vivo.
