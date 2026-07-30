import os
import sys
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

# Configuração básica
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'db', 'transporte_pacientes.db')

app.config['SECRET_KEY'] = 'cosmopolis_sistema_transporte_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelo do usuário
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nome_completo = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    tipo_usuario = db.Column(db.String(20), nullable=False, default='operador')
    ativo = db.Column(db.Boolean, nullable=False, default=True)

def resetar_senha_admin():
    """Reset da senha do usuário admin"""
    with app.app_context():
        try:
            # Buscar o usuário admin
            admin = Usuario.query.filter_by(username='admin').first()
            
            if admin:
                print(f"🔍 Usuário admin encontrado: {admin.username}")
                print(f"📧 Email: {admin.email}")
                
                # Gerar novo hash
                novo_hash = generate_password_hash('admin123')
                admin.password_hash = novo_hash
                
                db.session.commit()
                print("✅ Senha resetada com sucesso!")
                print("👤 Usuário: admin")
                print("🔐 Senha: admin123")
            else:
                print("❌ Usuário admin não encontrado!")
                print("🔧 Criando novo usuário admin...")
                
                # Criar novo usuário
                admin = Usuario(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    nome_completo='Administrador do Sistema',
                    email='admin@cosmopolis.sp.gov.br',
                    tipo_usuario='administrador',
                    ativo=True
                )
                
                db.session.add(admin)
                db.session.commit()
                print("✅ Usuário admin criado com sucesso!")
                print("👤 Usuário: admin")
                print("🔐 Senha: admin123")
                
        except Exception as e:
            print(f"❌ Erro: {e}")
            db.session.rollback()

if __name__ == '__main__':
    print("🔐 Resetando senha do usuário admin...")
    resetar_senha_admin()
    print("🎯 Processo concluído!")
    print("🎯 Processo concluído!")