# iTE One-Shot Installer (Windows PowerShell)
#   irm https://ite.kiishi.space/install.ps1 | iex
#
# Detects architecture, downloads the correct standalone iTE runtime,
# verifies the checksum, and installs to %LOCALAPPDATA%\iTE\bin\ite.exe.
#
# Environment overrides:
#   $env:ITE_INSTALL_MANIFEST_URL   - override manifest URL for dev/testing
#   $env:ITE_INSTALL_DIR            - override install directory
#   $env:ITE_INSTALL_VERSION        - pin a specific version
#   $env:ITE_INSTALL_SKIP_PATH      - skip PATH modification

param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ── Configuration ────────────────────────────────────────────
$ManifestUrl = if ($env:ITE_INSTALL_MANIFEST_URL) { $env:ITE_INSTALL_MANIFEST_URL } else { "https://ite.kiishi.space/releases/manifest.json" }
$ManagedRoot = if ($env:ITE_INSTALL_DIR) { $env:ITE_INSTALL_DIR } else { "$env:LOCALAPPDATA\iTE" }
$BinDir = "$ManagedRoot\bin"
$ExePath = "$BinDir\ite.exe"

# ── Helpers ──────────────────────────────────────────────────
function Write-Info    { Write-Host "[iTE] $args" -ForegroundColor Gray }
function Write-Success { Write-Host "[iTE] $args" -ForegroundColor Green }
function Write-Warn    { Write-Host "[iTE] $args" -ForegroundColor Yellow }
function Write-ErrorMsg { Write-Host "[iTE] $args" -ForegroundColor Red }
function Write-Step    { Write-Host "→ $args" -ForegroundColor White }

# ── Architecture detection ───────────────────────────────────
function Get-Target {
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { "x64" }
        "ARM64" { "arm64" }
        default {
            Write-ErrorMsg "Unsupported architecture: $env:PROCESSOR_ARCHITECTURE"
            throw "Unsupported architecture: $env:PROCESSOR_ARCHITECTURE"
        }
    }
    return "win32-$arch"
}

# ── Fetch manifest ───────────────────────────────────────────
function Get-Manifest {
    Write-Step "Fetching iTE release manifest..."
    try {
        $response = Invoke-WebRequest -Uri $ManifestUrl -UseBasicParsing -TimeoutSec 30
        return $response.Content | ConvertFrom-Json
    } catch {
        Write-ErrorMsg "Could not reach release server: $ManifestUrl"
        Write-ErrorMsg "Check your internet connection or try again later."
        throw "Could not reach release server."
    }
}

# ── Check existing install ───────────────────────────────────
function Test-ExistingInstall {
    param([string]$Version)

    if (Test-Path $ExePath) {
        try {
            $output = & $ExePath --version 2>&1
            $installedVersion = [regex]::Match($output, '(\d+\.\d+\.\d+)').Groups[1].Value
            if ($installedVersion -eq $Version) {
                Write-Success "iTE v$Version is already installed at $ExePath"
                Add-ToPath
                return $true
            } elseif ($installedVersion) {
                Write-Info "Updating iTE from v$installedVersion to v$Version..."
            } else {
                Write-Info "Repairing iTE install..."
            }
        } catch {
            Write-Info "Repairing iTE install..."
        }
    }

    return $false
}

# ── Download and verify ──────────────────────────────────────
function Invoke-Download {
    param([string]$Url, [string]$Sha256, [string]$ArchivePath)

    Write-Step "Downloading iTE..."
    try {
        Invoke-WebRequest -Uri $Url -OutFile $ArchivePath -UseBasicParsing -TimeoutSec 300
    } catch {
        Write-ErrorMsg "Download failed."
        Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
        throw "Download failed."
    }

    if ($Sha256) {
        Write-Step "Verifying checksum..."
        $actualHash = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
        if ($actualHash -ne $Sha256.ToLower()) {
            Write-ErrorMsg "Checksum verification failed!"
            Write-ErrorMsg "Expected: $Sha256"
            Write-ErrorMsg "Got:      $actualHash"
            Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
            throw "Checksum verification failed."
        }
    }
}

# ── Install ──────────────────────────────────────────────────
function Install-Artifact {
    param([string]$ArchivePath, [string]$ArchiveType)

    Write-Step "Installing to $BinDir..."

    if (-not (Test-Path $BinDir)) {
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    }

    $tempExtract = Join-Path $env:TEMP "ite-install-$([System.Guid]::NewGuid().ToString('N').Substring(0,8))"
    New-Item -ItemType Directory -Path $tempExtract -Force | Out-Null

    try {
        if ($ArchiveType -eq "zip") {
            Expand-Archive -Path $ArchivePath -DestinationPath $tempExtract -Force
        } else {
            Write-ErrorMsg "Unsupported archive type: $ArchiveType"
            throw "Unsupported archive type: $ArchiveType"
        }

        # Find the extracted directory (ite-{version}-{target}/)
        $extractedDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1

        if (-not $extractedDir) {
            Write-ErrorMsg "Archive extraction produced unexpected layout."
            throw "Archive extraction produced unexpected layout."
        }

        # PyInstaller one-dir archives contain an executable-named bundle
        # (ite.exe/ite.exe plus its dependencies). Copy the bundle's *contents*
        # into bin so ite.exe is always a file at the documented install path.
        $executableName = Split-Path -Path $ExePath -Leaf
        $bundleDir = Join-Path -Path $extractedDir.FullName -ChildPath $executableName
        $bundledExePath = Join-Path -Path $bundleDir -ChildPath $executableName
        if (-not (Test-Path -LiteralPath $bundledExePath -PathType Leaf)) {
            Write-ErrorMsg "Archive extraction produced unexpected layout: executable not found at $bundledExePath"
            throw "Archive extraction produced unexpected layout."
        }

        # Clear existing install, including hidden files left by an interrupted update.
        Get-ChildItem -Force -LiteralPath $BinDir | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Force -LiteralPath $bundleDir | Copy-Item -Destination $BinDir -Recurse -Force

        $realExePath = $ExePath

        # Verify executable (must be an actual file, not a directory)
        if (-not (Test-Path $realExePath -PathType Leaf)) {
            Write-ErrorMsg "Installation failed: executable not found at $realExePath"
            throw "Installation failed: executable not found at $realExePath"
        }

        # Version check
        $output = $null
        try {
            $output = & $realExePath --version 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "iTE exited with code $LASTEXITCODE."
            }
            $installedVersion = [regex]::Match($output, '(\d+\.\d+\.\d+)').Groups[1].Value
            Write-Success "iTE v$installedVersion installed to $realExePath"
        } catch {
            Write-ErrorMsg "iTE installed but failed to launch."
            if ($output) {
                $output | ForEach-Object { Write-ErrorMsg "iTE output: $_" }
            }
            Write-ErrorMsg "Windows reported: $($_.Exception.Message)"
            throw "iTE installed but failed to launch."
        }
    } finally {
        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
    }
}

# ── PATH management ──────────────────────────────────────────
function Add-ToPath {
    if ($env:ITE_INSTALL_SKIP_PATH -eq "1") {
        return
    }

    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $currentUserPath) { $currentUserPath = "" }
    $currentMachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (-not $currentMachinePath) { $currentMachinePath = "" }

    if ($currentUserPath -like "*$BinDir*" -or $currentMachinePath -like "*$BinDir*") {
        return  # Already in PATH
    }

    try {
        $newPath = if ($currentUserPath) { "$BinDir;$currentUserPath" } else { $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        $env:Path = "$BinDir;$env:Path"
        Write-Success "Added iTE to user PATH."
    } catch {
        Write-Warn "Could not update PATH automatically."
        Write-Host ""
        Write-Host "  Add this directory to your PATH manually:"
        Write-Host "  $BinDir"
        Write-Host ""
    }
}

# ── Main ─────────────────────────────────────────────────────
function Main {
    Write-Host ""
    Write-Host "iTE Installer" -ForegroundColor Cyan
    Write-Host ""

    $target = Get-Target
    Write-Info "Detected: $target"

    $manifest = Get-Manifest
    $version = if ($env:ITE_INSTALL_VERSION) { $env:ITE_INSTALL_VERSION } else { $manifest.version }

    if (-not $version) {
        Write-ErrorMsg "Could not determine iTE version from manifest."
        throw "Could not determine iTE version from manifest."
    }

    $asset = $manifest.assets.$target
    if (-not $asset) {
        Write-ErrorMsg "No build available for: $target"
        Write-ErrorMsg "Supported targets: win32-x64"
        throw "No build available for: $target"
    }

    if (Test-ExistingInstall -Version $version) {
        return
    }

    $archiveName = "ite-$version-$target.zip"
    $archivePath = Join-Path $env:TEMP $archiveName

    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue

    Invoke-Download -Url $asset.url -Sha256 $asset.sha256 -ArchivePath $archivePath
    Install-Artifact -ArchivePath $archivePath -ArchiveType $asset.archiveType
    Add-ToPath

    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Success "iTE is ready!"
    Write-Host ""
    Write-Info "Run: ite"
    Write-Host ""
}

try {
    Main
} catch {
    # Do not use `exit` here: this script is normally invoked through
    # `irm ... | iex`, where exit would terminate the caller's PowerShell host.
    Write-ErrorMsg "Installation stopped: $($_.Exception.Message)"
}
