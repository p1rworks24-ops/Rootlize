$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimePython = "C:\Users\gzlc3\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv (Join-Path $Root ".venv")
    } elseif (Test-Path $RuntimePython) {
        & $RuntimePython -m venv (Join-Path $Root ".venv")
    } else {
        throw "Python 3.11+ is required."
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}
& $Python (Join-Path $Root "run_benchmark.py") @args

