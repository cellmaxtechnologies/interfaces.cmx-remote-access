$ErrorActionPreference = "Stop"

Write-Host "Building pdm-api-server with PyInstaller (poetry venv)..."

poetry lock
poetry install
poetry run python -m pip install --upgrade pip
poetry run python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib cffi

poetry run python -m PyInstaller --clean --noconfirm ".\pdm_api_server.spec"

Copy-Item ".\install_service.ps1" ".\dist\pdm-api-server\install_service.ps1" -Force
Copy-Item ".\uninstall_service.ps1" ".\dist\pdm-api-server\uninstall_service.ps1" -Force

Write-Host "Build complete. Output in dist\pdm-api-server"
