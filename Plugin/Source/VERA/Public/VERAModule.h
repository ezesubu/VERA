// Copyright 2026 maVERAick. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class FSlateStyleSet;

/**
 * VERA editor module.
 *
 * VERA's UI and logic live in Python (Content/Python, bootstrapped by
 * init_unreal.py through the PythonScriptPlugin). This C++ module's only job is to
 * register a Slate style set holding VERA's logo, so the toolbar button injected
 * from Python can show the brand icon ("VERAStyle", "VERA.Logo") instead of a
 * generic engine glyph. It also makes VERA a compiled code plugin for Fab/Epic.
 */
class FVERAModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

private:
	TSharedPtr<FSlateStyleSet> StyleSet;
};
