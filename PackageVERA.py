import os
import sys
import json
import shutil
import subprocess
import zipfile

# Configurations
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(WORKSPACE_DIR, "Plugin")
UPLUGIN_PATH = os.path.join(PLUGIN_DIR, "VERA.uplugin")
PACKAGED_ROOT = os.path.join(WORKSPACE_DIR, "Packaged")

# Open-source: ship source + one packaged build for the latest UE. Anyone who
# wants another version clones the repo and builds it themselves.
UE_VERSIONS = {
    "5.7": r"C:\Program Files\Epic Games\UE_5.7",
}

def load_uplugin():
    with open(UPLUGIN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_uplugin(data):
    with open(UPLUGIN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def zip_directory(src_dir, zip_path):
    print(f"Compressing {src_dir} into {zip_path}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(src_dir))
                zipf.write(file_path, arcname)

_PY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo",
    # demo / minigame scripts — NOT part of the VERA tool (they hijack PIE)
    "vera_enemy.py", "vera_horror.py", "vera_lava.py", "vera_autopilot.py",
)

# Python deps the brain + UI need, bundled into the plugin (Fab forbids runtime
# pip installs). Targets the editor's Python (3.11) regardless of the host.
_BUNDLED_DEPS = ["anthropic>=0.40.0", "openai>=1.40.0", "mcp>=1.2.0", "PySide6"]


def assemble_plugin(bundle_deps=True):
    """Assemble Plugin/Content/Python from the tracked source — the single source
    of truth — so packaging always ships the CURRENT VERA, and bundle the Python
    deps into Content/Python/Lib/Win64/site-packages (the Fab layout; UE adds that
    folder to sys.path automatically, so no runtime pip install is needed)."""
    src_py = os.path.join(WORKSPACE_DIR, "UE57", "Content", "Python")
    src_plugins = os.path.join(WORKSPACE_DIR, "UE57", "VERA_Plugins")
    vera_pkg = os.path.join(WORKSPACE_DIR, "vera")
    dst_py = os.path.join(PLUGIN_DIR, "Content", "Python")

    print(f"[+] Assembling plugin Content/Python from source...")
    if os.path.exists(dst_py):
        shutil.rmtree(dst_py)
    os.makedirs(dst_py, exist_ok=True)

    # 1) editor scripts + chat UI (init_unreal, vera_ui, vera_bootstrap, vera_chat/, ...)
    shutil.copytree(src_py, dst_py, ignore=_PY_IGNORE, dirs_exist_ok=True)
    # 2) the vera/ Python package (importable: UE puts Content/Python on sys.path)
    shutil.copytree(vera_pkg, os.path.join(dst_py, "vera"), ignore=_PY_IGNORE)
    # 3) the studio plugins (found at <Content/Python>/VERA_Plugins by the factory)
    if os.path.isdir(src_plugins):
        shutil.copytree(src_plugins, os.path.join(dst_py, "VERA_Plugins"), ignore=_PY_IGNORE)

    if bundle_deps:
        site = os.path.join(dst_py, "Lib", "Win64", "site-packages")
        os.makedirs(site, exist_ok=True)
        print(f"[+] Bundling Python deps into {os.path.relpath(site, WORKSPACE_DIR)} ...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", *_BUNDLED_DEPS,
            "--target", site, "--python-version", "3.11",
            "--only-binary=:all:", "--upgrade",
        ])
    else:
        print("[i] Skipping dep bundling (bundle_deps=False) — plugin will rely on "
              "the runtime bootstrap instead. NOT Fab-compliant.")
    print(f"[+] Plugin assembled at {os.path.relpath(dst_py, WORKSPACE_DIR)}")


def build_for_version(version, ue_path):
    run_uat_path = os.path.join(ue_path, "Engine", "Build", "BatchFiles", "RunUAT.bat")
    if not os.path.exists(run_uat_path):
        print(f"[-] RunUAT.bat not found at {run_uat_path}. Skipping version {version}.")
        return False

    print(f"\n==================================================")
    print(f" Packaging VERA for Unreal Engine {version}")
    print(f"==================================================")

    uplugin_data = load_uplugin()
    original_engine_version = uplugin_data.get("EngineVersion", "")
    
    target_engine_version = f"{version}.0"
    uplugin_data["EngineVersion"] = target_engine_version
    save_uplugin(uplugin_data)
    print(f"[+] Updated .uplugin EngineVersion to: {target_engine_version}")

    output_dir = os.path.join(PACKAGED_ROOT, f"UE_{version}", "VERA")
    if os.path.exists(output_dir):
        print(f"[+] Cleaning previous build directory: {output_dir}")
        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)
    
    os.makedirs(os.path.dirname(output_dir), exist_ok=True)

    cmd = [
        run_uat_path,
        "BuildPlugin",
        f"-Plugin={UPLUGIN_PATH}",
        f"-Package={output_dir}",
        "-Rocket"
    ]
    
    print(f"[+] Running command: {' '.join(cmd)}")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            print(line, end="")
            
        process.wait()
        
        if process.returncode != 0:
            print(f"[-] Build failed for UE {version} with exit code {process.returncode}")
            return False
            
        print(f"[+] Build succeeded for UE {version}!")
        
        # Clean up Epic Games forbidden directories
        for folder_to_remove in ["Binaries", "Intermediate", "Saved", "Build"]:
            folder_path = os.path.join(output_dir, folder_to_remove)
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                print(f"[+] Removed {folder_to_remove} to comply with Fab requirements.")
                
        # Zip the packaged plugin folder
        zip_path = os.path.join(PACKAGED_ROOT, f"VERA_UE{version}.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        zip_directory(output_dir, zip_path)
        print(f"[+] Created ready-for-Fab ZIP: {zip_path}")
        return True

    except Exception as e:
        print(f"[-] Exception occurred during build: {str(e)}")
        return False
        
    finally:
        uplugin_data = load_uplugin()
        if original_engine_version:
            uplugin_data["EngineVersion"] = original_engine_version
        else:
            uplugin_data.pop("EngineVersion", None)
        save_uplugin(uplugin_data)
        print(f"[+] Restored .uplugin EngineVersion")

def main():
    print("VERA Unreal Engine Plugin Packager")
    print(f"Workspace: {WORKSPACE_DIR}")
    print(f"Plugin Path: {PLUGIN_DIR}")
    
    os.makedirs(PACKAGED_ROOT, exist_ok=True)

    # Assemble Content/Python from source first, so we always package current code.
    assemble_only = "--assemble-only" in sys.argv
    bundle_deps = "--no-bundle" not in sys.argv
    assemble_plugin(bundle_deps=bundle_deps)
    if assemble_only:
        print("[i] --assemble-only: plugin assembled, stopping before RunUAT.")
        return

    success_versions = []
    failed_versions = []
    
    for version, path in UE_VERSIONS.items():
        if os.path.exists(path):
            success = build_for_version(version, path)
            if success:
                success_versions.append(version)
            else:
                failed_versions.append(version)
        else:
            print(f"[i] Unreal Engine {version} not found at '{path}'. Skipping.")
            
    print("\n==================================================")
    print(" Packaging Summary")
    print("==================================================")
    print(f"Successful builds: {', '.join(success_versions) if success_versions else 'None'}")
    print(f"Failed builds: {', '.join(failed_versions) if failed_versions else 'None'}")
    print(f"ZIPs located in: {PACKAGED_ROOT}")
    print("==================================================")

if __name__ == "__main__":
    main()
