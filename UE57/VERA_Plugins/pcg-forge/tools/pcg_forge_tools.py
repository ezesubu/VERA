from __future__ import annotations
import json
from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

_SCRIPT_TMPL = '''
import unreal, json
from vera import vera_graph_utils

def _build_pcg(graph_path):
    out = {"ok": False, "warnings": []}
    
    graph = unreal.EditorAssetLibrary.load_asset(graph_path)
    if not graph:
        out["error"] = f"Could not load PCG graph at {graph_path}"
        return out
        
    try:
        input_node = graph.get_input_node()
        if input_node:
            input_node.set_node_position(0, 0)

        # Add Landscape Data node
        land_node = None
        land_tuple = graph.add_node_of_type(unreal.PCGGetLandscapeSettings)
        if land_tuple:
            land_node = land_tuple[0] if type(land_tuple) is tuple else land_tuple
            land_node.set_node_position(150, 0)
            
        # Add Surface Sampler
        sampler_node = None
        sampler_tuple = graph.add_node_of_type(unreal.PCGSurfaceSamplerSettings)
        if sampler_tuple:
            sampler_node = sampler_tuple[0] if type(sampler_tuple) is tuple else sampler_tuple
            sampler_node.set_node_position(300, 0)
            
        # Add Spawner
        spawner_node = None
        spawner_tuple = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
        if spawner_tuple:
            spawner_node = spawner_tuple[0] if type(spawner_tuple) is tuple else spawner_tuple
            spawner_node.set_node_position(600, 0)
            settings = spawner_tuple[1] if type(spawner_tuple) is tuple else spawner_tuple.get_settings()
            
            # Inject Grass Mesh 
            try:
                mesh = unreal.EditorAssetLibrary.load_asset('/Game/FullSample/Assets/Environment/Foliage/SM_Grass_Dk_01')
                params = settings.get_editor_property('mesh_selector_parameters')
                entry = unreal.PCGMeshSelectorWeightedEntry()
                entry.set_editor_property('weight', 1)
                desc = unreal.PCGSoftISMComponentDescriptor()
                desc.set_editor_property('static_mesh', mesh)
                entry.set_editor_property('descriptor', desc)
                params.set_editor_property('mesh_entries', [entry])
                out["warnings"].append("Mesh assigned successfully via python workaround!")
            except Exception as e:
                out["warnings"].append(f"Mesh assign error: {str(e)}")
                
        if land_node and sampler_node and spawner_node:
            # Wire properly using the standard library!
            vera_graph_utils.connect_nodes(land_node, "Out", sampler_node, "Surface")
            vera_graph_utils.connect_nodes(sampler_node, "Out", spawner_node, "In")
            out["warnings"].append("Wired nodes perfectly using vera_graph_utils.")
            
        unreal.EditorAssetLibrary.save_asset(graph_path)
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
        
    return out

print(json.dumps(_build_pcg(%(path)s)))
'''

class BuildPCGTool(Tool):
    name = "build_pcg_graph"
    description = "Automatically adds nodes (GetLandscapeData, Surface Sampler, Spawner) to an existing PCG Graph and wires them correctly via Python API."
    input_schema = {
        "type": "object",
        "properties": {
            "graph_path": {"type": "string", "description": "Asset path of the PCG graph"}
        },
        "required": ["graph_path"]
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        graph_path = (args.get("graph_path") or "/Game/PCW/Environment/CleanCityPCG").strip()
        
        script = _SCRIPT_TMPL % {
            "path": json.dumps(graph_path)
        }
        ctx.report("PCGForge", f"Building PCG nodes in {graph_path}")
        
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the editor: {e}", is_error=True)
            
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "PCG creation failed", is_error=True)

        try:
            data = json.loads((resp.get("output") or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return ToolResult(resp.get("output") or "(no output)", is_error=True)
            
        if not data.get("ok"):
            return ToolResult(data.get("error") or "PCG node creation failed due to API limitations", is_error=True)

        return ToolResult(f"Successfully added nodes to {graph_path}! Warnings: {data.get('warnings')}")
