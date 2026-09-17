# Local Ollama -> Cursor cloud agent bridge (HTTPS tunnel + health checks).
# Keeps cloudflared pointed at the local Ollama server so Cursor's Override Base URL can use a public /v1.
# Mirrors start-freellmapi-cursor-agent.ps1 in AppData/Local/FamFlowTools, adapted for Ollama.
$ErrorActionPreference = "Stop"

$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $Tools "ollama.env"
$StateFile = Join-Path $Tools "ollama-cursor-agent.json"
$LogFile = Join-Path $Tools "ollama-cursor-agent.log"
$OllamaExe = "C:\Users\jsmil\AppData\Local\Programs\Ollama\ollama.exe"
$AuthProxyScript = Join-Path $Tools "ollama_auth_proxy.py"

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

function Test-Gateway([string]$BaseUrl, [int]$Retries = 12, [string]$Token = "") {
  $uri = ($BaseUrl.TrimEnd("/") + "/models")
  $headers = @{}
  if ($Token) { $headers["Authorization"] = "Bearer $Token" }
  $lastError = $null
  for ($i = 1; $i -le $Retries; $i++) {
    try {
      $resp = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
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

function Stop-StaleAuthProxy {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'ollama_auth_proxy\.py' } |
    ForEach-Object {
      Write-Log "Stopping stale ollama_auth_proxy PID $($_.ProcessId)"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-AuthProxy([int]$ListenPort, [int]$UpstreamPort, [string]$Token) {
  $python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $python) { throw "python not found on PATH -- needed for ollama_auth_proxy.py" }
  Stop-StaleAuthProxy
  $stdout = Join-Path $Tools "ollama-auth-proxy.out.log"
  $stderr = Join-Path $Tools "ollama-auth-proxy.err.log"
  # Pass the token via env, never argv -- a plain command-line arg is visible
  # to any other process on the box via WMI/Get-CimInstance/Task Manager's
  # command-line column for as long as the proxy runs. Windows PowerShell 5.1's
  # Start-Process has no -Environment parameter, so set it on this process;
  # Start-Process's child inherits the parent environment at spawn time, then
  # restore/clear it immediately so it doesn't linger in this script's own env.
  $prevToken = $env:OLLAMA_TUNNEL_TOKEN
  $env:OLLAMA_TUNNEL_TOKEN = $Token
  try {
    Start-Process -FilePath $python -ArgumentList @(
      $AuthProxyScript,
      "--listen-port", $ListenPort,
      "--upstream-port", $UpstreamPort
    ) -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden
  } finally {
    if ($null -eq $prevToken) { Remove-Item Env:\OLLAMA_TUNNEL_TOKEN -ErrorAction SilentlyContinue }
    else { $env:OLLAMA_TUNNEL_TOKEN = $prevToken }
  }
  if (-not (Wait-Listening $ListenPort -TimeoutSec 15)) {
    throw "ollama_auth_proxy did not start listening on 127.0.0.1:$ListenPort"
  }
}

$envMap = Read-EnvMap $EnvFile
$port = if ($envMap["OLLAMA_PORT"]) { [int]$envMap["OLLAMA_PORT"] } else { 11434 }
$model = if ($envMap["OLLAMA_MODEL"]) { $envMap["OLLAMA_MODEL"] } else { "qwen2.5-coder:7b-instruct" }
$proxyPort = if ($envMap["OLLAMA_PROXY_PORT"]) { [int]$envMap["OLLAMA_PROXY_PORT"] } else { $port + 1 }
# Persist the token across re-runs so only the tunnel URL (not the Cursor API
# key too) needs updating when the trycloudflare URL rotates.
$token = $envMap["OLLAMA_TUNNEL_TOKEN"]
if (-not $token) {
  $bytes = New-Object byte[] 24
  $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $token = [Convert]::ToBase64String($bytes) -replace '[/+=]', ''
}

if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
  Write-Log "Starting Ollama server..."
  Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
}
if (-not (Wait-Listening $port)) {
  throw "Ollama is not listening on 127.0.0.1:$port"
}

$localCount = Test-Gateway "http://127.0.0.1:$port/v1"
Write-Log "Local Ollama OK ($localCount models)"

# Tunnel targets the auth proxy's port, never Ollama's raw port directly --
# the public trycloudflare URL must never expose Ollama's unauthenticated
# chat/model-management API to anyone who obtains it.
Start-AuthProxy -ListenPort $proxyPort -UpstreamPort $port -Token $token
Write-Log "Auth proxy up on 127.0.0.1:$proxyPort (token-gated) -> upstream 127.0.0.1:$port"

$tunnel = Start-Tunnel $proxyPort
$publicBase = ($tunnel.publicUrl.TrimEnd("/") + "/v1")
$publicCount = Test-Gateway $publicBase -Token $token
Write-Log "Public tunnel OK ($publicCount models) -> $publicBase"

$state = @{
  updatedAt = (Get-Date).ToUniversalTime().ToString("o")
  localBaseUrl = "http://127.0.0.1:$port/v1"
  publicBaseUrl = $publicBase
  cloudflaredPid = $tunnel.pid
  model = $model
  cursor = @{
    overrideOpenAiBaseUrl = $publicBase
    openAiApiKey = $token
    model = $model
  }
}
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding utf8

# Keep env in sync.
$lines = if (Test-Path $EnvFile) { Get-Content $EnvFile } else { @() }
$updates = @{
  OLLAMA_PUBLIC_URL = $tunnel.publicUrl
  OPENAI_BASE_URL = $publicBase
  OLLAMA_PROXY_PORT = $proxyPort
  OLLAMA_TUNNEL_TOKEN = $token
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
Write-Host "OpenAI API Key: $token"
Write-Host "  (this token is required -- the public URL is proxied through a"
Write-Host "   bearer-token gate in front of Ollama, not Ollama's raw port)"
Write-Host "Model: $model"
Write-Host ""
Write-Host "State: $StateFile"
Write-Host "Leave this tunnel running. Re-run this script if the URL expires."
