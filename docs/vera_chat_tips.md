# VERA Tips for the User Chat 💡

This is a collection of dynamic tips that we can inject randomly into VERA's chat interface while the user waits for an agent to think, or as welcome messages when opening the tool.

## Vision and Playtesting Tips
- **Autonomous Playtesting:** "Tip: Not sure if a level looks good? Tell VERA *'Test the level and tell me how it looks'*. VERA will start a simulation, take a screenshot, and evaluate it."
- **Live Captures:** "Tip: If you get stuck testing your game, pause and type *'VERA, take a screenshot of my gameplay'*. The agent will see exactly what you're seeing to help you fix the difficulty."
- **Art Critique:** "Tip: Does your lighting look flat? Ask VERA *'Critique the scene's lighting'* and its Art Critic Agent will suggest color and post-processing adjustments."

## Architecture and Configuration Tips
- **Swappable Models:** "Tip: VERA isn't tied to a single brain. You can go to your `.env` file and change `VERA_LLM_PROVIDER` to `OPENAI` or `ANTHROPIC` to use GPT or Claude if you prefer."
- **Architect Mode:** "Tip: For huge projects, use the magic command *'Create the architecture plan for...'*. VERA won't write code recklessly; instead it will lay out a master plan before building."

## Blueprint and Code Tips
- **Fast Generation:** "Tip: Instead of creating Blueprints by hand, tell VERA *'Create a blueprint for a treasure chest'*. VERA will connect the components and 3D meshes for you."
- **Semantic Memory:** "Tip: VERA remembers what it has already taught you. If you ask for something it has done before, it will use its semantic memory to execute it instantly without consuming AI tokens."
- **Quick Recovery (Undo):** "Tip: If VERA makes a serious mistake or deletes something by accident, tell it *'Revert last change'* and its Git Agent will return your project to the exact previous state."

---
*Note for the developer: These tips can be loaded into a JSON in the VERA UI frontend and iterated randomly with the `Math.random()` function.*
