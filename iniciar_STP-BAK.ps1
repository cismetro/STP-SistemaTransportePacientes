# Script para iniciar o STP - Sistema de Transportes de Paciente
# Prefeitura Municipal de Cosmópolis - SP

Set-Location "D:\Projetos\SistemaTransportePacientes"
& .\venv\Scripts\Activate.ps1


# Mensagem informativa
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Iniciando SCP - Sistema de Transporte de Paciente" -ForegroundColor Green
Write-Host "Prefeitura Municipal de Cosmopolis - SP" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Aguardando inicializacao do servidor..." -ForegroundColor Yellow
Write-Host ""


# Abre o navegador depois de alguns segundos
Start-Job { Start-Sleep -Seconds 3; Start-Process "http://127.0.0.1:5010" } | Out-Null

# Roda o servidor (fica ativo na janela)
python app.py
