$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$v4 = Join-Path $dir "V4.0"
$parts = Get-ChildItem -LiteralPath $v4 -Filter "源码包_V4.0.zip.b64.part*" | Sort-Object Name
if ($parts.Count -ne 14) { throw "分片数量不是 14：$($parts.Count)" }
$s = ($parts | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join ""
if ($s.Length -ne 106376) { throw "合并长度不是 106376：$($s.Length)" }
$b64 = Join-Path $v4 "源码包_V4.0.zip.b64"
$zip = Join-Path $v4 "源码包_V4.0.zip"
[IO.File]::WriteAllText($b64, $s, (New-Object Text.UTF8Encoding($false)))
certutil -decode $b64 $zip | Out-Null
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
if ($hash -ne "85C4EC1AA95387D89CF131D496BD48D5C946B221FDDFBF808C041B0471E93E7A") { throw "SHA256 不符：$hash" }
$out = Join-Path $v4 "源码"
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
Write-Host "OK $zip"
Write-Host "SHA256 $hash"
Write-Host "SRC $out"
