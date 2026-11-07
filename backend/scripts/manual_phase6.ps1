# Phase 6 manual test (Windows PowerShell 5.1+): quiz generation, grading, mastery and flashcards
# on a lecture that already has its summary/notes (run manual_phase5.ps1 first).
#
# Start the API first (cd backend; uvicorn app.main:app --reload), then from backend/:
#   .\scripts\manual_phase6.ps1                              # newest "ready" lecture of the test account
#   .\scripts\manual_phase6.ps1 -LectureId <id>
#   .\scripts\manual_phase6.ps1 -Interactive                 # you type the answers yourself
#   .\scripts\manual_phase6.ps1 -NumQuestions 8 -Difficulty hard -Types mcq,short_answer
#   .\scripts\manual_phase6.ps1 -RegenerateDeck              # replace the flashcard deck
#
# Without -Interactive it answers automatically (A for MCQs, true for true/false, a vague text for
# short answers) just to show the grading. Uses your Groq free quota (a few requests); it never
# calls OpenAI unless you set it. Saves the JSON responses to ..\storage\manual-test\.

param(
    [string]$LectureId = "",
    [int]$NumQuestions = 6,
    [string]$Difficulty = "mixed",
    [string[]]$Types = @("mcq", "true_false", "short_answer"),
    [switch]$Interactive,
    [switch]$RegenerateDeck,
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "manual-test@example.com",
    [string]$Password = "manual-test-password"
)
$ErrorActionPreference = "Stop"
$OutDir = Join-Path $PSScriptRoot "..\..\storage\manual-test"
New-Item -ItemType Directory -Force $OutDir | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# PowerShell 5.1 decodes JSON without a charset as Latin-1; decode the bytes as UTF-8 instead.
# On an error response it prints the API's error envelope before stopping.
function Invoke-Json([string]$Method, [string]$Uri, [string]$Body = $null, [int]$TimeoutSec = 900) {
    $req = @{ Method = $Method; Uri = $Uri; Headers = $headers; UseBasicParsing = $true; TimeoutSec = $TimeoutSec }
    if ($Body) { $req.ContentType = "application/json; charset=utf-8"; $req.Body = [System.Text.Encoding]::UTF8.GetBytes($Body) }
    try { $resp = Invoke-WebRequest @req }
    catch {
        $r = $_.Exception.Response
        if ($r) {
            $text = (New-Object System.IO.StreamReader($r.GetResponseStream(), [System.Text.Encoding]::UTF8)).ReadToEnd()
            Write-Host "HTTP $([int]$r.StatusCode): $text" -ForegroundColor Red
        }
        throw
    }
    [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json
}
function Show-Time($sec) { if ($null -eq $sec) { return "--:--" }; $t = [TimeSpan]::FromSeconds([double]$sec); "{0:D2}:{1:D2}" -f [int][Math]::Floor($t.TotalMinutes), $t.Seconds }
function Save-Json($obj, [string]$name) {
    $dest = Join-Path $OutDir $name
    [System.IO.File]::WriteAllText($dest, ($obj | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding $false))
    $dest
}

# 1. Account
$cred = @{ email = $Email; password = $Password } | ConvertTo-Json
try { Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/register" -ContentType "application/json" -Body $cred | Out-Null }
catch { if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw } }
$token = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $cred).access_token
$headers = @{ Authorization = "Bearer $token" }

# 2. Lecture
if (-not $LectureId) {
    $ready = @(Invoke-Json "Get" "$BaseUrl/api/lectures" | Where-Object { $_.status -eq "ready" })
    if ($ready.Count -eq 0) { throw "No 'ready' lecture for $Email. Run .\scripts\manual_phase5.ps1 first." }
    $LectureId = $ready[0].id
}
$lec = Invoke-Json "Get" "$BaseUrl/api/lectures/$LectureId"
Write-Host "Lecture $LectureId  '$($lec.title)'  ($(Show-Time $lec.duration_sec))"

# 3. Generate a quiz
$body = @{ num_questions = $NumQuestions; types = $Types; difficulty = $Difficulty } | ConvertTo-Json
$t0 = Get-Date
$quiz = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/generate-quiz" $body
$genSec = ((Get-Date) - $t0).TotalSeconds
$m = $quiz.meta
Write-Host ("`n=== QUIZ {0}: {1} of {2} questions, {3} LLM call(s), {4} invalid item(s) regenerated, {5:N1} s ===" -f `
    $quiz.quiz_id, $m.generated, $m.requested, $m.llm_calls, $m.invalid_items, $genSec)
if ($m.invalid_items) { Write-Host ("Rejected: " + (($m.invalid_reasons.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", ")) }

$answers = @{}
foreach ($q in $quiz.questions) {
    Write-Host ("`n[{0}] ({1}, {2}, topic: {3})" -f $q.id, $q.type, $q.difficulty, $q.topic)
    Write-Host "  $($q.question)"
    if ($q.type -eq "mcq") { for ($i = 0; $i -lt $q.options.Count; $i++) { Write-Host ("    {0}) {1}" -f "ABCD"[$i], $q.options[$i]) } }
    if ($Interactive) {
        $hint = switch ($q.type) { "mcq" { "A-D" } "true_false" { "true/false" } default { "your answer" } }
        $a = Read-Host "  Answer ($hint)"
        if ($q.type -eq "true_false" -and $a -match '^(true|false)$') { $answers[$q.id] = ($a -eq "true") } else { $answers[$q.id] = $a }
    } else {
        $answers[$q.id] = switch ($q.type) { "mcq" { "A" } "true_false" { $true } default { "I think it is about the main idea of this part of the lecture." } }
    }
}
Save-Json $quiz "$LectureId.quiz.json" | Out-Null

# 4. Submit
$res = Invoke-Json "Post" "$BaseUrl/api/quizzes/$($quiz.quiz_id)/submit" (@{ answers = $answers } | ConvertTo-Json)
Write-Host ("`n=== RESULT: {0} / {1} ({2}%), suggested next difficulty: {3} ===" -f $res.score, $res.total, $res.percent, $res.suggested_next_difficulty)
foreach ($r in $res.results) {
    $mark = if ($r.correct) { "OK  " } else { "WRONG" }
    Write-Host ("  {0} {1} [{2}] you: {3} | correct: {4} | graded by {5}" -f $mark, $r.id, (Show-Time $r.timestamp), $r.your_answer, $r.correct_answer, $r.graded_by)
    Write-Host "       $($r.explanation)"
    if ($r.feedback) { Write-Host "       feedback: $($r.feedback)" }
}
Write-Host "`nTopic mastery:"
$res.topics | ForEach-Object { Write-Host ("  {0,-45} {1}/{2} correct  mastery {3:N2}" -f $_.topic, $_.correct, $_.total, $_.mastery) }
Write-Host "Weak topics: $(if ($res.weak_topics.Count) { $res.weak_topics -join '; ' } else { '(none)' })"
Save-Json $res "$LectureId.quiz-result.json" | Out-Null

# 5. Flashcards
$deckBody = @{ regenerate = [bool]$RegenerateDeck } | ConvertTo-Json
$t0 = Get-Date
$deck = Invoke-Json "Post" "$BaseUrl/api/lectures/$LectureId/flashcards" $deckBody
$deckSec = ((Get-Date) - $t0).TotalSeconds
$defs = @($deck.cards | Where-Object { $_.kind -eq "definition" }).Count
Write-Host ("`n=== FLASHCARDS: {0} cards ({1} definition, {2} concept), cached={3}, {4:N1} s ===" -f $deck.total, $defs, ($deck.total - $defs), $deck.cached, $deckSec)
$deck.cards | Select-Object -First 8 | ForEach-Object { Write-Host ("  [{0}] ({1}) {2}`n         -> {3}" -f (Show-Time $_.timestamp), $_.kind, $_.front, $_.back) }
if ($deck.total -gt 0) {
    $card = $deck.cards[0]
    $after = Invoke-Json "Post" "$BaseUrl/api/flashcards/$($card.id)/review" '{"knew": true}'
    Write-Host ("`nReviewed '{0}' as known: box {1} -> {2}, next due {3}" -f $card.front, $card.box, $after.box, $after.due_at)
    $due = Invoke-Json "Get" "$BaseUrl/api/lectures/$LectureId/flashcards?due=true"
    Write-Host "Cards due now: $($due.total) of $($deck.total)"
}
$dest = Save-Json $deck "$LectureId.flashcards.json"
Write-Host "Saved quiz, result and deck JSON next to $dest"
Write-Host "Check: every question/card matches what the lecture says, and each timestamp points to where it is explained."
