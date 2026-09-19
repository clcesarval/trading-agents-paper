$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$node = 'C:\Program Files\nodejs'
if (!(Test-Path "$node\node.exe")) { throw 'Node.js não encontrado. Instale a versão LTS em https://nodejs.org/' }
$env:Path = "$node;$env:Path"
Write-Host "Node: $(& "$node\node.exe" --version)"
Write-Host "Instalando dependências do frontend..."
Push-Location "$project\frontend"
& "$node\npm.cmd" install
Pop-Location
Write-Host 'Frontend configurado. Python deve ser instalado separadamente se o comando python não existir.'
