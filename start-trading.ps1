$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv\Scripts\python.exe'
$systemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (!$systemPython) { $systemPython = (Get-Command py -ErrorAction SilentlyContinue).Source }
$node = 'C:\Program Files\nodejs'
if (!(Test-Path $python) -and !$systemPython) { throw 'Python não encontrado. Instale Python e adicione-o ao PATH.' }
if (!(Test-Path "$node\npm.cmd")) { throw 'Node.js não encontrado.' }
$env:Path = "$node;$env:Path"
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'vite' -and $_.CommandLine -match [regex]::Escape((Join-Path $project 'frontend')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if (!(Test-Path $python)) { Write-Host 'Preparando ambiente Python pela primeira vez...'; & $systemPython -m venv (Join-Path $project '.venv') }
Write-Host 'Verificando dependências do backend...'
& $python -m pip install -q -r (Join-Path $project 'backend\requirements.txt')
if (Test-Path (Join-Path $project 'tradingagents_upstream\pyproject.toml')) { Write-Host 'Verificando TradingAgents upstream...'; & $python -m pip install -q -e (Join-Path $project 'tradingagents_upstream') }
if (!(Test-Path (Join-Path $project 'frontend\node_modules'))) { Push-Location (Join-Path $project 'frontend'); & "$node\npm.cmd" install; Pop-Location }
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command', "Set-Location '$project'; & '$python' -m uvicorn backend.app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command', "Set-Location '$project\frontend'; & '$node\npm.cmd' run dev -- --host 127.0.0.1 --port 5173 --strictPort"
Write-Host 'Aguardando os serviços iniciarem...'
$ready = $false
for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 500; try { Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1 | Out-Null; $ready = $true; break } catch {} }
if (!$ready) { throw 'O frontend não iniciou na porta 5173. Verifique a janela do Vite.' }
try { Start-Process 'http://127.0.0.1:5173' -ErrorAction Stop } catch { Write-Host 'Serviços ativos; abra http://127.0.0.1:5173 no navegador.' -ForegroundColor Yellow }
Write-Host 'AI Trading Platform iniciada em http://127.0.0.1:5173' -ForegroundColor Green
