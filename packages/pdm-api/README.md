# Package - PDM-API

## Description

The `pdm-api` project provides an API for reading from the Product Data Management (PDM) system. It can create BOMs, search for files, retrieve files, and more.

Here is the full interface

```python
class PDMVault:

    @property
    def name(self) -> str:
        """Gets the name of the connected PDM vault."""

    @property
    def root_folder_path(self) -> str:
        """Gets the local path to the root folder of the PDM vault."""

    def create_folders(self, folder_path: str) -> bool:
        """Ensures the folder path exists in PDM, creating parent directories as needed."""

    def delete_empty_folder_structure(self, folder_path: str) -> bool:
        """Deletes a folder and its empty subfolders; fails if any files exist in the structure."""

    def get_files_in_folder(self, folder_path: str) -> Iterator[str]:
        """Yields the full paths of all files directly within the specified PDM folder."""

    def get_subfolders_in_folder(self, folder_path: str) -> Iterator[str]:
        """Yields the local paths of all subfolders directly within the specified PDM folder."""

    def get_children(self, filepath: str) -> Iterator[Dict[str, str]]:
        """Gets the direct children (references) of a PDM file and formats them."""

    def get_parents(self, filepath: str) -> Iterator[Dict[str, str]]:
        """Gets the direct parents (where-used) of a PDM file and formats them."""

    def import_file_to_pdm(self, local_filepath: str, pdm_dest_folder_path: str, new_filename: Optional[str] = None) -> str:
        """Imports a local file into the specified PDM folder, returning the PDM path."""

    def get_local_copy(self, pdm_filepath: str, local_dest_dir: str, new_filename: Optional[str] = None) -> str:
        """Gets a local copy of a PDM file to the specified directory, returning the local path."""

    def search_files(self,
                     filename_pattern: Optional[str] = None,
                     variable_conditions: Optional[Dict[str, str]] = None,
                     state_id_filter: Optional[int] = None,
                     directory: Optional[str] = None,
                     recursive: bool = DEFAULT_SEARCH_RECURSIVE) -> Iterator[Dict[str, str]]:
        """Searches for files in PDM based on various criteria and yields formatted results."""

    def delete_file(self, filepath: str, force_unlock: bool = False) -> bool:
        """Deletes a file from the PDM vault, optionally forcing an unlock if checked out."""

    def get_file_info(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves detailed information about a specific file in the PDM vault."""

    def get_reference_info(self, filepath: str) -> Optional[Dict[str, str]]:
        """Retrieves basic reference information for a specific file in the PDM vault."""

    def checkout_file(self, filepath: str) -> bool:
        """Checks out a file from the PDM vault."""

    def checkin_file(self, filepath: str, comment: str = "API Check-in") -> bool:
        """Checks in a file to the PDM vault with an optional comment."""

    def set_variable(self, filepath: str, var_name: str, var_value: Any, configuration: str = DEFAULT_CONFIG) -> None:
        """Sets the value of a data card variable for a specified file and configuration."""

    def get_derived_bom_data(self, filepath: str) -> Iterator[Dict[str, str]]:
        """Retrieves and yields data from the last derived Bill of Materials (BOM) for a file."""

    def get_computed_bom_data(self, filepath: str, bom_layout_name: str, config: str = DEFAULT_CONFIG) -> Iterator[Dict[str, str]]:
        """Retrieves and yields data from a computed Bill of Materials (BOM) for a file using a specific layout and configuration."""

class CMXVault(PDMVault):
    
    def __init__(self,username,password,vault_name):
        """Initializes a CMXVault instance, extending PDMVault with CMX-specific configurations."""
        
    def set_exclude_flags(self, **kwargs):
        """Sets boolean flags to control which components are excluded from the BOM."""
        
    def reset_bom_cache(self):
        """Clears the internal cache used for storing computed BOM data."""
    
    def generate_bom(self, part_number:str) -> list[dict]:
        """Generates a Bill of Materials (BOM) for the specified part number."""
```

please import errors as

```python
from pdm_api.exceptions import PDMError, PDMConnectionError, PDMFileNotFoundError, PDMFileInfoError, PDMOperationFailedError, PDMCastError
```

## Dependencies

Only relies on `EPDM.Interop.epdm.dll` and `EPDM.Interop.EPDMResultCode.dll`.

## HTTP fallback when PDM is not installed

If the EPDM/PDM interop cannot be loaded, the library can fall back to an existing PDM API server.
Set the environment variable below on the client machine:

- `PDM_API_URL` (example: `http://10.1.32.30:8000`)

When set, `PDMVault` and `CMXVault` will call the server for supported operations instead of local EPDM.

## REST Server

This package includes a small FastAPI server in `pdm_api/server.py`.

### Required env vars

- `PDM_DLL_PATH` should point to the PDM interop DLL on the server, for example:
  - `C:\Program Files (x86)\SOLIDWORKS PDM\EPDM.Interop.epdm.dll`
- `PDM_API_KEY` to require a shared API key on all requests (sent as `X-API-Key`)

Optional:
- `PDM_DLL_DIR` if you prefer providing just the directory (the DLL name is appended automatically)
- `PDM_API_HOST` (default `0.0.0.0`)
- `PDM_API_PORT` (default `8000`)

### Run locally

```powershell
python -m pip install fastapi uvicorn pythonnet pywin32
$env:PDM_DLL_PATH="C:\Program Files (x86)\SOLIDWORKS PDM\EPDM.Interop.epdm.dll"
uvicorn pdm_api.server:app --host 0.0.0.0 --port 8000
```

### Build a portable EXE (PyInstaller)

Use **32-bit Python** on the build machine to match the PDM client.

```powershell
.\build_pyinstaller.ps1
```

The build output will be in `dist\pdm-api-server`. Copy that folder to the server and run:

```powershell
$env:PDM_DLL_PATH="C:\Program Files (x86)\SOLIDWORKS PDM\EPDM.Interop.epdm.dll"
.\pdm-api-server\pdm-api-server.exe
```

### Run as a Windows Service (NSSM)

Download NSSM and place `nssm.exe` somewhere on the server, for example `C:\Tools\nssm.exe`.

Then install the service:

```powershell
.\install_service.ps1 -NssmPath "C:\Tools\nssm.exe" -AppFolder "C:\pdm-api-server" `
  -ServiceName "PdmApiServer" -PdmDllPath "C:\Program Files (x86)\SOLIDWORKS PDM\EPDM.Interop.epdm.dll" `
  -BindHost "0.0.0.0" -Port 8000
```

Uninstall:

```powershell
.\uninstall_service.ps1 -NssmPath "C:\Tools\nssm.exe" -ServiceName "PdmApiServer"
```

### Example requests

```powershell
# Health
Invoke-RestMethod http://localhost:8000/health

# Search
Invoke-RestMethod -Method Post http://localhost:8000/pdm/search -Body (@{
  username="pdm_user"; password="pdm_pass"; vault_name="YourVault";
  filename_pattern="*CA120725*"; directory="C:\YourVault\CAD"; recursive=$true
} | ConvertTo-Json) -ContentType "application/json"
```

## Backlog

### Vault Functionality

- [DONE] File search
- [DONE] Get reference from file  
- [DONE] Get children from a reference
- [DONE] Get parent from a reference
- [DONE] Filter references  
- [DOING] Generate BOM as list of dicts 
- [DONE] Retrieve file

## Notes
