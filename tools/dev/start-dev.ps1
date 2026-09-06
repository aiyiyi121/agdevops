$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $scriptDir)
$logDir = Join-Path $root '.runlogs'
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'

$backendPidFile = Join-Path $logDir 'backend.pid'
$frontendPidFile = Join-Path $logDir 'frontend.pid'
$backendOut = Join-Path $logDir 'backend.stdout.log'
$backendErr = Join-Path $logDir 'backend.stderr.log'
$frontendOut = Join-Path $logDir 'frontend.stdout.log'
$frontendErr = Join-Path $logDir 'frontend.stderr.log'

function Test-PortListening {
    param([int]$Port)

    $matches = netstat -ano -p TCP | Select-String -Pattern "LISTENING\s+\d+$"
    foreach ($line in $matches) {
        $text = ($line.ToString() -replace '\s+', ' ').Trim()
        $parts = $text.Split(' ')
        if ($parts.Length -lt 5) {
            continue
        }
        $local = $parts[1]
        if ($local -match ":(\d+)$" -and [int]$Matches[1] -eq $Port) {
            return $true
        }
    }
    return $false
}

function Get-PortProcess {
    param([int]$Port)

    $matches = netstat -ano -p TCP | Select-String -Pattern "LISTENING\s+\d+$"
    foreach ($line in $matches) {
        $text = ($line.ToString() -replace '\s+', ' ').Trim()
        $parts = $text.Split(' ')
        if ($parts.Length -lt 5) {
            continue
        }
        $local = $parts[1]
        $pidText = $parts[-1]
        if ($local -match ":(\d+)$" -and [int]$Matches[1] -eq $Port) {
            $ownerPid = 0
            if ([int]::TryParse($pidText, [ref]$ownerPid)) {
                return Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            }
            return $null
        }
    }
    return $null
}

function Clear-DevPort {
    param(
        [int]$Port,
        [string[]]$AllowedNames
    )

    $process = Get-PortProcess -Port $Port
    if (!$process) {
        return
    }

    if ($AllowedNames -contains $process.ProcessName) {
        Write-Host "Stopping process on port ${Port}: $($process.ProcessName) ($($process.Id))"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
        return
    }

    throw "Port $Port is occupied by $($process.ProcessName) (PID: $($process.Id)). Please stop it manually first."
}

function Stop-TrackedProcess {
    param(
        [string]$PidFile,
        [string]$Name
    )

    if (!(Test-Path $PidFile)) {
        return
    }

    $pidText = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (!$pidText) {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        return
    }

    $targetPid = 0
    if (![int]::TryParse($pidText, [ref]$targetPid)) {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        return
    }

    $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Stopping stale $Name process: $targetPid"
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
    }

    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

function Start-ServiceProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdOut,
        [string]$StdErr,
        [string]$PidFile,
        [int]$Port,
        [int]$WaitSeconds = 20
    )

    if (Test-PortListening -Port $Port) {
        throw "$Name port $Port is already in use. Please free it first or run .\\tools\\dev\\stop-dev.ps1."
    }

    if (Test-Path $StdOut) { Remove-Item $StdOut -Force -ErrorAction SilentlyContinue }
    if (Test-Path $StdErr) { Remove-Item $StdErr -Force -ErrorAction SilentlyContinue }

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr `
        -PassThru

    Set-Content -Path $PidFile -Value $process.Id -Encoding ascii

    for ($i = 0; $i -lt $WaitSeconds; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PortListening -Port $Port) {
            Write-Host "$Name started on port $Port (PID: $($process.Id))"
            return $process
        }

        if ($process.HasExited) {
            $stderr = if (Test-Path $StdErr) { Get-Content $StdErr -Tail 20 | Out-String } else { '' }
            throw "$Name failed to start.`n$stderr"
        }
    }

    $stderr = if (Test-Path $StdErr) { Get-Content $StdErr -Tail 20 | Out-String } else { '' }
    throw "$Name did not start listening on port $Port within ${WaitSeconds}s.`n$stderr"
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Stop-TrackedProcess -PidFile $backendPidFile -Name 'backend'
Stop-TrackedProcess -PidFile $frontendPidFile -Name 'frontend'
Clear-DevPort -Port 8000 -AllowedNames @('python', 'python3')
Clear-DevPort -Port 3000 -AllowedNames @('node')

$backend = Start-ServiceProcess `
    -Name 'Backend' `
    -FilePath 'python' `
    -ArgumentList @('-m', 'daphne', '-b', '0.0.0.0', '-p', '8000', 'sxdevops.asgi:application') `
    -WorkingDirectory $backendDir `
    -StdOut $backendOut `
    -StdErr $backendErr `
    -PidFile $backendPidFile `
    -Port 8000

$frontend = Start-ServiceProcess `
    -Name 'Frontend' `
    -FilePath 'npm.cmd' `
    -ArgumentList @('run', 'dev', '--', '--host', '0.0.0.0', '--port', '3000') `
    -WorkingDirectory $frontendDir `
    -StdOut $frontendOut `
    -StdErr $frontendErr `
    -PidFile $frontendPidFile `
    -Port 3000

Write-Host ''
Write-Host 'SxDevOps dev environment is ready.'
Write-Host 'Frontend: http://localhost:3000'
Write-Host 'Backend : http://localhost:8000'
Write-Host "Logs    : $logDir"
Write-Host ''
Write-Host 'Admin account is created only when SXDEVOPS_ADMIN_INITIAL_PASSWORD is configured.'
