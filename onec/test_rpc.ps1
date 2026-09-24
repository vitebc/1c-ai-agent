<#Requires -Version 5.1
<#
.SYNOPSIS
  Самодостаточный тест MCP-сервиса 1С: запуск без параметров, всё зашито внутри.

.DESCRIPTION
  Три проверки подряд, результат каждой — в консоль:
    1. tools/list — список инструментов;
    2. tools/call get_configuration_info — информация о конфигурации;
    3. tools/call execute_select — пробный запрос к данным.
  JSON собирается через ConvertTo-Json, экранировать ничего не нужно.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\test_rpc.ps1
#>

$ErrorActionPreference = "Continue"

# --- Параметры подключения (поменяй под себя) ---
$BaseUrl  = "http://192.168.0.178/ca2_td_update"
$User     = "agent"
$Password = "agent007"
# ------------------------------------------------

$uri  = ($BaseUrl.TrimEnd("/") + "/hs/mcp/rpc")
$pass = ConvertTo-SecureString $Password -AsPlainText -Force
$cred = New-Object PSCredential($User, $pass)

function Invoke-Mcp {
    param([hashtable]$Rpc)

    $body = $Rpc | ConvertTo-Json -Compress -Depth 10
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "--> $($Rpc.method)"
    try {
        $resp = Invoke-RestMethod -Uri $script:uri -Method Post `
            -ContentType "application/json" -Credential $script:cred -Body $body `
            -TimeoutSec 30 -ErrorAction Stop
    } catch {
        Write-Host "<-- ОШИБКА HTTP-транспорта:" -ForegroundColor Red
        Write-Host ("Тип исключения: " + $_.Exception.GetType().FullName)
        Write-Host ("Сообщение: " + $_.Exception.Message)
        $httpResp = $_.Exception.Response
        if ($httpResp) {
            try {
                Write-Host ("HTTP-статус: " + [int]$httpResp.StatusCode + " " + $httpResp.StatusDescription)
            } catch {
                Write-Host "(статус прочитать не удалось)"
            }
            try {
                $sr = New-Object System.IO.StreamReader($httpResp.GetResponseStream())
                $txt = $sr.ReadToEnd()
                if ([string]::IsNullOrEmpty($txt)) {
                    Write-Host "(тело ответа пустое)"
                } else {
                    Write-Host $txt
                }
            } catch {
                Write-Host ("(тело прочитать не удалось: " + $_.Exception.Message + ")")
            }
        } else {
            Write-Host "(HTTP-ответа нет: обрыв соединения, таймаут 30с или DNS)"
        }
        return
    }
    if ($resp.error) {
        Write-Host "<-- JSON-RPC error:" -ForegroundColor Red
        $resp.error | ConvertTo-Json -Depth 10 | Write-Host
        return
    }
    Write-Host "<-- OK:" -ForegroundColor Green
    $resp.result | ConvertTo-Json -Depth 10 | Write-Host
}

# 1. Список инструментов
Invoke-Mcp @{ jsonrpc = "2.0"; id = 1; method = "tools/list"; params = @{} }

# 2. Информация о конфигурации
Invoke-Mcp @{
    jsonrpc = "2.0"; id = 2; method = "tools/call"
    params  = @{ name = "get_configuration_info"; arguments = @{} }
}

# 3. Пробный запрос к данным
Invoke-Mcp @{
    jsonrpc = "2.0"; id = 3; method = "tools/call"
    params  = @{
        name      = "execute_select"
        arguments = @{ query = "ВЫБРАТЬ ПЕРВЫЕ 1 Номер ИЗ Документ.ЗаказКлиента"; limit = 5 }
    }
}

Write-Host ""
Write-Host ("=" * 70)
Write-Host "Готово."
