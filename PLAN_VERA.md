# VERA: Master Plan (Road to Fab v1.0)
![img.png](img.png)
This is the autonomous action plan to take VERA from a Python script to a native, professional plugin on the Epic Games store (Fab).

## 🟢 PHASE 1: Native Interface (C++ Slate UI) [COMPLETED]
*Goal: Integrate the VERA chat directly into the Unreal Editor.*
1. [x] Generate the C++ module scaffolding (`VERAModule.h/cpp`).
2. [x] Build the Slate layout: history box (ScrollBox), text input box (EditableTextBox), and send button.
3. [x] Integrate UI logic: when pressing "Send" or "Enter", capture the text and clear the box.

## 🟡 PHASE 2: Communication Bridge (C++ Sockets) [COMPLETED]
*Goal: Connect the frontend (Unreal UI) with the backend (VERA's Crew in Python).*
1. [x] Implement a TCP/Sockets client in C++ (`FSocket`).
2. [x] Send user commands from the Slate UI to VERA's port.
3. [x] Receive the AI's responses and render them in the chat history.

## 🟠 PHASE 3: Silent Auto-Start [COMPLETED]
*Goal: Zero configuration for the end user.*
1. [x] When the user opens the plugin, C++ must silently invoke `python_agent.py` to spin up the VERA backend in the background.
2. [x] Ensure the process dies cleanly when the Unreal Editor closes.

## 🔴 PHASE 4: Polish and Packaging [COMPLETED]
*Goal: Ready to sell on Fab.*
1. [x] Create a 128x128 logo for the plugin (`Resources/Icon128.png`).
2. [x] Final build with `PackageVERA.py` (C++ packaged successfully for UE 5.4 - 5.7).
3. [ ] Expand recipes (e.g. "Generate automatic exterior lighting").

## 🟣 PHASE 5: Autonomous Audit and Optimization [COMPLETED]
*Goal: VERA shouldn't just take orders, but proactively critique your project so it runs at 60 FPS.*
1. [x] **Scene Performance Analyzer:** Create an autonomous script that scans the level in real time to find expensive lights, unnecessary dynamic meshes, and give GPU optimization advice.
2. [x] **Convention Auto-Linter:** A robot that scans your entire `Content Browser` and automatically renames poorly named assets (e.g. changing "casa" to "SM_Casa" according to Epic's rules).
3. [x] **QA Playtester Bots:** An autonomous agent that starts Play-In-Editor (PIE) to test the game and read the red errors.

## 🔵 PHASE 6: Multi-Modal Fusion (Voice and Artistic Vision) [FUTURE VISION]
*Goal: Eliminate the keyboard. Talk to your graphics engine.*
1. [ ] **Voice Commands (Whisper):** Integrate local STT (Speech-to-Text) so you press a button in Slate and simply dictate orders to VERA with your microphone ("VERA, make it night time").
2. [ ] **Art Critic (Gemini Vision):** Allow VERA to take captures of the *Viewport* and critique the composition, color theory, and lighting of your scene, adjusting the Post-Process Volume for you.

## ⚫ PHASE 7: Autonomous Engineering (Blueprints & Bug Fixing) [FUTURE VISION]
*Goal: A hardcore agent that programs visual nodes and fixes your errors.*
1. [x] **Blueprint Generator (Graph API):** Use Python to dynamically create, link, and compile Blueprint nodes. Ask VERA to "create a door that opens when approached" and the agent will draw the Blueprint.
2. [ ] **Error Auto-Fixer (The GER Loop):** A watcher that reads Unreal's Output Log in real time. If it detects red text (compilation errors or exceptions), VERA reads it, understands why your code/Blueprint broke, and applies the fix without you doing anything.

---

# 🚀 VERA AAA VISION: THE AUTONOMOUS TECHNICAL AGENT
*Added 2026-06-10. Long-term goals to evolve VERA from a "chat" into a Lead Engineer.*

1. **Project Memory (COMPLETED)**: Local vector database, asset index, change history. (Mini Perforce).
2. **Full Project Understanding (COMPLETED)**: Global analyzer for FPS, Tick, World Partition, Lumen (`analyzer_agent.py`).
3. **Complete System Generator (COMPLETED)**: `ArchitectAgent` that generates Blueprints, Data Assets, UI, and Save Systems together.
4. **Real Auto-Fixer (COMPLETED)**: Advanced GER Loop to read CPP, stack traces, and recompile without intervention.
5. **Performance Architect (COMPLETED)**: Automatic tuning of Lights, LODs, HLODs, Nanite, and Streaming to reach 60 FPS (`performance_architect.py`).
6. **Multiplayer Engineer (COMPLETED)**: Detector of non-replicated logic, missing RPCs, and Authority validation (`network_linter.py`).
7. **Git Integration (PENDING)**: Autonomous version control (create branches, revert, explain diffs).
8. **Technical Art Director (COMPLETED)**: Gemini Vision critiquing composition, contrast, and storytelling.
9. **Complete Game Builder (COMPLETED)**: The holy grail ("Make an Extraction Shooter").
10. **Producer / PM Mode (COMPLETED)**: Project status analysis to detect missing features (`pm_agent.py`).

## Animations (roadmap)

- **Phase 1 (implemented 2026-06-12):** tools `inspect_actor_animability` (read-only)
  and `animate_actor` (destructive: animate/spawn). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase1-design.md`.
- **Phase 2 (implemented 2026-06-12):** visual perception — tool `capture_actor`
  (isolation + unlit + deterministic scrub/orbit, guaranteed restore). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase2-capture-design.md`.
- **Phase 3 (implemented 2026-06-12):** retargeting — tools `ensure_ik_rig`,
  `ensure_retargeter`, `retarget_animations` (find-first, auto-creation). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase3-retarget-design.md`.
  Future pending: Sequencer, Control Rig.

## 🌟 Nice to Have Plugins (Graph Modules)
- **`material-forge`**: A specialized plugin that leverages the new `vera_graph_utils` to autonomously generate, wire, and compile Master Materials and Instances. Useful for art days.
- **`metasound-forge`**: A specialized plugin to allow VERA to wire MetaSound nodes, creating procedural synthesizers, audio cues, and dynamic music directly within the engine. Useful for audio days.
