# 올리기 전 검사 한 번에: CI 와 같은 순서로 엔진 → 화면 → 데스크톱을 검사한다.
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1          # 검사만
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Fix     # 포맷·자동 수정 먼저
param([switch]$Fix)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$failed = @()

function Step($name, $dir, [scriptblock]$body) {
  Write-Host "`n== $name" -ForegroundColor Cyan
  Push-Location (Join-Path $root $dir)
  try { & $body; if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" } ; Write-Host "   ok" -ForegroundColor Green }
  catch { Write-Host "   실패: $_" -ForegroundColor Red; $script:failed += $name }
  finally { Pop-Location }
}

if ($Fix) {
  Step "엔진 포맷·자동 수정" "." { & $py -m ruff format . ; & $py -m ruff check . --fix }
  Step "화면 포맷" "app" { npm run format }
  Step "데스크톱 포맷" "desktop" { npm run format }
}

Step "엔진 lint" "." { & $py -m ruff check . }
Step "엔진 포맷" "." { & $py -m ruff format --check . }
Step "엔진 테스트" "." { & $py -m pytest }
Step "화면 포맷" "app" { npm run format:check }
Step "화면 lint" "app" { npm run lint }
Step "화면 테스트" "app" { npm test }
Step "화면 빌드" "app" { npm run build }
Step "데스크톱 포맷" "desktop" { npm run format:check }
Step "데스크톱 lint" "desktop" { npm run lint }
Step "데스크톱 테스트" "desktop" { npm test }

if ($failed.Count) { Write-Host "`n실패: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "`n전부 통과했어요." -ForegroundColor Green
