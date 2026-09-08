# Offline synthetic speech only; no microphone or external service is opened.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$folder = Join-Path $PSScriptRoot '..\artifacts\openai-smoke'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$output = Join-Path $folder 'synthetic-conversation.wav'
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @($synth.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name })
    if ($voices.Count -lt 2) { throw 'This check needs two installed synthetic voices.' }
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToWaveFile($output, $format)
    $synth.SelectVoice($voices[0])
    $synth.Speak('Hi Maya, this is Alex. Let us review the project. We will ship the Voice Loop update on Friday. Are the audio tests ready?')
    $synth.SelectVoice($voices[1])
    $synth.Speak('Hi Alex. Yes, the microphone and speaker tests are ready. I will check the transcripts tomorrow and send you the results.')
    $synth.SelectVoice($voices[0])
    $synth.Speak('That sounds good. Please include the Windows installer in the release. Thank you for your help.')
    $synth.SetOutputToNull()
    Write-Output 'Generated an offline two-voice test conversation.'
} finally {
    $synth.Dispose()
}
