$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'README 순서대로 .venv와 의존성을 먼저 설치하세요.' }
Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Force build | Out-Null
    & $pythonPath -c "import icons; icons.write_ico('build/PDF-Moa.ico')"
    if ($LASTEXITCODE -ne 0) { throw '아이콘 생성 실패' }
    & $pythonPath -m PyInstaller --noconfirm --onefile --windowed --icon build/PDF-Moa.ico --exclude-module pandas --collect-all tkinterdnd2 --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all pymupdf --name PDF-Moa app.py
    if ($LASTEXITCODE -ne 0) { throw '빌드 실패' }
} finally { Pop-Location }
