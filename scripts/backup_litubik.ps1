<#
Recurring full backup of a LitUbik instance onto this machine.

Downloads /api/admin/backup (superadmin account required) into -Dest as
litubik_backup_YYYYMMDD_HHmmss.zip, verifies the archive, then keeps only the
-Keep most recent copies. The zip holds litubik.db (consistent SQLite copy),
secret.key when the instance auto-generated one, and with -IncludeFiles every
stored project file (PDFs, raw RIS, protocols).

One-off run:
  powershell -ExecutionPolicy Bypass -File backup_litubik.ps1 `
    -BaseUrl https://litubik.example.org -Email admin@example.org `
    -PasswordFile C:\secrets\litubik_pwd.txt

Install as a daily scheduled task (03:30, current user):
  powershell -ExecutionPolicy Bypass -File backup_litubik.ps1 `
    -BaseUrl https://litubik.example.org -Email admin@example.org `
    -PasswordFile C:\secrets\litubik_pwd.txt -IncludeFiles -Install

The password file is a plain text file holding only the password: preferable
to -Password, which would end up readable in the scheduled task definition.

Restore (see docs/help/*/07-collaboration.md): stop the app, put litubik.db
(and secret.key) from the zip back into the data/ folder — removing any
litubik.db-wal / litubik.db-shm left behind — unzip storage/ next to them if
present, restart.
#>
param(
  [Parameter(Mandatory = $true)][string]$BaseUrl,
  [Parameter(Mandatory = $true)][string]$Email,
  [string]$Password,
  [string]$PasswordFile,
  [string]$Dest = "$env:USERPROFILE\LitUbik-backups",
  [int]$Keep = 3,
  [switch]$IncludeFiles,
  [switch]$Install,
  [string]$At = "03:30"
)

$ErrorActionPreference = 'Stop'
$BaseUrl = $BaseUrl.TrimEnd('/')

if (-not $Password) {
  if (-not $PasswordFile) {
    throw "Give the account password via -PasswordFile (recommended) or -Password."
  }
  $Password = (Get-Content -Raw $PasswordFile).Trim()
}

if ($Install) {
  # re-run this very script daily; the password stays in the file, not in the task
  if (-not $PasswordFile) {
    throw "-Install requires -PasswordFile: a plain -Password would be stored readable in the task."
  }
  $scriptPath = $MyInvocation.MyCommand.Path
  $taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" " +
              "-BaseUrl `"$BaseUrl`" -Email `"$Email`" -PasswordFile `"$PasswordFile`" " +
              "-Dest `"$Dest`" -Keep $Keep" + $(if ($IncludeFiles) { " -IncludeFiles" } else { "" })
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
  $trigger = New-ScheduledTaskTrigger -Daily -At $At
  Register-ScheduledTask -TaskName "LitUbik backup" -Action $action `
    -Trigger $trigger -Description "Daily LitUbik full backup (keeps $Keep)" -Force | Out-Null
  Write-Output "Scheduled task 'LitUbik backup' registered (daily at $At)."
  Write-Output "Test it now with: Start-ScheduledTask -TaskName 'LitUbik backup'"
  return
}

New-Item -ItemType Directory -Force $Dest | Out-Null

# --- login (session cookie) --------------------------------------------------
$body = @{ email = $Email; password = $Password } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" `
  -ContentType "application/json" -Body $body -SessionVariable session | Out-Null

# --- download ----------------------------------------------------------------
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Dest "litubik_backup_$stamp.zip"
$tmp = "$out.part"
$files = if ($IncludeFiles) { "true" } else { "false" }
try {
  Invoke-WebRequest -Uri "$BaseUrl/api/admin/backup?files=$files" `
    -WebSession $session -OutFile $tmp
  # the archive must open and contain the database before we trust it
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::OpenRead($tmp)
  try {
    if (-not ($zip.Entries | Where-Object { $_.FullName -eq "litubik.db" })) {
      throw "archive has no litubik.db — not a LitUbik backup"
    }
  } finally { $zip.Dispose() }
  Move-Item -Force $tmp $out
} finally {
  if (Test-Path $tmp) { Remove-Item -Force $tmp }
}
$sizeMb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Output "Backup OK: $out ($sizeMb Mo)"

# --- rotation: keep the $Keep most recent ------------------------------------
Get-ChildItem $Dest -Filter "litubik_backup_*.zip" |
  Sort-Object Name -Descending |
  Select-Object -Skip $Keep |
  ForEach-Object {
    Write-Output "Rotation: removing $($_.Name)"
    Remove-Item -Force $_.FullName
  }
