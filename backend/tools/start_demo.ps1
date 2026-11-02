# 시연 시작: 가짜 데이터(시연 DB)로 서버와 화면을 켜고 브라우저를 엽니다. 실제 DB(Supabase)에는 연결하지 않습니다.
#
# 사용법 (PowerShell, 어느 폴더에서든):
#   powershell -ExecutionPolicy Bypass -File backend\tools\start_demo.ps1            켜기 (시연 DB가 없으면 먼저 만듭니다)
#   powershell -ExecutionPolicy Bypass -File backend\tools\start_demo.ps1 -Reset     시연 DB를 처음 상태로 다시 만들고 켜기
#   powershell -ExecutionPolicy Bypass -File backend\tools\start_demo.ps1 -Stop      끄기
#
# 화면 주소: http://localhost:5180  (비밀번호는 아무거나 입력해도 됩니다)
param(
    [switch]$Reset,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $backend
$python = Join-Path $backend ".venv\Scripts\python.exe"
$demoDb = Join-Path $backend "lab\demo.db"
$backendPort, $frontendPort = 8100, 5180

function Stop-Port($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

if ($Stop) {
    Stop-Port $backendPort
    Stop-Port $frontendPort
    Write-Host "시연 서버를 껐어요."
    return
}

if (-not (Test-Path $python)) { throw "서버 준비가 안 되어 있어요: $python 이 없어요. docs/setup.md 의 '서버 준비하기'를 먼저 해 주세요." }

# 이미 켜져 있으면 먼저 끕니다. (켜진 서버가 DB 파일을 잡고 있으면 다시 만들 수 없고, 옛 화면·서버가 남지도 않게)
Stop-Port $backendPort
Stop-Port $frontendPort
Start-Sleep -Seconds 1

if ($Reset -or -not (Test-Path $demoDb)) {
    Write-Host "시연 DB를 만드는 중이에요 (1분 안팎)..."
    & $python (Join-Path $backend "tools\make_lab_data.py") --demo
    if ($LASTEXITCODE -ne 0) { throw "시연 DB를 만들지 못했어요. (.sl-history\데이터_가져오기\csv 폴더가 있어야 해요)" }
}

Start-Process -FilePath $python -ArgumentList @("tools\serve_lab.py", "--db", "lab\demo.db", "--port", $backendPort) -WorkingDirectory $backend -WindowStyle Minimized | Out-Null
$env:VITE_PROXY_TARGET = "http://127.0.0.1:$backendPort"
Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--port", $frontendPort) -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Minimized | Out-Null

$url = "http://localhost:$frontendPort"
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    Start-Sleep -Seconds 1
    try { $ready = (Invoke-RestMethod "$url/api/health" -TimeoutSec 2).lab -eq $true } catch { }
}
if (-not $ready) { throw "서버가 켜지지 않았어요. docs/setup.md 의 '자주 만나는 문제'를 확인해 주세요." }

Start-Process $url
Write-Host "시연을 시작했어요: $url  (비밀번호는 아무거나)"
Write-Host "끄려면: powershell -ExecutionPolicy Bypass -File backend\tools\start_demo.ps1 -Stop"
