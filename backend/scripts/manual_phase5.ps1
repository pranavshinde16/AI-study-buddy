# Phase 5 manual test (Windows PowerShell 5.1+): summary, topic notes and caching on a real lecture.
#
# Start the API first (cd backend; uvicorn app.main:app --reload), then from backend/:
#   .\scripts\manual_phase5.ps1                                  # uploads ..\media-files\Scalable_recording.mp3
#   .\scripts\manual_phase5.ps1 -File "C:\path\to\lecture.mp4"
#   .\scripts\manual_phase5.ps1 -LectureId <id>                  # reuse a lecture you already uploaded
#   .\scripts\manual_phase5.ps1 -LectureId <id> -Regenerate      # force new LLM calls
#
# It waits until the lecture is "ready" (SUMMARY_AUTO=true) or calls POST /summarize itself,
# prints the summary, takeaways, definitions and topics (with timestamps), calls /summarize a
# second time to show the cached response time, and saves the JSON to ..\storage\manual-test\.
# Uses your Groq free quota (several requests per lecture); it never calls OpenAI unless you set it.

param(
    [string]$File = (Join-Path $PSScriptRoot "..\..\media-files\Scalable_recording.mp3"),
    [string]$LectureId = "",
    [switch]$Regenerate,
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "manual-test@example.com",
    [string]$Password = "manual-test-password"
)
$ErrorActionPreference = "Stop"
$OutDir = Join-Path $PSScriptRoot "..\..\storage\manual-test"
New-Item -ItemType Directory -Force $OutDir | Out-Null

# PowerShell 5.1 decodes JSON without a charset as Latin-1, which garbles characters such as
# non-breaking hyphens in the model's text. Read the bytes and decode them as UTF-8 instead.
function Invoke-Json([string]$Method, [string]$Uri, [string]$Body = $null, [int]$TimeoutSec = 900) {
    $req = @{ Method = $Method; Uri = $Uri; Headers = $headers; UseBasicParsing = $true; TimeoutSec = $TimeoutSec }
    if ($Body) { $req.ContentType = "application/json"; $req.Body = $Body }
    $resp = Invoke-WebRequest @req
    [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Show-Time([double]$sec) { $t = [TimeSpan]::FromSeconds($sec); "{0:D2}:{1:D2}" -f [int][Math]::Floor($t.TotalMinutes), $t.Seconds }

# 1. Account
$cred = @{ email = $Email; password = $Password } | ConvertTo-Json
try { Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/register" -ContentType "application/json" -Body $cred | Out-Null }
catch { if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw } }
$token = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $cred).access_token
$headers = @{ Authorization = "Bearer $token" }

# 2. Upload unless a lecture id was given
if (-not $LectureId) {
    if (-not (Test-Path $File)) { throw "File not found: $File" }
    $File = (Resolve-Path $File).Path
    Write-Host "Uploading $File ..."
    $up = (& curl.exe -s -S -X POST "$BaseUrl/api/lectures/upload" -H "Authorization: Bearer $token" -F "file=@$File") | ConvertFrom-Json
    if (-not $up.lecture_id) { throw "Upload failed" }
    $LectureId = $up.lecture_id
}
Write-Host "Lecture $LectureId"

# 3. Wait while the pipeline is busy
$started = Get-Date
while ($true) {
    $st = Invoke-RestMethod -Uri "$BaseUrl/api/lectures/$LectureId/status" -Headers $headers
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host ("[{0,4}s] {1,-16} {2,3}%  {3}" -f $elapsed, $st.status, $st.progress, $st.stage_detail)
    if ($st.status -eq "failed") { throw "Pipeline failed: $($st.error)" }
    if ($st.status -eq "ready") { break }
    if ($st.status -eq "transcribed") {
        Start-Sleep -Seconds 3   # it may be about to start generating automatically
        $st2 = Invoke-RestMethod -Uri "$BaseUrl/api/lectures/$LectureId/status" -Headers $headers
        if ($st2.status -eq "transcribed") {
            if ($st2.error) { Write-Host "Previous generation error: $($st2.error)" }
            break
        }
        continue
    }
    Start-Sleep -Seconds 3
}

# 4. Summarize (generates if needed), then again to show the cache
$body = @{ regenerate = [bool]$Regenerate } | ConvertTo-Json
$t0 = Get-Date
$s = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/summarize" $body
$first = ((Get-Date) - $t0).TotalSeconds
$t0 = Get-Date
$s2 = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/summarize" '{"regenerate": false}'
$second = ((Get-Date) - $t0).TotalSeconds

Write-Host "`n=== SUMMARY ($($s.meta.mode), $($s.meta.windows) window(s), $($s.meta.llm_calls) LLM calls, model $($s.meta.model)) ==="
Write-Host $s.summary
Write-Host "`n=== KEY TAKEAWAYS ==="
$s.key_takeaways | ForEach-Object { Write-Host "  - $_" }
Write-Host "`n=== DEFINITIONS ==="
$s.definitions | ForEach-Object {
    $at = if ($null -ne $_.timestamp) { Show-Time $_.timestamp } else { "--:--" }
    Write-Host "  [$at] $($_.term): $($_.definition)"
}
Write-Host "`n=== TOPICS ==="
$s.topics | ForEach-Object { Write-Host ("  [{0} - {1}] {2}" -f (Show-Time $_.start), (Show-Time $_.end), $_.title) }

Write-Host ("`nFirst /summarize call : {0:N2} s (cached={1})" -f $first, $s.cached)
Write-Host ("Second /summarize call: {0:N2} s (cached={1})" -f $second, $s2.cached)

$dest = Join-Path $OutDir "$LectureId.summary.json"
[System.IO.File]::WriteAllText($dest, ($s | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
Write-Host "Saved $dest"
Write-Host "Check: topic times fall inside the lecture, and every statement matches what was said."
