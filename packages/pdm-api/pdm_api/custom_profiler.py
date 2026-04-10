import time
import atexit
import csv
from functools import wraps
import os
from collections import OrderedDict

# --- Global Profiler State ---
# Set this to False to disable the profiler entirely.
PROFILING_ENABLED = False

PROFILING_DATA = OrderedDict()
CALL_STACK = []
# Separate counters for top-level calls.
TOP_LEVEL_CLASS_COUNTER = 0
TOP_LEVEL_FUNC_COUNTER = 0

# --- Configuration ---
# Safely determine the project root. Assumes this script is within the project structure.
try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    # Fallback for environments where __file__ is not defined (e.g., some notebooks)
    PROJECT_ROOT = os.getcwd()

OUTPUT_FILENAME = os.path.join(PROJECT_ROOT, "profiling_report.csv")


def profile(func):
    """
    A decorator that profiles a function's execution time, call count, and
    position in the call hierarchy, writing the results to a CSV report.
    Can be disabled by setting the global PROFILING_ENABLED flag to False.
    """
    # If profiling is disabled, return the original function immediately.
    if not PROFILING_ENABLED:
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        global TOP_LEVEL_CLASS_COUNTER, TOP_LEVEL_FUNC_COUNTER

        # --- Step 1: Determine the function's ID in the call hierarchy ---
        parent_frame = CALL_STACK[-1] if CALL_STACK else None
        
        if parent_frame is None:
            # This is a top-level call.
            is_method = '.' in func.__qualname__
            if is_method:
                TOP_LEVEL_CLASS_COUNTER += 1
                hierarchical_id = chr(ord('A') + TOP_LEVEL_CLASS_COUNTER - 1)
            else:
                TOP_LEVEL_FUNC_COUNTER += 1
                hierarchical_id = str(TOP_LEVEL_FUNC_COUNTER)
        else:
            # This is a nested call.
            parent_id = parent_frame['hierarchical_id']
            children_map = parent_frame['children_map']
            func_qualname = func.__qualname__
            
            # Get or assign a stable child number for this function within its parent.
            if func_qualname not in children_map:
                children_map[func_qualname] = len(children_map) + 1
            child_number = children_map[func_qualname]
            
            hierarchical_id = f"{parent_id}.{child_number}"

        # --- Step 2: Initialize or retrieve the data node for this function call ---
        if hierarchical_id not in PROFILING_DATA:
            PROFILING_DATA[hierarchical_id] = {
                'name': func.__qualname__,
                'parent_id': parent_frame['hierarchical_id'] if parent_frame else None,
                'call_count': 0,
                'total_time_ns': 0,
                'self_time_ns': 0,
            }
        node = PROFILING_DATA[hierarchical_id]
        node['call_count'] += 1

        # --- Step 3: Push to stack and execute the function ---
        start_ns = time.perf_counter_ns()
        # Each frame on the stack needs its own map to track its direct children.
        CALL_STACK.append({'hierarchical_id': hierarchical_id, 'children_map': {}})

        try:
            result = func(*args, **kwargs)
        finally:
            # --- Step 4: Pop from stack and update timing stats ---
            end_ns = time.perf_counter_ns()
            total_duration_ns = end_ns - start_ns

            CALL_STACK.pop()

            node['total_time_ns'] += total_duration_ns
            node['self_time_ns'] += total_duration_ns # Temporarily add total time.

            # If this was a nested call, subtract its total time from its parent's self_time.
            if parent_frame and parent_frame['hierarchical_id'] in PROFILING_DATA:
                parent_node = PROFILING_DATA[parent_frame['hierarchical_id']]
                parent_node['self_time_ns'] -= total_duration_ns

            # --- Step 5: Update the report on disk ---
            # If the call stack is empty, a full top-level operation has completed.
            if not CALL_STACK:
                generate_report()
        
        return result
    return wrapper

def generate_report():
    """
    Writes the current state of the profiling data to the CSV file,
    sorted hierarchically.
    """
    if not PROFILING_DATA:
        return

    def natural_sort_key(item):
        """Sorts IDs like 'A.10' after 'A.9'."""
        hid = item[0]
        parts = []
        # Split by '.' and convert numeric parts to integers for correct sorting.
        for part in hid.split('.'):
            try:
                # Try to convert the part to an integer.
                parts.append(int(part))
            except ValueError:
                # If it fails (e.g., for 'A'), treat it as a string.
                parts.append(part)
        return parts

    sorted_items = sorted(PROFILING_DATA.items(), key=natural_sort_key)
    
    temp_filename = OUTPUT_FILENAME + ".tmp"
    
    try:
        print(f"[Profiler] Writing {len(sorted_items)} rows to {OUTPUT_FILENAME}...")
        with open(temp_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Function", "Call Count",
                "Total Time (s)", "Self Time (s)", "Parent ID"
            ])

            for hid, node in sorted_items:
                writer.writerow([
                    hid,
                    node['name'],
                    node['call_count'],
                    f"{node['total_time_ns'] / 1e9:.6f}",
                    f"{node['self_time_ns'] / 1e9:.6f}",
                    node['parent_id'] if node['parent_id'] else "TOP",
                ])
        
        os.replace(temp_filename, OUTPUT_FILENAME)

    except (IOError, PermissionError) as e:
        print(f"[Profiler] ERROR: Could not write to {OUTPUT_FILENAME}: {e}")
    finally:
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except OSError:
                pass

def finalize_profiling():
    """
    Explicitly saves the final profiling report. Call this at the end of your
    script or test suite for guaranteed output.
    """
    print("[Profiler] Finalizing report...")
    generate_report()

# Only register the exit function if profiling is actually enabled.
if PROFILING_ENABLED:
    atexit.register(finalize_profiling)
