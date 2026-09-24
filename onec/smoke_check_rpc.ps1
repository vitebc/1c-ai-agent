<#Requires -Version 5.1
<#
.SYNOPSIS
  Проверка JSON-RPC MCP-сервиса 1С (hs/mcp/rpc) без ручного экранирования JSON.

.DESCRIPTION
  Тело запроса собирается через ConvertTo-Json — кавычки экранировать не нужно.
  Авторизация — пользователь информационной базы 1С (Basic-авторизация HTTP).

.EXAMPLE
  # Список инструментов:
  .\smoke_check_rpc.ps1 -BaseUrl "http://192.168.0.178/ca2_td_update" -User "agent" -Password "agent007" -List

.EXAMPLE
  # Вызов инструмента без аргументов:
  .\smoke_check_rpc.ps1 -BaseUrl "http://192.168.0.178/ca2_td_update" -User "agent" -Password "agent007" -Call "get_configuration_info"

.EXAMPLE
  # Вызов с аргументами (JSON-строка):
  .\smoke_check_rpc.ps1 -BaseUrl "http://192.168.0.178/ca2_td_update" -User "agent" -Password "agent007" -Call "execute_select" -Arguments '{"query":"ВЫБРАТЬ ПЕРВЫЕ 1 Номер ИЗ Документ.ЗаказКлиента","limit":5}'
#>
[CmdletBinding(DefaultParameterSetName = "List")]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$User,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [Parameter(ParameterSetName = "List")]
    [switch]$List,

    [Parameter(ParameterSetName = "Call", Mandatory = $true)]
    [string]$Call,

    [Parameter(ParameterSetName = "Call")]
    [string]$Arguments = "{}"
)

$ErrorActionPreference = "Stop"

$uri = ($BaseUrl.TrimEnd("/") + "/hs/mcp/rpc")

if ($PSCmdlet.ParameterSetName -eq "Call") {
    try {
        $params = @{ name = $Call; arguments = ($Arguments | ConvertFrom-Json) }
    } catch {
        Write-Error "Аргументы -Arguments не являются валидным JSON: $_"
        exit 2
    }
    $rpc = @{ jsonrpc = "2.0"; id = 1; method = "tools/call"; params = $params }
} else {
    $rpc = @{ jsonrpc = "2.0"; id = 1; method = "tools/list"; params = @{} }
}

$body = $rpc | ConvertTo-Json -Compress -Depth 10
Write-Host "--> $uri"
Write-Host "--- body: $body"

$pass = ConvertTo-SecureString $Password -AsPlainText -Force
$cred = New-Object PSCredential($User, $pass)

try {
    $resp = Invoke-RestMethod -Uri $uri -Method Post -ContentType "application/json" `
        -Credential $cred -Body $body
} catch {
    Write-Host "<-- ОШИБКА HTTP-транспорта:" -ForegroundColor Red
    $stream = $_.Exception.Response.GetResponseStream()
    if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Host $reader.ReadToEnd()
    } else {
        Write-Host $_.Exception.Message
    }
    exit 1
}

if ($resp.error) {
    Write-Host "<-- JSON-RPC error:" -ForegroundColor Red
    $resp.error | ConvertTo-Json -Depth 10
    exit 1
}

if ($PSCmdlet.ParameterSetName -eq "Call") {
    $resp.result | ConvertTo-Json -Depth 10
} else {
    $resp.result.tools | Select-Object name | Format-Table -AutoSize
    Write-Host ("Всего инструментов: " + $resp.result.tools.Count)
}
