import builtins
from pdm_api.pdm_vault import PDMVault
from pdm_api import utils 
from pdm_api.exceptions import PDMError, PDMFileInfoError, PDMCastError, PDMFileNotFoundError
import os
from collections import defaultdict
from typing import Optional, Union, Any, Dict, List, Iterator, Tuple
import re
try:
    if os.environ.get("PDM_FORCE_HTTP", "").strip().lower() in ("1", "true", "yes", "on"):
        raise ImportError("PDM_FORCE_HTTP enabled; skipping COM imports.")
    from EPDM.Interop.epdm import (
        IEdmFile17,
        EdmObjectType,
        IEdmFolder5,
        IEdmUser5,
        EdmBomFlag,
        IEdmBom,
        IEdmBomView3,
        IEdmBomCell,
        EdmBomColumnType,
        IEdmEnumeratorVersion5,
        IEdmRevision5,
    )
except Exception:
    from pdm_api.pdm_vault import (
        IEdmFile17,
        EdmObjectType,
        IEdmFolder5,
        IEdmUser5,
        EdmBomFlag,
        IEdmBom,
        IEdmBomView3,
        IEdmBomCell,
        EdmBomColumnType,
        IEdmEnumeratorVersion5,
        IEdmRevision5,
    )
import time
from pdm_api.custom_profiler import profile

class CMXVault(PDMVault):
    
    def __init__(self,username,password,vault_name, use_http: Optional[bool] = None):
        # Backward compatibility: some environments may still have a PDMVault
        # base class without the newer `use_http` parameter.
        try:
            super().__init__(username, password, vault_name, use_http=use_http)
        except TypeError as exc:
            if "unexpected keyword argument 'use_http'" not in str(exc):
                raise
            super().__init__(username, password, vault_name)
        self._bom_header = ["Row ID", "Pos", "Part Number", "Rev", "Qty", "Tot", "Part Description", "State", "Drawing"]
        if getattr(self, "_use_http", False):
            self._cad_dir = "/CAD"
            self._released_docs_dir = "/Released documents"
            self._doc_dir = "/Product Documentation"
        else:
            self._cad_dir = f"C:\\{self._vault_name}\\CAD"
            self._released_docs_dir = f"C:\\{self._vault_name}\\Released documents"
            self._doc_dir = f"C:\\{self._vault_name}\\Product Documentation"
        self.computed_bom_cache = {}
        self.derived_bom_cache = {}
        # Cache for "force latest" reference tree resolution by FoundPath.
        # Key: full FoundPath; Value: IEdmReference11 root for that file (latest/current)
        self._latest_reference_tree_cache: Dict[str, Any] = {}
        self.indentation_length = 4
        self.valid_exclude_flags = {
            "inserted_parts": True,
            "non_blanks": True,
            "visibility": True,
            "repeated_parts": False,
            "skeleton_parts": True,
            "parts_outside_derived_bom":True
        }
    
    def set_exclude_flags(self, **kwargs):
        if getattr(self, "_use_http", False):
            return
        self.valid_exclude_flags.update(**kwargs)
        
    def reset_bom_cache(self):
        if getattr(self, "_use_http", False):
            return
        self.computed_bom_cache = {}
        self.derived_bom_cache = {}
        self._latest_reference_tree_cache = {}

    def _normalize_revision_overrides(self, revision_overrides: Optional[dict]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        if not isinstance(revision_overrides, dict):
            return normalized

        for raw_part, raw_revision in revision_overrides.items():
            part_num = str(raw_part).strip().upper()
            if not part_num:
                continue
            if part_num[0].isdigit() and not part_num.startswith("CA"):
                part_num = f"CA{part_num}"

            revision = str(raw_revision).strip().upper()
            if not revision:
                continue
            if revision == "SKIP":
                revision = "Skip"
            elif revision == "ACCEPT":
                revision = "Accept"

            normalized[part_num] = revision
        return normalized

    def _get_latest_reference_tree_for_found_path(self, found_path: str) -> Optional[Any]:
        """
        Return a root reference tree for the file at found_path, using the latest/current version.

        This intentionally ignores any parent assembly's pinned VersionRef so that traversal is
        consistent regardless of which assembly you start from.
        """
        if not found_path:
            return None
        cache_key = str(found_path)
        if cache_key in self._latest_reference_tree_cache:
            return self._latest_reference_tree_cache[cache_key]

        try:
            file_obj, folder_obj = self._get_pdm_file_and_folder(found_path)
            if not file_obj or not folder_obj:
                self._latest_reference_tree_cache[cache_key] = None
                return None
            # utils.LATEST_VERSION == 0 ("latest/current")
            ref = self._get_reference_tree_from_object(file_obj, folder_obj, version=utils.LATEST_VERSION)
            self._latest_reference_tree_cache[cache_key] = ref
            return ref
        except Exception:
            # Never fail due to "latest" optimization; fall back to caller-provided reference.
            self._latest_reference_tree_cache[cache_key] = None
            return None
    
    @profile
    def _get_first_path(self,pattern:str,directory:str = None) -> str:
        if directory is None:
            directory = self.root_folder_path
        search_result = self.search_files(filename_pattern = pattern, directory=directory)
        file_info = next(search_result,None)
        if file_info is None:
            raise FileNotFoundError(f"No file found for pattern '{pattern}' in directory '{directory}'")
        return file_info["path"]
    
    def _find_best_drawing_match(self, part_num_upper: str, part_data: dict, candidate_pdfs: list, revision_overrides: dict) -> Optional[dict]:
        """
        Filters a list of candidate PDFs to find the single best drawing for a given part.
        """
        core_num = part_data['core']
    
        # Allow common revision formats like A, B01, F01+ while rejecting malformed forms (e.g. 4B).
        # 1. (?:[A-Z]{1,3}-)?     -> Optional prefix like "TD-" or "M-"
        # 2. (?:CA)?              -> Optional "CA" prefix immediately before the core number
        # 3. ({core_num})         -> The core number (e.g. 334557)
        # 4. [-_]                 -> Separator
        # 5. ([A-Z]+(?:\d{0,2})?\+?) -> Revision (letter-first, optional digits, optional trailing '+')
        validation_regex_template = r"^(?:[A-Z]{{1,3}}-)?(?:CA)?({core_num})[-_]([A-Z]+(?:\d{{0,2}})?\+?)\s*\.PDF$"
        specific_regex = re.compile(validation_regex_template.format(core_num=re.escape(core_num)), re.IGNORECASE)

        valid_drawings = []
        for pdf in candidate_pdfs:
            match = specific_regex.match(pdf.get("name", ""))
            if match:
                pdf['extracted_rev'] = match.group(2).upper()
                valid_drawings.append(pdf)

        if not valid_drawings:
            return None

        state_priority = {"In Production": 1, "Released": 2, "Prototype": 3, "New": 4}
        override_rev = str(revision_overrides.get(part_num_upper, "")).strip().upper()
        target_part_rev = str(part_data.get("rev", "")).strip().upper()
        is_override = bool(override_rev)
        best_match = None
        is_validation_mode = self.valid_exclude_flags.get("valid_state", True) is False
        
        def get_prefix_priority(pdf_name_upper: str) -> int:
            if pdf_name_upper.startswith("M-"):
                return 1  # Priority 1 for 'M-'
            if '-' in pdf_name_upper.split('_')[0]:
                return 2  # Priority 2 for other prefixes like 'TD-'
            return 0      # Priority 0 for no prefix (highest)

        if is_override:
            filtered_candidates = [p for p in valid_drawings if p['extracted_rev'] == override_rev]
            if filtered_candidates:
                filtered_candidates.sort(key=lambda pdf: state_priority.get(pdf.get("state"), 99))
                filtered_candidates.sort(key=lambda pdf: get_prefix_priority(pdf.get("name", "").upper()))
                best_match = filtered_candidates[0]
        else:
            def get_rev_key(rev_string: str) -> tuple:
                match = re.match(r'^([A-Z]+)(\d+)?(\+)?$', rev_string)
                if not match:
                    # Handle purely numeric revisions if encountered
                    if rev_string.isdigit():
                        return ("", int(rev_string), 0)
                    return (rev_string, -1, 0)
                letter_part = match.group(1)
                number_part_str = match.group(2)
                plus_sign = match.group(3)
                number_val = float('inf') if number_part_str is None else int(number_part_str)
                plus_val = 1 if plus_sign else 0
                return (letter_part, number_val, plus_val)

            if is_validation_mode:
                # In validation mode, trust the part's own revision.
                # If no drawing exists for that exact revision, return None so BOM keeps part revision/state.
                if target_part_rev:
                    exact_rev_candidates = [p for p in valid_drawings if p["extracted_rev"] == target_part_rev]
                    if not exact_rev_candidates:
                        return None
                    exact_rev_candidates.sort(key=lambda pdf: state_priority.get(pdf.get("state"), 99))
                    exact_rev_candidates.sort(key=lambda pdf: get_prefix_priority(pdf.get("name", "").upper()))
                    best_match = exact_rev_candidates[0]
                else:
                    best_match = max(
                        valid_drawings,
                        key=lambda pdf: (
                            get_rev_key(pdf['extracted_rev']),
                            -get_prefix_priority(pdf.get("name", "").upper()),
                            -state_priority.get(pdf.get("state"), 99),
                        ),
                    )
            else:
                # Released/Production behavior remains state/prefix oriented.
                valid_drawings.sort(key=lambda pdf: get_rev_key(pdf['extracted_rev']), reverse=True)
                valid_drawings.sort(key=lambda pdf: state_priority.get(pdf.get("state"), 99))
                valid_drawings.sort(key=lambda pdf: get_prefix_priority(pdf.get("name", "").upper()))
                best_match = valid_drawings[0]
        
        return best_match

    @profile
    def _batch_find_drawing_paths(self, all_references: dict, revision_overrides: dict) -> dict:
        # Part 1: Get the exact part number for each component.
        parts_to_find = {}
        for ref_obj in all_references.values():
            if not hasattr(ref_obj, 'Name'): continue
            part_num = ref_obj.Name.rsplit(".", 1)[0] if "." in ref_obj.Name else ref_obj.Name
            part_num_upper = part_num.strip().upper()

            if part_num_upper.startswith("CA8") or part_num_upper.startswith("CA9"): continue

            computed_data = self.computed_bom_cache.get(part_num_upper, {})
            rev = revision_overrides.get(part_num_upper) or computed_data.get("Revision", "")
            if rev and part_num_upper not in parts_to_find:
                # Strip CA prefix for the search core to ensure we match filenames without CA
                core_num = part_num_upper
                if core_num.startswith("CA"):
                    core_num = core_num[2:]
                
                parts_to_find[part_num_upper] = {"rev": rev, "core": core_num}

        if not parts_to_find:
            return {}

        # Part 2: Execute a single broad search to gather all possible candidates.
        unique_core_nums = {v['core'] for v in parts_to_find.values()}
        # Search patterns: *CORE*
        search_patterns = [f"*{core_num}*" for core_num in unique_core_nums]
        
        # PDM search strings have limits. Chunk if necessary, but here we assume it fits.
        giant_search_string = "|".join(search_patterns)
        
        all_candidate_pdfs = []
        # Search in both locations
        for directory in [self._released_docs_dir, self._doc_dir]:
            try:
                results = self.search_files(filename_pattern=f"{giant_search_string}.pdf", directory=directory, recursive=True)
                all_candidate_pdfs.extend(list(results))
            except PDMFileNotFoundError:
                continue

        # Part 3: Loop through each part and use the filter function to find the best match.
        drawing_info_cache = {}
        for part_num_upper, data in parts_to_find.items():
            best_match = self._find_best_drawing_match(part_num_upper, data, all_candidate_pdfs, revision_overrides)
            
            if best_match:
                cache_key = f"{part_num_upper}|{data['rev']}"
                drawing_info_cache[cache_key] = best_match
            
        return drawing_info_cache
    
    @profile
    def _add_total_counts(self,bom,counts):
        for row_data in bom:
            if not counts: return
            part_number = row_data["Part Number"].strip()
            if part_number in counts:
                count = counts.pop(part_number)
                if row_data["Tot"] == "-":
                    row_data["Tot"] = str(count)
                    
    @profile
    def _get_reference_by_part_number(self, part_number: str) -> Optional[Any]:
        path = ""
        try:
            cad_pattern = f"{part_number}.sldasm|{part_number}.sldprt"
            path = self._get_first_path(cad_pattern, directory=self._cad_dir)
        except FileNotFoundError:
            try:
                generic_pattern = f"{part_number}.*"
                path = self._get_first_path(generic_pattern, directory=self.root_folder_path)
            except (FileNotFoundError, PDMError):
                return None
        
        try:
            file_obj, folder_obj = self._get_pdm_file_and_folder(path)
            if not file_obj or not folder_obj: return None
            return self._get_reference_tree_from_object(file_obj, folder_obj)
        except (PDMError) as e:
            return None
    

    @profile
    def generate_bom(self, part_number:str, revision_overrides: Optional[dict] = None) -> list[dict]:
        if getattr(self, "_use_http", False) and getattr(self, "_http", None):
            return self._http.generate_bom(part_number, revision_overrides)
        revision_overrides = self._normalize_revision_overrides(revision_overrides)

        # --- STEP 1: Find the top-level assembly ---
        search_pattern = f"{part_number}.sldasm|{part_number}.sldprt"
        try:
            path = self._get_first_path(search_pattern, directory=self._cad_dir)
        except FileNotFoundError:
            raise PDMFileNotFoundError(f"Top-level part number '{part_number}' not found in CAD directory.")

        file_to_process, folder_obj = self._get_pdm_file_and_folder(path)
        if not file_to_process or not folder_obj:
            raise PDMFileNotFoundError(f"Could not get PDM object for top-level part: {part_number} ({path}).")
        
        top_reference = self._get_reference_tree_from_object(file_to_process, folder_obj)
        if not top_reference:
            raise PDMFileInfoError(f"Could not get PDM reference tree for top-level part: {part_number} ({path}).")

        # --- STEP 2: Pre-fetch ALL data in optimized batches ---
        all_references = {}
        # Collect references using "force latest" resolution to avoid parent-pinned versions
        # causing inconsistent sub-BOMs depending on starting level.
        self._collect_all_references_recursively(top_reference, all_references)
        
        # Batch-update the computed BOM cache (for descriptions, states, etc.)
        for ref_path in all_references.keys():
            if ref_path: self._update_bom_cache(ref_path)

        # Batch-create the derived BOM cache (the first major bottleneck)
        derived_bom_data_cache = {}
        for ref_path, ref_obj in all_references.items():
            derived_bom_data_cache[ref_path] = self._create_derived_bom_cache(ref_obj)
            
        # BATCH FIND ALL DRAWINGS WITH A SINGLE EFFICIENT SEARCH
        drawing_path_cache = self._batch_find_drawing_paths(all_references, revision_overrides)

        # --- STEP 3: Build the BOM using only cached data ---
        bom = []
        counts = defaultdict(int)

        top_ref_path = top_reference.FoundPath
        derived_bom_for_top_level = derived_bom_data_cache.get(top_ref_path, {})
        bom_row, new_count, _, _ = self._create_bom_row("", ord('A'),
                                                      reference=top_reference, file_obj=file_to_process,
                                                      part_number_normalized_key=part_number, 
                                                      derived_bom_of_parent=derived_bom_for_top_level,
                                                      parent_count=1, counts=counts, has_total_count=False,
                                                      revision_overrides=revision_overrides,
                                                      drawing_path_cache=drawing_path_cache)
        bom.append(bom_row)

        initial_children = [c for c in self._get_children_from_reference(top_reference) if self._include(top_reference, c, derived_bom_for_top_level, counts, is_root=True, revision_overrides=revision_overrides)]
        self._add_to_bom_recursively(bom, initial_children, "", ord('B'), derived_bom_for_top_level, new_count, counts, revision_overrides, derived_bom_data_cache, drawing_path_cache)
        
        self._add_total_counts(bom, counts)
        return bom
    
    @profile
    def _create_derived_bom_cache(self, reference: Any) -> Dict[str, Dict[str, str]]:
        if not hasattr(reference, 'Name'): raise ValueError("Invalid reference object passed to _create_derived_bom_cache.")

        result_cache_updates: Dict[str, Dict[str, str]] = {}
        for potential_drawing in self._get_parents_from_reference(reference):
            drawing_path = potential_drawing.FoundPath
            if drawing_path.lower().endswith("slddrw"):
                if drawing_path in self.derived_bom_cache:
                    return self.derived_bom_cache[drawing_path]

                item_count = 0
                for row_item in self.get_derived_bom_data(drawing_path):
                    part_num_val = row_item.get("PART NUMBER")
                    if isinstance(part_num_val, str):
                        result_cache_updates[part_num_val.strip().upper()] = row_item
                        item_count += 1
                if item_count > 0:
                    self.derived_bom_cache[drawing_path] = result_cache_updates
                    break
        return result_cache_updates
    
    def _collect_all_references_recursively(self, reference: Any, collected_refs: dict):
        try:
            # If the reference has no path or we've seen it, stop.
            if not hasattr(reference, 'FoundPath') or not reference.FoundPath or reference.FoundPath in collected_refs:
                return
            
            # Resolve to latest/current reference tree for this FoundPath (cached).
            latest_ref = self._get_latest_reference_tree_for_found_path(reference.FoundPath)
            ref_to_use = latest_ref or reference

            # Store the full reference object, keyed by its unique path.
            collected_refs[ref_to_use.FoundPath] = ref_to_use

            # Get the children and recurse.
            children = self._get_children_from_reference(ref_to_use)
            for child in children:
                self._collect_all_references_recursively(child, collected_refs)
        except Exception:
            # Silently ignore errors during collection, like broken references.
            pass
    
    @profile
    def _add_to_bom_recursively(self, bom: List[Dict[str, str]], children_references: List[Any],
                                  parent_str_id: str, row_id: int,
                                  derived_bom_of_parent: Dict[str, Dict[str, str]], parent_count: int,
                                  counts: Dict[str, int],
                                  revision_overrides: Optional[Dict[str, str]],
                                  master_derived_bom_cache: Dict[str, Any],
                                  drawing_path_cache: Dict[str, str]):

        def sort_key(child: Any) -> tuple[int, Union[int, str]]:
            name = child.Name.split(".")[0].strip().upper()
            if name.startswith("AI-"): return (0, name)
            if name.startswith("CF-"): return (1, name)
            if name.startswith("IP-"): return (2, name)
            if name.startswith("TD-"): return (3, name)
            if name.startswith("TI-"): return (4, name)
            if name in derived_bom_of_parent:
                try:
                    item_no = derived_bom_of_parent[name].get("ITEM NO.")
                    if item_no and str(item_no).strip(): return (5, int(str(item_no).strip()))
                except: pass
            return (6, name)

        # Track part numbers already processed at this level to ignore duplicates (e.g., same part with different configurations)
        processed_part_numbers_at_this_level: set = set()

        for child in sorted(children_references, key=sort_key):
            # Force "latest/current" traversal for this child, ignoring any parent-pinned version.
            # This is the key behavior change that makes sub-BOMs independent of start level.
            child_latest_ref = self._get_latest_reference_tree_for_found_path(getattr(child, "FoundPath", "")) or child

            part_num, _ = child_latest_ref.Name.rsplit(".",1)
            part_num_upper = part_num.strip().upper()
            
            # Skip duplicate part numbers under the same parent (handles multiple configurations of same part)
            if part_num_upper in processed_part_numbers_at_this_level:
                continue
            processed_part_numbers_at_this_level.add(part_num_upper)
            
            file_obj, _ = self._get_pdm_file_and_folder(child_latest_ref.FoundPath)
            if not file_obj: continue

            computed_data = self.computed_bom_cache.get(part_num_upper, {})
            hide_children = self.valid_exclude_flags.get("visibility", True) and computed_data.get("Visibility", "").lower() == "dont show in production"
            has_total = hide_children or computed_data.get("Type", "").lower() in ("sldprt", "vir")
            
            bom_row, qty, str_id, next_row_id = self._create_bom_row(parent_str_id, row_id, 
                                                                  reference=child_latest_ref, file_obj=file_obj,
                                                                  part_number_normalized_key=part_num_upper, 
                                                                  derived_bom_of_parent=derived_bom_of_parent, 
                                                                  parent_count=parent_count, counts=counts, 
                                                                  has_total_count=has_total, 
                                                                  revision_overrides=revision_overrides,
                                                                  drawing_path_cache=drawing_path_cache)
            bom.append(bom_row)
            row_id = next_row_id
            
            if hide_children: continue

            derived_bom_for_child = master_derived_bom_cache.get(child_latest_ref.FoundPath, {})
            
            grandchildren = [
                gc for gc in self._get_children_from_reference(child_latest_ref)
                if self._include(child_latest_ref, gc, derived_bom_for_child, counts, is_root=False, revision_overrides=revision_overrides)
            ]
            if grandchildren:
                self._add_to_bom_recursively(bom, grandchildren, str_id, ord('A'), derived_bom_for_child, qty, counts, revision_overrides, master_derived_bom_cache, drawing_path_cache)

    @profile
    def _create_bom_row(self, parent_str_id: str, row_id: int, reference: Any,
                        file_obj: IEdmFile17,
                        part_number_normalized_key: str,
                        derived_bom_of_parent: Dict[str, Dict[str, str]], parent_count: int,
                        counts: Dict[str, int], has_total_count: bool,
                        revision_overrides: Dict[str, str],
                        drawing_path_cache: Dict[str, dict]) -> tuple[Dict[str, str], int, str, int]:
        
        computed_bom_row_source = self.computed_bom_cache.get(part_number_normalized_key, {})

        # This is the component's revision from the BOM structure, used for lookup.
        bom_rev_for_lookup = revision_overrides.get(part_number_normalized_key) or computed_bom_row_source.get("Revision", "")

        # Get the complete dictionary of the best-matched drawing from the cache.
        drawing_info = drawing_path_cache.get(f"{part_number_normalized_key}|{bom_rev_for_lookup}")

        # --- START: CORRECTED LOGIC FOR BOM ROW DATA ---
        if drawing_info:
            # If a drawing was found, use ITS data for Rev, State, and Drawing fields.
            final_rev_for_bom = drawing_info.get("extracted_rev", bom_rev_for_lookup)
            actual_state = drawing_info.get("state", computed_bom_row_source.get("State", "Unknown State"))
            final_drawing_path = drawing_info.get("path", "")
            final_drawing_name = os.path.basename(final_drawing_path)
        else:
            # If no drawing was found, use the component's original data.
            final_rev_for_bom = bom_rev_for_lookup
            actual_state = computed_bom_row_source.get("State", "Unknown State")
            final_drawing_path = ""
            final_drawing_name = ""
        # --- END: CORRECTED LOGIC ---

        derived_bom_row = derived_bom_of_parent.get(part_number_normalized_key)

        pos, leaf_row_id_component, current_qty_for_calc, qty_display_str = "", "", 1, "1"
        if derived_bom_row:
            pos = str(derived_bom_row.get("ITEM NO.", "")).strip()
            leaf_row_id_component = pos
            qty_from_derived_str = derived_bom_row.get("QTY.") or derived_bom_row.get("Default/QTY.", "1")
            qty_display_str = str(qty_from_derived_str)
            current_qty_for_calc = int(qty_display_str.strip()) if qty_display_str.strip().isdigit() else 1
        else:
            assigned_char_id = chr(row_id)
            leaf_row_id_component = assigned_char_id
            row_id += 1

        multiplied_qty_for_this_level = parent_count * current_qty_for_calc
        counts[part_number_normalized_key] += multiplied_qty_for_this_level

        str_id = ".".join([parent_str_id, leaf_row_id_component]).strip(".")
        indent = " " * (self.indentation_length * str_id.count("."))
        display_part_number = computed_bom_row_source.get("Part Number", reference.Name.rsplit(".", 1)[0])

        row = {
            "Row ID": str_id,
            "Pos": pos,
            "Part Number": indent + display_part_number,
            "Rev": final_rev_for_bom,
            "Qty": qty_display_str,
            "Tot": "-" if has_total_count else "",
            "Part Description": computed_bom_row_source.get("Description", ""),
            "State": actual_state,
            "Drawing": final_drawing_name,
            "Drawing Path": final_drawing_path,
            "Approved By": computed_bom_row_source.get("Approved by", "")
        }
        return row, multiplied_qty_for_this_level, str_id, row_id
    
    def _include(self, parent: Any, reference: Any, derived_bom_cache: dict, counts: dict, is_root: bool, revision_overrides: dict) -> bool:
        if not hasattr(reference, 'Name') or not isinstance(reference.Name, str) or "." not in reference.Name:
            return False

        part_num, ext = reference.Name.rsplit(".", 1)
        part_num = part_num.strip().upper()

        if revision_overrides and revision_overrides.get(part_num) == "Skip":
            return False

        if ext.lower() in ("sldblk", "cwr"): return False
        if part_num not in self.computed_bom_cache: self._update_bom_cache(reference.FoundPath)
        info = self.computed_bom_cache.get(part_num)
        if not info: return False
        if info.get("State", "").upper() in {"OBSOLETE"}: return False

        parent_num = parent.Name.rsplit(".",1)[0].strip().upper() if hasattr(parent,'Name') else ""
        p_info = self.computed_bom_cache.get(parent_num)
        if not p_info and not is_root: return False
        
        p_type = (p_info.get("Type", "") if p_info else "").upper()
        blank = (p_info.get("Blank", "") if p_info else "").upper()
        
        conditions = {
            "manual": re.search("CF-CA.*V", part_num) is None,
            "inserted": not (self.valid_exclude_flags.get("inserted_parts") and p_type == "SLDPRT" and part_num.startswith("CA")),
            "non_blanks": not (self.valid_exclude_flags.get("non_blanks") and blank.strip() != part_num and p_type == "SLDPRT" and part_num.startswith("CA")),
            "repeated": not (self.valid_exclude_flags.get("repeated_parts") and part_num in counts),
            "skeleton": not (self.valid_exclude_flags.get("skeleton_parts") and "SKELETT" in info.get("Description", "").upper())
        }
        return all(conditions.values())
    
    @profile
    def _update_bom_cache(self, path:str) -> None:
        part_num_from_path = os.path.basename(path).rsplit(".", 1)[0].upper()
        if part_num_from_path in self.computed_bom_cache:
            return

        file_obj, _ = self._get_pdm_file_and_folder(path)
        if not file_obj: return

        data_iter = self.get_computed_bom_data(file_obj=file_obj, bom_layout_name="Complete BOM")
        updates = {row.get("Part Number","").strip().upper(): row for row in data_iter if isinstance(row.get("Part Number"), str)}
        self.computed_bom_cache.update(updates)