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
			'Adamantina', 'Adolfo', 'Aguaí', 'Águas da Prata', 'Águas de Lindóia',
			'Águas de Santa Bárbara', 'Águas de São Pedro', 'Agudos', 'Alambari', 'Alfredo Marcondes',
			'Altair', 'Altinópolis', 'Alto Alegre', 'Alumínio', 'Álvares Florence',
			'Álvares Machado', 'Álvaro de Carvalho', 'Alvinlândia', 'Americana', 'Américo Brasiliense',
			'Américo de Campos', 'Amparo', 'Analândia', 'Andradina', 'Angatuba',
			'Anhembi', 'Anhumas', 'Aparecida', 'Aparecida d\'Oeste', 'Apiaí',
			'Araçariguama', 'Araçatuba', 'Araçoiaba da Serra', 'Aramina', 'Arandu',
			'Arapeí', 'Araraquara', 'Araras', 'Arco-Íris', 'Arealva',
			'Areias', 'Areiópolis', 'Ariranha', 'Artur Nogueira', 'Arujá',
			'Aspásia', 'Assis', 'Atibaia', 'Auriflama', 'Avaí',
			'Avanhandava', 'Avaré', 'Bady Bassitt', 'Balbinos', 'Bálsamo',
			'Bananal', 'Barão de Antonina', 'Barbosa', 'Bariri', 'Barra Bonita',
			'Barra do Chapéu', 'Barra do Turvo', 'Barretos', 'Barrinha', 'Barueri',
			'Bastos', 'Batatais', 'Bauru', 'Bebedouro', 'Bento de Abreu',
			'Bernardino de Campos', 'Bertioga', 'Bilac', 'Birigui', 'Biritiba-Mirim',
			'Boa Esperança do Sul', 'Bocaina', 'Bofete', 'Boituva', 'Bom Jesus dos Perdões',
			'Bom Sucesso de Itararé', 'Borá', 'Boracéia', 'Borborema', 'Borebi',
			'Botucatu', 'Bragança Paulista', 'Braúna', 'Brejo Alegre', 'Brodowski',
			'Brotas', 'Buri', 'Buritama', 'Buritizal', 'Cabrália Paulista',
			'Cabreúva', 'Caçapava', 'Cachoeira Paulista', 'Caconde', 'Cafelândia',
			'Caiabu', 'Caieiras', 'Caiuá', 'Cajamar', 'Cajati',
			'Cajobi', 'Cajuru', 'Campina do Monte Alegre', 'Campinas', 'Campo Limpo Paulista',
			'Campos do Jordão', 'Campos Novos Paulista', 'Cananéia', 'Canas', 'Cândido Mota',
			'Cândido Rodrigues', 'Canitar', 'Capão Bonito', 'Capela do Alto', 'Capivari',
			'Caraguatatuba', 'Carapicuíba', 'Cardoso', 'Casa Branca', 'Cássia dos Coqueiros',
			'Castilho', 'Catanduva', 'Catiguá', 'Cedral', 'Cerqueira César',
			'Cerquilho', 'Cesário Lange', 'Charqueada', 'Chavantes', 'Clementina',
			'Colina', 'Colômbia', 'Conchal', 'Conchas', 'Cordeirópolis',
			'Coroados', 'Coronel Macedo', 'Corumbataí', 'Cosmópolis', 'Cosmorama',
			'Cotia', 'Cravinhos', 'Cristais Paulista', 'Cruzália', 'Cruzeiro',
			'Cubatão', 'Cunha', 'Descalvado', 'Diadema', 'Dirce Reis',
			'Divinolândia', 'Dobrada', 'Dois Córregos', 'Dolcinópolis', 'Dourado',
			'Dracena', 'Duartina', 'Dumont', 'Echaporã', 'Eldorado',
			'Elias Fausto', 'Elisiário', 'Embaúba', 'Embu das Artes', 'Embu-Guaçu',
			'Emilianópolis', 'Engenheiro Coelho', 'Espírito Santo do Pinhal', 'Espírito Santo do Turvo', 'Estiva Gerbi',
			'Estrela d\'Oeste', 'Estrela do Norte', 'Euclides da Cunha Paulista', 'Fartura', 'Fernando Prestes','Fernandópolis', 'Fernão', 'Ferraz de Vasconcelos', 'Flora Rica', 'Floreal',
			'Flórida Paulista', 'Florínea', 'Franca', 'Francisco Morato', 'Franco da Rocha',
			'Gabriel Monteiro', 'Gália', 'Garça', 'Gastão Vidigal', 'Gavião Peixoto',
			'General Salgado', 'Getulina', 'Glicério', 'Guaiçara', 'Guaimbê',
			'Guaíra', 'Guapiaçu', 'Guapiara', 'Guará', 'Guaraçaí',
			'Guaraci', 'Guarani d\'Oeste', 'Guarantã', 'Guararapes', 'Guararema',
			'Guaratinguetá', 'Guareí', 'Guariba', 'Guarujá', 'Guarulhos',
			'Guatapará', 'Guzolândia', 'Herculândia', 'Holambra', 'Hortolândia',
			'Iacanga', 'Iacri', 'Iaras', 'Ibaté', 'Ibirá',
			'Ibirarema', 'Ibitinga', 'Ibiúna', 'Icém', 'Iepê',
			'Igaraçu do Tietê', 'Igarapava', 'Igaratá', 'Iguape', 'Ilhabela',
			'Ilha Comprida', 'Ilha Solteira', 'Indaiatuba', 'Indiana', 'Indiaporã',
			'Inúbia Paulista', 'Ipaussu', 'Iperó', 'Ipeúna', 'Ipiguá',
			'Iporanga', 'Ipuã', 'Iracemápolis', 'Irapuã', 'Irapuru',
			'Itaberá', 'Itai', 'Itajobi', 'Itaju', 'Itanhaém',
			'Itaóca', 'Itapecerica da Serra', 'Itapetininga', 'Itapeva', 'Itapevi',
			'Itapira', 'Itapirapuã Paulista', 'Itápolis', 'Itaporanga', 'Itapuí',
			'Itapura', 'Itaquaquecetuba', 'Itararé', 'Itariri', 'Itatiba',
			'Itatinga', 'Itirapina', 'Itirapuã', 'Itobi', 'Itu',
			'Itupeva', 'Ituverava', 'Jaborandi', 'Jaboticabal', 'Jacareí',
			'Jaci', 'Jacupiranga', 'Jaguariúna', 'Jales', 'Jambeiro',
			'Jandira', 'Jardinópolis', 'Jarinu', 'Jaú', 'Jeriquara',
			'Joanópolis', 'João Ramalho', 'José Bonifácio', 'Júlio Mesquita', 'Jumirim',
			'Jundiaí', 'Junqueirópolis', 'Juquiá', 'Juquitiba', 'Lagoinha',
			'Laranjal Paulista', 'Lavínia', 'Lavrinhas', 'Leme', 'Lençóis Paulista',
			'Limeira', 'Lindóia', 'Lins', 'Lorena', 'Lourdes',
			'Louveira', 'Lucélia', 'Lucianópolis', 'Luís Antônio', 'Luiziânia',
			'Lupércio', 'Lutécia', 'Macatuba', 'Macaubal', 'Macedônia',
			'Magda', 'Mairinque', 'Mairiporã', 'Manduri', 'Marabá Paulista',
			'Maracaí', 'Marapoama', 'Mariápolis', 'Marília', 'Marinópolis',
			'Martinópolis', 'Matão', 'Mauá', 'Mendonça', 'Meridiano',
			'Mesópolis', 'Miguelópolis', 'Mineiros do Tietê', 'Mira Estrela', 'Miracatu',
			'Mirandópolis', 'Mirante do Paranapanema', 'Mirassol', 'Mirassolândia', 'Mococa',
			'Mogi das Cruzes', 'Mogi Guaçu', 'Moji Mirim', 'Mombuca', 'Monções',
			'Mongaguá', 'Monte Alegre do Sul', 'Monte Alto', 'Monte Aprazível', 'Monte Azul Paulista','Monte Castelo', 'Monte Mor', 'Monteiro Lobato', 'Morro Agudo', 'Morungaba','Motuca', 'Murutinga do Sul', 'Nantes', 'Narandiba', 'Natividade da Serra',
			'Nazaré Paulista', 'Neves Paulista', 'Nhandeara', 'Nipoã', 'Nova Aliança',
			'Nova Campina', 'Nova Canaã Paulista', 'Nova Castilho', 'Nova Europa', 'Nova Granada','Nova Guataporanga', 'Nova Independência', 'Nova Luzitânia', 'Nova Odessa', 'Novais',
			'Novo Horizonte', 'Nuporanga', 'Ocauçu', 'Óleo', 'Olímpia',
			'Onda Verde', 'Oriente', 'Orindiúva', 'Orlândia', 'Osasco',
			'Oscar Bressane', 'Osvaldo Cruz', 'Ourinhos', 'Ouro Verde', 'Ouroeste',
			'Pacaembu', 'Palestina', 'Palmares Paulista', 'Palmeira d\'Oeste', 'Palmital',
			'Panorama', 'Paraguaçu Paulista', 'Paraibuna', 'Paraíso', 'Paranapanema',
			'Paranapuã', 'Parapuã', 'Pardinho', 'Pariquera-Açu', 'Parisi',
			'Patrocínio Paulista', 'Paulicéia', 'Paulínia', 'Paulistânia', 'Paulo de Faria',
			'Pederneiras', 'Pedra Bela', 'Pedranópolis', 'Pedregulho', 'Pedreira',
			'Pedrinhas Paulista', 'Pedro de Toledo', 'Penápolis', 'Pereira Barreto', 'Pereiras',
			'Peruíbe', 'Piedade', 'Pilar do Sul', 'Pindamonhangaba', 'Pindorama', 
			'Pinhalzinho', 'Piquerobi', 'Piquete', 'Piracaia', 'Piracicaba', 
			'Piraju', 'Pirajuí', 'Pirangi', 'Pirapora do Bom Jesus', 'Pirapozinho', 
			'Pirassununga', 'Piratininga', 'Pitangueiras', 'Planalto', 'Platina', 
			'Poá', 'Poloni', 'Pompéia', 'Pongaí', 'Pontal', 'Pontalinda', 
			'Pontes Gestal', 'Populina', 'Porangaba', 'Porto Feliz', 'Porto Ferreira', 
			'Potim', 'Potirendaba', 'Pracinha', 'Pradópolis', 'Praia Grande', 
			'Pratânia', 'Presidente Alves', 'Presidente Bernardes', 'Presidente Epitácio', 
			'Presidente Prudente', 'Presidente Venceslau', 'Promissão', 'Quadra', 
			'Quatá', 'Queiroz', 'Queluz', 'Quintana', 'Rafard', 'Rancharia', 
			'Redenção da Serra', 'Regente Feijó', 'Reginópolis', 'Registro', 
			'Restinga', 'Ribeira', 'Ribeirão Bonito', 'Ribeirão Branco', 'Ribeirão Corrente', 
			'Ribeirão do Sul', 'Ribeirão dos Índios', 'Ribeirão Grande', 'Ribeirão Pires', 
			'Ribeirão Preto', 'Rifaina', 'Rincão', 'Rinópolis', 'Rio Claro', 
			'Rio das Pedras', 'Rio Grande da Serra', 'Riolândia', 'Riversul', 'Rosana', 
			'Roseira', 'Rubiácea', 'Rubinéia', 'Sabino', 'Sagres', 'Sales', 
			'Sales Oliveira', 'Salesópolis', 'Salmourão', 'Saltinho', 'Salto', 
			'Salto de Pirapora', 'Salto Grande', 'Sandovalina', 'Santa Adélia', 
			'Santa Albertina', 'Santa Bárbara d\'Oeste', 'Santa Branca', 'Santa Clara d\'Oeste', 
			'Santa Cruz da Conceição', 'Santa Cruz da Esperança', 'Santa Cruz das Palmeiras', 
			'Santa Cruz do Rio Pardo', 'Santa Ernestina', 'Santa Fé do Sul', 
			'Santa Gertrudes', 'Santa Isabel', 'Santa Lúcia', 'Santa Maria da Serra', 
			'Santa Mercedes', 'Santa Rita d\'Oeste', 'Santa Rita do Passa Quatro', 
			'Santa Rosa de Viterbo', 'Santa Salete', 'Santana da Ponte Pensa', 
			'Santana de Parnaíba', 'Santo Anastácio', 'Santo André', 'Santo Antônio da Alegria', 
			'Santo Antônio de Posse', 'Santo Antônio do Aracanguá', 'Santo Antônio do Jardim', 
			'Santo Antônio do Pinhal', 'Santo Expedito', 'Santópolis do Aguapeí', 
			'Santos', 'São Bento do Sapucaí', 'São Bernardo do Campo', 'São Caetano do Sul', 
			'São Carlos', 'São Francisco', 'São João da Boa Vista', 'São João das Duas Pontes',
			'São João de Iracema','São João do Pau dalho','São Joaquim da Barra','São José da Bela Vista',
			'São José do Barreiro','São José do Rio Pardo','São José do Rio Preto','São José dos Campos',
			'São Lourenço da Serra','São Luiz do Paraitinga','São Manuel','São Miguel','Arcanjo','São Paulo',
			'São Pedro','São Pedro do Turvo','São Roque','São Sebastião','São Sebastião da Grama','São Simão','São Vicente','Sarapuí',
			'Sarutaiá','Sebastianópolis do Sul','Serra Azul','Serra Negra','Serrana','Sertãozinho','Sete  Barras','Severínia','Silveiras',
			'Socorro','Sorocaba','Sud Mennucci','Sumaré','Suzanápolis','Suzano','Tabapuã','Tabatinga','Taboão da Serra','Taciba','Taguaí','Taiaçu','Taiúva',
			'Tambaú','Tanabi','Tapiraí','Tapiratiba','Taquaral','Taquaritinga','Taquarituba','Taquarivaí',
			'Tarabai','Tarumã','Tatuí','Taubaté','Tejupá','Teodoro Sampaio','Terra Roxa','Tietê','Timburi',
			'Torre de Pedra','Torrinha','Trabiju','Tremembé','Três Fronteiras','Tuiuti','Tupã','Tupi Paulista',
			'Turiúba','Turmalina','Ubarana','Ubatuba','Ubirajara','Uchoa','União Paulista','Urânia', 'Uru',
			'Urupês','Valentim Gentil','Valinhos','Valparaíso','Vargem','Vargem Grande do Sul','Vargem Grande Paulista',
			'Várzea Paulista','Vera Cruz','Vinhedo','Viradouro','Vista Alegre do Alto','Vitória Brasil','Votorantim','Votuporanga','Zacarias','Peruíbe'
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

    // Criar o select de cidades
    createCidadeSelect(targetElementId, placeholder = 'Selecione a cidade...') {
        const container = document.getElementById(targetElementId);
        if (!container) {
            console.error(`❌ Elemento ${targetElementId} não encontrado!`);
            return;
        }

        // Criar o select
        const select = document.createElement('select');
        select.id = `${targetElementId}_select`;
        select.className = 'form-control cidade-select';
        select.style.marginBottom = '0.5rem';

        // Opção padrão
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = placeholder;
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
        outraOption.textContent = '🏙️ Outra cidade (digite abaixo)';
        select.appendChild(outraOption);

        // Inserir o select antes do input existente
        const inputElement = container.querySelector('input');
        if (inputElement) {
            this.inputElement = inputElement;
            this.inputElement.placeholder = 'Digite o endereço completo ou selecione uma cidade acima';
            container.insertBefore(select, inputElement);
            
            // Event listener para o select
            select.addEventListener('change', (e) => {
                const selectedValue = e.target.value;
                if (selectedValue && selectedValue !== 'outra') {
                    // Preencher o input com a cidade selecionada
                    this.inputElement.value = selectedValue + ', SP';
                    this.inputElement.focus();
                    // Posicionar cursor no final
                    setTimeout(() => {
                        const length = this.inputElement.value.length;
                        this.inputElement.setSelectionRange(length, length);
                    }, 100);
                } else if (selectedValue === 'outra') {
                    // Limpar e focar no input para digitação livre
                    this.inputElement.value = '';
                    this.inputElement.focus();
                    this.inputElement.placeholder = 'Digite o endereço completo da cidade';
                    select.selectedIndex = 0; // Voltar para "Selecione..."
                }
            });

            this.selectElement = select;
            console.log('✅ Select de cidades criado com sucesso!');
        } else {
            console.error('❌ Input não encontrado no container!');
        }
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






console.log('🎯 Sistema de cidades carregado! Use cidadesDebug.info() para debug');