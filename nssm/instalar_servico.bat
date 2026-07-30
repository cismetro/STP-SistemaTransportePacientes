@echo off
title Instalacao do Servico STP - Sistema Transporte de Pacientes
color 0B

echo ============================================================
echo  Instalando STP como Servico Windows
echo  Sistema Transporte de Pacientes - Prefeitura de Cosmopolis
echo ============================================================
echo.

set "DIR=%~dp0"
for %%i in ("%DIR%..") do set "RAIZ=%%~fi"
set "PYTHON=%RAIZ%\venv\Scripts\python.exe"
set "APP=%RAIZ%\app.py"
set "NSSM=%DIR%nssm.exe"
set "SERVICO=STP-SistemaTransportePacientes"
set "LOG=%RAIZ%\logs_whatsapp\servico_stp.log"

if not exist "%PYTHON%" (
    echo [ERRO] Python do venv nao encontrado em: %PYTHON%
    echo.
    pause
    exit /b 1
)

if not exist "%NSSM%" (
    echo [ERRO] nssm.exe nao encontrado em: %NSSM%
    echo.
    pause
    exit /b 1
)

echo [1/4] Removendo servico anterior se existir...
"%NSSM%" stop "%SERVICO%" >nul 2>&1
"%NSSM%" remove "%SERVICO%" confirm >nul 2>&1

echo [2/4] Instalando servico...
"%NSSM%" install "%SERVICO%" "%PYTHON%" "app.py"

echo [3/4] Configurando diretorio de trabalho, ambiente e logs...
"%NSSM%" set "%SERVICO%" AppDirectory "%RAIZ%"
"%NSSM%" set "%SERVICO%" AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "FLASK_ENV=development"
"%NSSM%" set "%SERVICO%" AppStdout "%LOG%"
"%NSSM%" set "%SERVICO%" AppStderr "%LOG%"
"%NSSM%" set "%SERVICO%" AppRotateFiles 1
"%NSSM%" set "%SERVICO%" AppRotateOnline 1
"%NSSM%" set "%SERVICO%" AppRotateSeconds 86400
"%NSSM%" set "%SERVICO%" AppNoConsole 1
"%NSSM%" set "%SERVICO%" AppExit "Default" Exit
"%NSSM%" set "%SERVICO%" AppThrottle 5000

echo [4/4] Iniciando servico (aguardando ate 30s)...
"%NSSM%" start "%SERVICO%"
if errorlevel 1 (
    echo [AVISO] Aguardando servico iniciar...
    timeout /t 10 /nobreak >nul
    "%NSSM%" start "%SERVICO%"
    if errorlevel 1 (
        echo [ERRO] Servico nao iniciou. Verifique o log: %LOG%
        echo.
        "%NSSM%" status "%SERVICO%"
        echo.
        pause
        exit /b 1
    )
)

echo.
echo Servico instalado e iniciado com sucesso!
echo.
echo Nome:  %SERVICO%
echo Raiz:  %RAIZ%
echo Python: %PYTHON%
echo Log:   %LOG%
echo.
echo Comandos uteis:
echo   nssm\nssm stop   "%SERVICO%"   - Parar servico
echo   nssm\nssm start  "%SERVICO%"   - Iniciar servico
echo   nssm\nssm status "%SERVICO%"   - Ver status
echo   nssm\nssm remove "%SERVICO%" confirm - Remover servico
echo.
pause
