@echo off
title Remocao do Servico STP - Sistema Transporte de Pacientes
color 0C

set "DIR=%~dp0"
set "NSSM=%DIR%nssm.exe"
set "SERVICO=STP-SistemaTransportePacientes"

if not exist "%NSSM%" (
    echo [ERRO] nssm.exe nao encontrado.
    exit /b 1
)

echo ============================================================
echo  Removendo Servico STP - Sistema Transporte de Pacientes
echo ============================================================
echo.

echo Parando servico...
"%NSSM%" stop "%SERVICO%"
echo.

echo Removendo servico...
"%NSSM%" remove "%SERVICO%" confirm

echo.
echo Servico removido com sucesso!
echo.
pause
