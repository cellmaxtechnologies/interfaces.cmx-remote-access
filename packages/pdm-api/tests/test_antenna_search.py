import pytest
import os
import time
from typing import Optional, Dict

import pdm_api.utils as utils
from pdm_api.pdm_vault import PDMVault
from pdm_api.exceptions import PDMConnectionError, PDMError


PDM_CELLMAX_VAULT = os.environ.get("PDM_VAULT_NAME", "").strip()
PDM_SHARED_USER = os.environ.get("PDM_USERNAME", "").strip()
PDM_SHARED_PASS = os.environ.get("PDM_PASSWORD", "").strip()
_vault_root_env = os.environ.get("PDM_VAULT_ROOT", "").strip().rstrip("\\/")
if not _vault_root_env and PDM_CELLMAX_VAULT:
    _vault_root_env = f"C:\\{PDM_CELLMAX_VAULT}"
SEARCH_DIRECTORY_CELLMAX = os.path.join(_vault_root_env, "CAD") if _vault_root_env else ""
SEARCH_PATTERN_CELLMAX_EXACT = "CA120925.sldasm"

@pytest.fixture(scope="module")
def admin_vault_cellmax() -> Optional[PDMVault]:
    target_vault_name = PDM_CELLMAX_VAULT
    username_val = PDM_SHARED_USER
    password_val = PDM_SHARED_PASS
    v = None
    try:
        if not (target_vault_name and username_val and password_val):
            pytest.skip("Missing PDM_USERNAME/PDM_PASSWORD/PDM_VAULT_NAME env vars.")
        v = PDMVault(username=username_val, password=password_val, vault_name=target_vault_name)
        assert v is not None, "Real PDMVault object is None after initialization."
        assert hasattr(v, 'name'), "Vault object does not have 'name' attribute."
        assert v.name == target_vault_name, \
            f"Logged in vault name mismatch. Expected '{target_vault_name}', Got '{v.name}'."
        assert hasattr(v, 'root_folder_path'), "Vault object does not have 'root_folder_path' attribute."
        root_path = v.root_folder_path
        assert root_path, "Vault root folder path is empty."
        return v
    except (PDMConnectionError, PDMError) as pdm_err:
        pytest.fail(f"FATAL (PDM Connection/Error): PDM Vault connection/setup failed for vault '{target_vault_name}' using user '{username_val}': {pdm_err}", pytrace=False)
    except ImportError as imp_err:
         pytest.fail(f"FATAL (Import Error): Required PDM library not found or failed to load: {imp_err}", pytrace=False)
    except AssertionError as assert_err:
         pytest.fail(f"FATAL (Assertion Error): PDM Vault object validation failed: {assert_err}", pytrace=False)
    except TypeError as type_err:
        pytest.fail(f"FATAL (TypeError): Mismatch calling PDMVault constructor - Check arguments. Error: {type_err}", pytrace=False)
    except Exception as e:
        pytest.fail(f"FATAL (Unexpected Error): PDM Vault setup failed unexpectedly for vault '{target_vault_name}' using user '{username_val}': {e}", pytrace=False)
    return None

@pytest.fixture(scope="function")
def vault_for_cellmax_test(admin_vault_cellmax: Optional[PDMVault]) -> PDMVault:
    if admin_vault_cellmax is None:
        pytest.fail("Admin vault fixture for _Cellmax resolved to None unexpectedly at function scope.", pytrace=False)
    return admin_vault_cellmax


RELEASED_STATE_ID = 10

@pytest.mark.parametrize(
    "test_id, filename_pattern, variable_conditions, search_directory, recursive, assertion_type, expected_count", 
    [
        
        pytest.param(
            "wildcard_name_sldasm",
            "CA120*.sldasm|CA220*.sldasm",
            None,
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "min",
            102,
            id="wildcard_name_sldasm"
        ),
         pytest.param(
            "exact_filename",
            SEARCH_PATTERN_CELLMAX_EXACT,
            None, 
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "exact",
            1,
            id="exact_filename"
        ),
        pytest.param(
            "desc_starts_with_CMA",
            "*.sldasm",
            {"Description": "CMA*"},
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "min",
            10,
            id="desc_starts_with_CMA"
        ),
        pytest.param(
            "state_released_and_name_CA120",
            "CA*20*.sldasm",
            {"Description": "CMA*", "State": "Released"}, # CORRECTED: Added State filter
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "min",
            5, 
            id="state_released_and_name_CA120"
        ),
        pytest.param(
            "name_contains_220915_sldasm",        
            "*220915*.sldasm",                      
            None,                                  
            SEARCH_DIRECTORY_CELLMAX,              
            True,                                  
            "min",                                 
            1,                                     
            id="name_contains_220915_sldasm"       
        ),
        pytest.param(
            "name_pattern_220915_A_pdf",           
            "*220915_A*pdf",                       
            None,                                  
            "C:\\_Cellmax",                      
            True,                                  
            "min",                                 
            1,                                     
            id="name_pattern_220915_A_pdf"         
        ),
        pytest.param(
            "search-based-on-date20",
            "*.pdf",
            {"Date": ">= \"2025-04-01\""}, 
            "C:\\_Cellmax\\ECN",
            True,
            "min",
            1, 
            id="search-based-on-date"
        ),
        # --- NEW TEST CASES START HERE ---
        pytest.param(
            "state_and_date_combined",
            "*.pdf",
            {"State": "ECN In Production", "Date": ">= \"2024-02-01\""},
            "C:\\_Cellmax\\ECN",
            True,
            "min",
            1,
            id="state_and_date_combined"
        ),
        pytest.param(
            "state_and_desc_combined",
            "*.sldasm",
            {"State": "Released", "Description": "CMA*"},
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "min",
            5,
            id="state_and_desc_combined"
        ),
        pytest.param(
            "app_startup_pattern",
            "CA130*.sldasm|CA12*.sldasm|CA22*.sldasm|CA318132.sldasm|CA330917.sldasm|CA327408.sldasm|CA327993.sldasm|CA332183.sldasm|CA332184.sldasm|CA331422.sldasm|CA331423.sldasm",
            None,
            SEARCH_DIRECTORY_CELLMAX,
            True,
            "min",
            1,
            id="app_startup_pattern"
        ),
    ]
)
def test_pdm_search(
    vault_for_cellmax_test: PDMVault,
    test_id: str,
    filename_pattern: Optional[str],
    variable_conditions: Optional[Dict[str, str]],
    search_directory: Optional[str],
    recursive: bool,
    assertion_type: str,
    expected_count: int
):
    vault = vault_for_cellmax_test
    log_extension = "_search_debug" # The extension for utils.log

    utils.log(f"\n--- Starting Pytest Case ID: {test_id} ---", ext=log_extension)
    utils.log(f"  Description: Search for files with pattern '{filename_pattern}'", ext=log_extension)
    utils.log(f"  Directory: '{search_directory}', Recursive: {recursive}", ext=log_extension)
    if variable_conditions:
        # This will log {'Date': '>= "2025-04-01"'} for the date test
        utils.log(f"  Variable Conditions: {variable_conditions}", ext=log_extension)
    start_time = time.time()

    # Call your PDMVault.search_files method.
    # It's assumed this method itself does not take extra logging parameters.
    search_results_iterable = vault.search_files(
        filename_pattern=filename_pattern,
        variable_conditions=variable_conditions,
        directory=search_directory,
        recursive=recursive
    )

    search_results = list(search_results_iterable)
    
    end_time = time.time()
    duration = end_time - start_time
    actual_results_count = len(search_results)

    utils.log(f"  Search for '{test_id}' completed in {duration:.2f} seconds.", ext=log_extension)
    utils.log(f"  Found {actual_results_count} items.", ext=log_extension)

    # Validate format_search_result functionality
    if actual_results_count > 0:
        utils.log(f"  Validating format_search_result functionality:", ext=log_extension)
        
        # Test format_search_result on the first few results (up to 3 for performance)
        test_count = min(3, actual_results_count)
        for i in range(test_count):
            result_dict = search_results[i]
            
            # Validate that result is a dictionary
            assert isinstance(result_dict, dict), \
                f"Test '{test_id}': Expected formatted result to be dict, got {type(result_dict)}"
            
            # Validate required keys are present
            required_keys = ["name", "path", "date", "state"]
            for key in required_keys:
                assert key in result_dict, \
                    f"Test '{test_id}': Missing required key '{key}' in formatted result"
            
            # Validate data types and non-empty values for critical fields
            file_name = result_dict.get("name")
            file_path = result_dict.get("path")
            file_date = result_dict.get("date")
            file_state = result_dict.get("state")
            
            assert isinstance(file_name, str) and file_name != "N/A", \
                f"Test '{test_id}': 'name' should be a non-N/A string, got '{file_name}'"
            
            assert isinstance(file_path, str) and file_path != "N/A", \
                f"Test '{test_id}': 'path' should be a non-N/A string, got '{file_path}'"
            
            assert isinstance(file_date, str), \
                f"Test '{test_id}': 'date' should be a string, got {type(file_date)} with value '{file_date}'"
            
            assert isinstance(file_state, str), \
                f"Test '{test_id}': 'state' should be a string, got {type(file_state)} with value '{file_state}'"
            
            # Log formatted result details
            log_message_item = f"    Result {i+1}: File='{file_name}', Path='{file_path}'"
            log_message_item += f", Date='{file_date}', State='{file_state}'"
            utils.log(log_message_item, ext=log_extension)
            
        # Additional validation for date-specific searches
        if variable_conditions and "Date" in variable_conditions:
            utils.log(f"  Validating date filtering for condition: {variable_conditions['Date']}", ext=log_extension)
            
            # Check that date values are not "N/A" for date-filtered searches
            date_na_count = sum(1 for result in search_results[:test_count] if result.get("date") == "N/A")
            if date_na_count > 0:
                utils.log(f"  Warning: {date_na_count} out of {test_count} results have date='N/A' in date-filtered search", ext=log_extension)
                
    elif actual_results_count == 0 and variable_conditions and "Date" in variable_conditions:
        # If no results specifically for a date search, add a note.
        utils.log(f"  Note: Search with date condition {variable_conditions['Date']} returned 0 items.", ext=log_extension)

    # Standard assertions for search results count
    assert isinstance(search_results, list), \
        f"Test '{test_id}': Search result should be a list, but got {type(search_results)}."

    if assertion_type == "min":
        assert actual_results_count >= expected_count, \
            f"Test '{test_id}': Expected at least {expected_count} results (found {actual_results_count}). Variable conditions: {variable_conditions}"
    elif assertion_type == "exact":
        assert actual_results_count == expected_count, \
            f"Test '{test_id}': Expected exactly {expected_count} results (found {actual_results_count}). Variable conditions: {variable_conditions}"
    else:
        utils.log(f"FATAL: Invalid assertion_type '{assertion_type}' for test '{test_id}'", ext="_error" + log_extension) # Log error before failing
        pytest.fail(f"Invalid assertion_type '{assertion_type}' specified for test '{test_id}'. Use 'min' or 'exact'.")

    utils.log(f"--- Pytest Case ID: {test_id} PASSED (Assertions met) ---", ext=log_extension)