$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$install = Join-Path $env:RUNNER_TEMP 'FotosClarasInstall'
$data = Join-Path $env:RUNNER_TEMP 'FotosClarasState'
$evidence = Join-Path $repo 'validation\installed'
New-Item -ItemType Directory -Force $data,$evidence | Out-Null
$env:FOTOSCLARAS_DATA = $data
$env:FOTOSCLARAS_SMOKE_DIR = $evidence
$env:QT_QPA_PLATFORM = 'offscreen'
$sentinel = Join-Path $data 'keep-settings.txt'
Set-Content $sentinel 'state-must-survive-upgrade'
python (Join-Path $PSScriptRoot 'state_probe.py') seed
if ($LASTEXITCODE -ne 0) { throw 'Could not seed actual catalog' }
$p = Start-Process (Join-Path $repo 'dist\Fotos-Claras-Previous-Setup.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOAUTOLAUNCH',"/DIR=$install") -Wait -PassThru
if ($p.ExitCode -ne 0) { throw 'Previous installer failed' }
$p = Start-Process (Join-Path $repo 'dist\Fotos-Claras-Setup.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOAUTOLAUNCH',"/DIR=$install") -Wait -PassThru
if ($p.ExitCode -ne 0) { throw 'Installer failed' }
$active = (Get-Content (Join-Path $install 'active-version.txt') -Raw).Trim()
if ($active -ne '0.9.0-beta.3') { throw 'Unexpected active version' }
$exe = Join-Path $install 'FotosClarasLauncher.exe'
$p = Start-Process $exe -ArgumentList '--smoke' -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'Installed UI timed out' }
if ($p.ExitCode -ne 0) { throw 'Installed UI failed' }
if (-not (Test-Path (Join-Path $evidence 'windows-home.png'))) { throw 'No installed UI screenshot' }
Copy-Item (Join-Path $evidence 'windows-home.png') (Join-Path $evidence 'new-version.png')
if ((Get-Content $sentinel -Raw).Trim() -ne 'state-must-survive-upgrade') { throw 'State was modified' }
python (Join-Path $PSScriptRoot 'state_probe.py') check
if ($LASTEXITCODE -ne 0) { throw 'Catalog state changed after upgrade' }
$previous = (Get-Content (Join-Path $install 'previous-version.txt') -Raw).Trim()
if ($previous -ne '0.9.0-beta.2') { throw 'Previous version missing' }
# Exercise the same launcher rollback used by the installed shortcut.
$p = Start-Process $exe -ArgumentList '--rollback-smoke' -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'Rollback timed out' }
if ($p.ExitCode -ne 0) { throw 'Rollback failed' }
$active = (Get-Content (Join-Path $install 'active-version.txt') -Raw).Trim()
if ($active -ne '0.9.0-beta.2') { throw 'Rollback did not change launcher pointer' }
python (Join-Path $PSScriptRoot 'state_probe.py') check
if ($LASTEXITCODE -ne 0) { throw 'Catalog state changed after rollback' }
Copy-Item (Join-Path $evidence 'windows-home.png') (Join-Path $evidence 'previous-version.png')
@{ installer='passed'; installed_exe='passed'; upgrade='passed'; rollback='passed'; preserved_state='passed'; os=$env:OS } | ConvertTo-Json | Set-Content (Join-Path $evidence 'result.json')
