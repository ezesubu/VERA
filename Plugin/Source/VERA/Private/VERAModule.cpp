// Copyright 2026 maVERAick. All Rights Reserved.

#include "VERAModule.h"

#include "Brushes/SlateImageBrush.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Styling/SlateStyle.h"
#include "Styling/SlateStyleRegistry.h"

#define LOCTEXT_NAMESPACE "FVERAModule"

void FVERAModule::StartupModule()
{
	// Register a Slate style set holding VERA's logo (Resources/Icon128.png) so the
	// toolbar button added from Python (init_unreal.py -> vera_ui.py) can reference
	// it as set_icon("VERAStyle", "VERA.Logo"). UE only lets toolbar entries use a
	// brush from a registered style set, which Python can't create — hence this C++.
	StyleSet = MakeShared<FSlateStyleSet>("VERAStyle");

	const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("VERA"));
	const FString ResourcesDir = Plugin.IsValid()
		? Plugin->GetBaseDir() / TEXT("Resources")
		: FPaths::ProjectPluginsDir() / TEXT("VERA/Resources");
	StyleSet->SetContentRoot(ResourcesDir);

	const FVector2D IconSize(32.0f, 32.0f);
	StyleSet->Set("VERA.Logo", new FSlateImageBrush(
		StyleSet->RootToContentDir(TEXT("Icon128"), TEXT(".png")), IconSize));

	FSlateStyleRegistry::RegisterSlateStyle(*StyleSet);
}

void FVERAModule::ShutdownModule()
{
	if (StyleSet.IsValid())
	{
		FSlateStyleRegistry::UnRegisterSlateStyle(*StyleSet);
		StyleSet.Reset();
	}
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FVERAModule, VERA)
