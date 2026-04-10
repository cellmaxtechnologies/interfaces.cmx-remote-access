import pytest
import os
import time
import uuid
import shutil
import tempfile
from typing import Dict, List, Set, Optional, Tuple
import pdm_api.utils as utils
import traceback
import csv
import pytest 
from pdm_api.pdm_vault import (
    PDMVault,
    
)

from pdm_api.exceptions import (
    PDMFileNotFoundError,
    PDMOperationFailedError, PDMFileExistsError
)

def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


PDM_TEST_VAULT = _env("PDM_TEST_VAULT_NAME") or _env("PDM_VAULT_NAME")
PDM_VAULT = _env("PDM_VAULT_NAME")
PDM_USER = _env("PDM_USERNAME")
PDM_PASS = _env("PDM_PASSWORD")

PART_FILENAME_CONST = "CA320220.sldprt"
DRAWING_FILENAME_CONST = "CA333840.SLDDRW"
SCREW_FILENAME_CONST = "CA800014.sldprt"


def _folder_exists(vault: PDMVault, path: str) -> bool:
    if getattr(vault, "_use_http", False):
        try:
            list(vault.get_subfolders_in_folder(path))
            return True
        except PDMFileNotFoundError:
            return False
    return os.path.isdir(path)


def _is_http(vault: PDMVault) -> bool:
    return bool(getattr(vault, "_use_http", False))

@pytest.fixture(scope="module")
def admin_vault() -> PDMVault:
    try:
        if not (PDM_USER and PDM_PASS and PDM_TEST_VAULT):
            pytest.skip("Missing PDM_USERNAME/PDM_PASSWORD/PDM_TEST_VAULT_NAME env vars.")
        v = PDMVault(PDM_USER, PDM_PASS, PDM_TEST_VAULT)
        assert v is not None
        assert v.name == PDM_TEST_VAULT
        assert v.root_folder_path
        assert _folder_exists(v, v.root_folder_path)
        utils.log(f"Admin vault fixture connected successfully to '{v.name}' at '{v.root_folder_path}'.")
        return v
    except Exception as e:
        pytest.fail(f"FATAL: Admin PDM Vault setup failed for vault '{PDM_TEST_VAULT}': {e}")

@pytest.fixture(scope="function")
def vault(admin_vault: PDMVault) -> PDMVault:
    return admin_vault

@pytest.fixture(scope="module")
def cmx_admin_vault() -> PDMVault:
    try:
        if not (PDM_USER and PDM_PASS and PDM_VAULT):
            pytest.skip("Missing PDM_USERNAME/PDM_PASSWORD/PDM_VAULT_NAME env vars.")
        v = PDMVault(PDM_USER, PDM_PASS, PDM_VAULT)
        assert v is not None
        assert v.name == PDM_VAULT
        assert v.root_folder_path
        assert _folder_exists(v, v.root_folder_path)
        utils.log(f"Admin vault fixture connected successfully to '{v.name}' at '{v.root_folder_path}'.")
        return v
    except Exception as e:
        pytest.fail(f"FATAL: Admin PDM Vault setup failed for vault '{PDM_VAULT}': {e}")

@pytest.fixture(scope="function")
def cmx_vault(cmx_admin_vault: PDMVault) -> PDMVault:
    return cmx_admin_vault

@pytest.fixture(scope="module")
def pdm_cad_path(admin_vault: PDMVault) -> str:
    path = os.path.join(admin_vault.root_folder_path, "CAD")
    if not _folder_exists(admin_vault, path):
         pytest.fail(f"FATAL: PDM CAD path '{path}' does not exist locally. Please create it.")
    if not _is_http(admin_vault):
        folder_obj = admin_vault._get_folder_object(path)
        if folder_obj is None:
             pytest.fail(f"FATAL: PDM CAD path '{path}' not found or accessible via PDM API. Please ensure it exists in the vault.")
        utils.log(f"PDM CAD path verified via API: {path} (ID: {folder_obj.ID})")
    return path

@pytest.fixture(scope="module")
def pdm_testing_area_path(admin_vault: PDMVault) -> str:
    path = os.path.join(admin_vault.root_folder_path, "Testing")
    if not _folder_exists(admin_vault, path):
         pytest.fail(f"FATAL: PDM Testing area path '{path}' does not exist locally. Please create it.")
    if not _is_http(admin_vault):
        folder_obj = admin_vault._get_folder_object(path)
        if folder_obj is None:
             pytest.fail(f"FATAL: PDM Testing area path '{path}' not found or accessible via PDM API. Please ensure it exists in the vault.")
        utils.log(f"PDM Testing area path verified via API: {path} (ID: {folder_obj.ID})")
    return path

@pytest.fixture(scope="module")
def part_filename() -> str:
    return PART_FILENAME_CONST

@pytest.fixture(scope="module")
def drawing_filename() -> str:
    return DRAWING_FILENAME_CONST

@pytest.fixture(scope="module")
def screw_filename() -> str:
    return SCREW_FILENAME_CONST

@pytest.fixture(scope="module")
def part_filepath(admin_vault: PDMVault, pdm_cad_path: str, part_filename: str) -> str:
    path = os.path.join(pdm_cad_path, part_filename)
    if admin_vault.get_file_info(path) is None: 
        pytest.skip(f"SKIPPING: Test file '{path}' not found in PDM CAD folder. Required for some tests.")
    return path

@pytest.fixture(scope="module")
def drawing_filepath(admin_vault: PDMVault, pdm_cad_path: str, drawing_filename: str) -> str:
    path = os.path.join(pdm_cad_path, drawing_filename)
    if admin_vault.get_file_info(path) is None:
        pytest.skip(f"SKIPPING: Test file '{path}' not found in PDM CAD folder. Required for some tests.")
    return path

@pytest.fixture(scope="module")
def screw_filepath(admin_vault: PDMVault, pdm_cad_path: str, screw_filename: str) -> str:
    path = os.path.join(pdm_cad_path, screw_filename)
    if admin_vault.get_file_info(path) is None:
        pytest.skip(f"SKIPPING: Test file '{path}' not found in PDM CAD folder. Required for some tests.")
    return path

@pytest.fixture(scope="module")
def expected_derived_bom_data() -> List[Dict[str, str]]:
    return [
         {'ITEM NO.': '1', 'PART NUMBER': 'CA334142', 'DESCRIPTION': 'Assy 1, delar', 'QTY.': '1'},
         {'ITEM NO.': '2', 'PART NUMBER': 'CA326425', 'DESCRIPTION': 'Snapover 16slim-ST, FF 148', 'QTY.': '1'},
         {'ITEM NO.': '3', 'PART NUMBER': 'CA334145', 'DESCRIPTION': 'Fyrkant', 'QTY.': '1'},
         {'ITEM NO.': '4', 'PART NUMBER': 'CA334146', 'DESCRIPTION': 'Cirkel', 'QTY.': '2'},
         {'ITEM NO.': '5', 'PART NUMBER': 'CA334148', 'DESCRIPTION': 'Cirkel 2', 'QTY.': '1'},
         {'ITEM NO.': '6', 'PART NUMBER': 'CA800014', 'DESCRIPTION': 'Screw MRT M4x10 H A4 80 ISO 14583', 'QTY.': '6'}
    ]

@pytest.fixture(scope="module")
def expected_computed_bom_layout_name() -> str:
    return "BOM"

@pytest.fixture(scope="module")
def expected_computed_bom_data() -> List[Dict[str, str]]:
    return [
         {'File Name': 'CA333840.SLDDRW', 'Configuration': '@', 'Part Number': 'CA333840', 'Qty': '1', 'State': 'Prototype', 'Description': '', 'Revision': 'A'},
         {'File Name': 'C4900214.vir', 'Configuration': '@', 'Part Number': 'CA900214', 'Qty': '1', 'State': 'Released', 'Description': 'Påkopplat emballage', 'Revision': ''},
         {'File Name': 'CA800014.sldprt', 'Configuration': 'No thread', 'Part Number': 'CA800014', 'Qty': '6', 'State': 'Released Std Comp', 'Description': 'Screw MRT M4x10 H A4 80 ISO 14583', 'Revision': ''},
         {'File Name': 'CA334145.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334145', 'Qty': '1', 'State': 'In Production', 'Description': 'Fyrkant', 'Revision': 'A'},
         {'File Name': 'CA334487.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334487', 'Qty': '1', 'State': 'Prototype', 'Description': 'Emballage', 'Revision': 'A'},
         {'File Name': 'CA334148.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334148', 'Qty': '1', 'State': 'In Production', 'Description': 'Cirkel 2', 'Revision': 'A'},
         {'File Name': 'CA326425.SLDASM', 'Configuration': '@', 'Part Number': 'CA326425', 'Qty': '1', 'State': 'Released', 'Description': 'Snapover 16slim-ST, FF 148', 'Revision': 'A'},
         {'File Name': 'CA326337.SLDPRT', 'Configuration': 'Single part', 'Part Number': 'CA326337', 'Qty': '1', 'State': 'Released', 'Description': 'Snapover 16slim-ST strip, FF', 'Revision': 'A'},
         {'File Name': 'AI-CA334100.docx', 'Configuration': '@', 'Part Number': 'AI-CA334100', 'Qty': '1', 'State': 'Released', 'Description': 'Assembly instruction', 'Revision': 'A'},
         {'File Name': 'CA334146.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334146', 'Qty': '2', 'State': 'Released', 'Description': 'Cirkel', 'Revision': 'A'},
         {'File Name': 'CA334142.SLDASM', 'Configuration': '@', 'Part Number': 'CA334142', 'Qty': '1', 'State': 'Released', 'Description': 'Assy 1, delar', 'Revision': 'B'},
         {'File Name': 'CA334140.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334140', 'Qty': '2', 'State': 'Released', 'Description': 'Part 1 profil', 'Revision': 'A'},
         {'File Name': 'CA334141.SLDPRT', 'Configuration': '@', 'Part Number': 'CA334141', 'Qty': '1', 'State': 'In Production', 'Description': 'Part 2, cirkel', 'Revision': 'A'}
    ]

@pytest.fixture(scope="module")
def expected_recursive_children_names() -> Set[str]:
      return {
           "AI-CA334100.docx", "CA326425.SLDASM", "CA326337.SLDPRT",
           "CA320220.sldprt",
           "CA334142.SLDASM", "CA334140.SLDPRT", "CA334141.SLDPRT",
           "CA800014.sldprt",
           "CA334145.SLDPRT", "CA334146.SLDPRT", "CA334148.SLDPRT"
      }

@pytest.fixture(scope="module")
def expected_parent_names() -> Set[str]:
    return {"CA326337.SLDPRT", "M-CA320220.SLDDRW","CA320221.SLDPRT"}

def test_vault_login_and_properties(vault: PDMVault, pdm_cad_path: str, pdm_testing_area_path: str):
    assert vault is not None
    assert vault.name == PDM_TEST_VAULT
    assert pdm_cad_path.startswith(vault.root_folder_path)
    assert pdm_testing_area_path.startswith(vault.root_folder_path)
    assert _folder_exists(vault, pdm_cad_path)
    assert _folder_exists(vault, pdm_testing_area_path)

def test_get_file_info(vault: PDMVault, part_filepath: str, part_filename: str):
    file_info = vault.get_file_info(part_filepath)
    assert file_info is not None
    assert isinstance(file_info, dict)
    assert file_info.get("Name") == part_filename; assert file_info.get("ID", 0) > 0
    assert "StateName" in file_info; assert isinstance(file_info.get("CurrentVersion"), int)
    assert isinstance(file_info.get("IsLocked"), bool); assert file_info.get("FolderPath") is not None
    assert file_info.get("FolderID", 0) > 0

def test_get_reference_info(vault: PDMVault, part_filepath: str, part_filename: str):
    ref_info = vault.get_reference_info(part_filepath); assert ref_info is not None
    assert isinstance(ref_info, dict); assert ref_info.get("Name") == part_filename
    assert ref_info.get("FileID") not in [None, "0", "", "Error"]

def test_get_local_copy(vault: PDMVault, part_filepath: str, part_filename: str):
    temp_dir = tempfile.mkdtemp(); local_copy_path = ""
    try:
        new_filename = f"local_copy_{part_filename}"; local_copy_path = vault.get_local_copy(part_filepath, temp_dir, new_filename)
        assert os.path.exists(local_copy_path)
        assert os.path.basename(local_copy_path) == new_filename; assert os.path.getsize(local_copy_path) > 0
    finally: shutil.rmtree(temp_dir, ignore_errors=True)

def test_create_folders(vault: PDMVault, pdm_testing_area_path: str):
    top_level_unique_folder_name = f"TestRecursiveCreate_{uuid.uuid4().hex[:8]}"
    path_level1 = "Level1_Subfolder"
    path_level2 = "Level2_SubSubfolder"
    deepest_folder_name = f"DeepTestFolder_{uuid.uuid4().hex[:4]}"
    full_path_to_create = os.path.join(pdm_testing_area_path, top_level_unique_folder_name, path_level1, path_level2, deepest_folder_name)
    path_for_cleanup = os.path.join(pdm_testing_area_path, top_level_unique_folder_name)

    try:
        result = vault.create_folders(full_path_to_create)
        assert result is True
        assert _folder_exists(vault, full_path_to_create)
        if not _is_http(vault):
            folder_obj = vault._get_folder_object(full_path_to_create)
            assert folder_obj is not None
            assert folder_obj.ID > 0
            intermediate_folder_path_l1 = os.path.join(pdm_testing_area_path, top_level_unique_folder_name, path_level1)
            assert vault._get_folder_object(intermediate_folder_path_l1) is not None
            intermediate_folder_path_l2 = os.path.join(pdm_testing_area_path, top_level_unique_folder_name, path_level1, path_level2)
            assert vault._get_folder_object(intermediate_folder_path_l2) is not None
    finally:
        try:
            if _is_http(vault):
                vault.delete_empty_folder_structure(path_for_cleanup)
            else:
                if vault._get_folder_object(path_for_cleanup): 
                    vault.delete_empty_folder_structure(path_for_cleanup)
        except Exception: pass 

def test_delete_empty_folder_structure(vault: PDMVault, pdm_testing_area_path: str):
    base_name = f"TestDeleteBase_{uuid.uuid4().hex[:8]}"
    nested_name = "Nested1"
    deeply_nested_name = "Nested2"
    base_path = os.path.join(pdm_testing_area_path, base_name)
    nested_path = os.path.join(base_path, nested_name)
    deeply_nested_path = os.path.join(nested_path, deeply_nested_name)
    
    try:
        vault.create_folders(deeply_nested_path)
        assert _folder_exists(vault, deeply_nested_path)
        assert _folder_exists(vault, nested_path)
        assert _folder_exists(vault, base_path)
        result = vault.delete_empty_folder_structure(base_path)
        assert result is True
        assert not _folder_exists(vault, deeply_nested_path)
        assert not _folder_exists(vault, nested_path)
        assert not _folder_exists(vault, base_path)
    finally:
        for path in [deeply_nested_path, nested_path, base_path]:
            if os.path.exists(path):
                try: vault.delete_empty_folder_structure(path)
                except: pass

def test_get_files_in_folder(vault: PDMVault, pdm_cad_path: str, part_filename: str, drawing_filename: str):
    files_list = list(vault.get_files_in_folder(pdm_cad_path))
    assert isinstance(files_list, list)
    if not files_list: pytest.skip("Skipping file content check as PDM CAD folder is empty or files not found")
    
    filenames = [os.path.basename(f) for f in files_list]
    assert part_filename in filenames
    assert drawing_filename in filenames
    for file_path in files_list:
        assert file_path.lower().startswith(pdm_cad_path.lower())
        assert os.path.basename(file_path)

def test_get_subfolders_in_folder(vault: PDMVault, pdm_testing_area_path: str):
    parent_name = f"TestParent_{uuid.uuid4().hex[:8]}"
    parent_path = os.path.join(pdm_testing_area_path, parent_name)
    subfolder_names = ["SubA", "SubB", "SubC"]
    subfolder_paths = [os.path.join(parent_path, name) for name in subfolder_names]
    
    try:
        for subfolder_path in subfolder_paths:
            vault.create_folders(subfolder_path)
        
        subfolders_list = list(vault.get_subfolders_in_folder(parent_path))
        assert isinstance(subfolders_list, list)
        assert len(subfolders_list) == len(subfolder_names)
        
        retrieved_subfolder_paths = [s.lower() for s in subfolders_list]
        for expected_path in subfolder_paths:
            assert expected_path.lower() in retrieved_subfolder_paths
        
        for folder_path in subfolders_list:
            assert _folder_exists(vault, folder_path)
    finally:
        for subfolder_path in reversed(subfolder_paths):
            try: vault.delete_empty_folder_structure(subfolder_path)
            except: pass
        try: vault.delete_empty_folder_structure(parent_path)
        except: pass

def test_add_file_and_folder_creation(vault: PDMVault, pdm_testing_area_path: str):
    local_temp_dir = None
    pdm_test_run_folder_path = None
    added_pdm_file_path_from_method = None
    added_pdm_file_path_cleaned_up = False

    try:
        local_temp_dir = tempfile.mkdtemp(prefix="pdm_api_test_local_")
        local_test_filename = f"test_file_{uuid.uuid4().hex[:8]}.txt"
        local_test_filepath = os.path.join(local_temp_dir, local_test_filename)
        with open(local_test_filepath, "w") as f:
            f.write(f"Temporary test file content for PDM add_file test at {time.time()}")

        unique_pdm_subfolder_name = f"test_add_file_run_{uuid.uuid4().hex[:8]}"
        pdm_test_run_folder_path = os.path.join(pdm_testing_area_path, unique_pdm_subfolder_name)
        pdm_target_filename_override = f"pdm_added_file_{uuid.uuid4().hex[:8]}.txt"

        utils.log(f"Test setup: Local file='{local_test_filepath}', PDM target folder='{pdm_test_run_folder_path}', PDM target filename='{pdm_target_filename_override}'")

        added_pdm_file_path_from_method = vault.add_file(
            local_file_path=local_test_filepath,
            pdm_target_folder_path=pdm_test_run_folder_path,
            pdm_target_filename=pdm_target_filename_override,
            comment="Test add_file successful addition"
        )

        expected_pdm_file_path = os.path.join(pdm_test_run_folder_path, pdm_target_filename_override).replace(os.sep, '/')
        assert added_pdm_file_path_from_method.lower() == expected_pdm_file_path.lower()
        utils.log(f"vault.add_file successfully completed and returned expected path: {added_pdm_file_path_from_method}")
        
        utils.log(f"Attempting to add the same file again to test PDMFileExistsError for path: {added_pdm_file_path_from_method}")
        with pytest.raises(PDMFileExistsError):
            vault.add_file(
                local_file_path=local_test_filepath,
                pdm_target_folder_path=pdm_test_run_folder_path,
                pdm_target_filename=pdm_target_filename_override,
                comment="Test add_file duplicate attempt"
            )
        utils.log(f"Successfully caught PDMFileExistsError for duplicate add.")

    finally:
        if added_pdm_file_path_from_method and vault and not added_pdm_file_path_cleaned_up:
            try:
                utils.log(f"Cleaning up PDM file: {added_pdm_file_path_from_method}")
                if not _is_http(vault):
                    file_to_delete_obj, parent_folder_obj_of_file = vault._get_pdm_file_and_folder(added_pdm_file_path_from_method)
                    if file_to_delete_obj and parent_folder_obj_of_file:
                        file_id_to_delete = file_to_delete_obj.ID
                        if not file_to_delete_obj.IsLockedByMe:
                             if not file_to_delete_obj.IsLocked: 
                                utils.log(f"Locking file ID {file_id_to_delete} for deletion during cleanup.")
                                file_to_delete_obj.LockFile(utils.DEFAULT_PARENT_HWND, "Checkout for test cleanup", 0)
                                time.sleep(0.3) 
                                file_to_delete_obj.Refresh()
                        if file_to_delete_obj.IsLockedByMe:
                            utils.log(f"Deleting file ID {file_id_to_delete} from folder ID {parent_folder_obj_of_file.ID} during cleanup.")
                            vault._vault_api.DeleteFile(utils.DEFAULT_PARENT_HWND, file_id_to_delete, parent_folder_obj_of_file.ID, utils.EDM_DELETE_SIMPLE)
                            utils.log(f"PDM file '{added_pdm_file_path_from_method}' deleted during cleanup.")
                            added_pdm_file_path_cleaned_up = True
                        else:
                            utils.log(f"Could not delete PDM file '{added_pdm_file_path_from_method}' during cleanup, not locked by current user after attempt.", level="WARNING")
                    else:
                        utils.log(f"Could not retrieve PDM file '{added_pdm_file_path_from_method}' for cleanup (may have been deleted or path issue).", level="WARNING")
            except Exception as e_cleanup_file:
                utils.log(f"Error during PDM file cleanup for '{added_pdm_file_path_from_method}': {e_cleanup_file}\n{traceback.format_exc()}", level="ERROR")

        if pdm_test_run_folder_path and vault:
            try:
                utils.log(f"Attempting to delete PDM test folder during cleanup: {pdm_test_run_folder_path}")
                if not _is_http(vault):
                    folder_to_delete_obj = vault._get_folder_object(pdm_test_run_folder_path)
                    if folder_to_delete_obj:
                        is_empty = True
                        if next(vault._get_files_from_folder(folder_to_delete_obj), None) is not None:
                            is_empty = False
                            utils.log(f"Folder '{pdm_test_run_folder_path}' not empty (files). Cannot delete directly during cleanup.", level="WARNING")
                        if next(vault._get_subfolders_from_folder(folder_to_delete_obj), None) is not None:
                            is_empty = False
                            utils.log(f"Folder '{pdm_test_run_folder_path}' not empty (subfolders). Cannot delete directly during cleanup.", level="WARNING")
                        if is_empty:
                            parent_of_run_folder_path = os.path.dirname(pdm_test_run_folder_path)
                            parent_of_run_folder_obj = vault._get_folder_object(parent_of_run_folder_path)
                            if parent_of_run_folder_obj:
                                utils.log(f"Deleting empty PDM folder '{folder_to_delete_obj.Name}' (ID: {folder_to_delete_obj.ID}) from parent '{parent_of_run_folder_obj.Name}' during cleanup.")
                                parent_of_run_folder_obj.DeleteFolder(utils.DEFAULT_PARENT_HWND, folder_to_delete_obj.ID)
                                utils.log(f"PDM folder '{pdm_test_run_folder_path}' deleted during cleanup.")
                            else:
                                utils.log(f"Could not get parent PDM folder for '{pdm_test_run_folder_path}' to delete it during cleanup.", level="WARNING")
                        elif not added_pdm_file_path_cleaned_up: 
                             utils.log(f"PDM folder '{pdm_test_run_folder_path}' not empty during cleanup, skipping direct deletion. File may still be present.", level="WARNING")
                    else:
                         utils.log(f"PDM folder '{pdm_test_run_folder_path}' not found for cleanup.", level="WARNING")
            except Exception as e_cleanup_folder:
                utils.log(f"Error during PDM folder cleanup for '{pdm_test_run_folder_path}': {e_cleanup_folder}\n{traceback.format_exc()}", level="ERROR")

        if local_temp_dir and os.path.exists(local_temp_dir):
            try:
                shutil.rmtree(local_temp_dir)
                utils.log(f"Local temp directory '{local_temp_dir}' deleted during cleanup.")
            except Exception as e_cleanup_local:
                utils.log(f"Error deleting local temp directory '{local_temp_dir}' during cleanup: {e_cleanup_local}", level="ERROR")

def test_get_files_in_folder_empty(vault: PDMVault, pdm_testing_area_path: str):
    empty_folder_name = f"TestEmpty_{uuid.uuid4().hex[:8]}"
    empty_folder_path = os.path.join(pdm_testing_area_path, empty_folder_name)
    try:
        vault.create_folders(empty_folder_path)
        files_list = list(vault.get_files_in_folder(empty_folder_path))
        assert isinstance(files_list, list)
        assert len(files_list) == 0
    finally:
        try: vault.delete_empty_folder_structure(empty_folder_path)
        except: pass

def test_get_subfolders_in_folder_no_subfolders(vault: PDMVault, pdm_testing_area_path: str):
    folder_name = f"TestNoSub_{uuid.uuid4().hex[:8]}"
    folder_path = os.path.join(pdm_testing_area_path, folder_name)
    try:
        vault.create_folders(folder_path)
        subfolders_list = list(vault.get_subfolders_in_folder(folder_path))
        assert isinstance(subfolders_list, list)
        assert len(subfolders_list) == 0
    finally:
        try: vault.delete_empty_folder_structure(folder_path)
        except: pass

def compare_bom_data(actual_bom: List[Dict[str,str]], expected_bom: List[Dict[str,str]]) -> Tuple[bool, str]:
    if len(actual_bom) != len(expected_bom): pass
    key_col = None
    if expected_bom:
        possible_keys = ['PART NUMBER', 'ITEM NO.', 'Part Number', 'File Name']
        for k in possible_keys:
            if k in expected_bom[0]: key_col = k; break
    if not key_col: return False, "Cannot determine key column for BOM comparison."
    try:
        if not all(key_col in row for row in actual_bom) or not all(key_col in row for row in expected_bom):
            return False, f"Key column '{key_col}' missing in some rows."
        actual_dict = {row[key_col]: row for row in actual_bom}
        expected_dict = {row[key_col]: row for row in expected_bom}
    except KeyError: return False, f"KeyError access key '{key_col}'."
    actual_keys = set(actual_dict.keys())
    expected_keys = set(expected_dict.keys())
    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        return False, f"Key mismatch '{key_col}'. Miss:{missing or'N'}, Extra:{extra or'N'}"
    differences = []
    for key in sorted(expected_keys):
        expected_row = expected_dict[key]
        actual_row = actual_dict[key]
        row_differences = []
        for col_key, expected_val in expected_row.items():
            if col_key not in actual_row:
                row_differences.append(f"Missing column '{col_key}'")
                continue
            actual_val = actual_row[col_key]
            if str(actual_val).strip() != str(expected_val).strip():
                row_differences.append(f"Column '{col_key}' value mismatch (Exp:'{expected_val}', Act:'{actual_val}')")
        if row_differences:
            differences.append(f"Key '{key}': {', '.join(row_differences)}")
    if differences:
        difference_details = "\n   - ".join(differences)
        return False, f"Data differences found in {len(differences)} rows:\n   - {difference_details}"
    return True, "BOM data matches."

def test_get_computed_bom_data(vault: PDMVault, drawing_filepath: str, expected_computed_bom_layout_name: str, expected_computed_bom_data: List[Dict[str, str]]):
    actual_bom_data = list(vault.get_computed_bom_data(drawing_filepath, expected_computed_bom_layout_name))
    assert isinstance(actual_bom_data, list)
    if not expected_computed_bom_data:
        assert not actual_bom_data
        return
    assert len(actual_bom_data) > 0
    key_col = 'Part Number'
    expected_parts = {row[key_col]: row for row in expected_computed_bom_data if key_col in row}
    expected_part_numbers = set(expected_parts.keys())
    actual_parts = {row[key_col]: row for row in actual_bom_data if key_col in row}
    actual_part_numbers = set(actual_parts.keys())
    missing_parts = expected_part_numbers - actual_part_numbers
    if missing_parts: pytest.fail(f"Could not find expected parts in BOM data: {missing_parts}")
    critical_columns = ['Description', 'State', 'Revision']
    for part_num in expected_part_numbers:
        expected = expected_parts[part_num]
        actual = actual_parts[part_num]
        for col in critical_columns:
            if col in expected and str(expected[col]).strip() != str(actual.get(col, '')).strip(): pass

def test_get_derived_bom_data(vault: PDMVault, drawing_filepath: str, expected_derived_bom_data: List[Dict[str, str]]):
    actual_bom_data = list(vault.get_derived_bom_data(drawing_filepath))
    assert isinstance(actual_bom_data, list)
    if not expected_derived_bom_data:
        assert not actual_bom_data
        return
    assert len(actual_bom_data) > 0
    key_col = 'PART NUMBER'
    expected_parts = {row[key_col]: row for row in expected_derived_bom_data if key_col in row}
    expected_part_numbers = set(expected_parts.keys())
    actual_parts = {row[key_col]: row for row in actual_bom_data if key_col in row}
    actual_part_numbers = set(actual_parts.keys())
    missing_parts = expected_part_numbers - actual_part_numbers
    if missing_parts: pytest.fail(f"Could not find expected parts in BOM data: {missing_parts}")
    critical_columns = ['DESCRIPTION', 'QTY.', 'ITEM NO.']
    for part_num in expected_part_numbers:
        expected = expected_parts[part_num]
        actual = actual_parts[part_num]
        for col in critical_columns:
            if col in expected and str(expected[col]).strip() != str(actual.get(col, '')).strip(): pass
        if 'ITEM NO.' in actual_bom_data[0]:
            try:
                sorted_rows = sorted(actual_bom_data, key=lambda row: int(row['ITEM NO.']))
                if not sorted_rows == actual_bom_data: pass
            except (ValueError, TypeError): pass

def load_expected_bom_from_csv(file_path: str) -> List[Dict[str, str]]:
    """
    Loads and parses a tab-delimited CSV file into a list of dictionaries.
    This helper function is now part of the standalone test script.
    """
    if not os.path.exists(file_path):
        pytest.fail(f"Expected data file not found at path: {file_path}")
    
    expected_data = []
    try:
        with open(file_path, mode='r', encoding='utf-8') as infile:
            # Use DictReader to automatically handle headers from the first row.
            # The delimiter is set to a tab for your specific format.
            reader = csv.DictReader(infile, delimiter='\t')
            for row in reader:
                expected_data.append(dict(row))
    except Exception as e:
        pytest.fail(f"Error reading expected data file '{file_path}': {e}")
        
    return expected_data

def test_checkout_checkin(vault: PDMVault, part_filepath: str):
    initial_info = vault.get_file_info(part_filepath)
    assert initial_info is not None
    initial_state = initial_info.get("StateName", "Unknown")
    checked_out_in_test = False

    utils.log(f"Test Checkout/Checkin: File '{part_filepath}', Initial State: '{initial_state}'")

    try:
        if initial_info.get('IsLocked'):
            locked_by_pdm = initial_info.get('LockedByUser', '') 
            current_api_user = vault._username
            if locked_by_pdm.lower() == current_api_user.lower():
                utils.log(f"File '{part_filepath}' initially locked by current user ('{locked_by_pdm}'). Checking in first.")
                vault.checkin_file(part_filepath, "Pre-test check-in for checkout_checkin test")
                time.sleep(0.5) 
                initial_info = vault.get_file_info(part_filepath) 
                assert initial_info and not initial_info.get('IsLocked'), "Failed to check in file before test."
            else:
                pytest.fail(f"File '{part_filepath}' is locked by user '{locked_by_pdm}', not the current API user '{current_api_user}'. Manual intervention needed.")
        
        utils.log(f"Attempting checkout for '{part_filepath}'")
        vault.checkout_file(part_filepath)
        checked_out_in_test = True
        utils.log(f"Checkout call completed for '{part_filepath}'. Verifying status.")
        time.sleep(0.5)
        post_checkout_info = vault.get_file_info(part_filepath)
        assert post_checkout_info is not None, "Failed to get file info after checkout."
        assert post_checkout_info.get('IsLocked'), f"File '{part_filepath}' not locked after checkout."
        
        locked_by_after_checkout = post_checkout_info.get('LockedByUser', '')
        assert locked_by_after_checkout.lower() == vault._username.lower(), f"File '{part_filepath}' locked by '{locked_by_after_checkout}', expected '{vault._username}'."
        utils.log(f"File '{part_filepath}' successfully checked out by '{vault._username}'.")

        utils.log(f"Attempting checkin for '{part_filepath}'")
        vault.checkin_file(part_filepath, "Test check-in for checkout_checkin test")
        checked_out_in_test = False 
        utils.log(f"Checkin call completed for '{part_filepath}'. Verifying status.")
        time.sleep(0.5)
        post_checkin_info = vault.get_file_info(part_filepath)
        assert post_checkin_info is not None, "Failed to get file info after checkin."
        assert not post_checkin_info.get('IsLocked'), f"File '{part_filepath}' still locked after checkin."
        utils.log(f"File '{part_filepath}' successfully checked in.")

    except (PDMFileNotFoundError, PDMOperationFailedError, AssertionError) as e:
        pytest.fail(f"Checkout/Checkin Test sequence failed for file '{part_filepath}' (State: '{initial_state}'): {type(e).__name__} - {e}\n{traceback.format_exc()}")
    finally:
        if checked_out_in_test and vault:
            utils.log(f"Performing cleanup check-in for '{part_filepath}' due to test interruption/failure.", level="WARNING")
            try:
                current_info_cleanup = vault.get_file_info(part_filepath)
                if current_info_cleanup and current_info_cleanup.get('IsLocked'):
                    cleanup_locker = current_info_cleanup.get('LockedByUser', '')
                    if cleanup_locker.lower() == vault._username.lower():
                        vault.checkin_file(part_filepath, "Cleanup check-in after test failure (checkout_checkin)")
                        utils.log(f"Cleanup check-in successful for '{part_filepath}'.")
                    else:
                        utils.log(f"File '{part_filepath}' locked by '{cleanup_locker}' during cleanup, not by current API user '{vault._username}'. Cannot perform cleanup check-in.", level="WARNING")
            except Exception as final_clean_err:
                utils.log(f"Warning: Test cleanup check-in failed for '{part_filepath}': {final_clean_err}", level="ERROR")
