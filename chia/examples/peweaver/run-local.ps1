param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

$ErrorActionPreference = 'Stop'

$ChiaRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$ToolRoot = Join-Path $WorkspaceRoot '.venv-peweaver'
$Yosys = Join-Path $ToolRoot 'Scripts\yowasp-yosys.exe'
$Python = Join-Path $ToolRoot 'Scripts\python.exe'
$RuntimeTemp = Join-Path $WorkspaceRoot '.tmp-yowasp'
$CacheRoot = Join-Path $WorkspaceRoot '.yowasp-cache'

if (-not (Test-Path -LiteralPath $Yosys -PathType Leaf)) {
    throw "Workspace-local Yosys was not found: $Yosys"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        throw 'Python was not found in the workspace venv or PATH.'
    }
    $Python = $PythonCommand.Source
}

New-Item -ItemType Directory -Force -Path $RuntimeTemp, $CacheRoot | Out-Null
$env:TEMP = $RuntimeTemp
$env:TMP = $RuntimeTemp
$env:YOWASP_CACHE_DIR = $CacheRoot
$env:PEWEAVER_YOSYS = $Yosys

Push-Location $ChiaRoot
try {
    & $Python 'examples\peweaver\equivalence_runner.py' @RunnerArgs
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $ExitCode
