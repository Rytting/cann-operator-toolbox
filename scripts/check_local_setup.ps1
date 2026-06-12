param(
    [string]$BoardIP = "192.168.0.2",
    [string]$BoardUser = "HwHiAiUser",
    [int]$BoardPort = 22,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "==== $Title ===="
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Resolve-PythonCandidate {
    param([string]$Path)
    if (-not $Path) { return $null }

    $exe = $Path
    if (Test-Path -LiteralPath $exe) {
        return (Resolve-Path -LiteralPath $exe).Path
    }

    $cmd = Get-Command $Path -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }

    return $null
}

function Test-Python {
    param([string]$PythonExe)

    if (-not $PythonExe) { return $null }

    $versionText = & $PythonExe --version 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $versionText) {
        return [pscustomobject]@{
            Path = $PythonExe
            Version = "cannot run"
            Major = 0
            Minor = 0
            Patch = 0
            Supported = $false
            Runnable = $false
            Error = ($versionText -join " ")
        }
    }

    $match = [regex]::Match(($versionText -join " "), "Python\s+(\d+)\.(\d+)\.(\d+)")
    if (-not $match.Success) { return $null }

    $major = [int]$match.Groups[1].Value
    $minor = [int]$match.Groups[2].Value
    $patch = [int]$match.Groups[3].Value
    $ok = ($major -gt 3) -or ($major -eq 3 -and $minor -ge 10)

    return [pscustomobject]@{
        Path = $PythonExe
        Version = $match.Value
        Major = $major
        Minor = $minor
        Patch = $patch
        Supported = $ok
        Runnable = $true
        Error = ""
    }
}

function Get-PythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    if ($PythonPath) {
        $resolvedUserPath = Resolve-PythonCandidate $PythonPath
        if ($resolvedUserPath) { $candidates.Add($resolvedUserPath) }
    }

    foreach ($name in @("python", "py")) {
        $resolved = Resolve-PythonCandidate $name
        if ($resolved) { $candidates.Add($resolved) }
    }

    foreach ($pattern in @(
        "$env:USERPROFILE\AppData\Local\Programs\Python\Python*\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
        "C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe",
        "$env:ProgramFiles\Python*\python.exe",
        "${env:ProgramFiles(x86)}\Python*\python.exe"
    )) {
        Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            $candidates.Add($_.FullName)
        }
    }

    return $candidates | Where-Object { $_ } | Select-Object -Unique
}

function Test-PythonPackages {
    param([string]$PythonExe)

    $packages = @("paramiko", "openpyxl", "matplotlib", "numpy")

    return $packages | ForEach-Object {
        $pkg = $_
        & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$pkg') else 1)" | Out-Null
        $status = if ($LASTEXITCODE -eq 0) { "OK" } else { "MISSING" }
        [pscustomobject]@{
            Name = $pkg
            Status = $status
        }
    }
}

function Show-NetworkInfo {
    param([string]$TargetIP)

    $ipRows = @()
    $cmd = Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue
    if ($cmd) {
        $ipRows = Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.IPAddress -ne "127.0.0.1" } |
            Select-Object InterfaceAlias, IPAddress, PrefixLength
    }

    if ($ipRows.Count -gt 0) {
        Write-Host "Local IPv4 addresses:"
        $ipRows | Format-Table -AutoSize

        $hasRNDIS = $ipRows | Where-Object { $_.IPAddress -eq "192.168.0.1" }
        $hasAPIPA = $ipRows | Where-Object { $_.IPAddress -like "169.254.*" }
        if ($hasRNDIS) {
            Write-Ok "Found local 192.168.0.1. This matches the common USB RNDIS setup."
        } elseif ($hasAPIPA) {
            Write-WarnLine "Found 169.254.x.x address. USB RNDIS may not have a manual IP yet."
            Write-Host "       Common setting: local adapter 192.168.0.1 / 255.255.255.0, no gateway."
        } else {
            Write-WarnLine "Did not find local 192.168.0.1. If using USB RNDIS, check the adapter IP."
        }
    } else {
        Write-WarnLine "Could not list local IPv4 addresses with Get-NetIPAddress."
        Write-Host "       Falling back to ipconfig:"
        $ipconfig = ipconfig 2>&1
        $ipconfig | Where-Object {
            $_ -match "IPv4|169\.254|192\.168|USB|RNDIS|Ethernet adapter|Wireless LAN adapter"
        } | ForEach-Object { Write-Host "       $_" }
    }

    Write-Host ""
    Write-Host "Testing board reachability: $TargetIP"
    $pingOk = Test-Connection -ComputerName $TargetIP -Count 1 -Quiet
    if ($pingOk) {
        Write-Ok "Ping to $TargetIP succeeded."
    } else {
        Write-WarnLine "Ping to $TargetIP failed. ICMP may be blocked; the SSH port check below is more important."
    }

    $tnc = Get-Command Test-NetConnection -ErrorAction SilentlyContinue
    if ($tnc) {
        $portResult = Test-NetConnection -ComputerName $TargetIP -Port $BoardPort -WarningAction SilentlyContinue
        if ($portResult.TcpTestSucceeded) {
            Write-Ok "TCP port $BoardPort is open on $TargetIP. SSH is likely reachable."
        } else {
            Write-WarnLine "TCP port $BoardPort is not reachable on $TargetIP."
        }
    } else {
        Write-WarnLine "Test-NetConnection is unavailable. Skipping TCP port check."
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "CANN Operator Toolbox local setup check"
Write-Host "Repository: $repoRoot"
Write-Host "Board: $BoardUser@$BoardIP`:$BoardPort"

Write-Section "Python"
$pythonInfos = @()
foreach ($candidate in Get-PythonCandidates) {
    $info = Test-Python $candidate
    if ($info) { $pythonInfos += $info }
}

if ($pythonInfos.Count -eq 0) {
    Write-Fail "No Python executable was found."
    Write-Host "Try installing Python 3.10+ from https://www.python.org/downloads/windows/"
    Write-Host "Then run this script again."
    $bestPython = $null
} else {
    $pythonInfos | Sort-Object -Property Supported -Descending | Format-Table Path, Version, Supported, Runnable -AutoSize
    $notRunnable = $pythonInfos | Where-Object { -not $_.Runnable }
    foreach ($item in $notRunnable) {
        Write-WarnLine "Found Python but could not run it: $($item.Path)"
        if ($item.Error) { Write-Host "       $($item.Error)" }
    }
    $bestPython = $pythonInfos | Where-Object { $_.Supported -and $_.Runnable } | Select-Object -First 1
    if ($bestPython) {
        Write-Ok "Selected Python: $($bestPython.Path)"
    } else {
        Write-Fail "Python was found, but no runnable Python 3.10+ executable was detected."
        Write-Host "If you know the path, run:"
        Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1 -PythonPath `"C:\Path\To\python.exe`""
    }
}

Write-Section "Python packages"
if ($bestPython) {
    $packageResults = Test-PythonPackages $bestPython.Path
    $packageResults | Format-Table Name, Status -AutoSize
    $missing = $packageResults | Where-Object { $_.Status -ne "OK" }
    if ($missing.Count -eq 0) {
        Write-Ok "Required Python packages are installed."
    } else {
        Write-WarnLine "Some packages are missing."
        Write-Host "Install command:"
        Write-Host "`"$($bestPython.Path)`" -m pip install paramiko openpyxl matplotlib numpy"
    }
} else {
    Write-WarnLine "Skipping package check because no supported Python was selected."
}

Write-Section "Network and board"
Show-NetworkInfo -TargetIP $BoardIP

Write-Section "SSH command"
$sshCmd = Get-Command ssh -ErrorAction SilentlyContinue
if ($sshCmd) {
    Write-Ok "ssh command found: $($sshCmd.Source)"
    Write-Host "Manual login test:"
    Write-Host "ssh $BoardUser@$BoardIP -p $BoardPort"
} else {
    Write-WarnLine "ssh command not found in PATH. The toolbox can still use Paramiko, but manual SSH testing is harder."
}

Write-Section "Start toolbox"
if ($bestPython) {
    Write-Host "Use this command from the repository root:"
    Write-Host "`"$($bestPython.Path)`" .\cann_toolbox\run_toolbox.py"
} else {
    Write-Host "After installing Python, run:"
    Write-Host "python .\cann_toolbox\run_toolbox.py"
}

Write-Host ""
Write-Host "Done. If something is marked [FAIL] or [WARN], fix that item before running board workflows."
