# Сборка внешней обработки «Платформа ЭДО» (.epf) из XML-исходников src\.
# Собирать ТОЙ ЖЕ платформой, которой сделаны исходники (8.3.21, формат 2.14): собранный файл
# открывается на этой версии и новее. Новее собрать можно, но тогда у пользователей со старой
# платформой файл не откроется. Нужна только платформа, рабочая база не нужна.
[CmdletBinding()]
param(
    [string] $Designer = 'C:\Program Files\1cv8\8.3.21.1895\bin\1cv8.exe',
    [string] $Src,                       # каталог исходников (по умолчанию ..\src)
    [string] $Out,                       # куда положить .epf (по умолчанию ..\dist\Платформа_ЭДО_<версия>.epf)
    [string] $ExpectedFormat = '2.14',
    [int]    $MinSizeKb = 300            # порог «сборка не пустая»
)
$ErrorActionPreference = 'Stop'
# В сеансе без консоли (ssh, задача планировщика) прогресс-бар роняет вызов с Win32 0x5.
$ProgressPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
if (-not $Src) { $Src = Join-Path $root 'src' }
$rootXml = Join-Path $Src 'ОФД_ЭДО.xml'
$objectModule = Join-Path $Src 'ОФД_ЭДО\Ext\ObjectModule.bsl'
$version = [regex]::Match((Get-Content -Raw -Encoding UTF8 $objectModule), 'РегистрационныеДанные\.Вставить\("Информация",\s*"[^"]*Сборка (\d+(?:\.\d+)+)').Groups[1].Value
if (-not $version) { throw "не прочитана версия из $objectModule" }
if (-not $Out) { $Out = Join-Path $root "dist\Платформа_ЭДО_$version.epf" }
if (-not (Test-Path $Designer)) { throw "не найден конфигуратор: $Designer" }
if (-not (Test-Path $rootXml)) { throw "не найден корневой файл исходников: $rootXml" }

# Формат исходников должен совпадать с платформой сборки: иначе либо отказ загрузки, либо шум в диффе.
$format = [regex]::Match((Get-Content -TotalCount 3 -Encoding UTF8 $rootXml) -join ' ', 'MetaDataObject[^>]*\sversion="([0-9.]+)"').Groups[1].Value
if ($format -ne $ExpectedFormat) { throw "формат исходников $format, ожидается $ExpectedFormat" }

New-Item -ItemType Directory -Force (Split-Path -Parent $Out) | Out-Null
$work = Join-Path ([IO.Path]::GetTempPath()) ('pedo-epf-build-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work | Out-Null
try {
    $log = Join-Path $work 'designer.log'
    $ib = Join-Path $work 'ib'
    # Конфигуратор из ssh: только Start-Process -Wait -PassThru, вызов через & не ждет GUI-приложение.
    $create = Start-Process $Designer -ArgumentList "CREATEINFOBASE File=""$ib"" /Out ""$log""" -Wait -PassThru
    if ($create.ExitCode -ne 0) { throw "создание файловой ИБ: код $($create.ExitCode)`n$(Get-Content -Raw $log -Encoding Default)" }
    if (Test-Path $Out) { Remove-Item -Force $Out }
    $load = Start-Process $Designer -ArgumentList "DESIGNER /F ""$ib"" /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles ""$rootXml"" ""$Out"" /Out ""$log""" -Wait -PassThru
    $logText = Get-Content -Raw $log -Encoding Default
    if ($load.ExitCode -ne 0 -or -not (Test-Path $Out)) { throw "сборка epf: код $($load.ExitCode)`n$logText" }
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

$size = (Get-Item $Out).Length
if ($size -lt ($MinSizeKb * 1KB)) { throw ("собран подозрительно маленький epf: {0} Б" -f $size) }
$hash = (Get-FileHash -Algorithm SHA256 $Out).Hash.ToLower()
Write-Host ("готово: {0}, версия {1}, {2:N0} Б, sha256 {3}" -f $Out, $version, $size, $hash)
