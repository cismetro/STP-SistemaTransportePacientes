# Define o fundo da janela como turquesa (#4fc9c4)
$Host.UI.RawUI.BackgroundColor = "DarkCyan"
Clear-Host

# Script para iniciar o STP - Sistema de Transportes de Paciente
# Prefeitura Municipal de Cosmópolis - SP

# Evita UnicodeEncodeError nos prints com emoji (console Windows cp1252)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
# Simulação / teste: NÃO envia WhatsApp para telefone real.
# Remova ou comente a linha abaixo quando for operação real.
$env:STP_BLOQUEAR_WHATSAPP = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Navega para o diretório do projeto
Set-Location "D:\Projetos\python\STP-SistemaTransportePacientes"

# Ativa o ambiente virtual transporte (se existir)
if (Test-Path ".\transporte\Scripts\Activate.ps1") {
    & .\transporte\Scripts\Activate.ps1
} else {
    Write-Host "Aviso: ambiente 'transporte' nao encontrado. Usando Python do sistema." -ForegroundColor Yellow
}

# Mensagem informativa
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Iniciando STP - Sistema de Transporte de Paciente" -ForegroundColor Green
Write-Host "Prefeitura Municipal de Cosmopolis - SP" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Aguardando inicializacao do servidor..." -ForegroundColor Yellow
Write-Host ""

# Abre o navegador depois de alguns segundos
Start-Job { Start-Sleep -Seconds 3; Start-Process "http://127.0.0.1:5022/transporte" } | Out-Null

# Roda o servidor (fica ativo na janela)
python app.py
