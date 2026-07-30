# SistemaTransportePacientes.ps1
# Script para criar a estrutura de pastas e arquivos do projeto SistemaTransportePacientes

# Função para criar pastas e arquivos
function New-ProjectStructure {
    param (
        [string]$BasePath
    )

    # Cria a pasta base do projeto
    New-Item -Path $BasePath -ItemType Directory -Force

    # Criação de arquivos na raiz
    $rootFiles = @("app.py", "config.py", "requirements.txt", ".env.example")
    foreach ($file in $rootFiles) {
        New-Item -Path (Join-Path $BasePath $file) -ItemType File -Force
    }

    # Sistema/
    $sistemaPath = Join-Path $BasePath "sistema"
    New-Item -Path $sistemaPath -ItemType Directory -Force
    New-Item -Path (Join-Path $sistemaPath "__init__.py") -ItemType File -Force

    # Sistema/Models
    $modelsPath = Join-Path $sistemaPath "models"
    New-Item -Path $modelsPath -ItemType Directory -Force
    $modelFiles = @("paciente.py", "motorista.py", "veiculo.py", "agendamento.py", "usuario.py")
    foreach ($file in $modelFiles) {
        New-Item -Path (Join-Path $modelsPath $file) -ItemType File -Force
    }

    # Sistema/Auth
    $authPath = Join-Path $sistemaPath "auth"
    New-Item -Path $authPath -ItemType Directory -Force
    $authFiles = @("utils.py", "routes.py")
    foreach ($file in $authFiles) {
        New-Item -Path (Join-Path $authPath $file) -ItemType File -Force
    }

    # Sistema/Routes
    $routesPath = Join-Path $sistemaPath "routes"
    New-Item -Path $routesPath -ItemType Directory -Force
    $routeFiles = @("pacientes.py", "motoristas.py", "veiculos.py", "agendamentos.py")
    foreach ($file in $routeFiles) {
        New-Item -Path (Join-Path $routesPath $file) -ItemType File -Force
    }

    # Sistema/Status
    $statusPath = Join-Path $sistemaPath "status"
    New-Item -Path $statusPath -ItemType Directory -Force
    New-Item -Path (Join-Path $statusPath "status_enum.py") -ItemType File -Force

    # Sistema/Services
    $servicesPath = Join-Path $sistemaPath "services"
    New-Item -Path $servicesPath -ItemType Directory -Force
    $serviceFiles = @("agendamento_service.py", "relatorios_service.py")
    foreach ($file in $serviceFiles) {
        New-Item -Path (Join-Path $servicesPath $file) -ItemType File -Force
    }

    # Sistema/Templates
    $templatesPath = Join-Path $sistemaPath "templates"
    New-Item -Path $templatesPath -ItemType Directory -Force
    $templateFiles = @("base.html", "login.html", "dashboard.html", "pacientes.html", "motoristas.html", "veiculos.html", "agendamentos.html")
    foreach ($file in $templateFiles) {
        New-Item -Path (Join-Path $templatesPath $file) -ItemType File -Force
    }

    # Sistema/Static
    $staticPath = Join-Path $sistemaPath "static"
    New-Item -Path $staticPath -ItemType Directory -Force
    # CSS
    $cssPath = Join-Path $staticPath "css"
    New-Item -Path $cssPath -ItemType Directory -Force
    $cssFiles = @("colors.css", "style.css")
    foreach ($file in $cssFiles) {
        New-Item -Path (Join-Path $cssPath $file) -ItemType File -Force
    }
    # JS
    $jsPath = Join-Path $staticPath "js"
    New-Item -Path $jsPath -ItemType Directory -Force
    New-Item -Path (Join-Path $jsPath "app.js") -ItemType File -Force

    # DB
    $dbPath = Join-Path $BasePath "db"
    New-Item -Path $dbPath -ItemType Directory -Force
    New-Item -Path (Join-Path $dbPath "database.py") -ItemType File -Force
    New-Item -Path (Join-Path $dbPath "migrations") -ItemType Directory -Force
}

# Caminho do projeto (pode alterar se quiser outro diretório)
$projectPath = Join-Path (Get-Location) "SistemaTransportePacientes"

# Cria a estrutura
New-ProjectStructure -BasePath $projectPath

Write-Host "Estrutura do projeto SistemaTransportePacientes criada com sucesso em $projectPath"
