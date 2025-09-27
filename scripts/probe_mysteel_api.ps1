# Quick probe for Mysteel multi-city price API
# Usage examples:
#   pwsh -File scripts/probe_mysteel_api.ps1
#   pwsh -File scripts/probe_mysteel_api.ps1 -Catalog '螺纹钢' -Spec 'HRB400E_20MM' -CityNames '上海','杭州','宁波','唐山'
#   pwsh -File scripts/probe_mysteel_api.ps1 -SingleCityOnly

param(
  [string]$Catalog = '螺纹钢',
  [string]$Spec = 'HRB400E_20MM',
  [string[]]$CityNames = @('上海','北京','南京','天津','唐山','广州'),
  [switch]$SingleCityOnly
)

$ErrorActionPreference = 'Stop'

function Get-MD5Hex([string]$s){
  $md5=[System.Security.Cryptography.MD5]::Create()
  $bytes=[Text.Encoding]::UTF8.GetBytes($s)
  $hash=$md5.ComputeHash($bytes)
  ($hash|ForEach-Object { $_.ToString('x2') }) -join ''
}

function Get-Sign([string]$path,[string]$version,[string]$appSec){
  $ts=[int64](([DateTimeOffset]::UtcNow).ToUnixTimeMilliseconds())
  $raw = 'path' + $path + 'timestamp' + $ts + 'version' + $version + $appSec
  $sign = (Get-MD5Hex $raw).ToUpper()
  return @($sign,$ts)
}

function Get-CityCodes([string[]]$names){
  # Fetch baiduData.js to extract city:name:code pairs
  $url = 'https://a.mysteelcdn.com/jgzs/jg/v1/js/baiduData.js?v=20220905'
  $r = Invoke-WebRequest -Uri $url -TimeoutSec 20 -Headers @{ 'User-Agent'='Mozilla/5.0' }
  $enc=[System.Text.Encoding]::GetEncoding('GB18030')
  $txt = $null
  try {
    $ms = New-Object System.IO.MemoryStream
    $r.RawContentStream.CopyTo($ms)
    $bytes = $ms.ToArray()
    $txt = $enc.GetString($bytes)
  } catch {
    $txt = $r.Content
  }

  $map = @{}
  foreach($n in $names){ $map[$n] = $null }

  # Match patterns like 上海:15278 across the file
  $rx = New-Object System.Text.RegularExpressions.Regex '([\u4e00-\u9fa5]{2,}):([0-9]{3,6})'
  $m = $rx.Matches($txt)
  foreach($mm in $m){
    $name = $mm.Groups[1].Value
    $code = $mm.Groups[2].Value
    if($map.ContainsKey($name) -and -not $map[$name]){ $map[$name] = $code }
  }
  # fallback hard-coded popular cities if not found
  $fallback = @{ '上海'='15278'; '北京'='15472'; '南京'='15407'; '天津'='15480'; '唐山'='15605'; '广州'='15738'; '杭州'='15372'; '宁波'='15584' }
  foreach($k in $names){ if(-not $map[$k] -and $fallback.ContainsKey($k)){ $map[$k] = $fallback[$k] } }
  return $map
}

function Parse-JsonOrJsonp([string]$text){
  if([string]::IsNullOrWhiteSpace($text)){ return $null }
  $pat = '^[\s\S]*?\(\s*([\s\S]*)\s*\)\s*;?\s*$'
  if([Text.RegularExpressions.Regex]::IsMatch($text,$pat)){
    $inner = [Text.RegularExpressions.Regex]::Match($text,$pat).Groups[1].Value
    try { return $inner | ConvertFrom-Json -ErrorAction Stop } catch { return $null }
  }
  try { return $text | ConvertFrom-Json -ErrorAction Stop } catch { return $null }
}

function Invoke-Mysteel([string]$catalog,[string]$spec,[string]$cityCsv,[string]$start='',[string]$end=''){
  $apiUrl = 'https://index.mysteel.com/zs/newprice/getBaiduChartMultiCity.ms'
  $m = [regex]::Match($apiUrl,'\.com(\S*)\.ms')
  if(-not $m.Success){ throw 'bad api url' }
  $path = $m.Groups[1].Value + '.ms'
  $version = '1.0.0'
  $appKey  = '47EE3F12CF0C443F8FD51EFDA73AC815'
  $appSec  = '3BA6477330684B19AA6AF4485497B5F2'
  $signArr = Get-Sign $path $version $appSec
  $sign = $signArr[0]
  $ts   = $signArr[1]
  $headers = @{
    version=$version; appKey=$appKey; timestamp=$ts; sign=$sign;
    'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
    'Referer'='https://index.mysteel.com/price/getChartMultiCity_1_0.html'
    'Accept'='application/json, text/javascript, */*; q=0.01'
    'X-Requested-With'='XMLHttpRequest'
    'Origin'='https://index.mysteel.com'
    'Accept-Language'='zh-CN,zh;q=0.9,en;q=0.6'
  }
  # Build query string via EscapeDataString to ensure proper encoding of CJK
  function Enc([string]$s){ [System.Uri]::EscapeDataString($s) }
  $uri = $apiUrl + '?catalog=' + (Enc $catalog) + '&city=' + (Enc $cityCsv) + '&spec=' + (Enc $spec) + '&callback=json&v=' + $ts
  if($start -and $end){ $uri += '&startTime=' + (Enc $start) + '&endTime=' + (Enc $end) }

  # Ensure TLS12
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
  $resp = Invoke-WebRequest -Uri $uri -Method Get -Headers $headers -TimeoutSec 20
  return $resp
}

#
# Main
#

Write-Host "[probe] Catalog=$Catalog Spec=$Spec Cities=$($CityNames -join ',')"
$map = Get-CityCodes $CityNames
foreach($k in $map.Keys){ if(-not $map[$k]){ Write-Warning "城市未找到编码: $k" } }
$pairs = @()
foreach($n in $CityNames){ if($map[$n]){ $pairs += "${n}:$($map[$n])" } }
if(-not $pairs){ throw '未找到任何城市编码，终止。' }
$multiCsv = ($pairs -join ',')

New-Item -ItemType Directory -Force -Path tmp | Out-Null
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'

if(-not $SingleCityOnly){
  try {
    Write-Host "[probe] multi-city request: $multiCsv"
    $r = Invoke-Mysteel -catalog $Catalog -spec $Spec -cityCsv $multiCsv
    $raw = $r.Content
    $path = "tmp/mysteel_multi_${ts}.txt"
    [System.IO.File]::WriteAllText($path, $raw, [System.Text.Encoding]::UTF8)
    $obj = Parse-JsonOrJsonp $raw
    $count = if($obj -and $obj.data){ $obj.data.Count } else { 0 }
    Write-Host "[probe] multi-city status=$($r.StatusCode) series=$count saved=$path"
  } catch {
    Write-Warning "multi-city 调用失败: $_"
  }
}

# single-city fallback
foreach($p in $pairs){
  try {
    Write-Host "[probe] single-city request: $p"
    $r = Invoke-Mysteel -catalog $Catalog -spec $Spec -cityCsv $p
    $raw = $r.Content
    $safe = ($p -replace '[^\w\-\.:]','_')
    $path = "tmp/mysteel_${safe}_${ts}.txt"
    [System.IO.File]::WriteAllText($path, $raw, [System.Text.Encoding]::UTF8)
    $obj = Parse-JsonOrJsonp $raw
    $count = if($obj -and $obj.data){ $obj.data.Count } else { 0 }
    $msg   = if($obj -and $obj.message){ $obj.message } else { '' }
    Write-Host "[probe] $p status=$($r.StatusCode) series=$count msg=$msg saved=$path"
  } catch {
    Write-Warning "single-city 调用失败 ${p}: $_"
  }
}

Write-Host "[probe] 完成。查看 tmp/ 目录中的抓包结果。"
