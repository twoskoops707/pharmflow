param(
  [string]$Src = "",
  [string]$DestDir = "C:\PharmFlow",
  [string]$ExeName = "PharmFlow.exe"
)
$ErrorActionPreference = "Stop"
if (-not $Src) {
  $candidates = @(
    "C:\Users\jsmil\pharmflow\dist\PharmFlow.exe",
    "C:\Users\jsmil\pharmflow\dist\PharmFlow\PharmFlow.exe"
  )
  foreach ($c in $candidates) { if (Test-Path $c) { $Src = $c; break } }
}
if (-not $Src -or -not (Test-Path $Src)) { throw "No built EXE found. Pass -Src." }
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
$dest = Join-Path $DestDir $ExeName
# Stop running EXE if it holds the file
Get-Process PharmFlow,CPharm -EA SilentlyContinue | ForEach-Object {
  try { Stop-Process -Id $_.Id -Force -EA Stop; "stopped pid=$($_.Id)" } catch { "warn stop $($_.Id): $_" }
}
Start-Sleep -Seconds 2
Copy-Item -LiteralPath $Src -Destination $dest -Force
$sh = New-Object -ComObject WScript.Shell
$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
foreach ($dir in @($programs, $startup)) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
# PharmFlow only — remove legacy CPharm.lnk so Start Menu is not dual-branded.
$legacy = Join-Path $programs "CPharm.lnk"
if (Test-Path $legacy) {
  Remove-Item -LiteralPath $legacy -Force
  "removed_legacy=$legacy"
}
$lnkPath = Join-Path $programs "PharmFlow.lnk"
$l = $sh.CreateShortcut($lnkPath)
$l.TargetPath = $dest
$l.WorkingDirectory = $DestDir
$l.Description = "PharmFlow phone farm"
$l.IconLocation = "$dest,0"
$l.Save()
"startmenu=$lnkPath -> $dest"
# Also pin a Desktop shortcut
$desk = [Environment]::GetFolderPath("Desktop")
$dl = $sh.CreateShortcut((Join-Path $desk "PharmFlow.lnk"))
$dl.TargetPath = $dest
$dl.WorkingDirectory = $DestDir
$dl.Description = "PharmFlow phone farm"
$dl.IconLocation = "$dest,0"
$dl.Save()
"desktop=$(Join-Path $desk 'PharmFlow.lnk')"
Get-Item $dest | Format-List FullName,Length,LastWriteTime
