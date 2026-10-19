# Install the official LibreDWG 0.14 win64 dwg2dxf into bin/win32-x64/ of this
# package with its GPL compliance files (see bin/README.md). The zip's sha256 is
# pinned; dwg2dxf.exe and every DLL at the zip root are copied, COPYING and
# SOURCE-OFFER.txt come from bin/, and VERSION.txt records the source.
#
# Usage (PowerShell 5.1 or 7, from any directory):
#   powershell -NoProfile -ExecutionPolicy Bypass -File zhitong\plugins\tool-cad\scripts\fetch-dwg2dxf-win64.ps1 [-Work <dir>]
param([string]$Work = (Join-Path ([System.IO.Path]::GetTempPath()) 'libredwg-0.14-win64'))
$ErrorActionPreference = 'Stop'

$Version = '0.14'
$Sha256 = '1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8'
$Url = "https://github.com/LibreDWG/libredwg/releases/download/$Version/libredwg-$Version-win64.zip"
$Here = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $Here 'bin\win32-x64'

New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Zip = Join-Path $Work "libredwg-$Version-win64.zip"
if (-not (Test-Path $Zip)) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
}
$Actual = (Get-FileHash -Algorithm SHA256 -Path $Zip).Hash.ToLowerInvariant()
if ($Actual -ne $Sha256) {
  Remove-Item -Force $Zip
  throw "sha256 mismatch for ${Url}: $Actual"
}

$Extract = Join-Path $Work 'extract'
if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
Expand-Archive -Path $Zip -DestinationPath $Extract
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Path (Join-Path $Extract 'dwg2dxf.exe') -Destination $Dest
Get-ChildItem -Path $Extract -Filter '*.dll' -File | Copy-Item -Destination $Dest
Copy-Item -Path (Join-Path $Here 'bin\COPYING') -Destination (Join-Path $Dest 'COPYING')
Copy-Item -Path (Join-Path $Here 'bin\SOURCE-OFFER.txt') -Destination (Join-Path $Dest 'SOURCE-OFFER.txt')
# UTF-8 without BOM: cad_open reports the first line verbatim.
[System.IO.File]::WriteAllLines((Join-Path $Dest 'VERSION.txt'), [string[]]@(
  "LibreDWG dwg2dxf $Version",
  "source: $Url",
  "source sha256: $Sha256",
  'build: official win64 release (dwg2dxf.exe and the DLLs at the zip root)',
  "installed: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
))
Write-Output "installed $(Join-Path $Dest 'dwg2dxf.exe')"
