#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

/**
 * VERA editor module.
 *
 * VERA's UI and logic live in Python (Content/Python, bootstrapped by
 * init_unreal.py through the PythonScriptPlugin). This C++ module exists so VERA
 * ships as a compiled code plugin installable from the Epic Games Launcher; it
 * intentionally does no work of its own.
 */
class FVERAModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
