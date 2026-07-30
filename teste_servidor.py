from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return '<h1>🚀 SERVIDOR FUNCIONANDO!</h1><p>Teste básico OK</p>'

@app.route('/teste')
def teste():
    return '<h2>✅ Rota teste funcionando!</h2>'

if __name__ == '__main__':
    print("🚀 Iniciando servidor de teste...")
    print("📱 Acesse: http://127.0.0.1:5010")
    app.run(debug=True, host='0.0.0.0', port=5010)