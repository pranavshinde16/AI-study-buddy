# Phase 4 manual test (Windows PowerShell 5.1+): upload a real recording and fetch its transcript.
#
# Start the API first (cd backend; uvicorn app.main:app --reload), then from backend/:
#   .\scripts\manual_phase4.ps1                                   # uses ..\media-files\Scalable_recording.mp3
#   .\scripts\manual_phase4.ps1 -File "C:\path\to\lecture.mp4"
#
# It registers a test account (or logs in if it exists), uploads with curl.exe, polls the status
# every 3 seconds, prints the first segments and saves txt/srt/vtt into ..\storage\manual-test\.
# Uses your real ASR provider (Groq free tier by default), so it counts against your free quota.

param(
    [string]$File = (Join-Path $PSScriptRoot "..\..\media-files\Scalable_recording.mp3"),
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "manual-test@example.com",
    [string]$Password = "manual-test-password",
    [string]$Title = ""
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $File)) { throw "File not found: $File" }
$File = (Resolve-Path $File).Path
$OutDir = Join-Path $PSScriptRoot "..\..\storage\manual-test"
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 1. Account: register (409 = already exists is fine), then log in.
$cred = @{ email = $Email; password = $Password } | ConvertTo-Json
try {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/register" -ContentType "application/json" -Body $cred | Out-Null
    Write-Host "Registered $Email"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
    Write-Host "Account $Email already exists; logging in"
}
$token = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $cred).access_token
$headers = @{ Authorization = "Bearer $token" }

# 2. Upload (curl.exe ships with Windows 10+; PowerShell 5.1 has no multipart -Form).
Write-Host "Uploading $File ..."
$curlArgs = @("-s", "-S", "-X", "POST", "$BaseUrl/api/lectures/upload", "-H", "Authorization: Bearer $token", "-F", "file=@$File")
if ($Title) { $curlArgs += @("-F", "title=$Title") }
$uploadJson = & curl.exe @curlArgs
$upload = $uploadJson | ConvertFrom-Json
if (-not $upload.lecture_id) { throw "Upload failed: $uploadJson" }
$id = $upload.lecture_id
Write-Host "Lecture $id accepted (status: $($upload.status))"

# 3. Poll status every 3 s.
$started = Get-Date
do {
    Start-Sleep -Seconds 3
    $st = Invoke-RestMethod -Uri "$BaseUrl/api/lectures/$id/status" -Headers $headers
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host ("[{0,4}s] {1,-16} {2,3}%  {3}" -f $elapsed, $st.status, $st.progress, $st.stage_detail)
} while ($st.status -notin @("transcribed", "ready", "failed"))

if ($st.status -eq "failed") { throw "Pipeline failed: $($st.error)" }

# 4. Transcript + downloads.
$tr = Invoke-RestMethod -Uri "$BaseUrl/api/lectures/$id/transcript" -Headers $headers
Write-Host "`nLanguage: $($tr.language)  Duration: $($tr.duration_sec) s  Segments: $($tr.segments.Count)"
$tr.segments | Select-Object -First 5 | ForEach-Object { Write-Host ("  [{0,8:N2} - {1,8:N2}] {2}" -f $_.start, $_.end, $_.text) }

foreach ($fmt in @("txt", "srt", "vtt")) {
    $dest = Join-Path $OutDir "$id.$fmt"
    Invoke-WebRequest -Uri "$BaseUrl/api/lectures/$id/transcript/download?format=$fmt" -Headers $headers -OutFile $dest -UseBasicParsing
    Write-Host "Saved $dest"
}
Write-Host "`nOpen the .srt in VLC next to the media file (Subtitle > Add Subtitle File) to check the timing."
Write-Host "Delete the lecture when done:  curl.exe -X DELETE $BaseUrl/api/lectures/$id -H `"Authorization: Bearer <token>`""
