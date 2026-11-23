#Requires -Version 5.1
<#
.SYNOPSIS
    Create the CPU or GPU Conda environment for building X-AnyLabeling.

.DESCRIPTION
    Conda runs the pip subprocess in the *current* directory.  Running
    `conda env create -f environment-gpu.yml` from a directory without
    pyproject.toml makes `-e .` point at that directory and fails with:
        file:///D:/somewhere does not appear to be a Python project

    This wrapper always changes to the repository root first, so the
    environment files work even when invoked from another directory.

.PARAMETER Device
    cpu or gpu.

.PARAMETER Recreate
    Remove an existing environment with the same name first.  Use this after
    a failed/partial `conda env create`.

.PARAMETER DryRun
    Print what would run without creating or removing anything.
#>
[CmdletBinding()]
param(
    [ValidateSet("cpu", "gpu")]
    [string]$Device = "cpu",

    [switch]$Recreate,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envName = "xanylabeling-$Device"
$envFile = Join-Path $repoRoot "environment-$Device.yml"

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml"))) {
    throw "Repository root not found at '$repoRoot' (pyproject.toml is missing)."
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Environment file not found: $envFile"
}
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "conda was not found on PATH. Open an Anaconda Prompt or initialize conda."
}

Write-Host "Repository : $repoRoot"
Write-Host "Environment: $envName"
Write-Host "File       : $envFile"

if ($DryRun) {
    Write-Host "Would run  : conda env create -f `"$envFile`""
    Write-Host "Working dir: $repoRoot"
    return
}

Push-Location -LiteralPath $repoRoot
try {
    $listed = (& conda env list) -join "`n"
    $exists = $listed -match "(?m)^\s*$([regex]::Escape($envName))\s"

    if ($Recreate) {
        if ($exists) {
            Write-Host "Removing existing environment '$envName'..."
            & conda env remove --name $envName --yes
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to remove existing environment '$envName'."
            }
        } else {
            Write-Host "No existing environment '$envName'; creating fresh."
        }
    } elseif ($exists) {
        throw "Environment '$envName' already exists. Re-run with -Recreate to remove and recreate it."
    }

    & conda env create -f $envFile
    if ($LASTEXITCODE -ne 0) {
        throw "conda env create failed. After fixing the error, re-run with -Recreate."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Activate with:"
Write-Host "  conda activate $envName"
