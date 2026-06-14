import os
import sys
import json
import shutil Se
import subprocess
import zipfile

# Configurations
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(WORKSPACE_DIR, "Plugin")
UPLUGIN_PATH = os.path.join(PLUGIN_DIR, "VERA.uplugin")
PACKAGED_ROOT = os.path.join(WORKSPACE_DIR, "Packaged")

UE_VERSIONS = {    
    "5.4": r"C:\Program Files\Epic Games\UE_5.4",    
    "5.5": r"C:\Program Files\Epic Games\UE_5.5",    
    "5.6": r"C:\Program Files\Epic Games\UE_5.6",
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
