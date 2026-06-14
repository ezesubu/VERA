// Copyright 2026 maVERAick. All Rights Reserved.

using UnrealBuildTool;

public class VERA : ModuleRules
{
	public VERA(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		// VERA's logic is in Python; this module only registers the Slate style set
		// that gives the editor toolbar button its VERA logo icon.
		PublicDependencyModuleNames.AddRange(new string[] { "Core" });
		PrivateDependencyModuleNames.AddRange(new string[] {
			"CoreUObject", "Engine", "Slate", "SlateCore", "Projects" });
	}
}
