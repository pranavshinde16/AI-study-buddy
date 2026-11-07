# Phase 7 manual test (Windows PowerShell 5.1+): grounded Q&A (/ask), refusals, chat with a
# follow-up (/chat), chat history, the generator list (/models) and the fine-tuned switch.
#
# Start the API first (cd backend; uvicorn app.main:app --reload), then from backend/:
#   .\scripts\manual_phase7.ps1                       # newest "ready" lecture of the test account
#   .\scripts\manual_phase7.ps1 -LectureId <id> -Question "..." -FollowUp "..." -OffTopic "..."
#
# The defaults fit the demo lecture (serverless computing). Uses your Groq free quota (a few
# requests); the first question of a lecture also loads the local embedding model (~20-30 s).
# The "finetuned" request is expected to return 503 MODEL_UNAVAILABLE until Ollama is set up (Phase 10).

param(
    [string]$LectureId = "",
    [string]$Question = "What are the two types of serverless architecture?",
    [string]$FollowUp = "Can you give an example of the first one?",
    [string]$OffTopic = "Who won the 2022 FIFA World Cup?",
    [string]$NearTopic = "What is the difference between TCP and UDP?",
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "manual-test@example.com",
    [string]$Password = "manual-test-password"
)
$ErrorActionPreference = "Stop"
$OutDir = Join-Path $PSScriptRoot "..\..\storage\manual-test"
New-Item -ItemType Directory -Force $OutDir | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# UTF-8 safe JSON calls (PowerShell 5.1 decodes JSON without a charset as Latin-1). Returns the
# error envelope instead of throwing when -AllowError is set.
function Invoke-Json([string]$Method, [string]$Uri, [string]$Body = $null, [switch]$AllowError) {
    $req = @{ Method = $Method; Uri = $Uri; Headers = $headers; UseBasicParsing = $true; TimeoutSec = 600 }
    if ($Body) { $req.ContentType = "application/json; charset=utf-8"; $req.Body = [System.Text.Encoding]::UTF8.GetBytes($Body) }
    try { $resp = Invoke-WebRequest @req; return [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json }
    catch {
        $r = $_.Exception.Response
        if (-not $r) { throw }
        $text = $_.ErrorDetails.Message  # PowerShell has already read the error body into here
        if (-not $text) { $text = (New-Object System.IO.StreamReader($r.GetResponseStream(), [System.Text.Encoding]::UTF8)).ReadToEnd() }
        if ($AllowError) { $obj = $text | ConvertFrom-Json; $obj | Add-Member -NotePropertyName http -NotePropertyValue ([int]$r.StatusCode); return $obj }
        Write-Host "HTTP $([int]$r.StatusCode): $text" -ForegroundColor Red
        throw
    }
}
function Show-Time($sec) { $t = [TimeSpan]::FromSeconds([double]$sec); "{0:D2}:{1:D2}" -f [int][Math]::Floor($t.TotalMinutes), $t.Seconds }
function Show-Answer($label, $a) {
    $m = $a.meta
    Write-Host ("`n=== {0} ===" -f $label)
    Write-Host ("answerable={0}  refusal={1}  top_score={2}  min_score={3}  generator={4}  {5:N0} ms (retrieval {6:N0} ms){7}" -f `
        $a.answerable, $m.refusal_reason, $m.top_score, $m.min_score, $m.generator, $m.latency_ms, $m.retrieval_ms, `
        $(if ($m.indexed_now) { "  [indexed now: $($m.chunks) chunks]" } else { "" }))
    if ($m.rewritten_question) { Write-Host "rewritten: $($m.rewritten_question)" }
    Write-Host $a.answer
    foreach ($s in $a.sources) {
        Write-Host ("  {0} [{1} - {2}] score {3:N3} cited={4}  {5}" -f $s.chunk_id, (Show-Time $s.start), (Show-Time $s.end), $s.score, $s.cited, ($s.excerpt.Substring(0, [Math]::Min(90, $s.excerpt.Length))))
    }
    if ($m.citations_dropped.Count) { Write-Host "  dropped invalid citations: $($m.citations_dropped -join ', ')" }
}

# 1. Account and lecture
$cred = @{ email = $Email; password = $Password } | ConvertTo-Json
try { Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/register" -ContentType "application/json" -Body $cred | Out-Null }
catch { if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw } }
$token = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $cred).access_token
$headers = @{ Authorization = "Bearer $token" }
if (-not $LectureId) {
    $ready = @(Invoke-Json "Get" "$BaseUrl/api/lectures" | Where-Object { $_.status -eq "ready" })
    if ($ready.Count -eq 0) { throw "No 'ready' lecture for $Email. Run .\scripts\manual_phase5.ps1 first." }
    $LectureId = $ready[0].id
}
Write-Host "Lecture $LectureId"
$models = Invoke-Json "Get" "$BaseUrl/api/models"
Write-Host ("Generators: " + (($models | ForEach-Object { "$($_.name) ($($_.provider)/$($_.model))" }) -join ", "))

# 2. /ask: on-topic, off-topic, near-topic
$results = [ordered]@{}
foreach ($pair in @(@("ON-TOPIC", $Question), @("OFF-TOPIC", $OffTopic), @("NEAR-TOPIC (not in the lecture)", $NearTopic))) {
    $a = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/ask" (@{ question = $pair[1]; model = "cloud" } | ConvertTo-Json)
    Show-Answer "$($pair[0]): $($pair[1])" $a
    $results[$pair[0]] = $a
}

# 3. /chat with a follow-up, then the stored history
$c1 = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/chat" (@{ message = $Question } | ConvertTo-Json)
Show-Answer "CHAT 1: $Question" $c1
$c2 = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/chat" (@{ message = $FollowUp; session_id = $c1.session_id } | ConvertTo-Json)
Show-Answer "CHAT 2 (follow-up): $FollowUp" $c2
$hist = Invoke-Json "Get" "$BaseUrl/api/lectures/$LectureId/chat/$($c1.session_id)"
Write-Host "`nHistory of session $($c1.session_id): $($hist.messages.Count) messages ($((($hist.messages | ForEach-Object { $_.role }) -join ', ')))"

# 4. The fine-tuned generator (Ollama, Phase 10)
$ft = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/ask" (@{ question = $Question; model = "finetuned" } | ConvertTo-Json) -AllowError
if ($ft.error) { Write-Host "`n=== FINETUNED === HTTP $($ft.http) $($ft.error.code): $($ft.error.message)" }
else { Show-Answer "FINETUNED" $ft }

$results["chat"] = @($c1, $c2)
$dest = Join-Path $OutDir "$LectureId.rag.json"
[System.IO.File]::WriteAllText($dest, ($results | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
Write-Host "`nSaved $dest"
Write-Host "Check: each answer matches the lecture, the cited times point to where it is said, and off-topic questions are refused."
