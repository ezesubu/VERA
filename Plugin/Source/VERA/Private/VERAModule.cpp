#include "VERAModule.h"

#define LOCTEXT_NAMESPACE "FVERAModule"

void FVERAModule::StartupModule()
{
	// No-op: VERA runs entirely from Content/Python (see init_unreal.py), which
	// the PythonScriptPlugin executes on editor startup. This module exists only
	// so VERA qualifies as a compiled code plugin for Epic Games / Fab.
}

void FVERAModule::ShutdownModule()
{
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FVERAModule, VERA)
