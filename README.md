# SistemaTransportePacientes
Sistema Transporte Pacientes Secretaria de Saúde Cosmópolis

Sistema de Transporte de Pacientes

📋 Descrição
Sistema completo de gerenciamento de transporte de pacientes desenvolvido para a Prefeitura Municipal de Cosmópolis. O sistema permite o controle total da frota municipal, agendamentos de transporte, cadastro de pacientes e motoristas, além de relatórios gerenciais completos.

🎯 Principais Funcionalidades

👥 Gestão de Pacientes: Cadastro completo com necessidades especiais e histórico médico

🚗 Controle de Frota: Gerenciamento de veículos, manutenções e documentações

👨‍💼 Administração de Motoristas: Controle de habilitações, disponibilidade e vínculos

📅 Agendamentos Inteligentes: Sistema completo de agendamentos com prioridades e status

📊 Relatórios Gerenciais: Exportação em PDF, Excel e CSV com filtros avançados

🔐 Sistema de Permissões: Controle granular de acesso por tipo de usuário

📱 Interface Responsiva: Design moderno adaptável a todos os dispositivos

🏗️ Estrutura do Projeto



sistema-transporte-pacientes/
├── app.py                          # Aplicação principal Flask
├── config.py                       # Configurações do sistema
├── requirements.txt                # Dependências Python
├── .env.example                    # Exemplo de variáveis de ambiente
├── 
├── db/
│   └── database.py                 # Configuração do banco de dados
│
├── sistema/
│   ├── models/                     # Modelos de dados (SQLAlchemy)
│   │   ├── paciente.py            # Modelo Paciente
│   │   ├── motorista.py           # Modelo Motorista
│   │   ├── veiculo.py             # Modelo Veículo
│   │   ├── agendamento.py         # Modelo Agendamento
│   │   └── usuario.py             # Modelo Usuário
│   │
│   ├── routes/                     # Rotas da aplicação
│   │   ├── pacientes.py           # CRUD Pacientes
│   │   ├── motoristas.py          # CRUD Motoristas
│   │   ├── veiculos.py            # CRUD Veículos
│   │   └── agendamentos.py        # CRUD Agendamentos
│   │
│   ├── services/                   # Serviços e lógica de negócio
│   │   ├── agendamento_service.py # Serviços de agendamento
│   │   └── relatorios_service.py  # Geração de relatórios
│   │
│   ├── auth/                       # Sistema de autenticação
│   │   ├── utils.py               # Utilitários de autenticação
│   │   └── routes.py              # Rotas de auth
│   │
│   ├── status/                     # Enumerações e status
│   │   └── status_enum.py         # Definições de status
│   │
│   └── templates/                  # Templates HTML
│       ├── base.html              # Template base
│       ├── login.html             # Página de login
│       ├── dashboard.html         # Dashboard principal
│       ├── pacientes.html         # Interface de pacientes
│       ├── motoristas.html        # Interface de motoristas
│       ├── veiculos.html          # Interface de veículos
│       └── agendamentos.html      # Interface de agendamentos
│
└── static/                         # Arquivos estáticos
    ├── css/                       # Estilos customizados
    ├── js/                        # JavaScript personalizado
    └── img/                       # Imagens e ícones

🛠️ Tecnologias Utilizadas

Backend
Flask 3.0+ - Framework web Python
SQLAlchemy - ORM para banco de dados
Flask-Login - Sistema de autenticação
Flask-WTF - Formulários e CSRF
PostgreSQL/MySQL - Banco de dados
ReportLab - Geração de PDFs
OpenPyXL - Geração de Excel

Frontend
HTML5 + CSS3 - Estrutura e estilização
Bootstrap 5.3 - Framework CSS
JavaScript ES6+ - Interatividade
Bootstrap Icons - Ícones
Moment.js - Manipulação de datas

Ferramentas
Python 3.9+ - Linguagem principal
Werkzeug - Servidor de desenvolvimento
Jinja2 - Template engine

🚀 Instalação e Configuração
1. Pré-requisitos


- Python 3.9 ou superior
- PostgreSQL ou MySQL
- pip (gerenciador de pacotes Python)
2. Clone o Repositório



git clone https://github.com/prefeitura-cosmopolis/sistema-transporte-pacientes.git
cd sistema-transporte-pacientes
3. Criar Ambiente Virtual



python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
4. Instalar Dependências



pip install -r requirements.txt
5. Configurar Variáveis de Ambiente



cp .env.example .env
Edite o arquivo .env com suas configurações:

env


# Configurações da Aplicação
SECRET_KEY=sua_chave_secreta_muito_forte_aqui
DEBUG=False
ENV=production

# Banco de Dados
DATABASE_URL=postgresql://usuario:senha@localhost/transporte_pacientes

# Email (opcional)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=sistema@cosmopolis.sp.gov.br
MAIL_PASSWORD=senha_do_email

# Configurações de Upload
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216

# Relatórios
REPORTS_FOLDER=relatorios
6. Configurar Banco de Dados


# Criar banco de dados
createdb transporte_pacientes

# Executar migrations (se disponível)
flask db upgrade

# Ou executar script de inicialização
python init_db.py
7. Criar Usuário Administrador



python create_admin.py
▶️ Execução
Desenvolvimento



python app.py
A aplicação estará disponível em http://localhost:5000

Produção



# Usando Gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Ou usando uWSGI
pip install uwsgi
uwsgi --http 0.0.0.0:5000 --module app:app --processes 4

👤 Usuários Padrão
Administrador
Usuário: admin
Senha: admin123
Permissões: Acesso total ao sistema
Operador
Usuário: operador
Senha: op123
Permissões: Gestão de agendamentos e consultas

🎮 Como Usar

1. Primeiro Acesso
Acesse http://localhost:5000
Faça login com usuário administrador
Configure os dados básicos do sistema

2. Cadastros Básicos
Motoristas: Cadastre os motoristas com CNH e dados pessoais
Veículos: Registre a frota com documentações
Pacientes: Cadastre os pacientes com necessidades especiais

3. Operação Diária
Agendamentos: Crie e gerencie os transportes
Dashboard: Monitore estatísticas em tempo real
Relatórios: Gere relatórios gerenciais

📊 Módulos do Sistema

🏠 Dashboard
Estatísticas em tempo real
Agendamentos do dia
Alertas importantes
Ações rápidas

👥 Pacientes
Cadastro completo com foto
Histórico médico
Necessidades especiais
Contatos de emergência

🚗 Veículos
Controle da frota municipal
Manutenções programadas
Vencimentos de documentos
Consumo de combustível

👨‍💼 Motoristas
Cadastro com habilitação
Controle de disponibilidade
Histórico de viagens
Vencimento de CNH

📅 Agendamentos
Agendamentos por prioridade
Controle de status em tempo real
Timeline de horários
Confirmações automáticas

📈 Relatórios
Relatórios gerenciais completos
Exportação em PDF, Excel e CSV
Filtros avançados
Gráficos e estatísticas

🔒 Segurança
Autenticação segura com hash de senhas
Controle de sessões com timeout automático
Validação CSRF em todos os formulários
Logs de auditoria para ações críticas
Backup automático do banco de dados
Criptografia de dados sensíveis

📱 Responsividade
Design Mobile-First adaptável a qualquer tela
PWA Ready com suporte a notificações
Offline-First para funcionalidades críticas
Touch-Friendly otimizado para tablets

🎨 Temas
Tema Claro/Escuro com alternância automática
Cores institucionais da Prefeitura
Alto contraste para acessibilidade
Fonte legível em todos os tamanhos

🤝 Como Contribuir
Fork o projeto
Crie uma branch para sua feature (git checkout -b feature/AmazingFeature)
Commit suas mudanças (git commit -m 'Add some AmazingFeature')
Push para a branch (git push origin feature/AmazingFeature)
Abra um Pull Request

📝 Licença
Este sistema foi desenvolvido especificamente para a Prefeitura Municipal de Cosmópolis e pode ser utilizado por outras entidades públicas mediante autorização.

📞 Suporte
Email: ti@cosmopolis.sp.gov.br
Telefone: (19) 3872-1234
Endereço: Prefeitura Municipal de Cosmópolis - SP

🏆 Créditos
Desenvolvido com ❤️ para a comunidade de Cosmópolis/SP

Versão: 1.0.0
Última Atualização: Dezembro 2024
Status: Em Produção ✅





🚀 Iniciando Sistema de Transporte de Pacientes...

🔍 Verificando banco em: 
D:\Projetos\SistemaTransportePacientes\db\transporte_pacientes.db

❌ Banco de dados não encontrado. Criando automaticamente...

✅ Tabelas criadas no banco de dados

✅ Usuário administrador criado: admin / admin123

📱 Acesse: http://localhost:5010

🏥 Prefeitura Municipal de Cosmópolis

👤 Login: admin / admin123


Rotas adicionadas:

/pacientes/cadastrar - Formulário de cadastro de pacientes
/veiculos/cadastrar - Formulário de cadastro de veículos
/motoristas/cadastrar - Formulário de cadastro de motoristas
/agendamentos/novo - Formulário de novo agendamento
✅ Funcionalidades:

📋 Formulários completos com validação
🧭 Breadcrumbs para navegação
⚠️ Avisos de funcionalidade em desenvolvimento
🎨 Botões coloridos (verde para salvar, cinza para cancelar)
📱 Layout responsivo com duas colunas
✅ Experiência do usuário:

Formulários realistas e funcionais
Navegação intuitiva
Feedback visual adequado
Mensagens de aviso para funcionalidades futuras
Execute o novo código e teste clicando em qualquer botão cinza! 🚀


✅ Modelos de banco de dados criados:

👥 Paciente - dados pessoais, endereço, SUS, etc.
🚗 Veiculo - placa, tipo, capacidade, adaptações PCD
👨‍💼 Motorista - CNH, categoria, status, vencimento
📅 Agendamento - transportes com origem/destino
✅ Funcionalidades reais implementadas:

💾 Cadastros funcionam e salvam no banco
📊 Dashboard atualiza automaticamente com dados reais
📋 Listagens mostram dados cadastrados
✅ Validações de campos obrigatórios e únicos
🔄 Relacionamentos entre tabelas
✅ Experiência do usuário:

📈 Contadores atualizados em tempo real
📝 Formulários completos e validados
📋 Tabelas organizadas com dados reais
🎨 Mensagens de sucesso/erro
🧭 Navegação intuitiva com breadcrumbs




PERMISSÕES DE ACESSO:
💰 Faturamento:
👁️ Visualizar: Contador, Supervisor, Administrador
✏️ Gerar/Pagar: Contador, Administrador


Nome de Usuário: contador
Nome Completo: Contador do Sistema
E-mail: contador@cosmopolis.sp.gov.br
Senha: contador123
Tipo de Usuário: 💰 Contador - Controle financeiro



/uso-veiculos
USUÁRIOS PARA TESTE:

OPÇÃO 1: Administrador (Recomendado)
Usuário: admin
Senha: admin123
Acesso: Total (pode usar todas as funcionalidades)

OPÇÃO 2: Qualquer usuário criado
O sistema de uso de veículos não tem restrições específicas
Qualquer usuário logado pode registrar uso de veículos



TESTANDO AS FUNCIONALIDADES:

TESTE 1: Iniciar Uso de Veículo
Clique em "🚦 Iniciar Uso de Veículo"
O que deve aparecer:
Formulário para registrar saída
Dropdown de agendamentos (pode estar vazio)
Dropdown de veículos (deve mostrar os veículos cadastrados)
Dropdown de motoristas (deve mostrar os motoristas ativos)

TESTE 2: Verificar se há dados necessários
Se os dropdowns estiverem vazios:


Para Veículos:
Vá em "🚗 Veículos"
Cadastre um veículo se não houver
Para Motoristas:
Vá em "👨‍💼 Motoristas"
Cadastre um motorista se não houver
Para Agendamentos (opcional):
Vá em "📅 Agendamentos"
Crie um agendamento para hoje se quiser testar integração

FUNCIONAL

O QUE ESSA ROTA FAZ:
✅ Mostra informações completas:

📊 Status do uso (em andamento/concluído)
🚗 Dados completos do veículo
👨‍💼 Informações do motorista
🗺️ Trajeto detalhado com origem/destino
⏱️ Duração calculada automaticamente
💰 Cálculos financeiros detalhados
📅 Agendamento relacionado (se houver)
📝 Observações do uso
✅ Funcionalidades dinâmicas:

⏱️ Cálculo de tempo em tempo real para usos em andamento
💰 Diferenciação entre veículos próprios e terceirizados
🏁 Botão para finalizar uso (se em andamento)
📊 Cálculos automáticos de custos





3A - Status dos Agendamentos 	_implantado
3B - CEP nos Agendamentos		_implantado
3C - Controle de Combustível	_implantado
3D - Notificações WhatsApp		_implantado
3E - Backup Automático			_implantado



==============3A - Status dos Agendamentos 	- ok 
Controle completo do fluxo de agendamentos:
Agendado → Confirmado → Em Andamento → Concluído
Botões para mudar status
Dashboard com status em tempo real
Alertas visuais por status
Histórico de mudanças

==============3B - CEP nos Agendamentos	 - ok
Localização precisa nos transportes:
CEP de origem (casa do paciente)
CEP de destino (hospital/clínica)
Cálculo automático de distância
Sugestão de veículo por distância
Relatórios por região

==============3C - Controle de Combustível ok
Gestão de custos de combustível:
Registro de abastecimentos
Controle de custos por veículo
Relatório de consumo
Gráficos de eficiência
Alertas de consumo alto

	
==============3D - Notificações WhatsApp - ok		
Comunicação automática:
Confirmar agendamentos via WhatsApp
Lembrete 1 dia antes
Aviso quando motorista sair
Confirmação de chegada
Status delivery por WhatsApp

Confirmação automática quando criar agendamento
Lembretes automáticos (1 dia antes às 14:00)
Notificação quando motorista sair
Confirmação de chegada ao destino
Interface web completa para gerenciamento
Logs detalhados de envios
Templates personalizáveis
Sistema de filas para envios
Agendamento automático



==============3E - Backup Automático ok		
Backup automático diário
Exportação para Excel
Sincronização em nuvem
Backup criptografado
Histórico de backups
--
Backup automático diário do banco
Exportação para Excel de todos os dados
Histórico de backups com controle de versões
Backup compactado e protegido
Agendamento automático de backups
Gestão de armazenamento (limpeza automática)
---
Interface completa com estatísticas
Histórico de backups
Ações via JavaScript/AJAX
Download de arquivos
Controle de permissões
Tratamento de erros
Feedback ao usuário

OPÇÕES POPULARES:
📊 Sistema de Analytics/Dashboard Avançado

Gráficos em tempo real
Estatísticas detalhadas
Métricas de performance
📱 Sistema de Notificações

WhatsApp/SMS automático
Lembretes de agendamentos
Alertas para motoristas
🗺️ Sistema de Rastreamento GPS

Localização em tempo real
Rotas otimizadas
Controle de trajetos
💰 Sistema Financeiro Completo

Controle de custos
Relatórios fiscais
Integração bancária
📋 Sistema de Relatórios Avançados

PDFs automáticos
Relatórios personalizados
Exportação múltipla
🏥 Sistema de Integração Hospitalar

API com hospitais
Sincronização de dados
Agendamentos externos
👥 Sistema de Gestão de Usuários Avançado

Permissões granulares
Auditoria de ações
Hierarquia organizacional
📞 Sistema de Call Center

Central de atendimento
Gravação de chamadas
Distribuição automática




3A - Status dos Agendamentos 	_implantado
3B - CEP nos Agendamentos		_implantado
3C - Controle de Combustível	_implantado
3D - Notificações WhatsApp		_implantado
3E - Backup Automático			_implantado

e dar uma olhada ndesta botão...  Ver Todos os Abastecimentos não está funcionando (criar rota)

--------------------------------------------------
configurando o zap
python configurar_whatsapp.py
.\iniciar_app.ps1
http://127.0.0.1:5010/whatsapp

Testar envio:

Digite seu número no campo de teste
Clique em "Enviar Teste"

1938726865
------------------------------------------------

