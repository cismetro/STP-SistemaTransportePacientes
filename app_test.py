import os
from flask import Flask

def create_app():
    app = Flask(__name__)
    
    # Configuração simples sem banco por enquanto
    app.config['SECRET_KEY'] = 'cosmopolis_sistema_transporte_2024'
    
    # Criar diretórios necessários
    os.makedirs('db', exist_ok=True)
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('relatorios', exist_ok=True)
    
    @app.route('/')
    def index():
        return '''
        <html>
        <head>
            <title>Sistema de Transporte - Teste</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 50px; background: #f5f5f5; text-align: center; }
                .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                .header { background: linear-gradient(135deg, #5D5CDE, #4a49c4); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .status { background: #e8f5e8; padding: 15px; border-radius: 5px; border-left: 4px solid #28a745; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚑 Sistema de Transporte de Pacientes</h1>
                    <p>Prefeitura Municipal de Cosmópolis</p>
                </div>
                
                <div class="status">
                    <h3>✅ Sistema Funcionando!</h3>
                    <p>Flask está rodando corretamente.</p>
                </div>
                
                <div style="text-align: left; margin: 20px 0;">
                    <h4>🔧 Status dos Diretórios:</h4>
                    <ul>
                        <li>📁 Pasta 'db': ''' + ('✅ Criada' if os.path.exists('db') else '❌ Não existe') + '''</li>
                        <li>📁 Pasta 'uploads': ''' + ('✅ Criada' if os.path.exists('uploads') else '❌ Não existe') + '''</li>
                        <li>📁 Pasta 'relatorios': ''' + ('✅ Criada' if os.path.exists('relatorios') else '❌ Não existe') + '''</li>
                    </ul>
                </div>
                
                <p><strong>🎯 Próximo passo:</strong> Configurar banco de dados</p>
            </div>
        </body>
        </html>
        '''
    
    return app

if __name__ == '__main__':
    app = create_app()
    print("🚀 Iniciando Sistema de Transporte (Modo Teste)...")
    print("📱 Acesse: http://localhost:5000")
    print("🏥 Prefeitura Municipal de Cosmópolis")
    app.run(debug=True, host='0.0.0.0', port=5000)