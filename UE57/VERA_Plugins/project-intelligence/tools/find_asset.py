"""find_asset tool: locate .uasset/.umap files by name in the project's Content/.

Pure filesystem walk under VERA_PROJECT_ROOT (default E:/PCW/VERA/UE57). Returns
matches as /Game/...-style paths (Content/ prefix stripped, extension dropped).
"""
import os

from vera.agent.tool import Tool, ToolContext, ToolResult

DEFAULT_PROJECT_ROOT = "E:/PCW/VERA/UE57"
MAX_RESULTS = 40


class FindAssetTool(Tool):
    name = "find_asset"
    description = (
        "Locate an asset by name. Searches the project's Content/ tree for "
        ".uasset/.umap files whose filename contains the given (case-insensitive) "
        "name, and returns matching /Game/...-style content paths. Use this when you "
        "need to confirm an asset exists or find its exact path before referencing it. "
        "Reflects the on-disk project (no editor needed)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Substring to match against asset filenames (case-insensitive).",
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = (args or {}).get("name", "")
        if not isinstance(name, str) or not name.strip():
            return ToolResult(content="find_asset: 'name' is required.", is_error=True)
        needle = name.strip().lower()

        project_root = os.environ.get("VERA_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)
        content_dir = os.path.join(project_root, "Content")
        if not os.path.isdir(content_dir):
            return ToolResult(
                content=f"find_asset: Content directory not found at {content_dir}",
                is_error=True,
            )

        matches = []
        truncated = False
        for root, _dirs, files in os.walk(content_dir):
            for f in files:
                stem, ext = os.path.splitext(f)
                if ext.lower() not in (".uasset", ".umap"):
                    continue
                if needle not in stem.lower():
                    continue
                rel = os.path.relpath(os.path.join(root, stem), content_dir)
                game_path = "/Game/" + rel.replace(os.sep, "/")
                matches.append(game_path)
                if len(matches) >= MAX_RESULTS:
                    truncated = True
                    break
            if truncated:
                break

        if not matches:
            return ToolResult(content=f"No assets found matching '{name}'.")

        header = f"Found {len(matches)} asset(s) matching '{name}'"
        if truncated:
            header += f" (showing first {MAX_RESULTS}; more exist)"
        header += ":"
        body = "\n".join(matches)
        return ToolResult(content=f"{header}\n{body}")
