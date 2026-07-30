# test_install.py
try:
    import flask
    print(f"✅ Flask: {flask.__version__}")
except ImportError as e:
    print(f"❌ Erro Flask: {e}")

try:
    import flask_sqlalchemy
    print(f"✅ Flask-SQLAlchemy: {flask_sqlalchemy.__version__}")
except ImportError as e:
    print(f"❌ Erro Flask-SQLAlchemy: {e}")

try:
    import flask_login
    print(f"✅ Flask-Login: {flask_login.__version__}")
except ImportError as e:
    print(f"❌ Erro Flask-Login: {e}")

try:
    import reportlab
    print(f"✅ ReportLab: {reportlab.Version}")
except ImportError as e:
    print(f"❌ Erro ReportLab: {e}")

try:
    import openpyxl
    print(f"✅ OpenPyXL: {openpyxl.__version__}")
except ImportError as e:
    print(f"❌ Erro OpenPyXL: {e}")

try:
    import sqlalchemy
    print(f"✅ SQLAlchemy: {sqlalchemy.__version__}")
except ImportError as e:
    print(f"❌ Erro SQLAlchemy: {e}")

print("\n🚀 Sistema pronto para desenvolvimento!")
print("📋 Próximo passo: Criar estrutura do projeto")