import os
import tempfile
import threading
import time
import logging
import traceback
from typing import Dict, Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from pdm_api.cmx_vault import CMXVault
from pdm_api.pdm_vault import PDMVault
from pdm_api.exceptions import (
    PDMError,
    PDMConnectionError,
    PDMFileNotFoundError,
    PDMFileExistsError,
    PDMOperationFailedError,
)


app = FastAPI(title="PDM API Server", version="1.0.0")

_vault_lock = threading.Lock()

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_log_path = os.path.join(_repo_root, "log.txt")
_logger = logging.getLogger("pdm_api.server")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _file_handler = logging.FileHandler(_log_path, encoding="utf-8")
    _file_handler.setLevel(logging.INFO)
    _formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    _file_handler.setFormatter(_formatter)
    _logger.addHandler(_file_handler)


def _log_info(message: str) -> None:
    _logger.info(message)


def _log_error(message: str) -> None:
    _logger.error(message)


def _load_root_env() -> None:
    env_path = os.path.join(_repo_root, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_root_env()


class VaultAuth(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    vault_name: str = Field(..., min_length=1)


class SearchRequest(VaultAuth):
    filename_pattern: Optional[str] = None
    directory: Optional[str] = None
    recursive: bool = True
    variable_conditions: Optional[Dict[str, str]] = None


class FilePathRequest(VaultAuth):
    filepath: str = Field(..., min_length=1)


class CreateFolderRequest(VaultAuth):
    folder_path: str = Field(..., min_length=1)


class FolderPathRequest(VaultAuth):
    folder_path: str = Field(..., min_length=1)


class SetVariableRequest(VaultAuth):
    filepath: str = Field(..., min_length=1)
    var_name: str = Field(..., min_length=1)
    var_value: str
    configuration: str = "Default"


class BomRequest(VaultAuth):
    part_number: str = Field(..., min_length=1)
    revision_overrides: Optional[Dict[str, str]] = None


def _get_vault(auth: VaultAuth, use_cmx: bool = False):
    # Create a new vault per request. Reusing a cached vault can leave the PDM connection
    # in a bad state so the second request hangs (works first time, not after).
    vault = CMXVault(auth.username, auth.password, auth.vault_name) if use_cmx else PDMVault(
        auth.username, auth.password, auth.vault_name
    )
    return vault


def _run_with_lock(fn, *args, **kwargs):
    with _vault_lock:
        return fn(*args, **kwargs)


def _raise_http_error(err: Exception) -> None:
    _log_error(f"PDM API error: {err}")
    if isinstance(err, PDMFileNotFoundError):
        raise HTTPException(status_code=404, detail=str(err))
    if isinstance(err, PDMFileExistsError):
        raise HTTPException(status_code=409, detail=str(err))
    if isinstance(err, (PDMConnectionError, PDMOperationFailedError, PDMError)):
        raise HTTPException(status_code=400, detail=str(err))
    raise HTTPException(status_code=500, detail=str(err))


def _vault_root(vault_name: str) -> str:
    base = os.environ.get("PDM_VAULT_ROOT", "").strip()
    if not base:
        return os.path.normpath(f"C:\\{vault_name}")
    return os.path.normpath(os.path.join(base, vault_name))


def _normalize_directory(vault_name: str, directory: Optional[str]) -> Optional[str]:
    if not directory:
        return directory
    normalized = directory.strip()
    if not normalized:
        return None
    vault_root = _vault_root(vault_name)
    if normalized.startswith(("./", ".\\")):
        normalized = normalized[2:]
        if not normalized:
            return vault_root
    if normalized.startswith(("/", "\\")):
        return os.path.normpath(os.path.join(vault_root, normalized.lstrip("/\\")))
    if not os.path.isabs(normalized):
        return os.path.normpath(os.path.join(vault_root, normalized))
    return os.path.normpath(normalized)


def _require_api_key(request: Request) -> None:
    expected = os.environ.get("PDM_API_KEY", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-API-Key", "")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    start = time.perf_counter()
    if request.url.path != "/health":
        try:
            _require_api_key(request)
        except HTTPException as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log_info(f"{request.method} {request.url.path} -> {exc.status_code} ({elapsed_ms} ms)")
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_error(f"{request.method} {request.url.path} -> 500 ({elapsed_ms} ms) {exc}")
        _log_error(traceback.format_exc())
        raise
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    _log_info(f"{request.method} {request.url.path} -> {response.status_code} ({elapsed_ms} ms)")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/pdm/search")
def search_files(request: SearchRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        directory = _normalize_directory(request.vault_name, request.directory)
        _log_info(
            f"search: vault='{request.vault_name}' dir='{directory}' pattern='{request.filename_pattern}' recursive={request.recursive}"
        )
        results = _run_with_lock(
            lambda: list(
                vault.search_files(
                    filename_pattern=request.filename_pattern,
                    variable_conditions=request.variable_conditions,
                    directory=directory,
                    recursive=request.recursive,
                )
            )
        )
        return {"count": len(results), "results": results}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/file-info")
def file_info(request: FilePathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        info = _run_with_lock(lambda: vault.get_file_info(request.filepath))
        if info is None:
            raise PDMFileNotFoundError(f"File not found: '{request.filepath}'")
        return info
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/vault-root")
def vault_root(request: VaultAuth):
    try:
        vault = _get_vault(request, use_cmx=False)
        return {"root_folder_path": vault.root_folder_path}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/children")
def get_children(request: FilePathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        results = _run_with_lock(lambda: list(vault.get_children(request.filepath)))
        return {"count": len(results), "results": results}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/parents")
def get_parents(request: FilePathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        results = _run_with_lock(lambda: list(vault.get_parents(request.filepath)))
        return {"count": len(results), "results": results}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/create-folders")
def create_folders(request: CreateFolderRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        created = _run_with_lock(lambda: vault.create_folders(request.folder_path))
        return {"created": bool(created)}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/files-in-folder")
def files_in_folder(request: FolderPathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        results = _run_with_lock(lambda: list(vault.get_files_in_folder(request.folder_path)))
        return {"count": len(results), "results": results}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/subfolders-in-folder")
def subfolders_in_folder(request: FolderPathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        results = _run_with_lock(lambda: list(vault.get_subfolders_in_folder(request.folder_path)))
        return {"count": len(results), "results": results}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/delete-empty-folder-structure")
def delete_empty_folder_structure(request: FolderPathRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        deleted = _run_with_lock(lambda: vault.delete_empty_folder_structure(request.folder_path))
        return {"deleted": bool(deleted)}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/set-variable")
def set_variable(request: SetVariableRequest):
    try:
        vault = _get_vault(request, use_cmx=False)
        _run_with_lock(
            lambda: vault.set_variable(
                filepath=request.filepath,
                var_name=request.var_name,
                var_value=request.var_value,
                configuration=request.configuration,
            )
        )
        return {"status": "ok"}
    except Exception as err:
        _raise_http_error(err)


@app.post("/pdm/download")
def download_file(request: FilePathRequest):
    temp_dir = tempfile.mkdtemp(prefix="pdm_download_")
    try:
        vault = _get_vault(request, use_cmx=False)
        _log_info(f"download: vault='{request.vault_name}' filepath='{request.filepath}' temp='{temp_dir}'")
        local_path = _run_with_lock(lambda: vault.get_local_copy(request.filepath, temp_dir))
        _log_info(f"download complete: local_path='{local_path}'")
        filename = os.path.basename(local_path)
        cleanup = BackgroundTask(lambda: _cleanup_temp_dir(temp_dir))
        return FileResponse(local_path, filename=filename, background=cleanup)
    except Exception as err:
        _cleanup_temp_dir(temp_dir)
        _raise_http_error(err)


@app.post("/pdm/upload")
def upload_file(
    username: str = Form(...),
    password: str = Form(...),
    vault_name: str = Form(...),
    target_folder_path: str = Form(...),
    new_filename: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    temp_dir = tempfile.mkdtemp(prefix="pdm_upload_")
    try:
        auth = VaultAuth(username=username, password=password, vault_name=vault_name)
        vault = _get_vault(auth, use_cmx=False)
        local_path = os.path.join(temp_dir, file.filename)
        with open(local_path, "wb") as f:
            f.write(file.file.read())
        pdm_path = _run_with_lock(
            lambda: vault.import_file_to_pdm(
                local_filepath=local_path,
                pdm_dest_folder_path=target_folder_path,
                new_filename=new_filename,
            )
        )
        return {"path": pdm_path}
    except Exception as err:
        _raise_http_error(err)
    finally:
        _cleanup_temp_dir(temp_dir)


@app.post("/cmx/generate-bom")
def generate_bom(request: BomRequest):
    try:
        vault = _get_vault(request, use_cmx=True)
        bom = _run_with_lock(lambda: vault.generate_bom(request.part_number, request.revision_overrides))
        return {"count": len(bom), "results": bom}
    except Exception as err:
        _raise_http_error(err)


def _cleanup_temp_dir(path: str) -> None:
    try:
        if path and os.path.isdir(path):
            for root, dirs, files in os.walk(path, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(path)
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("PDM_API_HOST", "0.0.0.0")
    port = int(os.environ.get("PDM_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
