import sys
import os
import time
from typing import Dict, List, Any, Set, Tuple, Optional, Iterator, Iterable
import builtins # For the @profile stub
from pdm_api.exceptions import (
    PDMError, PDMConnectionError, PDMCastError, 
    PDMOperationFailedError, PDMFileNotFoundError, PDMFileInfoError, PDMFileExistsError,
)
from pdm_api import utils
from pdm_api.http_client import HttpPdmClient
import traceback
import os
import tempfile
import shutil

from pdm_api.custom_profiler import profile



_PDM_AVAILABLE = True
_PDM_IMPORT_ERROR = None
_FORCE_HTTP = os.environ.get("PDM_FORCE_HTTP", "").strip().lower() in ("1", "true", "yes", "on")

try:
    if _FORCE_HTTP:
        raise ImportError("PDM_FORCE_HTTP enabled; skipping COM imports.")
    import clr

    pdm_dll_path = utils.resource_path(utils.PDM_DLL_NAME)
    clr.AddReference(pdm_dll_path)

    from EPDM.Interop.epdm import (
        EdmVault5, EdmObjectType, EdmBomFlag, EdmRefFlags, EdmBomColumnType,
        IEdmVault21, IEdmFile17, IEdmFolder5, IEdmReference11, IEdmSearch5,
        IEdmSearch9,
        IEdmBom, IEdmBomView3, IEdmState5, IEdmUser5, EdmObjectType,
        IEdmEnumeratorVariable5, IEdmPos5, IEdmBomCell, IEdmEnumeratorVersion5, IEdmRevision5, IEdmHistory,
        EdmHistoryItem,
        EdmUtility
    )
except Exception as e:
    _PDM_AVAILABLE = False
    _PDM_IMPORT_ERROR = e

    class _DummyEnum:
        def __getattr__(self, name):
            return 0

    EdmVault5 = object
    EdmObjectType = _DummyEnum()
    EdmBomFlag = _DummyEnum()
    EdmRefFlags = _DummyEnum()
    EdmBomColumnType = _DummyEnum()
    IEdmVault21 = object
    IEdmFile17 = object
    IEdmFolder5 = object
    IEdmReference11 = object
    IEdmSearch5 = object
    IEdmSearch9 = object
    IEdmBom = object
    IEdmBomView3 = object
    IEdmState5 = object
    IEdmUser5 = object
    IEdmEnumeratorVariable5 = object
    IEdmPos5 = object
    IEdmBomCell = object
    IEdmEnumeratorVersion5 = object
    IEdmRevision5 = object
    IEdmHistory = object
    EdmHistoryItem = object
    EdmUtility = object


class PDMVault:
    _vault_raw: EdmVault5
    _vault_api: Any
    _username: str
    _password: str
    _vault_name: str

    @profile
    def __init__(self, username: str, password: str, vault_name: str, use_http: Optional[bool] = None):
        self._username = username
        self._password = password
        if not vault_name:
            env_root = os.environ.get("PDM_VAULT_ROOT", "").strip()
            if env_root:
                self._vault_name = os.path.basename(env_root.rstrip("\\/"))
            else:
                self._vault_name = vault_name
        else:
            self._vault_name = vault_name
        self._use_http = False
        self._http = None
        self._http_root_cache = None
        self._file_object_cache = {}
        self._parents_cache = {}
        login_vault = None # Initialize to prevent UnboundLocalError in finally

        force_http_raw = os.environ.get("PDM_FORCE_HTTP", "").strip().lower()
        force_http = force_http_raw in ("1", "true", "yes", "on")
        if use_http is True or force_http:
            self._use_http = True
            self._http = HttpPdmClient.from_env(username, password, vault_name)
            utils.log("PDM initialized via HTTP.")
            return
        if use_http is False:
            # Explicit local mode requested; do not fall back to HTTP on import failure.
            if not _PDM_AVAILABLE:
                raise PDMConnectionError(
                    f"PDM local API unavailable and HTTP mode disabled. Error: {_PDM_IMPORT_ERROR}"
                )

        if not _PDM_AVAILABLE:
            self._use_http = True
            self._http = HttpPdmClient.from_env(username, password, vault_name)
            utils.log("PDM local API unavailable; using HTTP fallback.", error=str(_PDM_IMPORT_ERROR))
            return

        try:
            login_vault = EdmVault5()
            login_vault.Login(username, password, vault_name)
            if not login_vault.IsLoggedIn:
                raise PDMConnectionError(f"Login failed for vault '{vault_name}'. Check credentials/vault name/server access.")

            self._vault_raw = login_vault
            # Attempt to get a more recent interface if available
            try:
                vault21 = IEdmVault21(self._vault_raw) # Cast to IEdmVault21
                if vault21 is not None: # Check if cast was successful
                    self._vault_api = vault21
                else: # Cast returned None
                    self._vault_api = self._vault_raw
            except Exception as cast_e: # Catch potential errors during casting
                self._vault_api = self._vault_raw
                
        except (PDMConnectionError, PDMCastError) as e_pdm: # Catch specific PDM errors first
            raise e_pdm
        except AttributeError as ae: # Often indicates a problem with the COM object or interface
            raise PDMConnectionError(f"Failed PDM operation after login (API mismatch or DLL issue?). Error: {ae}") from ae
        except Exception as e_com: # Catch general COM exceptions (pythonnet often wraps them)
            error_msg = str(e_com)
            if hasattr(e_com, 'HResult'): # Check if it's a COMException with HResult
                hresult_str = hex(e_com.HResult & 0xFFFFFFFF) # Get unsigned HResult
                if hresult_str == "0x80040154": # REGDB_E_CLASSNOTREG
                    raise PDMConnectionError(f"PDM client not registered (COM Error {hresult_str}). Ensure PDM client is installed correctly. Details: {error_msg}") from e_com
                elif hresult_str == "0x80070005": # E_ACCESSDENIED
                    raise PDMConnectionError(f"PDM access denied (COM Error {hresult_str}). Check user permissions. Details: {error_msg}") from e_com
                else:
                    raise PDMConnectionError(f"PDM API error during login (HRESULT: {hresult_str}): {error_msg}") from e_com
            # Fallback for other generic exceptions during init
            raise PDMError(f"Unexpected error during vault initialization: {error_msg}") from e_com


    @property
    @profile
    def name(self) -> str:
        if self._use_http:
            return str(self._vault_name)
        try:
            return str(self._vault_api.Name)
        except Exception as e:
            return ""

    @property
    @profile
    def root_folder_path(self) -> str:
        """Gets the local file system path to the root folder of the vault."""
        if self._use_http:
            if self._http and not self._http_root_cache:
                try:
                    root = self._http.get_vault_root()
                    if root:
                        self._http_root_cache = root
                except Exception:
                    pass
            if self._http_root_cache:
                return str(self._http_root_cache)
            env_root = os.environ.get("PDM_VAULT_ROOT", "").strip()
            if env_root:
                return os.path.normpath(os.path.join(env_root, self._vault_name))
            return f"C:\\{self._vault_name}"
        try:
            root_folder_obj_raw = self._vault_api.RootFolder
            if root_folder_obj_raw:
                folder_api = IEdmFolder5(root_folder_obj_raw)
                if folder_api and hasattr(folder_api, 'LocalPath'):
                    return str(folder_api.LocalPath)
            return ""
        except Exception as e:
            return ""

    @profile
    def _get_folder_object(self, folder_path: str) -> Optional[IEdmFolder5]:
        if not folder_path:
            return None
        try:
            folder_obj_raw = self._vault_api.GetFolderFromPath(folder_path)
            if folder_obj_raw is None:
                return None
            folder_obj_specific = IEdmFolder5(folder_obj_raw)
            if folder_obj_specific is None or getattr(folder_obj_specific, 'ID', -1) < 0: # ID 0 is root, <0 invalid
                return None
            return folder_obj_specific
        except Exception:
            return None

    @profile
    def _refresh_pdm_object(self, pdm_object: Any) -> None:
        if pdm_object is not None and hasattr(pdm_object, 'Refresh'):
            try:
                pdm_object.Refresh()
                time.sleep(0.15) 
            except Exception:
                pass

    @profile
    def create_folders(self, folder_path: str) -> bool:
        if self._use_http and self._http:
            return self._http.create_folders(folder_path)
        if not folder_path:
            raise ValueError("Folder path cannot be empty for create_folders.")
        normalized_folder_path = os.path.normpath(folder_path)
        if self._get_folder_object(normalized_folder_path) is not None:
            return True
        vault_root = self.root_folder_path
        if not vault_root:
            raise PDMOperationFailedError("Could not determine vault root path. Cannot create folders.")
        normalized_vault_root = os.path.normpath(vault_root)
        if normalized_folder_path.lower() == normalized_vault_root.lower():
            raise PDMOperationFailedError(f"Vault root folder '{normalized_folder_path}' should already exist but was not found by _get_folder_object.")
        if not normalized_folder_path.lower().startswith(normalized_vault_root.lower()):
            raise PDMOperationFailedError(f"Target folder path '{normalized_folder_path}' is outside the PDM vault root '{normalized_vault_root}'.")
        parent_path = os.path.dirname(normalized_folder_path)
        folder_name = os.path.basename(normalized_folder_path)
        if not parent_path or parent_path == normalized_folder_path or \
           len(parent_path) < len(normalized_vault_root) or \
           not parent_path.lower().startswith(normalized_vault_root.lower()):
            raise PDMOperationFailedError(f"Cannot determine a valid PDM parent path for '{normalized_folder_path}' within vault '{normalized_vault_root}'. Calculated parent: '{parent_path}'.")
        if not self.create_folders(parent_path):
            return False 
        parent_folder_obj = self._get_folder_object(parent_path)
        if parent_folder_obj is None:
            raise PDMOperationFailedError(f"Parent folder '{parent_path}' was not found even after recursive creation attempt.")
        try:
            addfolder_output = None
            new_folder_id = 0 
            try:
                addfolder_output = parent_folder_obj.AddFolder(utils.DEFAULT_PARENT_HWND, folder_name)
                if isinstance(addfolder_output, int):
                    new_folder_id = addfolder_output
                else:
                    new_folder_id = 0 
            except TypeError: new_folder_id = 0
            except Exception: new_folder_id = 0

            if new_folder_id <= 0:
                time.sleep(0.1) 
                if self._get_folder_object(normalized_folder_path) is not None:
                    self._refresh_pdm_object(parent_folder_obj)
                    self._refresh_pdm_object(self._get_folder_object(normalized_folder_path))
                    return True
                raise PDMOperationFailedError(f"AddFolder for '{folder_name}' in '{parent_path}' resulted in an invalid ID or failure (ID: {new_folder_id}). Folder not found on re-check.")
            
            created_folder_obj = self._get_folder_object(normalized_folder_path)
            if created_folder_obj is None:
                time.sleep(0.2) 
                created_folder_obj = self._get_folder_object(normalized_folder_path)
                if created_folder_obj is None:
                    raise PDMOperationFailedError(f"Folder '{normalized_folder_path}' not found by _get_folder_object after AddFolder call (ID: {new_folder_id}), creation verification failed.")

            self._refresh_pdm_object(parent_folder_obj)
            self._refresh_pdm_object(created_folder_obj)
            return True
        except Exception as e: 
            err_str = str(e).lower()
            hresult_match_folder_exists = "0x80040301" in err_str
            if "already exist" in err_str or "file or folder already exists" in err_str or hresult_match_folder_exists:
                if self._get_folder_object(normalized_folder_path) is not None:
                    return True
                else: 
                    raise PDMOperationFailedError(f"PDM reported folder '{folder_name}' already exists in '{parent_path}', but it could not be retrieved. Original error: {e}") from e
            raise PDMOperationFailedError(f"Error creating PDM folder component '{folder_name}' in '{parent_path}': {e}") from e

    @profile
    def add_file(self, local_file_path: str, pdm_target_folder_path: str, pdm_target_filename: Optional[str] = None, comment: str = "File added via API") -> str:
        if self._use_http and self._http:
            return self._http.upload_file(local_file_path, pdm_target_folder_path, pdm_target_filename)
        if not os.path.exists(local_file_path):
            raise FileNotFoundError(f"Local source file not found: '{local_file_path}'")
        if not self.create_folders(pdm_target_folder_path):
                raise PDMOperationFailedError(f"Failed to create or ensure PDM target folder '{pdm_target_folder_path}' for file add operation.")
        dest_folder_obj = self._get_folder_object(pdm_target_folder_path)
        if dest_folder_obj is None:
            raise PDMOperationFailedError(f"PDM destination folder '{pdm_target_folder_path}' not found even after create_folders attempt.")
        filename_to_use_in_pdm = pdm_target_filename if pdm_target_filename and pdm_target_filename.strip() else os.path.basename(local_file_path)
        full_pdm_file_path_to_check = os.path.join(pdm_target_folder_path, filename_to_use_in_pdm)
        try:
            existing_file_check_tuple = self._vault_api.GetFileFromPath(full_pdm_file_path_to_check, None)
            if existing_file_check_tuple and existing_file_check_tuple[0] is not None:
                    raise PDMFileExistsError(f"File '{filename_to_use_in_pdm}' already exists in PDM folder '{pdm_target_folder_path}' at path '{full_pdm_file_path_to_check}'.")
        except PDMFileExistsError: raise
        except Exception: pass
        file_id_added = 0
        addfile_output = None
        try:
            addfile_output = dest_folder_obj.AddFile(utils.DEFAULT_PARENT_HWND, local_file_path, filename_to_use_in_pdm, 0)
            if isinstance(addfile_output, int):
                file_id_added = addfile_output
            else:
                file_id_added = 0
        except TypeError: file_id_added = 0
        except Exception: file_id_added = 0

        if file_id_added <= 0:
            raise PDMOperationFailedError(f"AddFile operation for '{filename_to_use_in_pdm}' in '{pdm_target_folder_path}' failed or returned an invalid File ID: {file_id_added}.")
        try:
            added_file_object_raw = self._vault_api.GetObject(EdmObjectType.EdmObject_File, file_id_added)
            if added_file_object_raw is None:
                raise PDMOperationFailedError(f"GetObject returned None for new File ID {file_id_added}. Cannot proceed with check-in.")
            file_to_checkin = IEdmFile17(added_file_object_raw)
            if file_to_checkin is None or getattr(file_to_checkin, 'ID', 0) <= 0:
                raise PDMCastError(f"Failed to cast or obtain valid IEdmFile17 object for File ID {file_id_added} for check-in.")
            file_to_checkin.UnlockFile(utils.DEFAULT_PARENT_HWND, comment, 0, None) 
            time.sleep(0.5) 
            file_to_checkin.Refresh() 
            if file_to_checkin.IsLocked:
                locked_by_user_raw = file_to_checkin.LockedByUser
                locker_name = "Unknown"
                if locked_by_user_raw:
                    try:
                        locker_user_iface = IEdmUser5(locked_by_user_raw)
                        if locker_user_iface: locker_name = locker_user_iface.Name
                    except: pass 
                raise PDMOperationFailedError(f"File '{file_to_checkin.Name}' is STILL LOCKED (by {locker_name}) after check-in attempt.")
            self._refresh_pdm_object(dest_folder_obj)
            final_pdm_path = os.path.join(dest_folder_obj.LocalPath, file_to_checkin.Name).replace(os.sep, '/')
            return final_pdm_path
        except Exception as e_checkin:
            raise PDMOperationFailedError(f"Error during check-in process for file ID {file_id_added} (Original file: '{filename_to_use_in_pdm}'): {e_checkin}") from e_checkin

    @profile
    def _get_pdm_file_and_folder(self, filepath: str) -> Tuple[Optional[IEdmFile17], Optional[IEdmFolder5]]:
        if not filepath:
            return None, None
        
        # --- OPTIMIZATION: Check cache first ---
        if filepath in self._file_object_cache:
            return self._file_object_cache[filepath]

        file_obj_as_file17: Optional[IEdmFile17] = None
        parent_folder_obj: Optional[IEdmFolder5] = None
        try:
            raw_file_obj, raw_parent_folder_obj = self._vault_api.GetFileFromPath(filepath, None)
            if raw_file_obj is None:
                # --- OPTIMIZATION: Cache the negative result ---
                self._file_object_cache[filepath] = (None, None)
                return None, None
            file_id = getattr(raw_file_obj, 'ID', 0)
            if file_id <= 0:
                self._file_object_cache[filepath] = (None, None)
                return None, None
            refreshed_raw_file_obj = self._vault_api.GetObject(EdmObjectType.EdmObject_File, file_id)
            if refreshed_raw_file_obj is None:
                self._file_object_cache[filepath] = (None, None)
                return None, None
            file_obj_as_file17 = IEdmFile17(refreshed_raw_file_obj)
            if file_obj_as_file17 is None or getattr(file_obj_as_file17, 'ID', 0) <= 0:
                raise PDMCastError(f"Failed to cast or get valid IEdmFile17 for file '{filepath}' (ID: {file_id}).")
            if raw_parent_folder_obj is not None:
                parent_folder_obj = IEdmFolder5(raw_parent_folder_obj)
                if parent_folder_obj is None or getattr(parent_folder_obj, 'ID', -1) < 0:
                    parent_folder_obj = None
            if parent_folder_obj is None:
                parent_folder_id = getattr(file_obj_as_file17, 'ParentFolderID', 0)
                if parent_folder_id >= 0: # ID 0 is vault root
                    raw_folder_from_id = self._vault_api.GetObject(EdmObjectType.EdmObject_Folder, parent_folder_id)
                    if raw_folder_from_id:
                        parent_folder_obj = IEdmFolder5(raw_folder_from_id)
                        if parent_folder_obj is None or getattr(parent_folder_obj, 'ID', -1) < 0:
                            parent_folder_obj = None
                if parent_folder_obj is None:
                    parent_dir_path = os.path.dirname(filepath)
                    if parent_dir_path and parent_dir_path.lower() != filepath.lower():
                        parent_folder_obj = self._get_folder_object(parent_dir_path)

            # --- OPTIMIZATION: Store result in cache ---
            self._file_object_cache[filepath] = (file_obj_as_file17, parent_folder_obj)
            return file_obj_as_file17, parent_folder_obj
        except PDMCastError as e_cast:
            raise
        except Exception:
            # --- OPTIMIZATION: Cache the negative result on error ---
            self._file_object_cache[filepath] = (None, None)
            return None, None

    @profile
    def _copy_file_from_objects(self, src_file_obj: IEdmFile17, src_folder_obj: IEdmFolder5, dest_folder_obj: IEdmFolder5, new_filename: Optional[str]):
        if not src_file_obj or not src_folder_obj or not dest_folder_obj:
            raise ValueError("Invalid PDM object provided for copy operation.")
        try:
            dest_folder_id = dest_folder_obj.ID
            src_file_id = src_file_obj.ID
            filename_to_use = new_filename if new_filename and new_filename.strip() else src_file_obj.Name
            self._vault_api.CopyFile(utils.DEFAULT_PARENT_HWND, src_file_id, dest_folder_id, 0, filename_to_use, EDM_COPY_SIMPLE, None)
        except Exception as e:
            raise PDMOperationFailedError(f"PDM CopyFile API call failed for source file ID {getattr(src_file_obj, 'ID', 'N/A')}: {e}") from e

    @profile
    def delete_empty_folder_structure(self, folder_path: str) -> bool:
        if self._use_http and self._http:
            return self._http.delete_empty_folder_structure(folder_path)
        folder_obj = self._get_folder_object(folder_path)
        if folder_obj is None:
            raise PDMFileNotFoundError(f"Folder not found for deletion: '{folder_path}'")
        try:
            if self._folder_structure_contains_files(folder_obj):
                raise PDMOperationFailedError(f"Cannot delete folder '{folder_path}': folder structure contains files.")
            self._delete_folder_recursive(folder_obj, folder_path)
            return True
        except Exception as e:
            raise PDMOperationFailedError(f"Error deleting folder structure '{folder_path}': {e}") from e

    @profile
    def _delete_folder_recursive(self, folder_obj: IEdmFolder5, folder_path: str) -> None:
        if not folder_obj:
            return
        subfolder_details_to_delete = []
        for sub_obj in self._get_subfolders_from_folder(folder_obj):
            sub_path = sub_obj.LocalPath 
            if sub_path:
                subfolder_details_to_delete.append((sub_obj, sub_path))
        for sub_obj_to_del, sub_path_to_del in subfolder_details_to_delete:
            self._delete_folder_recursive(sub_obj_to_del, sub_path_to_del)
        parent_dir_path = os.path.dirname(folder_path)
        if not parent_dir_path or parent_dir_path.lower() == folder_path.lower() or \
           (os.path.normpath(parent_dir_path).lower() == os.path.normpath(self.root_folder_path).lower() and folder_obj.ParentFolderID == 0) : # folder_obj.ID == 0 is root itself
            if os.path.normpath(folder_path).lower() == os.path.normpath(self.root_folder_path).lower():
                return 
        parent_pdm_folder_obj = self._get_folder_object(parent_dir_path)
        if parent_pdm_folder_obj is None:
            if folder_obj.ParentFolderID == 0: 
                parent_pdm_folder_obj = IEdmFolder5(self._vault_api.RootFolder)
            if parent_pdm_folder_obj is None:
                raise PDMOperationFailedError(f"Cannot find parent PDM folder for '{folder_path}' (calculated parent: '{parent_dir_path}') to delete folder ID {folder_obj.ID}.")
        try:
            parent_pdm_folder_obj.DeleteFolder(utils.DEFAULT_PARENT_HWND, folder_obj.ID)
        except Exception as e_del:
            raise PDMOperationFailedError(f"Failed to delete folder '{folder_obj.Name}' (ID: {folder_obj.ID}): {e_del}") from e_del

    @profile
    def _folder_structure_contains_files(self, folder_obj: IEdmFolder5) -> bool:
        if not folder_obj:
            return False
        file_pos = folder_obj.GetFirstFilePosition()
        if not file_pos.IsNull:
            return True
        sub_folder_pos = folder_obj.GetFirstSubFolderPosition()
        while not sub_folder_pos.IsNull:
            sub_folder_raw = folder_obj.GetNextSubFolder(sub_folder_pos)
            if sub_folder_raw:
                sub_folder_casted = IEdmFolder5(sub_folder_raw)
                if sub_folder_casted and self._folder_structure_contains_files(sub_folder_casted):
                    return True
            else: break
        return False

    @profile
    def get_files_in_folder(self, folder_path: str) -> Iterator[str]:
        if self._use_http and self._http:
            yield from self._http.get_files_in_folder(folder_path)
            return
        folder_obj = self._get_folder_object(folder_path)
        if folder_obj is None:
            raise PDMFileNotFoundError(f"Folder not found: '{folder_path}'")
        try:
            for file_obj in self._get_files_from_folder(folder_obj):
                yield os.path.join(folder_obj.LocalPath, file_obj.Name) # Use folder_obj.LocalPath for consistency
        except Exception as e:
            raise PDMOperationFailedError(f"Error getting files in folder '{folder_path}': {e}") from e

    @profile
    def get_subfolders_in_folder(self, folder_path: str) -> Iterator[str]:
        if self._use_http and self._http:
            yield from self._http.get_subfolders_in_folder(folder_path)
            return
        folder_obj = self._get_folder_object(folder_path)
        if folder_obj is None:
            raise PDMFileNotFoundError(f"Folder not found: '{folder_path}'")
        try:
            for subfolder_obj in self._get_subfolders_from_folder(folder_obj):
                yield subfolder_obj.LocalPath
        except Exception as e:
            raise PDMOperationFailedError(f"Error getting subfolders in folder '{folder_path}': {e}") from e

    @profile
    def _get_files_from_folder(self, folder_obj: IEdmFolder5) -> Iterator[IEdmFile17]:
        if not folder_obj: return
        try:
            pos = folder_obj.GetFirstFilePosition()
            while not pos.IsNull:
                file_obj_raw = folder_obj.GetNextFile(pos)
                if file_obj_raw is None: break
                yield IEdmFile17(file_obj_raw)
        except Exception as e:
            if "cursor is off-right" not in str(e).lower() and "0x80040208" not in str(e):
                raise PDMFileInfoError(f"Error iterating files in folder ID {folder_obj.ID}: {e}") from e

    @profile
    def _get_subfolders_from_folder(self, folder_obj: IEdmFolder5) -> Iterator[IEdmFolder5]:
        if not folder_obj: return
        try:
            pos = folder_obj.GetFirstSubFolderPosition()
            while not pos.IsNull:
                subfolder_obj_raw = folder_obj.GetNextSubFolder(pos)
                if subfolder_obj_raw is None: break
                subfolder_obj = IEdmFolder5(subfolder_obj_raw)
                if subfolder_obj is None:
                    raise PDMCastError(f"Failed to cast subfolder object to IEdmFolder5 in folder ID {folder_obj.ID}")
                yield subfolder_obj
        except Exception as e:
            if "cursor is off-right" not in str(e).lower() and "0x80040208" not in str(e):
                raise PDMFileInfoError(f"Error iterating subfolders in folder ID {folder_obj.ID}: {e}") from e
    
    @profile
    def _delete_file_from_object(self, file_obj: IEdmFile17, folder_obj: IEdmFolder5):
        if not file_obj or not folder_obj:
            raise ValueError("Invalid PDM object provided for delete operation.")
        try:
            folder_obj.DeleteFile(utils.DEFAULT_PARENT_HWND, file_obj.ID, utils.EDM_DELETE_SIMPLE)
        except Exception as e:
            raise PDMOperationFailedError(f"PDM DeleteFile API call failed for file ID {file_obj.ID}: {e}") from e

    @profile
    def _get_file_info_from_object(self, file_obj: IEdmFile17, folder_obj: Optional[IEdmFolder5]) -> Dict[str, Any]:
        if not file_obj:
            raise ValueError("Requires a valid IEdmFile17 object.")
        info: Dict[str, Any] = {}
        try:
            info = { "ID": file_obj.ID, "Name": file_obj.Name, "CurrentVersion": file_obj.CurrentVersion,
                     "CurrentRevision": getattr(file_obj, 'CurrentRevision', 'N/A'), "FileType": getattr(file_obj, 'FileType', 'N/A'),
                     "CategoryID": getattr(file_obj, 'CategoryID', 'N/A'), "IsLocked": file_obj.IsLocked, "FolderPath": None,
                     "FolderID": None, "StateName": None, "LockedByUser": None, "LockedByUserID": None, "LockedOnComputer": None }
            if folder_obj:
                info["FolderPath"] = folder_obj.LocalPath
                info["FolderID"] = folder_obj.ID
            state_raw = file_obj.CurrentState
            if state_raw:
                state_obj = IEdmState5(state_raw)
                info["StateName"] = state_obj.Name if state_obj else None
            if info.get("IsLocked"):
                user_raw = file_obj.LockedByUser
                if user_raw:
                    user_obj = IEdmUser5(user_raw)
                    if user_obj:
                        info["LockedByUser"] = user_obj.Name
                        info["LockedByUserID"] = user_obj.ID
                    else:
                        info["LockedByUser"] = "CastError"
                        info["LockedByUserID"] = -1
                info["LockedOnComputer"] = getattr(file_obj, 'LockedOnComputer', 'N/A')
            return info
        except Exception as e:
            raise PDMFileInfoError(f"Error extracting info for file ID {getattr(file_obj, 'ID', 'N/A')}: {e}") from e

    @profile
    def _get_reference_tree_from_object(self, file_obj: IEdmFile17, folder_obj: IEdmFolder5, version: int = 0) -> Optional[IEdmReference11]: # utils.LATEST_VERSION was 0
        if not file_obj or not folder_obj:
            return None
        try:
            # MODIFIED: Pass the requested version number to the API call
            reference_tree_raw = file_obj.GetReferenceTree(folder_obj.ID, version)
            if reference_tree_raw is None:
                return None
            ref_obj = IEdmReference11(reference_tree_raw)
            if ref_obj is None:
                raise PDMCastError("Cast to IEdmReference11 failed.")
            return ref_obj
        except PDMCastError as e_cast:
            raise PDMCastError(f"Cast failed getting reference tree: {e_cast}") from e_cast
        except Exception as e:
            raise PDMFileInfoError(f"Error getting reference tree for file ID {file_obj.ID}: {e}") from e

    @profile
    def _get_children_from_reference(self, parent_reference_node: IEdmReference11, version: int = 0) -> Iterator[IEdmReference11]:
        if not parent_reference_node:
            return

        pos_raw = None
        pos = None
        
        try:
            ref_flags = int(EdmRefFlags.EdmRef_File)
            # MODIFIED: Pass the requested version number to the API call
            result_tuple = parent_reference_node.GetFirstChildPosition4(
                utils.DEFAULT_PROJECT, 
                utils.GET_SUPPRESSED_COMPONENTS, 
                False, 
                False, 
                ref_flags, 
                utils.DEFAULT_CONFIG, 
                version
            )
            
            current_child_index = 0
            if isinstance(result_tuple, str) and result_tuple.startswith("pos_child_") and hasattr(parent_reference_node, '_children') and parent_reference_node._children: # Check for placeholder behavior
                pos_raw = result_tuple # Initial position
            elif isinstance(result_tuple, tuple) and len(result_tuple) >= 1: # More generic PDM API style
                pos_raw = result_tuple[0]
            else:
                return

            if pos_raw:
                pos = IEdmPos5(pos_raw) if not isinstance(pos_raw, IEdmPos5) else pos_raw 
                if pos is None and pos_raw is not None:
                    pass 
            else:
                return

            while pos_raw is not None:
                raw_next_child_ref = None
                try:
                    current_pos_for_api = pos if pos is not None else pos_raw
                    
                    if hasattr(parent_reference_node, '_children'):
                        if current_child_index < len(parent_reference_node._children):
                            raw_next_child_ref = parent_reference_node._children[current_child_index]
                            current_child_index += 1
                            if current_child_index >= len(parent_reference_node._children):
                                pos_raw = None
                        else:
                            raw_next_child_ref = None
                            pos_raw = None
                            break
                    else:
                        raw_next_child_ref = parent_reference_node.GetNextChild(current_pos_for_api)

                except Exception as e:
                    error_msg = str(e).lower()
                    if "cursor is off-right" in error_msg or "0x80040208" in error_msg:
                        break 
                    else:
                        raise 
                
                if raw_next_child_ref is None: 
                    break 
                
                child_reference = IEdmReference11(raw_next_child_ref) if not isinstance(raw_next_child_ref, IEdmReference11) else raw_next_child_ref
                if child_reference is None and raw_next_child_ref is not None :
                    raise PDMCastError(f"Cast to IEdmReference11 for child reference failed.")
                
                yield child_reference

        except PDMCastError:
            raise
        except Exception as e:
            raise PDMFileInfoError(f"Error collecting direct children: {e}") from e
    
    @profile
    def _get_parents_from_reference(self, child_reference_node: IEdmReference11) -> Iterator[IEdmReference11]:
        if not child_reference_node:
            return

        # --- OPTIMIZATION: Use cache for parent lookups ---
        ref_path = getattr(child_reference_node, 'FoundPath', None)
        if ref_path and ref_path in self._parents_cache:
            yield from self._parents_cache[ref_path]
            return

        parents_list = []
        pos_raw = None
        pos = None
        try:
            ref_flags = int(EdmRefFlags.EdmRef_File)
            pos_raw = child_reference_node.GetFirstParentPosition2(
                utils.LATEST_VERSION,
                False,
                ref_flags
            )
            current_parent_index = 0 # For placeholder

            if pos_raw:
                pos = IEdmPos5(pos_raw) if not isinstance(pos_raw, IEdmPos5) else pos_raw
                if pos is None and pos_raw is not None:
                    pass
            else:
                if ref_path: self._parents_cache[ref_path] = []
                return

            while pos_raw is not None:
                raw_next_parent_ref = None
                try:
                    current_pos_for_api = pos if pos is not None else pos_raw
                    
                    if hasattr(child_reference_node, '_parents'):
                        if current_parent_index < len(child_reference_node._parents):
                            raw_next_parent_ref = child_reference_node._parents[current_parent_index]
                            current_parent_index += 1
                            if current_parent_index >= len(child_reference_node._parents):
                                pos_raw = None
                        else:
                            raw_next_parent_ref = None
                            pos_raw = None
                            break
                    else:
                        raw_next_parent_ref = child_reference_node.GetNextParent(current_pos_for_api)

                except Exception as e:
                    error_msg = str(e).lower()
                    if "cursor is off-right" in error_msg or "0x80040208" in error_msg:
                        break
                    else:
                        raise
                
                if raw_next_parent_ref is None:
                    break
                
                parent_reference = IEdmReference11(raw_next_parent_ref) if not isinstance(raw_next_parent_ref, IEdmReference11) else raw_next_parent_ref
                if parent_reference is None and raw_next_parent_ref is not None :
                    raise PDMCastError(f"Cast to IEdmReference11 for parent reference failed.")
                
                parents_list.append(parent_reference) # Collect for caching
            
            # --- OPTIMIZATION: Cache the result ---
            if ref_path:
                self._parents_cache[ref_path] = parents_list
            
            yield from parents_list

        except PDMCastError:
            raise
        except Exception as e:
            raise PDMFileInfoError(f"Error collecting direct parents: {e}") from e

    # --- New Public Methods ---
    @profile
    def get_children(self, filepath: str) -> Iterator[Dict[str, str]]:
        """
        Gets the direct children (references) of a PDM file and formats them.
        Yields a dictionary for each child reference.
        """
        if self._use_http and self._http:
            yield from self._http.get_children(filepath)
            return
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if not file_obj or not folder_obj:
            log_msg = f"Parent file or folder not found for get_children: '{filepath}'."
            if not file_obj: log_msg += " File object is None."
            if not folder_obj: log_msg += " Folder object is None."
            raise PDMFileNotFoundError(f"Parent file or folder not found for get_children operation: '{filepath}'")
        
        try:
            root_reference = self._get_reference_tree_from_object(file_obj, folder_obj)
            if root_reference:
                for child_ref_obj in self._get_children_from_reference(root_reference):
                    yield utils.format_reference_data(child_ref_obj)
            else:
                return iter([]) 
        except (PDMCastError, PDMFileInfoError, PDMFileNotFoundError) as e: 
            raise 
        except Exception as e: 
            # Wrap in a PDM specific error if not already one
            raise PDMFileInfoError(f"Unexpected error during get_children for '{filepath}': {e}") from e

    @profile
    def get_parents(self, filepath: str) -> Iterator[Dict[str, str]]:
        """
        Gets the direct parents (where-used) of a PDM file and formats them.
        Yields a dictionary for each parent reference.
        """
        if self._use_http and self._http:
            yield from self._http.get_parents(filepath)
            return
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if not file_obj or not folder_obj:
            log_msg = f"Child file or folder not found for get_parents: '{filepath}'."
            if not file_obj: log_msg += " File object is None."
            if not folder_obj: log_msg += " Folder object is None."
            raise PDMFileNotFoundError(f"Child file or folder not found for get_parents operation: '{filepath}'")
        
        try:
            root_reference = self._get_reference_tree_from_object(file_obj, folder_obj)
            if root_reference:
                for parent_ref in self._get_parents_from_reference(root_reference):
                    yield utils.format_reference_data(parent_ref)
            else:
                return iter([])
        except (PDMCastError, PDMFileInfoError, PDMFileNotFoundError) as e:
            raise
        except Exception as e:
            raise PDMFileInfoError(f"Unexpected error during get_parents for '{filepath}': {e}") from e

    def import_file_to_pdm(self, local_filepath: str, pdm_dest_folder_path: str, new_filename: Optional[str] = None) -> str:
        if self._use_http and self._http:
            return self._http.upload_file(local_filepath, pdm_dest_folder_path, new_filename)
        log_ext_import_pdm: str = "-pdm_api_import"
        if not os.path.exists(local_filepath):
            raise PDMFileNotFoundError(f"Local source file not found: '{local_filepath}'")
        
        dest_folder_obj: Optional[Any] = self._get_folder_object(pdm_dest_folder_path)
        if dest_folder_obj is None:
            raise PDMFileNotFoundError(f"PDM destination folder not found: '{pdm_dest_folder_path}'")

        src_filename_str: str = os.path.basename(local_filepath)
        filename_to_use_in_pdm: str = new_filename if new_filename and new_filename.strip() else src_filename_str
        
        pdm_expected_filepath_str: str = os.path.join(pdm_dest_folder_path, filename_to_use_in_pdm).replace(os.sep, '/')

        file_id_from_add: int = 0
        error_code_from_add: int = -1 # Initialize to a non-zero error state
        added_file_object_pdm: Optional[Any] = None

        try:
            if not hasattr(dest_folder_obj, 'AddFile2'):
                raise PDMOperationFailedError(f"PDM API version error: AddFile2 not available on folder object for '{pdm_dest_folder_path}'.")

            
            add_result: Any = dest_folder_obj.AddFile2(utils.DEFAULT_PARENT_HWND, local_filepath, filename_to_use_in_pdm, 0) # type: ignore[attr-defined]
            
            if isinstance(add_result, tuple) and len(add_result) == 2:
                file_id_from_add = int(add_result[0])
                error_code_from_add = int(add_result[1])
            elif isinstance(add_result, int): # If it only returns the file_id and error_code is implicit via exceptions
                file_id_from_add = add_result
                error_code_from_add = 0 # Assume success if no exception and int ID returned
            else:
                raise PDMOperationFailedError(f"AddFile2 PDM call returned unexpected result structure for file '{filename_to_use_in_pdm}'.")

            if file_id_from_add <= 0: # Primary check based on returned ID
                raise PDMOperationFailedError(f"AddFile2 returned invalid ID: {file_id_from_add} (PDM ErrorCode: {error_code_from_add}) for file '{filename_to_use_in_pdm}'.")

            if hasattr(self._vault_api, 'GetObject'):
                get_object_exception_occurred: bool = False
                try:
                    pdm_enum_member_for_file: Any = EdmObjectType.EdmObject_File # type: ignore[name-defined] 
                    added_file_object_pdm = self._vault_api.GetObject(pdm_enum_member_for_file, file_id_from_add) # type: ignore[attr-defined]
                except NameError as ne: 
                    get_object_exception_occurred = True
                    added_file_object_pdm = None
                    raise PDMOperationFailedError(f"Failed to use EdmObjectType for GetObject (NameError): {str(ne)}") from ne
                except Exception as e_get_id: 
                    get_object_exception_occurred = True
                    added_file_object_pdm = None
                    raise PDMOperationFailedError(f"Failed to retrieve PDM file object by ID {file_id_from_add} using GetObject: {str(e_get_id)}") from e_get_id
                
            else:
                added_file_object_pdm = None
            
            checkin_success: bool = self.checkin_file(
                filepath=pdm_expected_filepath_str, 
                comment="Initial import via API",
                file_object_to_use=added_file_object_pdm, 
                folder_object_to_use=dest_folder_obj 
            )
            
            if not checkin_success:
                raise PDMOperationFailedError(f"Check-in for file '{pdm_expected_filepath_str}' reported as unsuccessful from checkin_file method.")

            if dest_folder_obj and hasattr(dest_folder_obj, 'Refresh'):
                dest_folder_obj.Refresh() # type: ignore[attr-defined]
                time.sleep(0.5) 
                return pdm_expected_filepath_str

        except PDMOperationFailedError as e_op: 
            raise 
        except Exception as e: 
            raise PDMOperationFailedError(f"Error importing and checking in file '{local_filepath}' to '{pdm_dest_folder_path}': {str(e)}") from e

    def get_local_copy(self, pdm_filepath: str, local_dest_dir: str, new_filename: Optional[str] = None) -> str:
        if self._use_http and self._http:
            return self._http.download_file(pdm_filepath, local_dest_dir, new_filename)
        log_ext_get_local: str = "-pdm_api_get_copy" # Define a unique extension for these logs
        file_obj: Optional[Any] 
        folder_obj: Optional[Any]
        file_obj, folder_obj = self._get_pdm_file_and_folder(pdm_filepath)

        if file_obj is None or folder_obj is None:
            raise PDMFileNotFoundError(f"PDM file not found or folder inaccessible: '{pdm_filepath}'")

        if not os.path.exists(local_dest_dir):
            try:
                os.makedirs(local_dest_dir, exist_ok=True)
            except OSError as e:
                raise PDMOperationFailedError(f"Cannot create local destination directory '{local_dest_dir}': {e}") from e
        
        dest_filename_str: str = new_filename if new_filename else file_obj.Name # type: ignore[attr-defined]
        local_dest_filepath_str: str = os.path.join(local_dest_dir, dest_filename_str)

        try:
            file_obj.GetFileCopy(utils.DEFAULT_PARENT_HWND, None, local_dest_filepath_str, 0) # type: ignore[attr-defined]
            
            if not os.path.exists(local_dest_filepath_str):
                file_obj.GetFileCopy(utils.DEFAULT_PARENT_HWND, None, local_dest_filepath_str, 1) # type: ignore[attr-defined]

            if not os.path.exists(local_dest_filepath_str):
                raise PDMOperationFailedError(f"PDM GetFileCopy API call failed to create local file: '{local_dest_filepath_str}' after trying flags 0 and 1.")
            
            return local_dest_filepath_str
        except Exception as e:
            if isinstance(e, PDMOperationFailedError): # Re-raise specific PDM errors if already caught
                raise 
            raise PDMOperationFailedError(f"Error getting local copy of '{pdm_filepath}' via GetFileCopy: {e}") from e

    @profile
    def _create_search2_object(self, directory: Optional[str] = None, recursive: bool = False) -> IEdmSearch9:
        start_folder_path = directory if directory else self.root_folder_path
        if not start_folder_path:
            raise PDMOperationFailedError("Cannot determine search start directory (vault root path may not be set).")

        start_folder = self._get_folder_object(start_folder_path)
        if start_folder is None:
            is_local_dir = os.path.isdir(start_folder_path)
            raise PDMFileNotFoundError(f"Search start folder '{start_folder_path}' could not be accessed via PDM API. (Check path validity. Local exists: {is_local_dir})")

        try:
            if not hasattr(self._vault_api, 'CreateSearch2'):
                raise PDMOperationFailedError("Vault object does not support the CreateSearch2 method. Requires IEdmVault21 or higher interface.")

            search_raw = self._vault_api.CreateSearch2()
            if search_raw is None:
                raise PDMOperationFailedError("Vault CreateSearch2() method returned None.")

            search_object = IEdmSearch9(search_raw)
            if search_object is None:
                search_fallback = IEdmSearch5(search_raw) if hasattr(EPDM.Interop.epdm, 'IEdmSearch5') else None
                if search_fallback:
                    search_object = search_fallback
                else:
                    raise PDMCastError("Failed to cast search object to IEdmSearch9 (or any fallback).")

            search_object.StartFolderID = start_folder.ID
            search_object.Recursive = recursive
            search_object.FindFiles = True
            search_object.FindFolders = False

            return search_object

        except AttributeError as ae:
            raise PDMOperationFailedError(f"PDM API object missing expected method/property (check API version/cast resulted in older interface?): {ae}") from ae
        except (PDMCastError, PDMOperationFailedError, PDMFileNotFoundError) as pdm_e:
            raise pdm_e
        except Exception as e:
            raise PDMOperationFailedError(f"Unexpected error creating search object: {e}") from e

    @profile
    def search_files(self,
                     filename_pattern: Optional[str] = None,
                     variable_conditions: Optional[Dict[str, str]] = None,
                     directory: Optional[str] = None,
                     recursive: bool = utils.DEFAULT_SEARCH_RECURSIVE) -> Iterator[Dict[str, str]]:
        if self._use_http and self._http:
            yield from self._http.search_files(filename_pattern, variable_conditions, directory, recursive)
            return

        if not filename_pattern and not variable_conditions:
            filename_pattern = '*'

        try:
            search_object = self._create_search2_object(directory=directory, recursive=recursive)

            if filename_pattern:
                search_object.FileName = filename_pattern
            
            conditions_for_pdm = variable_conditions.copy() if variable_conditions else {}
            target_state_name = None

            if 'State' in conditions_for_pdm:
                target_state_name = conditions_for_pdm.pop('State')

            if conditions_for_pdm:
                try:
                    if not hasattr(search_object, 'AddVariable2'):
                        raise PDMOperationFailedError("Search object is missing 'AddVariable2' method.")
                    for var_name, condition in conditions_for_pdm.items():
                        search_object.AddVariable2(var_name, condition)
                except Exception as var_err:
                    raise PDMOperationFailedError(f"Error calling AddVariable2: {var_err}") from var_err

            result = search_object.GetFirstResult()
            
            while result:
                formatted_result = utils.format_search_result(result)
                
                # --- START: Added diagnostic logging ---
                # This will log every result from the initial PDM search before manual filtering.
                if target_state_name:
                    utils.log(
                        f"Manual Filter Check: File='{formatted_result.get('name')}', "
                        f"FileState='{formatted_result.get('state')}', "
                        f"TargetState='{target_state_name}'",
                        ext="_search_debug_filter"
                    )
                # --- END: Added diagnostic logging ---

                if target_state_name:
                    if formatted_result.get('state') == target_state_name:
                        yield formatted_result
                else:
                    yield formatted_result
                
                try:
                    next_result = search_object.GetNextResult()
                    result = next_result
                except Exception:
                    break
            
        except (PDMFileNotFoundError, PDMCastError, PDMOperationFailedError) as pdm_e:
            raise pdm_e
        except Exception as e:
            raise PDMOperationFailedError(f"Unexpected error during PDM file search: {e}") from e
    
    @profile
    def delete_file(self, filepath: str, force_unlock: bool = False) -> bool:
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if not file_obj or not folder_obj:
            raise PDMFileNotFoundError(f"File to be deleted not found in PDM: '{filepath}'")

        try:
            if file_obj.IsLocked:
                locker_user_obj = file_obj.LockedByUser
                locker = IEdmUser5(locker_user_obj) if locker_user_obj else None
                locker_name = locker.Name if locker else "Unknown User"

                if locker and locker.Name != self._username:
                    if not force_unlock:
                        raise PDMOperationFailedError(f"Cannot delete file '{filepath}'. It is currently checked out by user '{locker_name}'.")
                    else:
                        try:
                            file_obj.UnlockFile(utils.DEFAULT_PARENT_HWND, "Force unlock before API delete", 0, None)
                        except Exception as unlock_err:
                            raise PDMOperationFailedError(f"Failed to force unlock '{filepath}' (locked by '{locker_name}'): {unlock_err}") from unlock_err
                elif locker and locker.Name == self._username:
                    try:
                        file_obj.UnlockFile(utils.DEFAULT_PARENT_HWND, "Unlock by current user before API delete", 0, None)
                    except Exception as unlock_err:
                        raise PDMOperationFailedError(f"Failed to unlock '{filepath}' (locked by current user): {unlock_err}") from unlock_err
                else:
                    if not force_unlock:
                        raise PDMOperationFailedError(f"Cannot delete file '{filepath}'. It is checked out, but the locker is unknown.")
                    else:
                        try:
                            file_obj.UnlockFile(utils.DEFAULT_PARENT_HWND, "Force unlock (unknown locker) before API delete", 0, None)
                        except Exception as unlock_err:
                            pass

            folder_obj.DeleteFile(utils.DEFAULT_PARENT_HWND, file_obj.ID, True)
            return True

        except (PDMOperationFailedError, ValueError, PDMFileNotFoundError) as e:
            raise e
        except Exception as e:
            raise PDMOperationFailedError(f"An unexpected error occurred while attempting to delete file '{filepath}': {e}") from e

    @profile
    def get_file_info(self, filepath: str) -> Optional[Dict[str, Any]]:
        if self._use_http and self._http:
            try:
                return self._http.get_file_info(filepath)
            except PDMFileNotFoundError:
                return None
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if file_obj is None:
            return None
        try:
            return self._get_file_info_from_object(file_obj, folder_obj)
        except PDMFileInfoError as e:
            return None
        except Exception as e:
            return None

    @profile
    def get_reference_info(self, filepath: str) -> Optional[Dict[str, str]]:
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if not file_obj or not folder_obj:
            return None
        try:
            root_reference = self._get_reference_tree_from_object(file_obj, folder_obj)
            return utils.format_reference_data(root_reference) if root_reference else None
        except (PDMCastError, PDMFileInfoError) as e:
            return None
        except Exception as e:
            return None

    def checkout_file(self, filepath: str) -> bool:
        log_ext_checkout: str = "-pdm_api_checkout"
        file_obj: Optional[IEdmFile17]
        folder_obj: Optional[IEdmFolder5]
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)

        if not file_obj or not folder_obj:
            raise PDMFileNotFoundError(f"File not found for checkout operation: '{filepath}'")

        current_file_state: str = "Unknown"
        try:
            file_info_data: Optional[Dict[str, Any]] = self.get_file_info(filepath) # Assuming get_file_info exists
            current_file_state = file_info_data.get("StateName", "Unknown") if file_info_data else "Unknown (File info retrieval failed)"
            is_locked_initial: bool = file_obj.IsLocked
            if is_locked_initial:
                locked_by_user_obj_initial: Optional[Any] = file_obj.LockedByUser
                locker_name_initial: Optional[str] = None
                if locked_by_user_obj_initial:
                    try:
                        locker_pdm_user_interface_initial: Any = IEdmUser5(locked_by_user_obj_initial)
                        locker_name_initial = locker_pdm_user_interface_initial.Name
                    except Exception as e_user_name_initial:
                        locker_name_initial = "ErrorRetrievingName"
                
                if locker_name_initial and locker_name_initial.lower() == self._username.lower():
                    return True
                else:
                    err_msg_locked: str = f"File '{filepath}' is already checked out by '{locker_name_initial if locker_name_initial else 'another user (name unknown)'}'."
                    raise PDMOperationFailedError(err_msg_locked)
            
            file_obj.LockFile(folder_obj.ID, utils.DEFAULT_PARENT_HWND, 0) 
            time.sleep(1.0) 
            file_obj.Refresh() 
            is_locked_after_command: bool = file_obj.IsLocked
            if is_locked_after_command:
                locked_by_user_obj_after: Optional[Any] = file_obj.LockedByUser
                locker_name_after: Optional[str] = None
                if locked_by_user_obj_after:
                    try:
                        locker_pdm_user_interface_after: Any = IEdmUser5(locked_by_user_obj_after)
                        locker_name_after = locker_pdm_user_interface_after.Name
                    except Exception as e_user_name_after:
                        
                        locker_name_after = "ErrorRetrievingName"

                if locker_name_after and locker_name_after.lower() == self._username.lower():
                    return True
                else:
                    err_msg_inconsistent: str = f"Checkout status inconsistency: File '{filepath}' is locked after command, but not by the expected user '{self._username}'. Actual locker: '{locker_name_after if locker_name_after else 'None/Unknown'}'."
                    raise PDMOperationFailedError(err_msg_inconsistent)
            else:
                err_msg_not_locked: str = f"Checkout failed: LockFile command was sent for '{filepath}', but the file is not locked after refresh. Check user permissions for checkout in state '{current_file_state}' or if the state itself prohibits checkout."
                raise PDMOperationFailedError(err_msg_not_locked)

        except PDMOperationFailedError as op_err_checkout:
            raise 
        except Exception as e_checkout:
            error_msg_str: str = str(e_checkout)
            hresult_str = ""
            if hasattr(e_checkout, 'HResult'):
                hresult_str = hex(e_checkout.HResult & 0xFFFFFFFF)
            
            # E_EDM_PERMISSION_DENIED typically for rights
            if hresult_str == "0x8004010a": 
                raise PDMOperationFailedError(f"Checkout failed for '{filepath}': Permission denied (Error {hresult_str}). User '{self._username}' may lack checkout rights for this file or in state '{current_file_state}'.") from e_checkout
            # E_EDM_INVALID_FILE_STATE if state transition for checkout is not allowed
            elif hresult_str == "0x8004010d": 
                raise PDMOperationFailedError(f"Checkout failed for '{filepath}': Invalid file state for checkout (Error {hresult_str}). Current state is '{current_file_state}'.") from e_checkout
            # E_EDM_FILE_IS_CHECKED_OUT (often by another user)
            elif hresult_str == "0x80040209":
                raise PDMOperationFailedError(f"Checkout failed for '{filepath}': File is already checked out (Error {hresult_str}).") from e_checkout
            else:
                raise PDMOperationFailedError(f"Checkout failed for '{filepath}' due to an unexpected error (HRESULT: {hresult_str if hresult_str else 'N/A'}): {error_msg_str}") from e_checkout

    def checkin_file(self, filepath: str, comment: str = "API Check-in", 
                         file_object_to_use: Optional[IEdmFile17] = None, 
                         folder_object_to_use: Optional[IEdmFolder5] = None) -> bool:
        log_ext_checkin: str = "-pdm_api_checkin"
        
        specific_file_obj: Optional[IEdmFile17] = file_object_to_use
        
        if not specific_file_obj: 
            fetched_file_obj_path: Optional[IEdmFile17] = None
            max_retries_get_file: int = 3
            retry_delay_seconds: float = 0.5 

            for attempt in range(max_retries_get_file):
                fetched_file_obj_path, _ = self._get_pdm_file_and_folder(filepath) 
                if fetched_file_obj_path is not None:
                    specific_file_obj = fetched_file_obj_path
                    break
                if attempt < max_retries_get_file - 1:
                    time.sleep(retry_delay_seconds)
            
            if not specific_file_obj:
                raise PDMFileNotFoundError(f"File not found for check-in operation after all attempts: '{filepath}'")
        
        current_file_state_for_checkin: str = "Unknown"
        try:
            file_info_data_ci: Optional[Dict[str, Any]] = self.get_file_info(filepath)
            current_file_state_for_checkin = file_info_data_ci.get("StateName", "Unknown") if file_info_data_ci else "Unknown"

            is_locked_initial: bool = specific_file_obj.IsLocked
            
            if not is_locked_initial:
                return True

            locked_by_user_obj: Optional[Any] = specific_file_obj.LockedByUser
            locker_name_pdm: Optional[str] = None
            if locked_by_user_obj:
                try:
                    locker_pdm_user_interface: Any = IEdmUser5(locked_by_user_obj)
                    locker_name_pdm = locker_pdm_user_interface.Name
                except Exception as e_user_name:
                    locker_name_pdm = "ErrorRetrievingName"
            
            if not locker_name_pdm or locker_name_pdm.lower() != self._username.lower():
                raise PDMOperationFailedError(f"Check-in failed: File '{filepath}' is currently checked out by '{locker_name_pdm if locker_name_pdm else 'another user or unknown'}', not the current API user '{self._username}'.")

            specific_file_obj.UnlockFile(utils.DEFAULT_PARENT_HWND, comment, 0, None) 
                                
            time.sleep(1.0) 
            specific_file_obj.Refresh() 
            
            is_locked_after_checkin: bool = specific_file_obj.IsLocked
            
            if not is_locked_after_checkin:
                return True
            else:
                raise PDMOperationFailedError(f"Check-in failed: UnlockFile command was sent for '{filepath}', but the file remains locked after refresh. Check for potential issues or required check-in conditions in state '{current_file_state_for_checkin}'.")

        except PDMOperationFailedError as op_err_checkin:
            raise 
        except Exception as e_checkin: 
            error_msg_str_ci: str = str(e_checkin)
            hresult_str_ci = ""
            if hasattr(e_checkin, 'HResult'):
                hresult_str_ci = hex(e_checkin.HResult & 0xFFFFFFFF)

            if hresult_str_ci == "0x8004010a": # E_EDM_PERMISSION_DENIED
                raise PDMOperationFailedError(f"Check-in failed for '{filepath}': Permission denied (Error {hresult_str_ci}). User '{self._username}' may lack check-in rights for this file or in state '{current_file_state_for_checkin}'.") from e_checkin
            elif hresult_str_ci == "0x8004010d": # E_EDM_INVALID_FILE_STATE
                raise PDMOperationFailedError(f"Check-in failed for '{filepath}': Invalid file state for check-in (Error {hresult_str_ci}). Current state is '{current_file_state_for_checkin}'.") from e_checkin
            else:
                raise PDMOperationFailedError(f"Check-in failed for '{filepath}' due to an unexpected error (HRESULT: {hresult_str_ci if hresult_str_ci else 'N/A'}): {error_msg_str_ci}") from e_checkin

    @profile
    def set_variable(self, filepath: str, var_name: str, var_value: Any, configuration: str = utils.DEFAULT_CONFIG) -> None:
        if self._use_http and self._http:
            return self._http.set_variable(filepath, var_name, var_value, configuration)
        file_obj, folder_obj = self._get_pdm_file_and_folder(filepath)
        if not file_obj or not folder_obj:
            raise PDMFileNotFoundError(f"File not found for set_variable operation: '{filepath}'")

        try:
            if not file_obj.IsLocked or not file_obj.LockedByUser:
                locker_name = 'Not Checked Out'
                raise PDMOperationFailedError(f"Set variable failed: File '{filepath}' must be checked out by the current user ('{self._username}') before setting variables. Current status: {locker_name}.")
            else:
                locker = IEdmUser5(file_obj.LockedByUser)
                if not locker or locker.Name != self._username:
                    locker_name = locker.Name if locker else 'Unknown User'
                    raise PDMOperationFailedError(f"Set variable failed: File '{filepath}' must be checked out by the current user ('{self._username}'). Currently locked by: '{locker_name}'.")
        except Exception as lock_check_err:
            raise PDMOperationFailedError(f"Error occurred while checking lock status for set_variable on '{filepath}': {lock_check_err}") from lock_check_err

        enum_var = None
        config_to_try = configuration
        try:
            enum_var_raw = file_obj.GetEnumeratorVariable(config_to_try)
            if not enum_var_raw and config_to_try == utils.DEFAULT_CONFIG:
                config_to_try = ""
                enum_var_raw = file_obj.GetEnumeratorVariable(config_to_try)
            if not enum_var_raw:
                raise PDMOperationFailedError(f"Cannot get variable enumerator for file '{filepath}', configuration '{configuration}' (or fallback '').")

            enum_var = IEdmEnumeratorVariable5(enum_var_raw)
            if enum_var is None:
                raise PDMCastError(f"Failed to cast variable enumerator for file '{filepath}'.")

            enum_var.SetVar(var_name, config_to_try, var_value)
            enum_var.Flush()

        except (PDMCastError, PDMOperationFailedError, AssertionError) as known_err:
            raise known_err
        except Exception as e:
            error_msg = str(e)
            if "variable was not found" in error_msg.lower() or "0x80040111" in error_msg:
                raise PDMOperationFailedError(f"Set variable failed: Variable '{var_name}' was not found on the data card for configuration '{config_to_try}' on file '{filepath}'.") from e
            elif "could not get configuration" in error_msg.lower() or "0x80040103" in error_msg:
                raise PDMOperationFailedError(f"Set variable failed: Configuration '{config_to_try}' could not be found for file '{filepath}'.") from e
            elif "access denied" in error_msg.lower() or "0x80070005" in error_msg:
                raise PDMOperationFailedError(f"Set variable failed: Access denied for file '{filepath}'. Ensure it is checked out by user '{self._username}'. Error details: {error_msg}") from e
            elif "0x80040118" in error_msg:
                raise PDMOperationFailedError(f"Set variable failed: Variable '{var_name}' is read-only in the current state or configuration '{config_to_try}' for file '{filepath}'.") from e
            else:
                raise PDMOperationFailedError(f"Set variable failed for '{var_name}' on file '{filepath}', config '{config_to_try}': Unexpected error: {error_msg}") from e

    @profile
    def _get_derived_bom_object(self, file_obj: IEdmFile17) -> Optional[IEdmBom]:
        if file_obj is None:
            raise ValueError("PDM_API_INTERNAL_ERROR: file_obj cannot be None for _get_derived_bom_object")

        try:
            derived_boms_info_array: Optional[Any] = file_obj.GetDerivedBOMs()
            log_drawing_name: str = file_obj.Name if hasattr(file_obj, 'Name') else "UnknownDrawing"

            if not derived_boms_info_array:
                return None

            bom_definitions_list = list(derived_boms_info_array)
            

            selected_bom_to_return: Optional[IEdmBom] = None

            for i, bom_info_item in enumerate(reversed(bom_definitions_list)):
                bom_id: int = -1
                bom_name_str: str = "N/A_NAME"
                original_list_index: int = len(bom_definitions_list) - 1 - i

                if hasattr(bom_info_item, 'mlBomID'):
                    bom_id = bom_info_item.mlBomID
                if hasattr(bom_info_item, 'mbsBomName'):
                    bom_name_str = bom_info_item.mbsBomName
                
                

                if bom_id <= 0:
                    continue 

                bom_object_raw: Any
                try:
                    bom_object_raw = self._vault_api.GetObject(EdmObjectType.EdmObject_BOM, bom_id)
                except Exception as e_get_obj:
                    raise PDMFileInfoError(
                        f"PDM_API_ERROR: Failed to retrieve PDM BOM object for BOM ID {bom_id} (name: '{bom_name_str}') "
                        f"from file '{log_drawing_name}': {e_get_obj}"
                    ) from e_get_obj
                
                if bom_object_raw is None:
                    continue

                current_pdm_bom_obj: Optional[IEdmBom] = None
                try:
                    casted_obj = IEdmBom(bom_object_raw)
                    if casted_obj is None: 
                        continue 
                    current_pdm_bom_obj = casted_obj
                except Exception as e_cast_bom: 
                    continue 
                
                bom_view_raw: Any = None
                try:
                    bom_view_raw = current_pdm_bom_obj.GetView(utils.LATEST_VERSION)
                except Exception as e_get_view: 
                    continue 
                if bom_view_raw is None:
                    continue
                
                bom_view_specific: Any = None
                try:
                    bom_view_specific = IEdmBomView3(bom_view_raw)
                    if bom_view_specific is None:
                        continue
                except Exception as e_cast_view:
                    continue

                row_count: int = 0
                try:
                    rows_array: Any = bom_view_specific.GetRows()
                    if rows_array:
                        materialized_rows = list(rows_array)
                        row_count = len(materialized_rows)
                        if row_count > 0:
                            selected_bom_to_return = current_pdm_bom_obj 
                            break 
                except Exception as e_get_rows: 
                    continue 
                
            if selected_bom_to_return:
                return selected_bom_to_return
            else:
                return None 
            
        except Exception as e: 
            file_id_for_error = file_obj.ID if hasattr(file_obj, 'ID') else 'N/A'
            raise PDMFileInfoError(f"General error processing derived BOMs for file ID {file_id_for_error}: {e}") from e

    @profile
    def _get_bom_view(self, bom_obj: IEdmBom, version: int = utils.LATEST_VERSION) -> Optional[Any]:
        if bom_obj is None:
            return None
        try:
            bom_view_raw = bom_obj.GetView(version)
            return bom_view_raw
        except Exception as e:
            bom_id_str = getattr(bom_obj, 'ID', 'N/A')
            raise PDMFileInfoError(f"Error getting BOM view for BOM ID {bom_id_str}, version {version}: {e}") from e

    @profile
    def _get_computed_bom_view(self, 
                                 file_obj: IEdmFile17, 
                                 bom_layout_name: str, 
                                 version: int = utils.LATEST_VERSION, # Parameter name kept as 'version' for consistency with PDM API
                                 config: str = utils.DEFAULT_CONFIG) -> Optional[Any]:
        if file_obj is None:
            return None
        try:
            bom_flags = int(EdmBomFlag.EdmBf_ShowSelected) 
            # The 'version' parameter here is now the passed-in 'version_to_fetch'
            bom_view_raw = file_obj.GetComputedBOM(bom_layout_name, version, config, bom_flags)
            return bom_view_raw
        except Exception as e:
            raise PDMFileInfoError(
                f"Error getting computed BOM using layout '{bom_layout_name}' for file ID {getattr(file_obj, 'ID', 'N/A')}, "
                f"config '{config}', version {version}: {e}"
            ) from e

    @profile
    def _get_bom_cells(self, bom_view_object: Any) -> Optional[Tuple[List[Any], List[Any]]]:
        if bom_view_object is None:
            return None
        try:
            bom_view3 = IEdmBomView3(bom_view_object)
            if bom_view3 is None:
                raise PDMCastError("Failed to cast the provided BOM view object to IEdmBomView3.")

            column_definitions_raw = bom_view3.GetColumns()
            bom_rows_raw = bom_view3.GetRows()

            if not column_definitions_raw or not bom_rows_raw:
                return None

            return list(column_definitions_raw), list(bom_rows_raw)
        except PDMCastError as e:
            raise PDMCastError(f"Casting error while getting BOM cells: {e}") from e
        except Exception as e:
            raise PDMFileInfoError(f"Error extracting columns or rows from the BOM view: {e}") from e

    @profile
    def _extract_dict_from_bom_cell(self, bom_cell_raw: Any, column_definitions: List[Any]) -> Dict[str, str]:
        cell_data = {}
        path_name = ""
        file_name = ""
        name_without_ext = ""
        item_id = ""

        if bom_cell_raw is None:
            return {}

        try:
            cell = IEdmBomCell(bom_cell_raw)
            if cell is None:
                raise PDMCastError("Failed to cast raw BOM row object to IEdmBomCell.")

            try:
                path_name = cell.GetPathName() or ""
            except Exception:
                path_name = "Error"

            file_name = os.path.basename(path_name) if path_name and path_name != "Error" else ""
            name_without_ext = os.path.splitext(file_name)[0] if file_name else ""

            try:
                item_id = str(cell.GetItemID())
            except Exception:
                item_id = ""


            for column in column_definitions:
                caption = "UnknownColumn"
                var_id = -1
                var_type_enum = None
                cell_value_str = ""

                try:
                    caption = getattr(column, 'mbsCaption', '?')
                    var_id = getattr(column, 'mlVariableID', -1)
                    var_type_enum = getattr(column, 'meType', None)
                except Exception as col_err:
                    cell_data[caption] = "ErrorReadingColumnDef"
                    continue

                try:
                    if var_id != -1 and var_type_enum is not None:
                        result_tuple_or_value = cell.GetVar(var_id, var_type_enum)
                        value_to_use = None

                        if isinstance(result_tuple_or_value, tuple):
                            if len(result_tuple_or_value) >= 2 and result_tuple_or_value[1] is not None:
                                value_to_use = result_tuple_or_value[1]
                            elif len(result_tuple_or_value) >= 1 and result_tuple_or_value[0] is not None:
                                value_to_use = result_tuple_or_value[0]
                        else:
                            value_to_use = result_tuple_or_value

                        if value_to_use is not None:
                            cell_value_str = str(value_to_use)

                    if not cell_value_str:
                        var_type_val = int(var_type_enum) if var_type_enum is not None else -999
                        if var_type_val == EdmBomColumnType.EdmBomCol_PartNumber and name_without_ext:
                            cell_value_str = name_without_ext
                        elif var_type_val == EdmBomColumnType.EdmBomCol_Name and file_name:
                            cell_value_str = file_name
                        elif var_type_val == EdmBomColumnType.EdmBomCol_Path and path_name and path_name != "Error":
                            cell_value_str = path_name
                        elif var_type_val == EdmBomColumnType.EdmBomCol_ID and item_id:
                            cell_value_str = item_id

                except Exception as getval_err:
                    cell_value_str = "ErrorGettingValue"

                cell_data[caption] = cell_value_str

            return cell_data

        except PDMCastError as e:
            return {"Error": "Cell Cast Fail"}
        except Exception as cell_err:
            return {"Error": "Cell Process Fail"}

    @profile
    def _get_version_number_from_revision_label(self, file_obj: IEdmFile17, revision_label: str) -> int:
        if not file_obj or not revision_label:
            return 0

        target_revision_upper = revision_label.strip().upper()

        try:
            ver_enum = IEdmEnumeratorVersion5(file_obj)
            if not ver_enum:
                return 0

            pos = ver_enum.GetFirstRevisionPosition()
            all_versions_for_revision = []

            while pos is not None and not pos.IsNull:
                try:
                    rev_obj_raw = ver_enum.GetNextRevision(pos)
                    if not rev_obj_raw:
                        break
                    
                    rev_obj = IEdmRevision5(rev_obj_raw)
                    if rev_obj and hasattr(rev_obj, 'Name') and hasattr(rev_obj, 'VersionNo'):
                        current_rev_name = rev_obj.Name.strip().upper()
                        if current_rev_name == target_revision_upper:
                            all_versions_for_revision.append(rev_obj.VersionNo)
                except Exception:
                    break

            if all_versions_for_revision:
                return all_versions_for_revision[-1]
            else:
                return 0

        except Exception:
            return 0
    
    @profile
    def _extract_dicts_from_bom_view(self, bom_view_object: Any) -> Iterator[Dict[str, str]]:
        if bom_view_object is None:
            return

        try:
            cell_info = self._get_bom_cells(bom_view_object)
            if cell_info is None:
                return

            column_definitions, bom_rows = cell_info
            if not column_definitions or not bom_rows:
                return

            for bom_cell_raw in bom_rows:
                cell_data = self._extract_dict_from_bom_cell(bom_cell_raw, column_definitions)
                if cell_data and any(str(value).strip() for value in cell_data.values() if value not in ["Error", "ErrorGettingValue", ""]):
                    yield cell_data

        except Exception as e:
            return


    @profile
    def get_derived_bom_data(self, filepath: str) -> Iterator[Dict[str, str]]:
        file_obj, _ = self._get_pdm_file_and_folder(filepath)
        if file_obj is None:
            raise PDMFileNotFoundError(f"File not found for get_derived_bom_data: '{filepath}'")

        try:
            bom_obj = self._get_derived_bom_object(file_obj)
            if bom_obj is None:
                return

            bom_view = self._get_bom_view(bom_obj, utils.LATEST_VERSION)
            if bom_view is None:
                return

            yield from self._extract_dicts_from_bom_view(bom_view)

        except (PDMCastError, PDMFileInfoError, PDMOperationFailedError) as e:
            raise PDMOperationFailedError(f"Failed to get or process derived BOM data for '{filepath}': {e}") from e
        except Exception as e:
            raise PDMOperationFailedError(f"Unexpected error retrieving derived BOM data for '{filepath}': {e}") from e

    @profile
    def get_computed_bom_data(self,
                              bom_layout_name: str,
                              file_obj: IEdmFile17,
                              config: str = utils.DEFAULT_CONFIG,
                              version_to_fetch: int = utils.LATEST_VERSION) -> Iterator[Dict[str, str]]:

        # Handle cases where positional arguments might be swapped by checking the type of file_obj.
        if isinstance(file_obj, str):
            filepath = bom_layout_name
            actual_bom_layout_name = file_obj
            pdm_file_obj, _ = self._get_pdm_file_and_folder(filepath)
        else:
            pdm_file_obj = file_obj
            actual_bom_layout_name = bom_layout_name

        if pdm_file_obj is None:
            raise PDMFileInfoError("A valid PDM file object or filepath must be provided to get_computed_bom_data.")

        try:
            bom_view_raw = self._get_computed_bom_view(pdm_file_obj, actual_bom_layout_name, version_to_fetch, config)
            if bom_view_raw is None:
                return iter([])

            yield from self._extract_dicts_from_bom_view(bom_view_raw)

        except (PDMCastError, PDMFileInfoError, PDMOperationFailedError) as e:
            raise PDMOperationFailedError(
                f"Failed to get or process computed BOM data for file ID {getattr(pdm_file_obj, 'ID', 'N/A')} "
                f"using layout '{actual_bom_layout_name}', version {version_to_fetch}: {e}"
            ) from e
        except Exception as e:
            raise PDMOperationFailedError(
                f"Unexpected error retrieving computed BOM data for file ID {getattr(pdm_file_obj, 'ID', 'N/A')}, version {version_to_fetch}: {e}"
            ) from e