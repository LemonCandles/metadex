# 🗡️ Metadex

> O catálogo estatístico e rastreador definitivo do Meta de Dota 2.

## 🎯 Objetivo do Projeto

O **Metadex** é uma plataforma de inteligência de dados construída para analisar, identificar e monitorar o M.E.T.A. (*Most Effective Tactic Available*) do Dota 2 em tempo real. 

Em vez de depender de achismos ou opiniões, o projeto consome dados brutos de partidas de alto nível, aplica técnicas de mineração de dados para encontrar correlações (ex: sinergia entre Heróis e Itens, impacto do tempo de jogo na taxa de vitória) e exibe esses *insights* em um dashboard com design focado na experiência do jogador.

Este projeto serve como um laboratório prático para unir três pilares da tecnologia:
1. **Engenharia de Redes:** Consumo assíncrono de APIs, controle de *rate limits* e paginação.
2. **Ciência de Dados:** Limpeza, transformação e descoberta de padrões (Deltas de *Win Rate*) usando DataFrames.
3. **Desenvolvimento Web:** Criação de uma interface tátil, moderna e responsiva (*Dark/Gaming Mode*).

## 🛠️ Stack Tecnológico Previsto

O projeto utiliza uma arquitetura desacoplada (Monorepo), separando o motor de análise de dados da interface visual.

**Backend & Data Science (Motor de Dados)**
*   **Python 3:** Linguagem principal para os scripts e servidor.
*   **Pandas:** Exploração de dados, cruzamento de variáveis e cálculos estatísticos.
*   **FastAPI:** Criação da API interna de forma assíncrona e rápida.
*   **HTTPX:** Biblioteca moderna para requisições HTTP assíncronas (coleta de dados).
*   **OpenDota API:** Fonte primária e aberta de dados das partidas de Dota 2.

**Frontend (Interface do Usuário)**
*   **Next.js (React):** Framework para renderização das páginas e consumo da API interna.
*   **Tailwind CSS:** Estilização da interface, focada em componentes modernos e responsivos.
*   **shadcn/ui & Lucide:** Componentes base e iconografia.
*   **Recharts:** Renderização de gráficos interativos (Radares, Linhas de Tendência).

## 📂 Estrutura do Repositório

```text
metadex/
├── backend/                  # Motor de Processamento e API
│   ├── app/
│   │   ├── main.py           # Ponto de entrada da API (FastAPI)
│   │   ├── rotas/            # Endpoints servidos para o frontend
│   │   ├── servicos/         # Integração com a OpenDota API
│   │   └── mineracao/        # Lógica de negócio e cálculos do Pandas
│   ├── notebooks/            # Jupyter Notebooks para testes e exploração de dados
│   ├── requirements.txt      # Dependências do Python
│   └── .env.example          # Variáveis de ambiente de exemplo
│
├── frontend/                 # Interface de Usuário
│   ├── src/
│   │   ├── app/              # Estrutura de rotas do Next.js
│   │   ├── components/       # Componentes visuais (Cards, Gráficos)
│   │   └── lib/              # Funções utilitárias e chamadas à API interna
│   ├── package.json          # Dependências do Node.js
│   └── tailwind.config.ts    # Configurações de estilo global
│
└── README.md                 # Documentação principal do projeto
