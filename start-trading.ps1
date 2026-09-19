$ErrorActionPreference = 'Stop'
chcp 65001 > $null
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv\Scripts\python.exe'
$systemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (!$systemPython) { $systemPython = (Get-Command py -ErrorAction SilentlyContinue).Source }
$node = 'C:\Program Files\nodejs'
if (!(Test-Path $python) -and !$systemPython) { throw 'Python não encontrado. Instale Python e adicione-o ao PATH.' }
if (!(Test-Path "$node\npm.cmd")) { throw 'Node.js não encontrado.' }
$env:Path = "$node;$env:Path"

# Evita instâncias duplicadas do Vite ou do Uvicorn deste mesmo projeto; nunca
# encerra processos de outros projetos ou não relacionados (o filtro exige o
# caminho do projeto atual na linha de comando).
$projectEscaped = [regex]::Escape($project)
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'vite' -and $_.CommandLine -match $projectEscaped } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'backend\.app\.main' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (!(Test-Path $python)) { Write-Host 'Preparando ambiente Python pela primeira vez...'; & $systemPython -m venv (Join-Path $project '.venv') }
Write-Host 'Verificando dependências do backend...'
& $python -m pip install -q -r (Join-Path $project 'backend\requirements.txt')
if (Test-Path (Join-Path $project 'tradingagents_upstream\pyproject.toml')) { Write-Host 'Verificando TradingAgents upstream...'; & $python -m pip install -q -e (Join-Path $project 'tradingagents_upstream') }
if (!(Test-Path (Join-Path $project 'frontend\node_modules'))) { Push-Location (Join-Path $project 'frontend'); & "$node\npm.cmd" install; Pop-Location }

Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', "chcp 65001 > `$null; `$env:PYTHONUTF8='1'; `$env:PYTHONIOENCODING='utf-8'; Set-Location '$project'; & '$python' -m uvicorn backend.app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', "chcp 65001 > `$null; Set-Location '$project\frontend'; & '$node\npm.cmd' run dev -- --host 127.0.0.1 --port 5173 --strictPort"

Write-Host 'Aguardando o backend responder em /api/health...'
$backendReady = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try { (Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 1).status | Out-Null; $backendReady = $true; break } catch {}
}
if (!$backendReady) { throw 'O backend não respondeu em /api/health (porta 8000). Verifique a janela do Uvicorn.' }

Write-Host 'Aguardando o frontend responder na porta 5173...'
$frontendReady = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try { Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1 | Out-Null; $frontendReady = $true; break } catch {}
}
if (!$frontendReady) { throw 'O frontend não iniciou na porta 5173. Verifique a janela do Vite.' }

try { Start-Process 'http://127.0.0.1:5173' -ErrorAction Stop } catch { Write-Host 'Serviços ativos; abra http://127.0.0.1:5173 no navegador.' -ForegroundColor Yellow }
Write-Host 'AI Trading Platform iniciada em http://127.0.0.1:5173' -ForegroundColor Green
