# Wrapper for Windows Task Scheduler.
# Logs full output to e:\contentbot\logs\run_<timestamp>.log

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile   = Join-Path $logDir "run_$timestamp.log"

# Prune log files older than 30 days
Get-ChildItem $logDir -Filter "run_*.log" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$python = "C:\Users\kawa crtve\AppData\Local\Programs\Python\Python312\python.exe"
$script = Join-Path $PSScriptRoot "main.py"

"=== ContentBot scheduled run started: $(Get-Date) ===" | Out-File -FilePath $logFile -Encoding utf8
& $python $script 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$exitCode = $LASTEXITCODE
"=== Exit code: $exitCode  (finished: $(Get-Date)) ===" | Out-File -FilePath $logFile -Append -Encoding utf8

exit $exitCode
