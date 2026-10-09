# Импорт новой версии обработки вендора в ветку vendor: архив (.rar) или .epf -> XML платформой 8.3.21.
# Порядок: рядом с рабочей копией main сделать вторую на ветке vendor-import/<версия> от vendor
# (git worktree add ..\pedo-vendor -b vendor-import/<версия> origin/vendor) и запустить скрипт из main:
# .\build\vendor-import.ps1 -Root ..\pedo-vendor -Source <файл> -Version <версия>;
# коммит, PR в vendor; после слияния - тег vendor/<версия> и PR vendor -> main.
# Скрипт трогает только src\ (целиком заменяет его выгрузкой вендора) - наши файлы в ветку vendor не попадают.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Source,      # ofd-edo.rar с platformaofd.ru или сам .epf
    [Parameter(Mandatory = $true)] [string] $Version,     # версия вендора, например 1.0.5.3.8
    [Parameter(Mandatory = $true)] [string] $Root,        # рабочая копия на ветке vendor-import/<версия>
    [string] $Designer = 'C:\Program Files\1cv8\8.3.21.1895\bin\1cv8.exe',
    [string] $SevenZip = 'C:\ProgramData\chocolatey\bin\7z.exe',
    [string] $ExpectedFormat = '2.14'
)
$ErrorActionPreference = 'Stop'
# В сеансе без консоли (ssh, задача планировщика) прогресс-бар роняет вызов с Win32 0x5.
$ProgressPreference = 'SilentlyContinue'

$root = (Resolve-Path $Root).Path
$branch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim()
if ($branch -notlike 'vendor-import/*') { throw "импорт делается в ветке vendor-import/<версия> от vendor, сейчас: $branch" }
if (-not (Test-Path $Designer)) { throw "не найден конфигуратор: $Designer" }

$work = Join-Path ([IO.Path]::GetTempPath()) ('pedo-vendor-import-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work | Out-Null
try {
    $epf = $Source
    if ($Source -like '*.rar') {
        & $SevenZip x -y "-o$work\rar" $Source | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "распаковка архива: 7z вернул $LASTEXITCODE" }
        $found = @(Get-ChildItem -Recurse "$work\rar" -Filter *.epf)
        if ($found.Count -ne 1) { throw "в архиве ожидается ровно один .epf, найдено $($found.Count)" }
        $epf = $found[0].FullName
    }
    $epfHash = (Get-FileHash -Algorithm SHA256 $epf).Hash.ToLower()
    $log = Join-Path $work 'designer.log'
    $ib = Join-Path $work 'ib'
    $dump = Join-Path $work 'dump'
    $create = Start-Process $Designer -ArgumentList "CREATEINFOBASE File=""$ib"" /Out ""$log""" -Wait -PassThru
    if ($create.ExitCode -ne 0) { throw "создание файловой ИБ: код $($create.ExitCode)" }
    $unload = Start-Process $Designer -ArgumentList "DESIGNER /F ""$ib"" /DisableStartupDialogs /DumpExternalDataProcessorOrReportToFiles ""$dump\ОФД_ЭДО.xml"" ""$epf"" -Format Hierarchical /Out ""$log""" -Wait -PassThru
    if ($unload.ExitCode -ne 0 -or -not (Test-Path "$dump\ОФД_ЭДО.xml")) { throw "выгрузка epf: код $($unload.ExitCode)`n$(Get-Content -Raw $log -Encoding Default)" }
    # Приведение к устойчивому виду: сборка и повторная выгрузка. Платформа при сборке переставляет
    # порядок обработчиков в части форм; без этого перестановка всплывает шумом в первом же PR,
    # где форму выгрузили из конфигуратора. Второй круг дает то же самое байт в байт (проверено на 1.0.5.3.8).
    $canonicalEpf = Join-Path $work 'canonical.epf'
    $build = Start-Process $Designer -ArgumentList "DESIGNER /F ""$ib"" /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles ""$dump\ОФД_ЭДО.xml"" ""$canonicalEpf"" /Out ""$log""" -Wait -PassThru
    if ($build.ExitCode -ne 0 -or -not (Test-Path $canonicalEpf)) { throw "сборка для приведения: код $($build.ExitCode)`n$(Get-Content -Raw $log -Encoding Default)" }
    $dump = Join-Path $work 'canonical'
    $unload = Start-Process $Designer -ArgumentList "DESIGNER /F ""$ib"" /DisableStartupDialogs /DumpExternalDataProcessorOrReportToFiles ""$dump\ОФД_ЭДО.xml"" ""$canonicalEpf"" -Format Hierarchical /Out ""$log""" -Wait -PassThru
    if ($unload.ExitCode -ne 0 -or -not (Test-Path "$dump\ОФД_ЭДО.xml")) { throw "повторная выгрузка: код $($unload.ExitCode)" }
    $format = [regex]::Match((Get-Content -TotalCount 3 -Encoding UTF8 "$dump\ОФД_ЭДО.xml") -join ' ', 'MetaDataObject[^>]*\sversion="([0-9.]+)"').Groups[1].Value
    if ($format -ne $ExpectedFormat) { throw "выгрузка в формате $format, ожидается $ExpectedFormat - не та платформа?" }

    $src = Join-Path $root 'src'
    if (Test-Path $src) { Remove-Item -Recurse -Force $src }
    Copy-Item -Recurse $dump $src
    Write-Host "src заменен выгрузкой вендора $Version (формат $format, epf sha256 $epfHash)"
    Write-Host "коммит: git add -A src; git commit -m ""vendor $Version`n`nИсточник: $(Split-Path -Leaf $Source), epf sha256 $epfHash, выгрузка 8.3.21 (формат $format)"""
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
