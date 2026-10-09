# Общее для сборки и импорта: файловая база с конфигурацией-заглушкой build\stub-config.
# ⚠️ В пустой базе конфигуратор, выгружая или собирая внешнюю обработку, не может разрешить ссылочные
# типы конфигурации (cfg:CatalogRef.Организации и т.п.) и молча пишет вместо них строку. Заглушка держит
# пустые объекты с теми же именами; типы во внешней обработке связываются по имени, поэтому собранная
# на заглушке обработка работает в настоящей конфигурации. Новый тип у вендора - добавить объект в заглушку.

function Invoke-Designer {
    param([string] $Designer, [string] $Arguments, [string] $Log, [string] $Stage)
    # Из ssh конфигуратор - только Start-Process -Wait -PassThru: вызов через & не ждет GUI-приложение.
    $process = Start-Process $Designer -ArgumentList "$Arguments /Out ""$Log""" -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "${Stage}: код $($process.ExitCode)`n$(Get-Content -Raw $Log -Encoding Default -ErrorAction SilentlyContinue)"
    }
}

function New-StubInfobase {
    param([string] $Designer, [string] $Work)
    $stubConfig = Join-Path $PSScriptRoot 'stub-config'
    if (-not (Test-Path (Join-Path $stubConfig 'Configuration.xml'))) { throw "не найдена заглушка: $stubConfig" }
    $ib = Join-Path $Work 'ib'
    $log = Join-Path $Work 'designer.log'
    Invoke-Designer $Designer "CREATEINFOBASE File=""$ib""" $log 'создание файловой ИБ'
    Invoke-Designer $Designer "DESIGNER /F ""$ib"" /DisableStartupDialogs /LoadConfigFromFiles ""$stubConfig""" $log 'загрузка заглушки'
    Invoke-Designer $Designer "DESIGNER /F ""$ib"" /DisableStartupDialogs /UpdateDBCfg" $log 'обновление конфигурации БД'
    return $ib
}
