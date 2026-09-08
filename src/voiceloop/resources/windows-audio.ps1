# VoiceLoop audio provisioning. Runs elevated; only touches VB-CABLE / Hi-Fi endpoints.
param([string]$CablePackage = '', [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$nameKey = '{a45c254e-df1c-4efd-8020-67d146a850e0},14'
$descriptionKey = '{a45c254e-df1c-4efd-8020-67d146a850e0},2'
$audioRoot = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio'

function Get-CableEndpoints {
    foreach ($direction in @('Render', 'Capture')) {
        foreach ($device in Get-ChildItem -LiteralPath "$audioRoot\$direction" -ErrorAction SilentlyContinue) {
            $properties = Get-ItemProperty -LiteralPath "$($device.PSPath)\Properties"
            $name = [string]$properties.$nameKey
            $description = [string]$properties.$descriptionKey
            $identity = "$name $description"
            $hardware = [string]$properties.'{a8b865dd-2e3d-4094-ad97-e593a70c75d6},8'
            # Driver-supplied description survives our friendly-name changes. Never match
            # an arbitrary device merely because somebody named it VoiceLoop.
            $kind = if ($hardware -eq 'VBAudioHFVAIO') { 'hifi' }
                elseif ($hardware -eq 'VBAudioVACWDM' -and $description -notmatch '16\s*Ch') { 'cable' }
                else { '' }
            if ($kind) {
                [pscustomobject]@{ Id=$device.PSChildName; Path="$($device.PSPath)\Properties";
                    Direction=$direction; Kind=$kind; Name=$(if ($name) { $name } else { $description }) }
            }
        }
    }
}

function Get-VerifiedPackage($url, $checksum, $folder) {
    $zip = Join-Path $folder 'driver.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    (New-Object Net.WebClient).DownloadFile($url, $zip)
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $checksum) {
        throw 'Downloaded driver checksum mismatch. No installer was run.'
    }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $folder 'package') -Force
    return (Join-Path $folder 'package')
}

function Invoke-Vendor($path, $arguments) {
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'BUREL VINCENT|Vincent Burel') {
        throw "VB-Audio signature verification failed: $path"
    }
    $process = Start-Process -FilePath $path -ArgumentList $arguments -WorkingDirectory (Split-Path $path) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(300000)) {
        throw 'The vendor installer is still waiting for Windows approval. Finish its dialog and retry setup.'
    }
    # VB installers have version-specific return codes. Verify actual endpoints below.
    Write-Output "Vendor installer exit code: $($process.ExitCode)"
}

if ($CheckOnly) {
    @(Get-CableEndpoints) | ConvertTo-Json -Depth 3
    exit 0
}
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Error 'Run audio setup with administrator approval.'; exit 1 }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Write-Error 'This audio setup supports Windows x64.'; exit 1 }
$stateDir = Join-Path $env:ProgramData 'VoiceLoop'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
Start-Transcript -Path (Join-Path $stateDir 'setup.log') -Append | Out-Null
$work = Join-Path $env:TEMP ('VoiceLoop-Audio-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
Add-Type -Path (Join-Path $PSScriptRoot 'WindowsAudio.cs')
$defaults = @()
foreach ($flow in 0,1) {
    foreach ($role in 0,1,2) {
        $defaults += [pscustomobject]@{ Flow=$flow; Role=$role; Id=[VoiceLoop.AudioNames]::DefaultDevice($flow,$role) }
    }
}
try {
    $endpoints = @(Get-CableEndpoints)
    if (-not ($endpoints | Where-Object Kind -eq 'cable')) {
        if (-not $CablePackage) {
            $baseDir = New-Item -ItemType Directory -Path (Join-Path $work 'cable')
            $CablePackage = Get-VerifiedPackage 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip' 'b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb' $baseDir.FullName
        }
        $setup = Get-ChildItem -LiteralPath $CablePackage -Filter 'VBCABLE_Setup_x64.exe' -Recurse | Select-Object -First 1
        if (-not $setup) { throw 'The complete VB-CABLE driver package is missing.' }
        Invoke-Vendor $setup.FullName '-i -h'
    }
    if (-not ($endpoints | Where-Object Kind -eq 'hifi')) {
        $hiDir = New-Item -ItemType Directory -Path (Join-Path $work 'hifi')
        $hiPackage = Get-VerifiedPackage 'https://download.vb-audio.com/Download_CABLE/HiFiCableAsioBridgeSetup_v1007.zip' '3ecf204bfd8579d36bb918f9856eb1eaddd49c75146f5e8a8f59dcb8375ae89a' $hiDir.FullName
        $setup = Get-ChildItem -LiteralPath $hiPackage -Filter 'HiFiCableAsioBridgeSetup.exe' -Recurse | Select-Object -First 1
        if (-not $setup) { throw 'The Hi-Fi Cable installer is missing.' }
        Invoke-Vendor $setup.FullName '-i -h'
    }
    # Allow normal PnP discovery; never restart the audio service under a meeting.
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        $endpoints = @(Get-CableEndpoints)
        if (@($endpoints | Select-Object Kind,Direction -Unique).Count -ge 4) { break }
        Start-Sleep -Seconds 2
    }
    if (@($endpoints | Select-Object Kind,Direction -Unique).Count -lt 4) {
        $services = @(Get-Service -Name 'VBAudioVACMME','VBAudioHIFI*' -ErrorAction SilentlyContinue)
        if ($services.Count -lt 2) { throw 'A virtual driver did not register. Check the vendor installer and Windows driver security messages.' }
        Write-Output 'Driver services registered, but not all endpoints are available. Restart Windows and run Audio setup again.'
        exit 3010
    }
    $backup = Join-Path $stateDir 'endpoint-names.json'
    if (-not (Test-Path -LiteralPath $backup)) {
        $endpoints | Select-Object Id,Direction,Kind,Name | ConvertTo-Json | Set-Content -LiteralPath $backup -Encoding UTF8
    }
    foreach ($endpoint in $endpoints) {
        $newName = switch ("$($endpoint.Kind)/$($endpoint.Direction)") {
            'cable/Capture' { 'VoiceLoop Mic' }
            'cable/Render' { 'VoiceLoop Mic Feed' }
            'hifi/Render' { 'VoiceLoop Speaker' }
            'hifi/Capture' { 'VoiceLoop Speaker Capture' }
        }
        $flow = if ($endpoint.Direction -eq 'Render') { '0' } else { '1' }
        $id = "{0.0.$flow.00000000}.$($endpoint.Id)"
        if ([VoiceLoop.AudioNames]::Rename($id, $newName) -ne $newName) {
            throw "Could not set the name $newName."
        }
        # Hi-Fi Cable does not resample. Keep both sides at the same 48 kHz rate.
        if ($endpoint.Kind -eq 'hifi') { [VoiceLoop.AudioNames]::SetRate($id, 48000) }
    }
    Write-Output 'VoiceLoop Mic and VoiceLoop Speaker configured. Reopen audio applications to refresh their device names.'
    exit 0
} catch {
    Write-Output "Audio setup failed: $_"
    exit 1
} finally {
    foreach ($original in $defaults) {
        if ($original.Id -and [VoiceLoop.AudioNames]::DefaultDevice($original.Flow,$original.Role) -ne $original.Id) {
            try { [VoiceLoop.AudioNames]::RestoreDefault($original.Id, $original.Role) }
            catch { Write-Output "Could not restore the previous Windows default: $_" }
        }
    }
    Stop-Transcript | Out-Null
    # Retain vendor extraction on failure for diagnostics; no recursive cleanup or shared driver removal.
}
