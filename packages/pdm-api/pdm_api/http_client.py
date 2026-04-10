import os
import re
import json
from pdm_api import utils
from typing import Dict, Optional, Iterable, Any
from urllib.parse import urljoin

import requests

from pdm_api.exceptions import (
    PDMError,
    PDMConnectionError,
    PDMFileNotFoundError,
    PDMFileExistsError,
    PDMOperationFailedError,
)


def _read_timeout_env(default: int = 60) -> int:
    raw = os.environ.get("PDM_HTTP_TIMEOUT", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


class HttpPdmClient:
    def __init__(self, base_url: str, username: str, password: str, vault_name: str, timeout: int = 60):
        self._base_url = base_url.rstrip("/") + "/"
        self._username = username
        self._password = password
        self._vault_name = vault_name
        self._timeout = timeout
        self._api_key = os.environ.get("PDM_API_KEY", "").strip()
        self._trace_http = os.environ.get("PDM_HTTP_TRACE", "").strip().lower() in ("1", "true", "yes", "on")

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, val in value.items():
                key_lower = str(key).lower()
                if key_lower in {"password", "api_key", "x-api-key"}:
                    redacted[key] = "***"
                else:
                    redacted[key] = self._redact(val)
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _trace(self, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self._trace_http:
            return
        if payload is None:
            utils.log(message, ext="_http_trace")
            return
        try:
            utils.log(f"{message} {json.dumps(self._redact(payload), ensure_ascii=True)}", ext="_http_trace")
        except Exception:
            utils.log(message, ext="_http_trace")

    @classmethod
    def from_env(cls, username: str, password: str, vault_name: str, timeout: int = 60) -> "HttpPdmClient":
        base_url = os.environ.get("PDM_API_URL", "").strip()
        if not base_url:
            raise PDMConnectionError(
                "PDM API URL is not configured. Set PDM_API_URL to the server base URL."
            )
        api_key = os.environ.get("PDM_API_KEY", "").strip()
        if not api_key:
            raise PDMConnectionError(
                "PDM API key is not configured. Set PDM_API_KEY to authenticate."
            )
        resolved_timeout = _read_timeout_env(timeout)
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            vault_name=vault_name,
            timeout=resolved_timeout,
        )

    def _url(self, path: str) -> str:
        return urljoin(self._base_url, path.lstrip("/"))

    def _auth_payload(self) -> Dict[str, Any]:
        return {
            "username": self._username,
            "password": self._password,
            "vault_name": self._vault_name,
        }

    def _raise_for_response(self, response: requests.Response) -> None:
        detail = None
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
        except Exception:
            detail = response.text.strip() or None

        message = detail or f"HTTP {response.status_code} from PDM API"
        if response.status_code == 404:
            raise PDMFileNotFoundError(message)
        if response.status_code == 409:
            raise PDMFileExistsError(message)
        if response.status_code in (400, 422):
            raise PDMOperationFailedError(message)
        raise PDMError(message)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {}) or {}
        if self._api_key and "X-API-Key" not in headers:
            headers["X-API-Key"] = self._api_key
        file_info = None
        if "files" in kwargs and isinstance(kwargs["files"], dict):
            file_info = {key: getattr(val, "name", None) if hasattr(val, "name") else None for key, val in kwargs["files"].items()}
        self._trace(
            "HTTP ->",
            {
                "method": method,
                "url": self._url(path),
                "params": kwargs.get("params"),
                "json": kwargs.get("json"),
                "data": kwargs.get("data"),
                "files": file_info,
                "headers": headers,
            },
        )
        try:
            response = requests.request(
                method,
                self._url(path),
                timeout=self._timeout,
                headers=headers,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise PDMConnectionError(f"PDM API request failed: {exc}") from exc

        if response.status_code >= 400:
            self._raise_for_response(response)
        content_type = response.headers.get("content-type", "")
        body_preview = None
        if "application/json" in content_type:
            try:
                body_preview = response.json()
            except Exception:
                body_preview = response.text[:2000]
        elif "text/" in content_type:
            body_preview = response.text[:2000]
        else:
            body_preview = f"<{content_type or 'binary'} {len(response.content)} bytes>"
        self._trace("HTTP <-", {"status": response.status_code, "body": body_preview})
        return response

    def search_files(
        self,
        filename_pattern: Optional[str],
        variable_conditions: Optional[Dict[str, str]],
        directory: Optional[str],
        recursive: bool,
    ) -> Iterable[Dict[str, str]]:
        payload = {
            **self._auth_payload(),
            "filename_pattern": filename_pattern,
            "directory": directory,
            "recursive": recursive,
            "variable_conditions": variable_conditions,
        }
        response = self._request("POST", "/pdm/search", json=payload)
        data = response.json()
        return data.get("results", [])

    def get_file_info(self, filepath: str) -> Optional[Dict[str, Any]]:
        payload = {**self._auth_payload(), "filepath": filepath}
        response = self._request("POST", "/pdm/file-info", json=payload)
        return response.json()

    def get_vault_root(self) -> str:
        payload = self._auth_payload()
        response = self._request("POST", "/pdm/vault-root", json=payload)
        return response.json().get("root_folder_path", "")

    def get_children(self, filepath: str) -> Iterable[Dict[str, str]]:
        payload = {**self._auth_payload(), "filepath": filepath}
        response = self._request("POST", "/pdm/children", json=payload)
        return response.json().get("results", [])

    def get_parents(self, filepath: str) -> Iterable[Dict[str, str]]:
        payload = {**self._auth_payload(), "filepath": filepath}
        response = self._request("POST", "/pdm/parents", json=payload)
        return response.json().get("results", [])

    def create_folders(self, folder_path: str) -> bool:
        payload = {**self._auth_payload(), "folder_path": folder_path}
        response = self._request("POST", "/pdm/create-folders", json=payload)
        return bool(response.json().get("created", False))

    def get_files_in_folder(self, folder_path: str) -> Iterable[str]:
        payload = {**self._auth_payload(), "folder_path": folder_path}
        response = self._request("POST", "/pdm/files-in-folder", json=payload)
        return response.json().get("results", [])

    def get_subfolders_in_folder(self, folder_path: str) -> Iterable[str]:
        payload = {**self._auth_payload(), "folder_path": folder_path}
        response = self._request("POST", "/pdm/subfolders-in-folder", json=payload)
        return response.json().get("results", [])

    def delete_empty_folder_structure(self, folder_path: str) -> bool:
        payload = {**self._auth_payload(), "folder_path": folder_path}
        response = self._request("POST", "/pdm/delete-empty-folder-structure", json=payload)
        return bool(response.json().get("deleted", False))

    def set_variable(self, filepath: str, var_name: str, var_value: Any, configuration: str) -> None:
        payload = {
            **self._auth_payload(),
            "filepath": filepath,
            "var_name": var_name,
            "var_value": var_value,
            "configuration": configuration,
        }
        self._request("POST", "/pdm/set-variable", json=payload)

    def download_file(
        self, pdm_filepath: str, local_dest_dir: str, new_filename: Optional[str]
    ) -> str:
        payload = {**self._auth_payload(), "filepath": pdm_filepath}
        response = self._request("POST", "/pdm/download", json=payload, stream=True)

        if not os.path.isdir(local_dest_dir):
            os.makedirs(local_dest_dir, exist_ok=True)

        filename = new_filename
        if not filename:
            content_disposition = response.headers.get("content-disposition", "")
            match = re.search(r'filename="?(?P<name>[^"]+)"?', content_disposition, re.IGNORECASE)
            if match:
                filename = match.group("name")
            else:
                filename = os.path.basename(pdm_filepath)

        local_path = os.path.join(local_dest_dir, filename)
        with open(local_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        return local_path

    def upload_file(
        self, local_filepath: str, target_folder_path: str, new_filename: Optional[str]
    ) -> str:
        if not os.path.exists(local_filepath):
            raise PDMFileNotFoundError(f"Local source file not found: '{local_filepath}'")

        data = {
            **self._auth_payload(),
            "target_folder_path": target_folder_path,
        }
        if new_filename:
            data["new_filename"] = new_filename

        with open(local_filepath, "rb") as handle:
            files = {"file": (os.path.basename(local_filepath), handle, "application/octet-stream")}
            response = self._request("POST", "/pdm/upload", data=data, files=files)
        payload = response.json()
        return payload.get("path", "")

    def generate_bom(self, part_number: str, revision_overrides: Optional[Dict[str, str]]) -> list[Dict[str, Any]]:
        payload = {
            **self._auth_payload(),
            "part_number": part_number,
            "revision_overrides": revision_overrides,
        }
        response = self._request("POST", "/cmx/generate-bom", json=payload)
        return response.json().get("results", [])
