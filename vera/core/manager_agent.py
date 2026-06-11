"""
VERA Manager Agent — The Orchestrator of the VERA Crew.

Responsible for receiving natural language commands, checking the Action Cache 
for zero-token hits, and delegating to sub-agents (PythonAgent, PerceptionAgent).
"""

import logging
from typing import Optional

from vera.core.blackboard import Blackboard
from vera.core.python_agent import UEPythonAgent
from vera.core.perception_agent import PerceptionAgent
from vera.core.blueprint_generator import BlueprintGenerator
from vera.core.qa_agent import QAAgent
from vera.core.decision_agent import DecisionAgent
from vera.core.log_qa_agent import LogQAAgent

logger = logging.getLogger(__name__)

class ManagerAgent:
    def __init__(self, blackboard: Blackboard):
        self.blackboard = blackboard
        self.action_cache = blackboard.action_cache
        
        # Initialize the Crew
        self.python_agent = UEPythonAgent(blackboard)
        self.perception_agent = PerceptionAgent(blackboard)
        self.bp_generator = BlueprintGenerator(self.python_agent)
        self.qa_agent = QAAgent(self.python_agent)
        
        from vera.core.architect_agent import ArchitectAgent
        self.architect_agent = ArchitectAgent(self)
        
        from vera.core.git_agent import GitAgent
        self.git_agent = GitAgent("e:/PCW/VERA")
        
        from vera.llm.llm_factory import LLMFactory
        self.llm = LLMFactory.get_client()
        
        from vera.core.art_critic_agent import ArtCriticAgent
        self.art_critic = ArtCriticAgent(self.llm, self.python_agent)
        
        from vera.tools.cloud_sync import CloudSyncAgent
        self.cloud_sync = CloudSyncAgent("e:/PCW/VERA/vera/recipes")
        
        from vera.core.voice_agent import VoiceAgent
        self.voice_agent = VoiceAgent(self)
        
        # Interactive Decision Maker
        self.decision_agent = DecisionAgent(self.llm)
        
        # Log QA Agent (Standalone calls)
        self.log_qa_agent = LogQAAgent(self.llm)

    def _progress(self, agent: str, msg: str) -> None:
        self.blackboard.report_progress(agent, msg)

    def _route_command(self, command: str) -> str:
        """Uses LLM to classify the user's command into a routing category."""
        system_instruction = (
            "You are the Manager Agent for VERA. Route the user's task to a sub-agent: "
            "1. 'PERCEPTION' -> Requires clicking a UI button or reading the screen. "
            "2. 'PYTHON' -> Standard editor tasks, modifying actors, setting variables. "
            "3. 'BLUEPRINT' -> Explicit request to CREATE a Blueprint class. "
            "4. 'QA' -> Request to test the game or play the level. "
            "5. 'ARCHITECT' -> Massive multi-step project ('Make me a game', 'Build a level'). "
            "6. 'GIT' -> Request to commit code, create a branch, or revert changes. "
            "7. 'CRITIC' -> Request to analyze the scene composition, lighting, or artistic quality. "
            "8. 'LOG_QA' -> Request to check the logs for errors or warnings ('busca errores', 'analiza el log'). "
            "Reply with EXACTLY ONE word: PERCEPTION, PYTHON, BLUEPRINT, QA, ARCHITECT, GIT, CRITIC, or LOG_QA."
        )
        route = self.llm.generate_text(system_instruction, command)
        if not route: return "PYTHON"
        
        route = route.strip().upper()
        for valid in ["PERCEPTION", "PYTHON", "BLUEPRINT", "QA", "ARCHITECT", "GIT", "CRITIC", "LOG_QA"]:
            if valid in route: return valid
        return "PYTHON"

    def execute_command(self, command: str) -> bool:
        """
        Main entry point for VERA.
        1. Check Cache
        2. If Miss, Delegate to Sub-Agents
        3. Save to Cache on success
        """
        logger.info(f"[Manager] Received command: '{command}'")
        self._progress("Manager", "command received")

        # 1. Zero-Token Check (Semantic Cache)
        # Assuming action_cache is now SemanticMemory with .recall()
        cached_solution = self.action_cache.recall(command)
        if cached_solution:
            logger.info(f"[Manager] Cache HIT! Replaying recipe...")
            self._progress("Manager", "cache hit — replaying recipe")
            # For this MVP, if it's a code block, we just execute it via python_agent
            return self.python_agent._execute_code(cached_solution)

        # 2. Cache Miss - We must think and delegate.
        logger.info("[Manager] Cache MISS. Delegating task to Crew...")
        self._progress("Manager", "thinking…")

        # 3. Decision Check (Ambiguity Guard)
        ambiguity_eval = self.decision_agent.evaluate_ambiguity(command)
        if ambiguity_eval.get("is_ambiguous"):
            question = ambiguity_eval.get("clarifying_question")
            logger.info(f"[Manager] Command is ambiguous. Delegating to DecisionAgent to ask user: {question}")
            print(f"\n[VERA] 🤔 {question}")
            self._progress("Manager", f"need clarification: {question}")
            # Halt execution and return False, indicating that the command wasn't executed
            # but rather a question was asked to the user.
            return False
        
        route = self._route_command(command)
        logger.info(f"[Manager] Route selected: {route}")
        self._progress("Manager", f"routed to {route.title()}")

        success = False
        steps_taken = []
        
        if route == "ARCHITECT":
            self._progress("Architect", "planning project")
            success = self.architect_agent.plan_project(command)
            if success:
                steps_taken.append({"action": "architect_plan", "task": command})

        elif route == "BLUEPRINT":
            logger.info("[Manager] LLM Routed to Blueprint Generator.")
            self._progress("Blueprint", "generating blueprint")
            bp_name = command.replace("crea un blueprint de", "").replace("create a blueprint for", "").strip().replace(" ", "_")
            if not bp_name:
                bp_name = "BP_Autogen"
            success, msg = self.bp_generator.create_blueprint_with_components(bp_name)
            if success:
                steps_taken.append({"action": "blueprint", "name": bp_name})

        elif route == "QA":
            logger.info("[Manager] LLM Routed to QA Agent.")
            self._progress("QA", "running tests")
            lower_cmd = command.lower()
            if "jugando" in lower_cmd or "en vivo" in lower_cmd or "gameplay" in lower_cmd:
                success, msg = self.qa_agent.take_gameplay_shot()
                if success:
                    steps_taken.append({"action": "qa_live_gameplay_shot", "screenshot": msg})
            elif "visual" in lower_cmd or "screenshot" in lower_cmd or "captura" in lower_cmd or "ver" in lower_cmd:
                success, msg = self.qa_agent.run_visual_playtest()
                if success:
                    steps_taken.append({"action": "qa_visual_playtest", "screenshot": msg})
            else:
                success, msg = self.qa_agent.run_test_suite()
                if success:
                    steps_taken.append({"action": "qa_test"})
                
        elif route == "GIT":
            logger.info("[Manager] LLM Routed to GitAgent.")
            self._progress("Git", "version control")
            if "revert" in command.lower():
                self.git_agent.revert_last_action()
                steps_taken.append({"action": "git_revert"})
            else:
                self.git_agent.auto_commit_fix(command)
                steps_taken.append({"action": "git_commit"})
                
        elif route == "CRITIC":
            logger.info("[Manager] LLM Routed to ArtCriticAgent.")
            self._progress("Critic", "analyzing scene")
            critique = self.art_critic.critique_scene()
            steps_taken.append({"action": "art_critique", "notes": critique})
            
        elif route == "LOG_QA":
            logger.info("[Manager] LLM Routed to LogQAAgent.")
            self._progress("LogQA", "scanning editor log")
            import os
            # Read all recent warnings/errors
            if os.path.exists(self.log_qa_agent.log_path):
                self.log_qa_agent._last_file_size = 0 # Force read whole file or just recent tail
                # Let's read the whole file but just get the warnings
                issues = self.log_qa_agent.get_new_warnings_and_errors()
                if issues:
                    report = self.log_qa_agent.analyze_issues(issues)
                    logger.info(f"[Manager] Found errors:\n{report}")
                    print(f"\n[VERA Log QA] 🚨 {report}")
                else:
                    logger.info("[Manager] No errors found.")
                    print("\n[VERA Log QA] ✅ No se encontraron errores ni warnings en el log reciente.")
            success = True
            steps_taken.append({"action": "log_qa_check"})
            
        elif route == "PYTHON":
            logger.info("[Manager] LLM Routed to UE Python Agent.")
            self._progress("Python", "writing & executing script")
            success = self.python_agent.run(command)
            if success:
                steps_taken.append({"action": "python_script", "task": command})
            else:
                logger.warning("[Manager] Python execution failed. Initiating Autonomous Fallback to PERCEPTION.")
                route = "PERCEPTION" # Cascading Fallback
                
        # NOT an elif so that PYTHON can fall through to PERCEPTION
        if route == "PERCEPTION":
            logger.info("[Manager] LLM Routed to Perception/UI Agent.")
            self._progress("Perception", "reading the screen")

            # 1. Try Hotkeys first (Fastest, doesn't steal mouse)
            from vera.core.hotkey_agent import HotkeyAgent
            hotkey_agent = HotkeyAgent()
            
            # The LLM should extract the intention, e.g. "open_project_settings"
            # For this MVP, we pass the command directly or rely on LLM keyword matching
            matched_action = None
            for action in hotkey_agent.get_available_actions():
                if action.replace("_", " ") in command.lower():
                    matched_action = action
                    break
                    
            if matched_action:
                success = hotkey_agent.execute_hotkey(matched_action)
                if success:
                    steps_taken.append({"action": "hotkey", "keys": matched_action})
            else:
                # 2. Fallback to physical mouse clicks if no hotkey exists
                logger.info("[Manager] No hotkey found. Falling back to Visual Mouse Control.")
                target = command
                coords = self.perception_agent.find_element(target, target)
                if coords:
                    logger.info(f"[Manager] Executing physical click at X:{coords['x']}, Y:{coords['y']}")
                    try:
                        import pyautogui
                        pyautogui.moveTo(coords["x"], coords["y"], duration=0.5)
                        pyautogui.click()
                        steps_taken.append({"action": "click", "target": target, "coords": coords})
                        success = True
                    except ImportError:
                        logger.error("[Manager] PyAutoGUI not installed. Cannot perform click.")
                        success = False
        else:
            logger.info("[Manager] LLM Routed to UE Python Agent.")
            success = self.python_agent.run(command)
            if success:
                steps_taken.append({"action": "python_script", "task": command})

        # 3. If successful, cache it for next time
        if success and steps_taken:
            self.action_cache.save(command, steps_taken)
            
        return success

    def _replay_recipe(self, steps: list) -> bool:
        """Executes a previously cached list of steps without LLM calls."""
        for step in steps:
            logger.debug(f"[Manager] Replaying step: {step}")
            action = step.get("action")
            if action == "click":
                # PyAutoGUI execution here
                logger.info(f"[Replay] Clicking at {step.get('coords')}")
            elif action == "python_script":
                # Skip generation/evaluation and go straight to execution
                logger.info(f"[Replay] Executing cached python script")
                # self.python_agent._execute_code(step.get("code"))
        return True
