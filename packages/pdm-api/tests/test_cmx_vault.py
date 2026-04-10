# tests/test_cmx_vault.py
import pytest
import pandas as pd
import pdm_api.utils as utils
import time
import re
import difflib
from typing import Optional
import os

from pdm_api.cmx_vault import CMXVault
from pdm_api.exceptions import PDMFileNotFoundError,PDMOperationFailedError

from typing import Dict, Any, List, Union

def csv_bom2dict_list(path:str,sep:str):
    with open(path,"r") as file:
        header,*data = file.read().split("\n")
    result = []
    for row in data:
        if not row.strip(): # Skip empty lines
            continue
        row_data = row.split(sep)
        columns = header.split(sep)
        result.append(dict(zip(columns,row_data)))
    return result

@pytest.fixture
def cmx_vault():
    username = os.environ.get("PDM_USERNAME", "").strip()
    password = os.environ.get("PDM_PASSWORD", "").strip()
    vault_name = os.environ.get("PDM_VAULT_NAME", "").strip()
    if not (username and password and vault_name):
        pytest.skip("Missing PDM_USERNAME/PDM_PASSWORD/PDM_VAULT_NAME env vars.")
    return CMXVault(username, password, vault_name)

@pytest.fixture
def expected_bom():
    return csv_bom2dict_list("tests/resources/test_bom_220915.csv","\t")

def show(bom,ext):
    for row in bom:
        for k,v in row.items():
            utils.log(f"{k} = {v}", ext = ext)
from typing import List, Dict


def write_bom_to_csv(
    bom_data: List[Dict[str, str]],
    part_number: str,
    output_filename: Optional[str] = None
) -> str:
    """
    Writes a Bill of Materials (BOM) to a tab-separated file, preserving
    all whitespace that is already present in the data values.

    Args:
        bom_data: A list of dictionaries, where each dictionary represents a BOM row.
        part_number: The main part_number for which the BOM was generated.
        output_filename: Optional. The desired filename for the output file.
                         If None, it defaults to "bom_CA{part_number}.csv".

    Returns:
        The absolute path to the generated file.
    """
    # Use the exact header list from your original code.
    header = [
        "Row ID", "Pos", "Part Number", "Rev", "Qty", "Tot",
        "Part Description", "State", "Drawing"
    ]

    # Determine the output file path.
    if output_filename is None:
        file_name = f"bom_CA{part_number}.csv"
    else:
        file_name = output_filename

    output_filepath = utils.resource_path(file_name)

    # Ensure the directory exists.
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    with open(output_filepath, 'w', encoding='utf-8') as f:
        # Loop through each row in the BOM data.
        for row_dict in bom_data:
            # Create a list of values for the specified columns.
            # str() preserves any existing whitespace in the data.
            row_values = [str(row_dict.get(col, "")) for col in header]

            # Join the values with a tab and write the line to the file.
            line = "\t".join(row_values)
            f.write(line + "\n")

    return output_filepath


@pytest.fixture
def expected_bom_path_120915():
    return fr"tests/resources/expected_bom_120915.csv"

def _normalize_part_number_from_bom_row(row: Dict[str, str]) -> str:
    # Generated BOM uses indentation via leading spaces; normalize for comparisons.
    return str(row.get("Part Number", "")).strip().upper()

def _format_bom_row_for_log(row: Dict[str, str]) -> str:
    """
    Compact one-line representation for side-by-side diff logs.
    Keep it stable (strip indentation) so alignment is readable.
    """
    row_id = str(row.get("Row ID", "")).strip()
    pos = str(row.get("Pos", "")).strip()
    part = _normalize_part_number_from_bom_row(row)
    qty = str(row.get("Qty", "")).strip()
    rev = str(row.get("Rev", "")).strip()
    state = str(row.get("State", "")).strip()
    desc = str(row.get("Part Description", "")).strip()
    return f"{row_id:>10} | Pos {pos:>3} | {part:<18} | Qty {qty:<4} | Rev {rev:<4} | {state:<14} | {desc}"

def _row_key_for_alignment(row: Dict[str, str]) -> tuple[str, str]:
    """
    Alignment key used to match lines across two BOMs.
    Prefer POS+PART to avoid accidentally matching same part at different POS.
    """
    return (str(row.get("Pos", "")).strip(), _normalize_part_number_from_bom_row(row))

def _write_subbom_alignment_log(
    *,
    top_level: str,
    sub_level: str,
    subtree_from_top: List[Dict[str, str]],
    bom_from_sub_level: List[Dict[str, str]],
    canonical_from_top: List[tuple],
    canonical_from_sub: List[tuple],
) -> str:
    """
    Writes a detailed side-by-side comparison log with gaps inserted to align sequences.
    One output file per top-level assembly name, per user request.
    """
    top_level = top_level.strip().upper()
    sub_level = sub_level.strip().upper()
    log_path = f"log-subbom-compare-{top_level}.txt"

    left_rows = subtree_from_top  # includes sub_level root + descendants (as seen from top)
    right_rows = bom_from_sub_level  # includes sub_level root + descendants (starting from sub)

    left_keys = [_row_key_for_alignment(r) for r in left_rows]
    right_keys = [_row_key_for_alignment(r) for r in right_rows]

    # Summary diffs (set based)
    left_key_set = set(left_keys)
    right_key_set = set(right_keys)
    missing_from_top_view = sorted(list(right_key_set - left_key_set))
    extra_in_top_view = sorted(list(left_key_set - right_key_set))

    # Alignment diff (sequence-based)
    sm = difflib.SequenceMatcher(a=left_keys, b=right_keys, autojunk=False)
    opcodes = sm.get_opcodes()

    COL_W = 140
    def pad(s: str, width: int = COL_W) -> str:
        s = s.replace("\t", " ")
        if len(s) > width:
            return s[: width - 3] + "..."
        return s.ljust(width)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("=== SUB-BOM CONSISTENCY CHECK (gap-aligned) ===\n")
        f.write(f"Top level: {top_level}\n")
        f.write(f"Sub level: {sub_level}\n")
        f.write(f"Generated at top level -> extracted subtree size: {len(left_rows)} rows\n")
        f.write(f"Generated directly at sub level size:           {len(right_rows)} rows\n")
        f.write("\n")

        f.write("--- Canonical compare (descendants only; (Pos, Part, Qty) sorted) ---\n")
        f.write(f"Canonical-from-top count: {len(canonical_from_top)}\n")
        f.write(f"Canonical-from-sub count: {len(canonical_from_sub)}\n")
        f.write(f"Canonical identical?:     {canonical_from_top == canonical_from_sub}\n")
        f.write("\n")

        f.write("--- Set diffs on alignment keys (includes root + descendants) ---\n")
        f.write(f"Missing from top-view subtree (present when starting at {sub_level}): {len(missing_from_top_view)}\n")
        for k in missing_from_top_view[:200]:
            f.write(f"  MISSING  Pos='{k[0]}' Part='{k[1]}'\n")
        if len(missing_from_top_view) > 200:
            f.write(f"  ... truncated ({len(missing_from_top_view) - 200} more)\n")
        f.write(f"Extra in top-view subtree (not present when starting at {sub_level}): {len(extra_in_top_view)}\n")
        for k in extra_in_top_view[:200]:
            f.write(f"  EXTRA    Pos='{k[0]}' Part='{k[1]}'\n")
        if len(extra_in_top_view) > 200:
            f.write(f"  ... truncated ({len(extra_in_top_view) - 200} more)\n")
        f.write("\n")

        f.write("--- Side-by-side alignment (SequenceMatcher on (Pos, Part)) ---\n")
        f.write(pad("LEFT: extracted subtree from top") + " || " + "RIGHT: generated starting at sub\n")
        f.write(pad("-" * (COL_W - 1)) + " || " + ("-" * (COL_W - 1)) + "\n")

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for li, rj in zip(range(i1, i2), range(j1, j2)):
                    f.write(pad(_format_bom_row_for_log(left_rows[li])) + " || " + _format_bom_row_for_log(right_rows[rj]) + "\n")
            elif tag == "delete":
                for li in range(i1, i2):
                    f.write(pad(_format_bom_row_for_log(left_rows[li])) + " || " + "\n")
            elif tag == "insert":
                for rj in range(j1, j2):
                    f.write(pad("") + " || " + _format_bom_row_for_log(right_rows[rj]) + "\n")
            elif tag == "replace":
                left_chunk = left_rows[i1:i2]
                right_chunk = right_rows[j1:j2]
                max_len = max(len(left_chunk), len(right_chunk))
                for k in range(max_len):
                    lstr = _format_bom_row_for_log(left_chunk[k]) if k < len(left_chunk) else ""
                    rstr = _format_bom_row_for_log(right_chunk[k]) if k < len(right_chunk) else ""
                    f.write(pad(lstr) + " || " + rstr + "\n")

        f.write("\n")
        f.write("=== END ===\n")

    return log_path

def _safe_getattr(obj: object, attr_name: str, default: str = "N/A") -> str:
    try:
        if not hasattr(obj, attr_name):
            return default
        val = getattr(obj, attr_name)
        # Avoid dumping huge objects; prefer scalars/strings.
        if val is None:
            return ""
        return str(val)
    except Exception as e:
        return f"<error reading {attr_name}: {e}>"

def _collect_reference_path_to_part(cmx_vault: CMXVault, root_reference: object, target_part_number: str) -> List[object]:
    """
    Returns the path of reference nodes from root -> target (inclusive).
    Match is done on base filename of reference.Name (before extension), normalized.
    """
    target_part_number = target_part_number.strip().upper()
    if root_reference is None:
        return []

    def ref_base_name(ref: object) -> str:
        name = _safe_getattr(ref, "Name", "")
        base = name.rsplit(".", 1)[0] if "." in name else name
        return base.strip().upper()

    stack: List[tuple[object, List[object]]] = [(root_reference, [root_reference])]
    seen_paths = set()

    while stack:
        node, path = stack.pop()
        node_found_path = _safe_getattr(node, "FoundPath", "")
        if node_found_path:
            if node_found_path in seen_paths:
                continue
            seen_paths.add(node_found_path)

        if ref_base_name(node) == target_part_number:
            return path

        try:
            children = list(cmx_vault._get_children_from_reference(node))
        except Exception:
            children = []

        for child in reversed(children):
            stack.append((child, path + [child]))

    return []

def _log_reference_metadata_for_scenario(
    *,
    log_path: str,
    scenario_name: str,
    cmx_vault: CMXVault,
    root_reference: object,
    target_part_number: str,
) -> None:
    """
    Append reference metadata to the given log file.
    Includes root->target chain, plus parents of target, plus derived BOM drawing chosen.
    """
    target_part_number = target_part_number.strip().upper()

    ref_path_nodes = _collect_reference_path_to_part(cmx_vault, root_reference, target_part_number)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(f"=== REFERENCE METADATA: {scenario_name} ===\n")

        root_name = _safe_getattr(root_reference, "Name", "")
        root_found = _safe_getattr(root_reference, "FoundPath", "")
        root_ver = _safe_getattr(root_reference, "VersionRef", "")
        root_fileid = _safe_getattr(root_reference, "FileID", "")
        f.write(f"Root Name: {root_name}\n")
        f.write(f"Root FoundPath: {root_found}\n")
        f.write(f"Root VersionRef: {root_ver}\n")
        f.write(f"Root FileID: {root_fileid}\n")
        f.write("\n")

        if not ref_path_nodes:
            f.write(f"Could not locate target part '{target_part_number}' in reference tree.\n")
            f.write("=== END REFERENCE METADATA ===\n")
            return

        f.write(f"Root -> Target chain length: {len(ref_path_nodes)}\n")
        f.write("Chain (each node):\n")

        # These are the most likely EPDM reference fields that hint at version/config differences.
        extra_fields_to_try = [
            "Configuration", "ConfigurationName", "ReferencedConfiguration", "RefConfiguration",
            "IsSuppressed", "Suppressed", "Flags", "ReferenceType", "ParentFileID", "TreeDepth"
        ]

        for idx, ref in enumerate(ref_path_nodes):
            ref_name = _safe_getattr(ref, "Name", "")
            ref_found = _safe_getattr(ref, "FoundPath", "")
            ref_ver = _safe_getattr(ref, "VersionRef", "")
            ref_fileid = _safe_getattr(ref, "FileID", "")
            f.write(f"- [{idx}] Name='{ref_name}'\n")
            f.write(f"      FoundPath='{ref_found}'\n")
            f.write(f"      VersionRef='{ref_ver}'  FileID='{ref_fileid}'\n")
            for field in extra_fields_to_try:
                val = _safe_getattr(ref, field, default="(missing)")
                if val != "(missing)" and val != "N/A":
                    f.write(f"      {field}='{val}'\n")
            f.write("\n")

        target_ref = ref_path_nodes[-1]

        # Log parents of target (often includes the drawing that provides derived BOM).
        f.write("Parents of target (from EPDM reference API):\n")
        try:
            parents = list(cmx_vault._get_parents_from_reference(target_ref))
        except Exception as e:
            parents = []
            f.write(f"  <error fetching parents: {e}>\n")

        if parents:
            for p in parents:
                p_name = _safe_getattr(p, "Name", "")
                p_found = _safe_getattr(p, "FoundPath", "")
                p_ver = _safe_getattr(p, "VersionRef", "")
                p_fileid = _safe_getattr(p, "FileID", "")
                f.write(f"  - Name='{p_name}' FoundPath='{p_found}' VersionRef='{p_ver}' FileID='{p_fileid}'\n")
        else:
            f.write("  (none)\n")

        # Log which derived BOM drawing was used by _create_derived_bom_cache for this target reference.
        f.write("\nDerived BOM selection for target (via _create_derived_bom_cache):\n")
        before_keys = set(getattr(cmx_vault, "derived_bom_cache", {}).keys())
        try:
            derived_map = cmx_vault._create_derived_bom_cache(target_ref)
        except Exception as e:
            derived_map = {}
            f.write(f"  <error creating derived BOM cache: {e}>\n")
        after_keys = set(getattr(cmx_vault, "derived_bom_cache", {}).keys())
        new_keys = list(after_keys - before_keys)

        if new_keys:
            f.write(f"  Derived BOM drawing key(s) added: {new_keys}\n")
        else:
            # If already cached, attempt to infer by checking which key contains the part number.
            f.write("  No new derived BOM cache key added (likely already cached).\n")
            f.write(f"  Current derived_bom_cache keys count: {len(after_keys)}\n")

        f.write(f"  Derived BOM item count (mapped rows): {len(derived_map)}\n")
        sample_parts = sorted(list(derived_map.keys()))[:30]
        if sample_parts:
            f.write(f"  Sample mapped part numbers (first 30): {sample_parts}\n")
        f.write("=== END REFERENCE METADATA ===\n")

def _extract_subtree_from_bom(bom: List[Dict[str, str]], root_part_number: str) -> List[Dict[str, str]]:
    """
    Extract a subtree (root row + all descendants) from a hierarchical BOM list.

    The BOM uses "Row ID" with dot-separated paths (e.g., "1.2.3").
    """
    root_part_number = root_part_number.strip().upper()

    root_row = None
    for row in bom:
        if _normalize_part_number_from_bom_row(row) == root_part_number:
            root_row = row
            break

    assert root_row is not None, f"Could not find root part '{root_part_number}' in BOM."
    root_row_id = str(root_row.get("Row ID", "")).strip()
    assert root_row_id, f"Found root part '{root_part_number}' but it had empty Row ID."

    subtree = [root_row]
    prefix = root_row_id + "."
    for row in bom:
        row_id = str(row.get("Row ID", "")).strip()
        if row_id.startswith(prefix):
            subtree.append(row)
    return subtree

def _canonicalize_bom_descendants_for_compare(bom_subtree: List[Dict[str, str]]) -> List[tuple]:
    """
    Compare only descendants, and only on stable BOM fields that reflect structure.
    We intentionally exclude Row ID / Tot / drawing-path-ish fields to avoid false diffs.
    """
    if not bom_subtree:
        return []

    # Skip the subtree root itself; starting-at-root vs extracted-from-parent can differ in root Qty.
    descendants = bom_subtree[1:]
    canonical = []
    for row in descendants:
        canonical.append((
            str(row.get("Pos", "")).strip(),
            _normalize_part_number_from_bom_row(row),
            str(row.get("Qty", "")).strip(),
        ))
    canonical.sort()
    return canonical

def _assert_contains_part_with_pos(canonical_rows: List[tuple], part_number: str, pos: str):
    part_number = part_number.strip().upper()
    pos = str(pos).strip()
    assert any(r_pos == pos and r_part == part_number for (r_pos, r_part, _r_qty) in canonical_rows), \
        f"Expected to find part '{part_number}' at pos '{pos}' but it was missing."

def _assert_not_contains_part(canonical_rows: List[tuple], part_number: str):
    part_number = part_number.strip().upper()
    assert all(r_part != part_number for (_r_pos, r_part, _r_qty) in canonical_rows), \
        f"Part '{part_number}' should NOT be in BOM but was present."

def test_subbom_same_regardless_of_start_level_CA120726_vs_CA330313(cmx_vault: CMXVault):
    """
    Regression test:
    Top nivå: CA120726
    Undernivå: CA330313

    The sub-BOM for CA330313 must be identical whether:
    - we generate BOM for CA120726 and extract the CA330313 subtree, or
    - we generate BOM starting directly at CA330313.

    Also asserts known problematic parts:
    - CA332438 (pos 19), CA332447 (pos 62), CA332448 (pos 63) must exist
    - CA331639 and CA331785 must NOT exist in the BOM
    """
    top_level = "CA120726"
    sub_level = "CA330313"

    cmx_vault.reset_bom_cache()
    bom_top = cmx_vault.generate_bom(top_level)
    subtree_from_top = _extract_subtree_from_bom(bom_top, sub_level)
    canonical_from_top = _canonicalize_bom_descendants_for_compare(subtree_from_top)

    cmx_vault.reset_bom_cache()
    bom_sub = cmx_vault.generate_bom(sub_level)
    canonical_from_sub = _canonicalize_bom_descendants_for_compare(bom_sub)

    # Always write a detailed, gap-aligned log for debugging (one file per top-level assembly).
    log_path = _write_subbom_alignment_log(
        top_level=top_level,
        sub_level=sub_level,
        subtree_from_top=subtree_from_top,
        bom_from_sub_level=bom_sub,
        canonical_from_top=canonical_from_top,
        canonical_from_sub=canonical_from_sub,
    )

    # Also write reference-tree metadata to the SAME per-top-level log file, so it can be shared externally.
    try:
        top_ref = cmx_vault._get_reference_by_part_number(top_level)
        sub_ref = cmx_vault._get_reference_by_part_number(sub_level)
        _log_reference_metadata_for_scenario(
            log_path=log_path,
            scenario_name=f"{top_level} (tree) -> locate {sub_level} node",
            cmx_vault=cmx_vault,
            root_reference=top_ref,
            target_part_number=sub_level,
        )
        _log_reference_metadata_for_scenario(
            log_path=log_path,
            scenario_name=f"{sub_level} (tree root)",
            cmx_vault=cmx_vault,
            root_reference=sub_ref,
            target_part_number=sub_level,
        )
    except Exception as e:
        # Never fail the test due to debug logging; include a note in the log file instead.
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write("=== REFERENCE METADATA LOGGING ERROR ===\n")
            f.write(str(e) + "\n")
            f.write("=== END REFERENCE METADATA LOGGING ERROR ===\n")

    assert canonical_from_top == canonical_from_sub, (
        "Sub-BOM mismatch: CA330313 differs depending on whether we start at CA120726 "
        "or directly at CA330313. This indicates inconsistent include/derived-BOM logic. "
        f"See '{log_path}' for a gap-aligned side-by-side comparison."
    )

    # Must exist (these were reported missing in top-level view but present in under-level)
    _assert_contains_part_with_pos(canonical_from_top, "CA332438", "19")
    _assert_contains_part_with_pos(canonical_from_top, "CA332447", "62")
    _assert_contains_part_with_pos(canonical_from_top, "CA332448", "63")

    # Must not exist (these were reported as incorrectly included)
    _assert_not_contains_part(canonical_from_top, "CA331639")
    _assert_not_contains_part(canonical_from_top, "CA331785")

@pytest.mark.line_profile
def test_generate_bom(cmx_vault:CMXVault):
    t0  = time.perf_counter()
    part_number = "335291"
    bom = cmx_vault.generate_bom(f"CA{part_number}")
    write_bom_to_csv(bom,f"CA{part_number}",f"BOM_CA{part_number}.csv")
    t1 = time.perf_counter()
    utils.log(f"Execution time: {(t1-t0):.2f} s",ext = "_execution_times")
    show(bom,f"_complete_bom_{part_number}")

def test_generate_bom_with_revision_override_for_320656(cmx_vault:CMXVault):
    """
    Tests that generating a BOM for another single part (320656) with a revision
    override correctly fetches the data for that specific historical version.
    """
    t0 = time.perf_counter()
    
    # 1. Define the target part number and the specific revision override
    part_number = "CA320656"
    rev_override = "C"
    rev_overrides = {part_number: rev_override}

    # 2. Generate the BOM for this single part with the override applied
    cmx_vault.reset_bom_cache()
    bom = cmx_vault.generate_bom(part_number, rev_overrides)
    
    # 3. Perform assertions on the result
    assert bom, "BOM generation returned an empty list."
    bom_row = bom[0]

    print(f"\n--- Testing Override for {part_number} ---")
    print(f"Time taken: {time.perf_counter() - t0:.4f}s")
    print(f"Found Part: {bom_row['Part Number'].strip()}, Rev: {bom_row['Rev']}, State: '{bom_row['State']}', Drawing: '{bom_row['Drawing']}'")
    
    # 4. Verify that the correct part, revision, and state were retrieved
    assert bom_row["Part Number"].strip() == part_number
    assert bom_row["Rev"] == rev_override
    assert bom_row["State"] == "In Production"

    # 5. Verify that the found drawing name is valid and contains the key info
    found_drawing = bom_row["Drawing"]
    assert part_number in found_drawing, f"Drawing name '{found_drawing}' does not contain the part number '{part_number}'"
    assert rev_override in found_drawing, f"Drawing name '{found_drawing}' does not contain the revision '{rev_override}'"
    
    print(f"SUCCESS: Part state for {part_number} is correctly listed as 'In Production' for revision C.")
    print(f"SUCCESS: Drawing name '{bom_row['Drawing']}' is a valid format and includes revision C.")

def test_generate_bom_with_revision_override(cmx_vault:CMXVault):
    """
    Tests that generating a BOM for a single part with a revision override
    correctly fetches the data card for that specific historical version and
    constructs a valid drawing filename from multiple possible formats.
    """
    t0 = time.perf_counter()
    
    # 1. Define the target part number and the specific revision override
    part_number = "CA322247"
    rev_override = "C"
    rev_overrides = {part_number: rev_override}

    # 2. Generate the BOM for this single part with the override applied
    cmx_vault.reset_bom_cache()
    bom = cmx_vault.generate_bom(part_number, rev_overrides)
    
    # 3. Perform assertions on the result
    assert bom, "BOM generation returned an empty list."
    assert len(bom) == 1, "BOM for a single part should contain exactly one row."
    
    bom_row = bom[0]

    print(f"\n--- Testing Override for {part_number} ---")
    print(f"Time taken: {time.perf_counter() - t0:.4f}s")
    print(f"Found Part: {bom_row['Part Number'].strip()}, Rev: {bom_row['Rev']}, State: '{bom_row['State']}', Drawing: '{bom_row['Drawing']}'")
    
    # 4. Generate all possible valid drawing names based on the logic in _get_pdf_drawing_path
    prefixes = (f"M-{part_number}", part_number)
    separators = (f"_{rev_override}", f"-{rev_override}")
    postfixes = (".pdf", " .pdf")

    expected_drawing_names = {
        f"{prefix}{separator}{postfix}"
        for prefix in prefixes
        for separator in separators
        for postfix in postfixes
    }

    # 5. Verify that the correct part, revision, state, and drawing were retrieved
    assert bom_row["Part Number"].strip() == part_number
    assert bom_row["Drawing"] in expected_drawing_names
    assert bom_row["Rev"] == rev_override
    assert bom_row["State"] == "In Production"
    
    
    print("SUCCESS: Part state is correctly listed as 'In Production' for revision C.")
    print(f"SUCCESS: Drawing name '{bom_row['Drawing']}' is a valid format and includes revision C.")
        

# Define the expected column keys once for consistency
BOM_COLUMN_KEYS: List[str] = [
    "Row ID", "Pos", "Part Number", "Rev", "Qty", "Tot", 
    "Part Description", "State", "Drawing"
]

def parse_bom_line_to_dict(line: str, line_number: int, filepath_for_error: str) -> Union[Dict[str, str], None]:
    """
    Parses a single tab-separated BOM line into a dictionary.
    Returns None if the line is malformed or missing 'Row ID'.
    Logs warnings for issues.
    """
    values = line.split('\t')
    if len(values) != len(BOM_COLUMN_KEYS):
        utils.log(
            f"BOM_PARSE_WARN: Malformed line {line_number} in '{filepath_for_error}'. "
            f"Expected {len(BOM_COLUMN_KEYS)} columns, got {len(values)}.",
            Line_Content=line, ext="-bom-comparison-parse"
        )
        return None

    row_dict = {key: value for key, value in zip(BOM_COLUMN_KEYS, values)}
    row_id = row_dict.get("Row ID")
    if not row_id: 
        utils.log(
            f"BOM_PARSE_WARN: Missing or empty 'Row ID' in parsed line {line_number} of '{filepath_for_error}'.",
            Line_Content=line, ext="-bom-comparison-parse"
        )
        return None
    return row_dict

def read_reference_bom_file_to_dict(filepath: str) -> Dict[str, Dict[str, str]]:
    """
    Reads a reference BOM file and parses it into a dictionary keyed by "Row ID".
    Each value is a dictionary representing the BOM row.
    """
    parsed_bom: Dict[str, Dict[str, str]] = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for i, line_content in enumerate(f):
                line_content = line_content.rstrip("\n")
                if not line_content:
                    continue
                
                row_dict = parse_bom_line_to_dict(line_content, i + 1, filepath)
                if row_dict is None:
                    continue

                row_id = row_dict["Row ID"] 
                if row_id in parsed_bom:
                     utils.log(
                        f"BOM_PARSE_WARN: Duplicate 'Row ID' '{row_id}' found in reference BOM '{filepath}' at line {i+1}. "
                        "Previous entry will be overwritten.",
                        Line_Content=line_content, ext="-bom-comparison-parse"
                     )
                parsed_bom[row_id] = row_dict
        return parsed_bom
    except FileNotFoundError:
        pytest.fail(f"Reference BOM file not found: {filepath}")
        return {} 

def format_bom_row_dict_to_string(bom_row_dict: Dict[str, str]) -> str:
    """
    Formats a single BOM row dictionary into a tab-separated string.
    Uses the global BOM_COLUMN_KEYS for order.
    """
    row_values: List[str] = [str(bom_row_dict.get(key, "")) for key in BOM_COLUMN_KEYS]
    return "\t".join(row_values)    
        

drawing_test_cases = [
    ("Prioritize M- over TD-", "CA327408", [
        {"name": "TD-CA327408_U.pdf", "state": "Released"},
        {"name": "M-CA327408_D.pdf", "state": "Released"}
    ], "M-CA327408_D.pdf"),
    ("Prioritize No Prefix over M-", "CA330917", [
        {"name": "TD-CA330917_U.pdf", "state": "Released"},
        {"name": "M-CA330917_C.pdf", "state": "Released"},
        {"name": "CA330917_A.pdf", "state": "Released"}
    ], "CA330917_A.pdf"),
    ("Select Highest Revision for M-", "CA123456", [
        {"name": "M-CA123456_A.pdf", "state": "Released"},
        {"name": "M-CA123456_C.pdf", "state": "Released"},
        {"name": "M-CA123456_B.pdf", "state": "Released"}
    ], "M-CA123456_C.pdf"),
    ("Select Best State (In Prod > Released)", "CA654321", [
        {"name": "M-CA654321_A.pdf", "state": "Released"},
        {"name": "M-CA654321_B.pdf", "state": "In Production"}
    ], "M-CA654321_B.pdf"),
]

@pytest.mark.parametrize("test_id, part_number, candidates, expected", drawing_test_cases)
def test_drawing_search_functionality(cmx_vault, test_id, part_number, candidates, expected):
    """
    Tests the drawing selection logic by directly calling _find_best_drawing_match
    with a controlled set of mock PDF candidate data.
    """
    # This part_data would normally be derived from the component
    part_data = {"core": part_number}
    revision_overrides = {}

    # Call the private method directly to unit test its logic
    best_match = cmx_vault._find_best_drawing_match(
        part_number,
        part_data,
        candidates,
        revision_overrides
    )

    assert best_match is not None, f"Test '{test_id}': Expected to find a drawing but got None."
    assert best_match["name"] == expected, \
        f"Test '{test_id}': For part '{part_number}', expected drawing '{expected}' but got '{best_match['name']}'."

def debug_search_patterns(cmx_vault: CMXVault, part_name: str, revision: str):
    """
    Debug the search patterns used in _get_pdf_drawing_path to understand why searches are failing.
    """
    base_name, ext = part_name.rsplit(".", 1)
    
    # Replicate the logic from _get_pdf_drawing_path
    pres = ("M-", "") if ext.lower() in ("sldprt", "sldasm") else ("",)
    posts = (" ", "")
    seps = ("_", "-")
    dirs = (cmx_vault._released_docs_dir, cmx_vault._doc_dir)
    
    # Generate candidate patterns
    candidate_patterns = [
        f"{pre}{base_name}{sep}{revision}{post}.pdf" 
        for sep in seps 
        for pre in pres 
        for post in posts
    ]
    
    utils.log(f"Debug search patterns for {part_name} rev {revision}:", 
             Patterns=str(candidate_patterns), ext="_drawing_search_debug")
    
    # Test each pattern in each directory
    for pattern in set(candidate_patterns):
        for directory in dirs:
            utils.log(f"Testing pattern '{pattern}' in directory '{directory}'", ext="_drawing_search_debug")
            
            try:
                # Test if directory exists
                folder_obj = cmx_vault._get_folder_object(directory)
                if not folder_obj:
                    utils.log(f"Directory does not exist: {directory}", ext="_drawing_search_debug")
                    continue
                
                # Test the search
                search_results = list(cmx_vault.search_files(
                    filename_pattern=pattern,
                    directory=directory,
                    recursive=True
                ))
                
                if search_results:
                    utils.log(f"FOUND matches for pattern '{pattern}' in '{directory}'", 
                             Results=str(search_results), ext="_drawing_search_debug")
                    print(f"    → Found {len(search_results)} matches for '{pattern}' in {os.path.basename(directory)}")
                    for result in search_results:
                        print(f"      - {result.get('name', 'N/A')} (State: {result.get('state', 'N/A')})")
                else:
                    utils.log(f"No matches for pattern '{pattern}' in '{directory}'", ext="_drawing_search_debug")
                    
            except Exception as e:
                utils.log(f"Search failed for pattern '{pattern}' in '{directory}'", 
                         Error=str(e), ext="_drawing_search_debug")

def test_broad_search_for_CA318220(cmx_vault: CMXVault):
    """
    Tests that a broad wildcard search for a specific part number (CA318220)
    finds all known drawing variations for that part, including those with/without trailing spaces.
    """
    part_number = "CA318220"
    search_pattern = f"*{part_number}*.pdf"
    
    # CORRECTED: Now expects both versions of the revision 'R' drawing.
    expected_filenames = {
        "M-CA318220_R02.pdf",
        "M-CA318220_R01.pdf",
        "M-CA318220_R .pdf",  # With trailing space
        "M-CA318220_R.pdf"   # Without trailing space
    }

    print(f"\n--- Testing broad search for '{search_pattern}' ---")
    utils.log(f"Testing broad search for '{search_pattern}'", ext="_broad_search_test")

    # Search in all relevant drawing directories
    found_results = []
    for directory in [cmx_vault._released_docs_dir, cmx_vault._doc_dir]:
        try:
            results = list(cmx_vault.search_files(
                filename_pattern=search_pattern,
                directory=directory,
                recursive=True
            ))
            found_results.extend(results)
        except Exception as e:
            pytest.fail(f"Search in directory '{directory}' failed with error: {e}")

    # Assert that we found at least as many files as we expect.
    assert len(found_results) >= len(expected_filenames), \
        f"Search found only {len(found_results)} file(s), but expected at least {len(expected_filenames)}."

    # Get a set of the unique filenames from the results.
    found_filenames = {os.path.basename(result.get("path", "")) for result in found_results}
    
    # Check if all expected files are present in the search results.
    missing_files = expected_filenames - found_filenames

    if missing_files:
        pytest.fail(
            f"Broad search for '{search_pattern}' did not find all expected files.\n"
            f"Missing: {sorted(list(missing_files))}\n"
            f"Found: {sorted(list(found_filenames))}"
        )

    print(f"✓ Broad search PASSED: Found all {len(expected_filenames)} expected drawings for {part_number}.")
    utils.log("SUCCESS: Broad search found all expected drawings.", ext="_broad_search_test")

def test_find_specific_drawings(cmx_vault: CMXVault):
    """
    Test finding specific known drawings by calling the batch search function directly.
    """
    # Test cases: part numbers and expected drawings that should be found
    test_cases = [
        {"part_number": "A-CA318243", "revision": "Q", "expected": "A-CA318243_Q.pdf"},
        {"part_number": "AA-CA332732", "revision": "A", "expected": "AA-CA332732_A.pdf"}, 
        {"part_number": "CA318243", "revision": "M", "expected": "M-CA318243_M .pdf"},  # Note the space before .pdf
    ]
    
    for test_case in test_cases:
        part_number = test_case["part_number"]
        revision = test_case["revision"]
        expected_drawing = test_case["expected"]
        
        try:
            # Get the actual reference from PDM to build the input for the batch function.
            reference = cmx_vault._get_reference_by_part_number(part_number)
            
            if reference:
                # --- Corrected Logic: Call _batch_find_drawing_paths directly ---
                # 1. Manually prepare the inputs the function expects.
                all_references = {part_number: reference}
                revision_overrides = {part_number: revision}
                cmx_vault.computed_bom_cache[part_number] = {"Revision": revision}

                # 2. Call the batch function, treating this as an override test.
                drawing_cache = cmx_vault._batch_find_drawing_paths(all_references, revision_overrides)
                
                # 3. The cache key is "{part_number}|{bom_revision}".
                drawing_info = drawing_cache.get(f"{part_number}|{revision}")
                
                if drawing_info:
                    drawing_path = drawing_info.get("path", "")
                    drawing_filename = os.path.basename(drawing_path) if drawing_path else drawing_info.get("name", "")
                    
                    # 4. Assert that we found the expected drawing.
                    assert drawing_filename.strip() == expected_drawing.strip(), f"Expected '{expected_drawing}' but found '{drawing_filename}'"
                
                else:
                    assert False, f"No drawing found for {part_number} rev {revision}, expected '{expected_drawing}'"
            else:
                assert False, f"No PDM reference found for part {part_number}"
                
        except Exception as e:
            utils.log(f"Part: {part_number}, Rev: {revision}", 
                      Expected=expected_drawing,
                      Error=str(e),
                      ext="_drawing_search_results")
            raise

def test_batch_drawing_search_stage(cmx_vault: CMXVault):
    """
    Tests the first stage of the batch drawing search: using a single, large,
    OR-combined search pattern to find all candidate drawings at once.
    """
    utils.log("=== Testing Batch Drawing Search Stage (Broad Search) ===", ext="_batch_drawing_search_test")

    # 1. Define the part numbers we need drawings for.
    parts_to_find = [
        "A-CA318243",
        "AA-CA332732",
        "CA318243"
    ]
    
    # Define the exact filenames we expect to be in the results.
    expected_drawings = [
        "A-CA318243_Q.pdf",
        "AA-CA332732_A.pdf",
        "M-CA318243_M .pdf"
    ]

    # 2. Replicate the logic from _batch_find_drawing_paths to build the search string.
    search_patterns = [f"*{part}*" for part in parts_to_find]
    giant_search_string = "|".join(search_patterns)
    full_pattern = f"{giant_search_string}.pdf"
    
    utils.log(f"Constructed batch search pattern: {full_pattern}", ext="_batch_drawing_search_test")

    # 3. Execute the search across all relevant drawing directories.
    all_candidate_pdfs = []
    for directory in [cmx_vault._released_docs_dir, cmx_vault._doc_dir]:
        try:
            results = list(cmx_vault.search_files(
                filename_pattern=full_pattern,
                directory=directory,
                recursive=True
            ))
            all_candidate_pdfs.extend(results)
        except PDMFileNotFoundError:
            utils.log(f"Search directory not found: {directory}", ext="_batch_drawing_search_test")
            continue
            
    utils.log(f"Broad search found {len(all_candidate_pdfs)} candidate files.", ext="_batch_drawing_search_test")
    assert len(all_candidate_pdfs) > 0, "Broad search returned zero candidate files."

    # 4. Assert that all our expected drawings are present in the candidate list.
    found_filenames = {os.path.basename(pdf.get("path", "")).strip() for pdf in all_candidate_pdfs}
    
    missing_drawings = []
    for expected in expected_drawings:
        # Normalize the expected name by stripping whitespace, just like the found names.
        normalized_expected = expected.strip()
        if normalized_expected not in found_filenames:
            missing_drawings.append(normalized_expected)
            
    if missing_drawings:
        pytest.fail(
            f"Broad search failed to find expected drawings: {missing_drawings}\n"
            f"Found {len(found_filenames)} files, but not the required ones."
        )
    
    utils.log(f"SUCCESS: Broad search found all expected drawings.", ext="_batch_drawing_search_test")
    print("\n✓ Batch drawing search stage test passed.")
    
@pytest.mark.parametrize(
    "test_id, part_to_find, candidate_pdfs, revision_overrides, expected_filename",
    [
        pytest.param(
            "default_highest_rev",
            {"name": "CA123456", "data": {"rev": "A", "core": "CA123456"}},
            [
                {"name": "M-CA123456_A.pdf", "state": "Released", "path": "/path/to/A.pdf"},
                {"name": "M-CA123456_B.pdf", "state": "Released", "path": "/path/to/B.pdf"}
            ],
            {},
            "M-CA123456_B.pdf",
            id="default_logic_chooses_highest_revision"
        ),
        pytest.param(
            "override_specific_rev",
            {"name": "CA123456", "data": {"rev": "A", "core": "CA123456"}},
            [
                {"name": "M-CA123456_A.pdf", "state": "Released", "path": "/path/to/A.pdf"},
                {"name": "M-CA123456_B.pdf", "state": "Released", "path": "/path/to/B.pdf"}
            ],
            {"CA123456": "A"},
            "M-CA123456_A.pdf",
            id="override_logic_chooses_exact_revision"
        ),
        pytest.param(
            "state_priority",
            {"name": "CA123456", "data": {"rev": "A", "core": "CA123456"}},
            [
                {"name": "M-CA123456_B.pdf", "state": "Released", "path": "/path/to/B_released.pdf"},
                {"name": "M-CA123456_B.pdf", "state": "In Production", "path": "/path/to/B_in_prod.pdf"}
            ],
            {},
            "M-CA123456_B.pdf",
            id="state_priority_chooses_in_production_over_released"
        ),
        pytest.param(
            "no_valid_match",
            {"name": "CA123456", "data": {"rev": "A", "core": "CA123456"}},
            [
                {"name": "M-CA123456_B_prod.pdf", "state": "Released", "path": "/path/to/invalid1.pdf"},
                {"name": "Archive_M-CA123456_B.pdf", "state": "Released", "path": "/path/to/invalid2.pdf"}
            ],
            {},
            None,
            id="returns_none_if_no_valid_candidates_found"
        ),
        # --- NEW TEST CASES START HERE ---
        pytest.param(
            "ignore_invalid_revision_format",
            {"name": "CA789", "data": {"rev": "A", "core": "CA789"}},
            [
                {"name": "CA789_4B.pdf", "state": "Released", "path": "/path/to/invalid.pdf"},      # Invalid: Digit first in revision
                {"name": "CA789_B.pdf", "state": "Released", "path": "/path/to/valid.pdf"}         # Valid: Should be chosen
            ],
            {},
            "CA789_B.pdf",
            id="filter_ignores_invalid_revision_format_like_4B"
        ),
        pytest.param(
            "ignore_extra_text",
            {"name": "CA789", "data": {"rev": "A", "core": "CA789"}},
            [
                {"name": "CA789_prod_B_extra.pdf", "state": "Released", "path": "/path/to/invalid1.pdf"}, # Invalid: Extra text
                {"name": "CA789-C.pdf", "state": "Released", "path": "/path/to/valid.pdf"},              # Valid: Should be chosen
                {"name": "CA789_B_experimental.pdf", "state": "Released", "path": "/path/to/invalid2.pdf"}# Invalid: Extra text
            ],
            {},
            "CA789-C.pdf",
            id="filter_ignores_extra_text_around_revision"
        )
    ]
)
def test_drawing_filter_logic(cmx_vault: CMXVault, test_id: str, part_to_find: dict, candidate_pdfs: list, revision_overrides: dict, expected_filename: Optional[str]):
    """
    Tests the isolated drawing filter and selection logic of _find_best_drawing_match.
    """
    part_name = part_to_find["name"]
    part_data = part_to_find["data"]
    
    best_match = cmx_vault._find_best_drawing_match(part_name, part_data, candidate_pdfs, revision_overrides)
    
    found_filename = best_match.get("name") if best_match else None
    
    # Assertions to validate the outcome
    if expected_filename is None:
        assert best_match is None, f"Test '{test_id}': Expected no match, but found '{found_filename}'"
    else:
        assert best_match is not None, f"Test '{test_id}': Found no match, but expected '{expected_filename}'"
        assert found_filename == expected_filename, f"Test '{test_id}': Expected '{expected_filename}', but found '{found_filename}'"

    # Reporting Logic
    candidate_filenames = {pdf.get("name") for pdf in candidate_pdfs}
    
    ignored_files = []
    if found_filename:
        ignored_files = sorted([name for name in candidate_filenames if name != found_filename])
    else:
        ignored_files = sorted(list(candidate_filenames))
    
    print(f"\n✓ Test '{test_id}': Correctly found '{found_filename or 'None'}'")
    if ignored_files:
        print(f"  - Ignored {len(ignored_files)} invalid candidate(s): {ignored_files}")
        
def test_drawing_priority_for_CA318220(cmx_vault: CMXVault):
    """
    Directly tests the _batch_find_drawing_paths logic for a part with multiple revisions.
    This test avoids calling generate_bom and focuses only on the drawing selection.
    """
    part_name_in_bom = "M-CA318220"
    log_ext = "_drawing_priority_test"
    utils.log(f"\n--- Testing Drawing Priority for: {part_name_in_bom} ---", ext=log_ext)

    # Mock the inputs that generate_bom would normally provide to _batch_find_drawing_paths
    class MockReference:
        def __init__(self, name):
            self.Name = name
    
    mock_ref = MockReference(f"{part_name_in_bom}.sldprt")
    all_references = {part_name_in_bom: mock_ref}
    
    # We must manually set the part's revision in the cache, as this is done before drawing search.
    # Assume the part's revision in the BOM is 'R'.
    cmx_vault.computed_bom_cache[part_name_in_bom] = {"Revision": "R"}

    # --- Scenario 1: Test Default Behavior (Should find highest/latest revision: R) ---
    utils.log("SCENARIO 1: Default search (no override)", ext=log_ext)
    
    # Call the batch function directly with no overrides.
    drawing_cache_default = cmx_vault._batch_find_drawing_paths(all_references, revision_overrides={})
    
    # In our revision scheme, the latest is "R" and earlier ones are "R01", "R02", ...
    # Also note: there may be both "R.pdf" and "R .pdf" variants (with/without trailing space).
    expected_drawing_default_variants = {"M-CA318220_R.pdf", "M-CA318220_R .pdf"}
    # The cache key is "{part_number}|{bom_revision}"
    found_path_default = drawing_cache_default.get(f"{part_name_in_bom}|R")
    
    assert found_path_default, "Default search failed: No drawing path was found."
    found_filename_default = os.path.basename(found_path_default.get("path", "")) if isinstance(found_path_default, dict) else os.path.basename(found_path_default)
    
    utils.log(
        f"Default Result: Found='{found_filename_default}', Expected one of {sorted(list(expected_drawing_default_variants))}",
        ext=log_ext
    )
    assert found_filename_default in expected_drawing_default_variants, (
        "Default search failed. Expected latest revision drawing to be one of "
        f"{sorted(list(expected_drawing_default_variants))}, but got '{found_filename_default}'."
    )
    print(f"\n✓ Default Test PASSED: Correctly found latest revision '{found_filename_default}'.")

    # --- Scenario 2: Test Override Behavior (Should find exact revision 'R' in best state) ---
    utils.log("SCENARIO 2: Override search for revision 'R'", ext=log_ext)
    
    revision_overrides = {part_name_in_bom: "R"}
    
    # Call the batch function with the override.
    drawing_cache_override = cmx_vault._batch_find_drawing_paths(all_references, revision_overrides=revision_overrides)

    expected_drawing_override = "M-CA318220_R .pdf"
    found_path_override = drawing_cache_override.get(f"{part_name_in_bom}|R")

    assert found_path_override, "Override search failed: No drawing path was found."
    found_filename_override = os.path.basename(found_path_override.get("path", "")) if isinstance(found_path_override, dict) else os.path.basename(found_path_override)
    
    utils.log(f"Override Result: Found='{found_filename_override}', Expected='{expected_drawing_override}'", ext=log_ext)
    assert found_filename_override == expected_drawing_override, f"Override search failed. Expected '{expected_drawing_override}', but got '{found_filename_override}'."
    print(f"✓ Override Test PASSED: Correctly found override revision '{expected_drawing_override}' in state 'In Production'.")

@pytest.mark.parametrize(
    "part_number, override_revision, candidates, expected_name",
    [
        pytest.param(
            "CA334557",
            "B01+",
            [
                {"name": "CA334557_A.pdf", "state": "Released", "path": "/path/to/released_a.pdf"},
                {"name": "CA334557_B01+.pdf", "state": "Evaluation file under editing", "path": "/path/to/eval_b01_plus.pdf"},
            ],
            "CA334557_B01+.pdf",
            id="ca334557_prefers_plus_revision_with_override",
        ),
        pytest.param(
            "CA334052",
            "F01+",
            [
                {"name": "CA334052_E.pdf", "state": "Released", "path": "/path/to/released_e.pdf"},
                {"name": "CA334052_F01+.pdf", "state": "Evaluation file under editing", "path": "/path/to/eval_f01_plus.pdf"},
            ],
            "CA334052_F01+.pdf",
            id="ca334052_prefers_plus_revision_with_override",
        ),
    ],
)
def test_drawing_filter_supports_plus_revisions_for_validation_cases(
    part_number: str,
    override_revision: str,
    candidates: List[Dict[str, str]],
    expected_name: str,
):
    cmx_vault = CMXVault.__new__(CMXVault)
    core = part_number[2:] if part_number.startswith("CA") else part_number
    best_match = cmx_vault._find_best_drawing_match(
        part_num_upper=part_number,
        part_data={"core": core},
        candidate_pdfs=candidates,
        revision_overrides={part_number: override_revision},
    )

    assert best_match is not None, f"Expected a drawing match for {part_number} with override {override_revision}."
    assert best_match["name"] == expected_name
    assert best_match["extracted_rev"] == override_revision

def test_generate_bom_validation_revision_overrides_for_CA120776(cmx_vault: CMXVault):
    """
    Regression for validation BOM generation:
    CA334557 should resolve to B01+ (evaluation file under editing)
    CA334052 should resolve to F01+ (evaluation file under editing)
    """
    target_assembly = "CA120776"
    revision_overrides = {
        "CA334557": "B01+",
        "CA334052": "F01+",
    }

    cmx_vault.reset_bom_cache()
    bom = cmx_vault.generate_bom(target_assembly, revision_overrides=revision_overrides)
    assert bom, f"BOM generation returned empty result for {target_assembly}."

    def find_row(part_number: str) -> Optional[Dict[str, str]]:
        normalized_part = part_number.strip().upper()
        for row in bom:
            if str(row.get("Part Number", "")).strip().upper() == normalized_part:
                return row
        return None

    row_334557 = find_row("CA334557")
    assert row_334557 is not None, "Expected part CA334557 in generated BOM."
    assert row_334557.get("Rev", "") == "B01+"
    assert "evaluation file under editing" in str(row_334557.get("State", "")).lower()

    row_334052 = find_row("CA334052")
    assert row_334052 is not None, "Expected part CA334052 in generated BOM."
    assert row_334052.get("Rev", "") == "F01+"
    assert "evaluation file under editing" in str(row_334052.get("State", "")).lower()

@pytest.mark.parametrize(
    "part_number, part_revision, candidates, expected_name",
    [
        pytest.param(
            "CA334557",
            "B01+",
            [
                {"name": "CA334557_A.pdf", "state": "Released", "path": "/path/to/released_a.pdf"},
                {"name": "CA334557_B01+.pdf", "state": "Evaluation file under editing", "path": "/path/to/eval_b01_plus.pdf"},
            ],
            "CA334557_B01+.pdf",
            id="validation_prefers_latest_b01_plus_over_a",
        ),
        pytest.param(
            "CA334052",
            "F01+",
            [
                {"name": "M-CA334052_E.pdf", "state": "Released", "path": "/path/to/released_e.pdf"},
                {"name": "M-CA334052_F01+.pdf", "state": "Evaluation file under editing", "path": "/path/to/eval_f01_plus.pdf"},
            ],
            "M-CA334052_F01+.pdf",
            id="validation_prefers_latest_f01_plus_over_e",
        ),
    ],
)
def test_validation_mode_selects_latest_revision_without_overrides(
    part_number: str,
    part_revision: str,
    candidates: List[Dict[str, str]],
    expected_name: str,
):
    cmx_vault = CMXVault.__new__(CMXVault)
    cmx_vault.valid_exclude_flags = {"valid_state": False}
    core = part_number[2:] if part_number.startswith("CA") else part_number
    best_match = cmx_vault._find_best_drawing_match(
        part_num_upper=part_number,
        part_data={"core": core, "rev": part_revision},
        candidate_pdfs=candidates,
        revision_overrides={},
    )

    assert best_match is not None
    assert best_match["name"] == expected_name

def test_validation_mode_returns_none_when_drawing_for_part_revision_is_missing():
    cmx_vault = CMXVault.__new__(CMXVault)
    cmx_vault.valid_exclude_flags = {"valid_state": False}
    best_match = cmx_vault._find_best_drawing_match(
        part_num_upper="CA334557",
        part_data={"core": "334557", "rev": "B"},
        candidate_pdfs=[{"name": "CA334557_A.pdf", "state": "Released", "path": "/path/to/released_a.pdf"}],
        revision_overrides={},
    )
    assert best_match is None

def test_generate_bom_validation_prefers_latest_revision_without_overrides_for_CA120776(cmx_vault: CMXVault):
    """
    Validation BOM regression:
    Without revision overrides, Validation mode should still pick latest revision drawings.
    """
    target_assembly = "CA120776"
    cmx_vault.reset_bom_cache()
    cmx_vault.set_exclude_flags(valid_state=False)
    bom = cmx_vault.generate_bom(target_assembly, revision_overrides={})
    assert bom, f"BOM generation returned empty result for {target_assembly}."

    for target_part in ("CA334557", "CA334052"):
        expected_rev = str(cmx_vault.computed_bom_cache.get(target_part, {}).get("Revision", "")).strip().upper()
        assert expected_rev, f"Expected computed BOM cache revision for {target_part}."
        rows = [r for r in bom if str(r.get("Part Number", "")).strip().upper() == target_part]
        assert rows, f"Expected part {target_part} in generated BOM."
        assert all(str(r.get("Rev", "")).strip().upper() == expected_rev for r in rows), (
            f"Expected {target_part} rev to follow part revision '{expected_rev}' when validation drawing is missing."
        )