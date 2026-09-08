# Launch only our built window, without opening audio. Detect missing DLLs and startup exceptions.
param(
    [string]$AppPath = "$PSScriptRoot\..\dist\VoiceLoop\VoiceLoop.exe",
    [ValidateSet('check-ui', 'check-capture')][string]$Check = 'check-ui',
    [switch]$Pixels
)
$ErrorActionPreference = 'Stop'
$executable = (Resolve-Path -LiteralPath $AppPath).Path
$logs = Join-Path $PSScriptRoot '..\artifacts'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stderr = Join-Path $logs 'packaged-ui-stderr.txt'
$stdout = Join-Path $logs 'packaged-ui-stdout.txt'
$report = Join-Path $logs ('packaged-' + $Check + '-' + [guid]::NewGuid().ToString('N') + '.json')
$previousPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = 'windows'
$process = $null
try {
    $arguments = $Check + ' --output "' + $report + '"'
    if ($Pixels -and $Check -eq 'check-capture') { $arguments += ' --pixels' }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $executable
    $process.StartInfo.Arguments = $arguments
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    [void]$process.Start()
    $readOutput = $process.StandardOutput.ReadToEndAsync()
    $readError = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(20000)) { throw 'Packaged UI timed out.' }
    $readOutput.Result | Set-Content -LiteralPath $stdout
    $readError.Result | Set-Content -LiteralPath $stderr
    if ($process.ExitCode -ne 0) { throw "Packaged UI exit code: $($process.ExitCode). $($readError.Result)" }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($Check -eq 'check-capture') {
        if ($result.native_toggle -ne 'passed' -or $result.audio_opened -ne $false -or $result.network_used -ne $false) { throw 'Packaged capture-protection diagnostic failed.' }
        if ($Pixels -and $result.desktop_pixels -ne 'passed') { throw 'Packaged desktop pixel capture check failed.' }
        Write-Output ('PASS: packaged capture protection. Report: ' + $report)
        return
    }
    if ($result.ui -ne 'ok' -or $result.audio_started -ne $false) { throw 'Invalid UI diagnostic report.' }
    if ($result.tray_actions -ne 'ok' -or $result.transcription_worker -ne 'ok' -or $result.network_used -ne $false) { throw 'Packaged desktop/worker diagnostic failed.' }
    if ($result.timer_reset -ne 'ok' -or $result.speaker_silence_prompt -ne 'ok') { throw 'Packaged timer or silence prompt diagnostic failed.' }
    if ($result.search_suggestions -ne 'ok' -or $result.tray_status_icons -ne 'ok') { throw 'Packaged suggestions or tray icon diagnostic failed.' }
    Write-Output 'PASS: packaged Qt/floating controls, timer reset, silence prompt, tray, credentials, transcription worker; no audio or network.'
} finally {
    $env:QT_QPA_PLATFORM = $previousPlatform
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id }
    if ($process) { $process.Dispose() }
}
