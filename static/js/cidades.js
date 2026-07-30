// Script para gerenciar as cidades de São Paulo usando API do IBGE
class CidadesSP {
    constructor() {
        this.cidades = [];
        this.selectElement = null;
        this.inputElement = null;
        this.isLoaded = false;
        this.cacheKey = 'cidades_sp_ibge';
        this.cacheExpiry = 24 * 60 * 60 * 1000; // 24 horas em millisegundos
    }

    // Verificar se há dados em cache válidos
    getCachedCidades() {
        try {
            const cached = localStorage.getItem(this.cacheKey);
            if (cached) {
                const data = JSON.parse(cached);
                const now = new Date().getTime();
                
                if (now - data.timestamp < this.cacheExpiry) {
                    console.log('📦 Usando cidades do cache local (válido por mais ' + 
                        Math.round((this.cacheExpiry - (now - data.timestamp)) / (1000 * 60 * 60)) + ' horas)');
                    return data.cidades;
                } else {
                    console.log('⏰ Cache expirado, buscando dados atualizados...');
                    localStorage.removeItem(this.cacheKey);
                }
            }
        } catch (error) {
            console.log('⚠️ Cache inválido, removendo e buscando da API...');
            localStorage.removeItem(this.cacheKey);
        }
        return null;
    }

    // Salvar dados no cache
    setCachedCidades(cidades) {
        try {
            const data = {
                cidades: cidades,
                timestamp: new Date().getTime(),
                total: cidades.length
            };
            localStorage.setItem(this.cacheKey, JSON.stringify(data));
            console.log(`💾 ${cidades.length} cidades salvas no cache local`);
        } catch (error) {
            console.log('⚠️ Não foi possível salvar no cache:', error.message);
        }
    }

    // Carregar as cidades da API do IBGE
    async loadCidades() {
        // Tentar usar cache primeiro
        const cachedCidades = this.getCachedCidades();
        if (cachedCidades && cachedCidades.length > 0) {
            this.cidades = cachedCidades;
            this.isLoaded = true;
            return this.cidades;
        }

        try {
            console.log('🏙️ Carregando cidades de São Paulo via API IBGE...');
            console.log('🌐 URL: https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios');
            
            // Mostrar loading se possível
            this.showLoading();
            
            // Fazer request para API do IBGE (Estado de São Paulo = código 35)
            const response = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                // Timeout de 10 segundos
                signal: AbortSignal.timeout(10000)
            });
            
            if (!response.ok) {
                throw new Error(`Erro HTTP: ${response.status} - ${response.statusText}`);
            }
            
            const municipios = await response.json();
            
            if (!Array.isArray(municipios) || municipios.length === 0) {
                throw new Error('Dados inválidos recebidos da API');
            }
            
            // Extrair apenas os nomes, ordenar alfabeticamente e remover duplicatas
            this.cidades = [...new Set(municipios.map(municipio => municipio.nome))].sort((a, b) => {
                return a.localeCompare(b, 'pt-BR', { sensitivity: 'base' });
            });
            
            // Salvar no cache
            this.setCachedCidades(this.cidades);
            
            this.isLoaded = true;
            this.hideLoading();
            
            console.log(`✅ ${this.cidades.length} cidades carregadas com sucesso da API IBGE!`);
            console.log(`📍 Primeiras cidades: ${this.cidades.slice(0, 5).join(', ')}...`);
            
            return this.cidades;
            
        } catch (error) {
            console.error('❌ Erro ao carregar da API IBGE:', error.message);
            this.hideLoading();
            
            // Fallback: usar lista estática das principais cidades de SP
            console.log('🔄 Usando lista de fallback com principais cidades...');
            this.cidades = [
                'Adamantina', 'Águas de Lindóia', 'Americana', 'Araçatuba', 'Araraquara',
                'Araras', 'Assis', 'Atibaia', 'Barretos', 'Barueri', 'Bauru', 'Botucatu',
                'Bragança Paulista', 'Campinas', 'Campos do Jordão', 'Carapicuíba',
                'Caraguatatuba', 'Casa Branca', 'Catanduva', 'Cosmópolis', 'Cotia',
                'Cruzeiro', 'Cubatão', 'Diadema', 'Ferraz de Vasconcelos', 'Franca',
                'Franco da Rocha', 'Guaratinguetá', 'Guarujá', 'Guarulhos', 'Hortolândia',
                'Indaiatuba', 'Itanhaém', 'Itapetininga', 'Itapevi', 'Itu', 'Jacareí',
                'Jaú', 'Jundiaí', 'Leme', 'Limeira', 'Marília', 'Mauá', 'Mogi das Cruzes',
                'Mogi Guaçu', 'Osasco', 'Ourinhos', 'Paulínia', 'Piracicaba', 'Praia Grande',
                'Presidente Prudente', 'Ribeirão Pires', 'Ribeirão Preto', 'Rio Claro',
                'Salto', 'Santa Bárbara d\'Oeste', 'Santo André', 'Santos', 'São Bernardo do Campo',
                'São Caetano do Sul', 'São Carlos', 'São João da Boa Vista', 'São José dos Campos',
                'São Paulo', 'São Roque', 'São Sebastião', 'São Vicente', 'Sorocaba',
                'Sumaré', 'Suzano', 'Taboão da Serra', 'Taubaté', 'Ubatuba', 'Valinhos',
                'Vinhedo', 'Votuporanga'
            ];
            
            this.isLoaded = true;
            return this.cidades;
        }
    }

    // Mostrar indicador de loading
    showLoading() {
        const container = document.getElementById('destino-container');
        if (container) {
            let loadingDiv = container.querySelector('.loading-cidades');
            if (!loadingDiv) {
                loadingDiv = document.createElement('div');
                loadingDiv.className = 'loading-cidades';
                loadingDiv.innerHTML = '🔄 Carregando cidades...';
                loadingDiv.style.cssText = 'color: #4fc9c4; font-size: 0.875rem; margin-bottom: 0.5rem;';
                container.insertBefore(loadingDiv, container.firstChild);
            }
        }
    }

    // Esconder indicador de loading
    hideLoading() {
        const container = document.getElementById('destino-container');
        if (container) {
            const loadingDiv = container.querySelector('.loading-cidades');
            if (loadingDiv) {
                loadingDiv.remove();
            }
        }
    }

    // Criar o select de cidades com placeholders inteligentes
    createCidadeSelect(targetElementId, placeholder = 'Selecione a cidade...') {
        const container = document.getElementById(targetElementId);
        if (!container) {
            console.error(`❌ Elemento ${targetElementId} não encontrado!`);
            return;
        }

        // Verificar se já existe um select
        const existingSelect = container.querySelector('.cidade-select');
        if (existingSelect) {
            existingSelect.remove();
        }

        // Buscar o input existente
        const inputElement = container.querySelector('input[name="destino"], input#destino');
        if (!inputElement) {
            console.error('❌ Input de destino não encontrado!');
            return;
        }

        console.log('✅ Input encontrado:', inputElement);

        // Criar o select
        const select = document.createElement('select');
        select.id = `${targetElementId}_select`;
        select.className = 'cidade-select';
        select.style.cssText = `
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--border-color, #e5e5e5);
            border-radius: 0.5rem;
            font-size: 1rem;
            background: white;
            margin-bottom: 0.5rem;
            box-sizing: border-box;
        `;

        // Opção padrão
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = '🏙️ Escolha uma cidade ou digite o endereço abaixo';
        select.appendChild(defaultOption);

        // Adicionar as cidades
        this.cidades.forEach(cidade => {
            const option = document.createElement('option');
            option.value = cidade;
            option.textContent = cidade;
            select.appendChild(option);
        });

        // Opção "Outra cidade"
        const outraOption = document.createElement('option');
        outraOption.value = 'outra';
        outraOption.textContent = '✍️ Digitar endereço manualmente';
        select.appendChild(outraOption);

        // Garantir que o input seja visível com placeholder inicial
        inputElement.style.cssText = `
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--border-color, #e5e5e5);
            border-radius: 0.5rem;
            font-size: 1rem;
            background: white;
            box-sizing: border-box;
            display: block !important;
            visibility: visible !important;
            margin-top: 0.5rem;
        `;
        
        // Placeholder inicial neutro
        inputElement.placeholder = 'Endereço será preenchido automaticamente pela seleção acima';

        // Inserir o select ANTES do input
        container.insertBefore(select, inputElement);
        
        // Armazenar referências
        this.inputElement = inputElement;
        this.selectElement = select;
        
        // Event listener inteligente
        select.addEventListener('change', (e) => {
            const selectedValue = e.target.value;
            console.log('🏙️ Cidade selecionada:', selectedValue);
            
            if (selectedValue && selectedValue !== 'outra') {
                // Preencher o input com a cidade selecionada
                this.inputElement.value = selectedValue + ', SP';
                this.inputElement.placeholder = 'Complete com rua, número e bairro se necessário';
                this.inputElement.focus();
                
                // Posicionar cursor no final
                setTimeout(() => {
                    const length = this.inputElement.value.length;
                    this.inputElement.setSelectionRange(length, length);
                }, 100);
                
            } else if (selectedValue === 'outra') {
                // Limpar e focar no input para digitação livre
                this.inputElement.value = '';
                this.inputElement.placeholder = 'Digite o endereço completo: Rua, nº, bairro, cidade';
                this.inputElement.focus();
                
            } else {
                // Opção vazia selecionada - voltar ao estado inicial
                this.inputElement.value = '';
                this.inputElement.placeholder = 'Endereço será preenchido automaticamente pela seleção acima';
            }
        });

        console.log('✅ Select de cidades criado com placeholders inteligentes!');
        console.log('📍 Input visível:', inputElement.style.display !== 'none');
    }

    // Inicializar o sistema
    async init(targetElementId, placeholder) {
        console.log('🚀 Inicializando sistema de cidades...');
        try {
            await this.loadCidades();
            this.createCidadeSelect(targetElementId, placeholder);
            console.log('✅ Sistema de cidades inicializado com sucesso!');
        } catch (error) {
            console.error('❌ Erro ao inicializar sistema de cidades:', error);
        }
    }

    // Método para buscar cidade por nome (para autocomplete futuro)
    searchCidade(query) {
        if (!query || query.length < 2) return [];
        
        const queryLower = query.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        return this.cidades.filter(cidade => {
            const cidadeLower = cidade.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
            return cidadeLower.includes(queryLower);
        });
    }

    // Validar se a cidade existe
    isValidCidade(cidade) {
        return this.cidades.some(c => 
            c.toLowerCase() === cidade.toLowerCase()
        );
    }

    // Limpar cache (método utilitário)
    clearCache() {
        localStorage.removeItem(this.cacheKey);
        console.log('🗑️ Cache de cidades limpo');
    }

    // Forçar reload da API
    async forceReload() {
        this.clearCache();
        this.isLoaded = false;
        await this.loadCidades();
        console.log('🔄 Dados recarregados da API');
    }
}

// Instância global
const cidadesSP = new CidadesSP();

// Inicializar quando o DOM estiver pronto
document.addEventListener('DOMContentLoaded', function() {
    console.log('📱 DOM carregado - verificando se é página de agendamento...');
    
    // Verificar se estamos na página de agendamento
    const targetElement = document.querySelector('#destino-container');
    if (targetElement) {
        console.log('🎯 Página de agendamento detectada!');
        
        // Aguardar um pouco para garantir que tudo foi carregado
        setTimeout(() => {
            cidadesSP.init('destino-container', '🏙️ Selecione a cidade de destino...');
        }, 500);
    } else {
        console.log('ℹ️ Não é uma página de agendamento, sistema de cidades não será carregado');
    }
});

// Função para validar formulário (opcional)
function validateDestinoForm() {
    const destinoInput = document.getElementById('destino');
    if (destinoInput && destinoInput.value.trim() === '') {
        // Criar modal customizado em vez de alert
        showCustomAlert('Por favor, selecione uma cidade ou digite o endereço de destino!', 'warning');
        destinoInput.focus();
        return false;
    }
    return true;
}

// Função para mostrar alerta customizado
function showCustomAlert(message, type = 'info') {
    // Criar modal simples
    const modal = document.createElement('div');
    modal.className = 'custom-alert-modal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    
    const alertBox = document.createElement('div');
    alertBox.style.cssText = `
        background: white;
        padding: 2rem;
        border-radius: 0.5rem;
        max-width: 400px;
        text-align: center;
        box-shadow: 0 0.5rem 1rem rgba(0,0,0,0.2);
    `;
    
    const icon = type === 'warning' ? '⚠️' : type === 'error' ? '❌' : 'ℹ️';
    
    alertBox.innerHTML = `
        <div style="font-size: 2rem; margin-bottom: 1rem;">${icon}</div>
        <p style="margin-bottom: 1.5rem; color: #333;">${message}</p>
        <button onclick="this.closest('.custom-alert-modal').remove()" 
                style="background: #4fc9c4; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 0.25rem; cursor: pointer;">
            OK
        </button>
    `;
    
    modal.appendChild(alertBox);
    document.body.appendChild(modal);
    
    // Auto-remover após 5 segundos
    setTimeout(() => {
        if (modal.parentNode) {
            modal.remove();
        }
    }, 5000);
}

// Funções utilitárias globais para debug
window.cidadesDebug = {
    info: () => {
        console.log('📊 Informações do sistema de cidades:');
        console.log(`Carregado: ${cidadesSP.isLoaded}`);
        console.log(`Total de cidades: ${cidadesSP.cidades.length}`);
        console.log(`Cache ativo: ${!!cidadesSP.getCachedCidades()}`);
    },
    clearCache: () => cidadesSP.clearCache(),
    reload: () => cidadesSP.forceReload(),
    search: (query) => cidadesSP.searchCidade(query)
};

console.log('🎯 Sistema de cidades carregado com placeholders inteligentes!');