Set-Location "D:\Projetos\SistemaTransportePacientes"
& .\venv\Scripts\Activate.ps1

# Abre o navegador depois de alguns segundos
Start-Job { Start-Sleep -Seconds 3; Start-Process "http://127.0.0.1:5010" } | Out-Null

# Roda o servidor (fica ativo na janela)
python app.py




#  cd "D:\Projetos\SistemaGerenciamentoTransportePaciente"

#   https://convex.dev/try-chef/PROJET2578