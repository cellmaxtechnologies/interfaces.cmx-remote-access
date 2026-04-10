import os
import sys
from typing import Dict, List, Any


LATEST_VERSION = 0
PDM_DLL_NAME = "EPDM.Interop.epdm.dll"
DEFAULT_CONFIG = "Default"
DEFAULT_PROJECT = ""
GET_SUPPRESSED_COMPONENTS = False
DEFAULT_SEARCH_RECURSIVE = True
DEFAULT_BOM_DEPTH = 100
DEFAULT_PARENT_HWND = 0 # Already defined as DEFAULT_PARENT_HWND_VAL in standalone
EDM_COPY_SIMPLE = 0
EDM_DELETE_SIMPLE = 0
        
def resource_path(resource_filename: str) -> str:
    """
    Get the absolute path to a resource file.

    This function is useful for accessing resource files in a way that also works
    when the code is packaged into a standalone executable using tools like PyInstaller.

    Parameters:
        resource_filename: The filename of the resource to locate.

    Returns:
        The absolute path to the resource file.

    Example:
        >>> resource_path("my_image.png")
        '/path/to/executable_or_script/resources/my_image.png'
    """

    env_path = os.environ.get("PDM_DLL_PATH", "").strip()
    if env_path:
        return env_path

    env_dir = os.environ.get("PDM_DLL_DIR", "").strip()
    if env_dir:
        return os.path.join(env_dir, resource_filename)

    if hasattr(sys, "_MEIPASS"):
        # PyInstaller onefile/onedir uses _MEIPASS for bundled resources.
        src_dir = sys._MEIPASS
    else:
        src_dir = os.path.abspath(os.path.dirname(__file__))

    # Support both onedir layouts:
    # - dist/app/resources
    # - dist/app/_internal/resources
    candidate_paths = [
        os.path.join(src_dir, "resources", resource_filename),
        os.path.join(src_dir, "_internal", "resources", resource_filename),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            return path

    return candidate_paths[0]

def log(*texts,ext="",**args):
    with open(f"log{ext}.txt",'a',encoding="utf-8") as file:
        all_text = "\t".join([f"{t}" for t in texts])+"\n"
        all_values = "\n".join([f"{k}: {v}" for k,v in args.items()])+"\n"*(bool(args))
        file.write(all_text+all_values)

def format_search_result(pdm_search_result: Any) -> Dict[str, Any]:
    result_data = {}

    get_data = lambda name : str(getattr(pdm_search_result, name, "N/A"))
    result_data["name"] = get_data('Name')
    result_data["path"] = get_data('Path')
    result_data["date"] = get_data('FileDate')
    result_data["state"] = get_data('StateName')
    
    return result_data

def format_reference_data(pdm_reference) -> Dict[str, str]:
    try:
        return {
            "Name": str(getattr(pdm_reference, 'Name', '')),
            "FoundPath": str(getattr(pdm_reference, 'FoundPath', '')),
            "VersionRef": str(getattr(pdm_reference, 'VersionRef', '')),
            "FileID": str(getattr(pdm_reference, 'FileID', '0'))
        }
    except Exception as e:
        return {"Name": "Error", "FoundPath": "Error", "VersionRef": "Error", "FileID": "Error"}
