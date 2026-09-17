# Local Ollama -> Cursor cloud agent bridge (HTTPS tunnel + health checks).
# Keeps cloudflared pointed at the local Ollama server so Cursor's Override Base URL can use a public /v1.
# Mirrors start-freellmapi-cursor-agent.ps1 in AppData/Local/FamFlowTools, adapted for Ollama.
$ErrorActionPreference = "Stop"

$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $Tools "ollama.env"
$StateFile = Join-Path $Tools "ollama-cursor-agent.json"
$LogFile = Join-Path $Tools "ollama-cursor-agent.log"
$OllamaExe = "C:\Users\jsmil\AppData\Local\Programs\Ollama\ollama.exe"

function Write-Log([string]$Message) {
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
  Add-Content -Path $LogFile -Value $line -Encoding utf8
  Write-Host $line
}

function Read-EnvMap([string]$Path) {
  $map = @{}
  if (-not (Test-Path $Path)) { return $map }
  Get-Content $Path | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      $map[$Matches[1]] = $Matches[2]
    }
  }
  return $map
}

function Wait-Listening([int]$ListenPort, [int]$TimeoutSec = 45) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue) {
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Stop-StaleTunnel {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and
      $_.CommandLine -match 'cloudflared.*tunnel.*--url\s+http://127\.0\.0\.1:' -and
      $_.CommandLine -match 'ollama-cursor-agent'
    } |
    ForEach-Object {
      Write-Log "Stopping stale cloudflared PID $($_.ProcessId)"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-Tunnel([int]$ListenPort) {
  $cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
  if (-not $cloudflared) {
    $fallback = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path $fallback) { $cloudflared = $fallback }
  }
  if (-not $cloudflared) {
    throw "cloudflared not found. Install: winget install Cloudflare.cloudflared"
  }

  Stop-StaleTunnel

  $stdout = Join-Path $Tools "ollama-cursor-agent.cloudflared.out.log"
  $stderr = Join-Path $Tools "ollama-cursor-agent.cloudflared.err.log"
  if (Test-Path $stdout) { Remove-Item $stdout -Force }
  if (Test-Path $stderr) { Remove-Item $stderr -Force }

  $args = @(
    "tunnel",
    "--url", "http://127.0.0.1:$ListenPort",
    "--logfile", (Join-Path $Tools "ollama-cursor-agent.cloudflared.log"),
    "--loglevel", "info"
  )

  Write-Log "Starting cloudflared -> http://127.0.0.1:$ListenPort"
  $proc = Start-Process -FilePath $cloudflared -ArgumentList $args `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
    -WindowStyle Hidden -PassThru

  $deadline = (Get-Date).AddSeconds(60)
  $publicUrl = $null
  while ((Get-Date) -lt $deadline) {
    foreach ($file in @($stdout, $stderr)) {
      if (-not (Test-Path $file)) { continue }
      $text = Get-Content $file -Raw -ErrorAction SilentlyContinue
      if ($text -match '(https://[a-z0-9-]+\.trycloudflare\.com)') {
        $publicUrl = $Matches[1]
        break
      }
    }
    if ($publicUrl) { break }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }

  if (-not $publicUrl) {
    throw "cloudflared did not publish a trycloudflare URL within 60s (PID $($proc.Id))"
  }

  return @{
    pid = $proc.Id
    publicUrl = $publicUrl
  }
}

function Test-Gateway([string]$BaseUrl, [int]$Retries = 12) {
  $uri = ($BaseUrl.TrimEnd("/") + "/models")
  $lastError = $null
  for ($i = 1; $i -le $Retries; $i++) {
    try {
      $resp = Invoke-RestMethod -Uri $uri -TimeoutSec 30
      $count = @($resp.data).Count
      if ($count -lt 1) { throw "Gateway /v1/models returned no models" }
      if ($i -gt 1) { Write-Log "Gateway probe succeeded on attempt $i" }
      return $count
    } catch {
      $lastError = $_
      if ($i -lt $Retries) {
        Write-Log "Gateway probe attempt $i failed; retrying in 5s..."
        Start-Sleep -Seconds 5
      }
    }
  }
  throw $lastError
}

$envMap = Read-EnvMap $EnvFile
$port = if ($envMap["OLLAMA_PORT"]) { [int]$envMap["OLLAMA_PORT"] } else { 11434 }
$model = if ($envMap["OLLAMA_MODEL"]) { $envMap["OLLAMA_MODEL"] } else { "qwen2.5-coder:7b-instruct" }

if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
  Write-Log "Starting Ollama server..."
  Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
}
if (-not (Wait-Listening $port)) {
  throw "Ollama is not listening on 127.0.0.1:$port"
}

$localCount = Test-Gateway "http://127.0.0.1:$port/v1"
Write-Log "Local Ollama OK ($localCount models)"

$tunnel = Start-Tunnel $port
$publicBase = ($tunnel.publicUrl.TrimEnd("/") + "/v1")
$publicCount = Test-Gateway $publicBase
Write-Log "Public tunnel OK ($publicCount models) -> $publicBase"

$state = @{
  updatedAt = (Get-Date).ToUniversalTime().ToString("o")
  localBaseUrl = "http://127.0.0.1:$port/v1"
  publicBaseUrl = $publicBase
  cloudflaredPid = $tunnel.pid
  model = $model
  cursor = @{
    overrideOpenAiBaseUrl = $publicBase
    openAiApiKey = "any non-empty value works, Ollama does not check it"
    model = $model
  }
}
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding utf8

# Keep env in sync.
$lines = if (Test-Path $EnvFile) { Get-Content $EnvFile } else { @() }
$updates = @{
  OLLAMA_PUBLIC_URL = $tunnel.publicUrl
  OPENAI_BASE_URL = $publicBase
}
$newLines = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($line in $lines) {
  $matched = $false
  foreach ($key in $updates.Keys) {
    if ($line -match "^\s*$key\s*=") {
      $newLines.Add("$key=$($updates[$key])")
      $seen[$key] = $true
      $matched = $true
      break
    }
  }
  if (-not $matched) { $newLines.Add($line) }
}
foreach ($key in $updates.Keys) {
  if (-not $seen[$key]) { $newLines.Add("$key=$($updates[$key])") }
}
$newLines | Set-Content -Path $EnvFile -Encoding utf8

Write-Log "Cursor agent ready."
Write-Host ""
Write-Host "=== Cursor Settings -> Models ==="
Write-Host "Override OpenAI Base URL: $publicBase"
Write-Host "OpenAI API Key: (any non-empty value, e.g. ollama-local)"
Write-Host "Model: $model"
Write-Host ""
Write-Host "State: $StateFile"
Write-Host "Leave this tunnel running. Re-run this script if the URL expires."
