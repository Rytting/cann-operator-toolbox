param(
    [string]$InstallRoot = "",
    [string]$DownloadUrl = "https://github.com/Rytting/cann-operator-toolbox/archive/refs/heads/main.zip",
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

function Write-Step([string]$Message) {
    Write-Host "[CANN Toolbox Update] $Message"
}

function Require-ToolboxRoot([string]$Root) {
    $required = @(
        "README.md",
        "LICENSE",
        "cann_toolbox\run_toolbox.py",
        "cann_toolbox\VERSION"
    )
    foreach ($rel in $required) {
        $path = Join-Path $Root $rel
        if (-not (Test-Path -LiteralPath $path)) {
            throw "InstallRoot does not look like a CANN Operator Toolbox release directory. Missing: $rel`nPlease pass -InstallRoot with the cann-operator-toolbox root directory."
        }
    }
}

function Read-Version([string]$Root) {
    $versionFile = Join-Path $Root "cann_toolbox\VERSION"
    if (Test-Path -LiteralPath $versionFile) {
        return (Get-Content -LiteralPath $versionFile -Encoding UTF8 -Raw).Trim()
    }
    return "unknown"
}

function Save-UserConfig([string]$Root, [string]$TempRoot) {
    $configFile = Join-Path $Root "cann_toolbox\config\toolbox_config.json"
    $savedFile = Join-Path $TempRoot "toolbox_config.json"
    if (Test-Path -LiteralPath $configFile) {
        Copy-Item -LiteralPath $configFile -Destination $savedFile -Force
        return $savedFile
    }
    return ""
}

function Restore-UserConfig([string]$Root, [string]$SavedFile) {
    if ([string]::IsNullOrWhiteSpace($SavedFile)) {
        return
    }
    if (-not (Test-Path -LiteralPath $SavedFile)) {
        return
    }
    $configDir = Join-Path $Root "cann_toolbox\config"
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    Copy-Item -LiteralPath $SavedFile -Destination (Join-Path $configDir "toolbox_config.json") -Force
    Write-Step "User config restored: cann_toolbox\config\toolbox_config.json"
}

$scriptPath = $MyInvocation.MyCommand.Path
$scriptDir = Split-Path -Parent $scriptPath
$toolboxDir = Split-Path -Parent $scriptDir
$defaultRoot = Split-Path -Parent $toolboxDir

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = $defaultRoot
}

$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
Require-ToolboxRoot $InstallRoot

$oldVersion = Read-Version $InstallRoot
Write-Step "Install root: $InstallRoot"
Write-Step "Current version: $oldVersion"

$gitDir = Join-Path $InstallRoot ".git"
$git = Get-Command git -ErrorAction SilentlyContinue
if ((Test-Path -LiteralPath $gitDir) -and $git) {
    Write-Step "Git repository detected. Running git pull."
    git -C $InstallRoot pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) {
        throw "git pull failed. If local files were changed, commit or back them up first, or download the zip release again."
    }
    $newVersion = Read-Version $InstallRoot
    Write-Step "Update complete: $oldVersion -> $newVersion"
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$tempRoot = Join-Path $env:TEMP "cann_toolbox_update_$stamp"
$zipPath = Join-Path $tempRoot "cann-operator-toolbox-main.zip"
$extractRoot = Join-Path $tempRoot "extract"
$backupRoot = "$InstallRoot.backup_$stamp"

New-Item -ItemType Directory -Force -Path $tempRoot, $extractRoot | Out-Null
$savedUserConfig = Save-UserConfig $InstallRoot $tempRoot
if (-not [string]::IsNullOrWhiteSpace($savedUserConfig)) {
    Write-Step "User config saved before update."
}

Write-Step "No Git repository detected. Downloading latest zip."
Write-Step "Download URL: $DownloadUrl"
Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath

Write-Step "Extracting update package."
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force
$sourceRoot = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
if (-not $sourceRoot) {
    throw "No source directory found after extracting the update package."
}
Require-ToolboxRoot $sourceRoot.FullName

Write-Step "Backing up current install root to: $backupRoot"
Copy-Item -LiteralPath $InstallRoot -Destination $backupRoot -Recurse -Force

Write-Step "Copying files into install root. Make sure the toolbox window is closed."
Get-ChildItem -LiteralPath $sourceRoot.FullName -Force | ForEach-Object {
    $dest = Join-Path $InstallRoot $_.Name
    Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
}
Restore-UserConfig $InstallRoot $savedUserConfig

$newVersion = Read-Version $InstallRoot
Write-Step "Update complete: $oldVersion -> $newVersion"
Write-Step "Backup saved at: $backupRoot"
if (-not $KeepDownload) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
