import subprocess
import sys
import os
import time
import socket

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# ================= CONFIGURAÇÕES =================
PORTA = 5010
URL = f"http://localhost:{PORTA}"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
APP_FILE = os.path.join(BASE_DIR, "app.py")

CHROMEDRIVER_PATH = r"C:\chromedriver_win32\chromedriver.exe"
# =================================================


def servidor_ativo(host="127.0.0.1", port=5010, timeout=1):
    """Verifica se a porta do Flask está respondendo"""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def abrir_chrome():
    print("🌐 Abrindo Google Chrome via ChromeDriver...")

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.get(URL)


def iniciar_servidor():
    print("🚀 Iniciando Sistema de Transporte de Pacientes...")
    print(f"📁 Diretório: {BASE_DIR}")

    if not os.path.exists(VENV_PYTHON):
        print("❌ Python do ambiente virtual não encontrado!")
        sys.exit(1)

    if not os.path.exists(APP_FILE):
        print("❌ app.py não encontrado!")
        sys.exit(1)

    if not os.path.exists(CHROMEDRIVER_PATH):
        print("❌ ChromeDriver não encontrado!")
        sys.exit(1)

    # Inicia o Flask em novo console
    subprocess.Popen(
        [VENV_PYTHON, APP_FILE],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    print("⏳ Aguardando servidor responder na porta 5010...")

    for _ in range(30):  # até 30 segundos
        if servidor_ativo(port=PORTA):
            print("✅ Servidor ativo!")
            abrir_chrome()
            return
        time.sleep(1)

    print("❌ Servidor não respondeu a tempo.")
    sys.exit(1)


if __name__ == "__main__":
    iniciar_servidor()
