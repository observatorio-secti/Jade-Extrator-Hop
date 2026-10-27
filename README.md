# Jade Extrator Hop · Extrator Apache Hop do SimCC (`Jade-Extrator-Hop`)

Motor de extração e transformação de currículos XML da Plataforma Lattes e carga de conjuntos de dados de referência (Qualis, JCR, localidades, áreas CNPq) baseado em **Apache Hop**, integrante do **Ecossistema Observatório CT&I Bahia / SimCC**.

Este projeto é empacotado como a imagem Docker `gleidsoncosta/simcc-extrator:latest` e orquestrado de forma efêmera pelo serviço [`simcc-etl`](../simcc-etl/README.md).

> 📖 Para o guia completo de integração entre `simcc-admin`, `Jade-Extrator-Hop`, `simcc-etl` e `simcc-back`, consulte [`Simcc/README.md`](../README.md).

---

## 🧱 Arquitetura e Fluxo de Workflows

O projeto expõe dois workflows principais em `workflows/`:

```text
1. workflows/Seeding.hwf (Rotina `hop_seed` no simcc-etl — 1ª execução)
   └── pipelines/Seeding/
       ├── País, Estado, Cidade e Grandes Áreas do CNPq
       ├── Qualis (2017–2020 e 2021–2024) e JCR
       └── Grupos de Pesquisa e Bolsistas de Fomento

2. workflows/Index.hwf (Rotina `hop_index` no simcc-etl — execução por lote XML)
   ├── ImportProprietaryData.hwf
   │   ├── ImportInstitution.hpl  (Lê academic.institutions do admin_db -> write_db)
   │   └── ImportResearcher.hpl   (Cruza XMLs com academic.researchers no admin_db)
   ├── ImportBasicData.hwf        (Dados gerais, endereço, idiomas, prêmios)
   ├── ImportExpertiseData.hwf    (Áreas e subáreas de atuação do pesquisador)
   ├── ImportResearcherData.hwf   (Formação acadêmica, atuação profissional, projetos, orientações)
   └── ImportProductionData.hwf   (Artigos, livros, capítulos, eventos, patentes, softwares, produção técnica/artística)
```

---

## 📁 Estrutura de Diretórios

```text
Jade-Extrator-Hop/
├── datasets/                          # Planilhas e CSVs de semente (Seeding.hwf)
│   ├── country.csv
│   ├── state.csv
│   ├── jcr.csv
│   ├── qualis-2017-2020.xlsx
│   ├── qualis-2021-2024.xlsx
│   ├── research_groups.csv
│   └── funded_researchers.csv
├── metadata/
│   └── rdbms/                         # Definições de conexões JDBC (ApplicationDB e ApplicationAdminDB)
├── pipelines/                         # Pipelines Apache Hop (.hpl)
│   ├── BasicData/                     # Extração de dados cadastrais do currículo Lattes
│   ├── ExpertiseData/                 # Áreas de conhecimento CNPq
│   ├── ProductionData/                # Produções bibliográficas, técnicas e artísticas
│   ├── ProprietaryData/               # Sincronização de instituições e pesquisadores com o admin_db
│   ├── ResearcherData/                # Formação, projetos e orientações
│   ├── Seeding/                       # Carga de tabelas auxiliares a partir de datasets/
│   └── ReadXML.hpl                    # Leitura do diretório de currículos XML
├── workflows/                         # Workflows orquestradores Apache Hop (.hwf)
│   ├── Seeding.hwf                    # Workflow de carga inicial de dados de referência
│   ├── Index.hwf                      # Workflow principal de indexação dos currículos Lattes
│   ├── ImportBasicData.hwf
│   ├── ImportExpertiseData.hwf
│   ├── ImportProductionData.hwf
│   ├── ImportProprietaryData.hwf
│   └── ImportResearcherData.hwf
├── Dockerfile                         # Imagem baseada em apache/hop:latest (/files/jade-extrator)
├── compose.yaml                       # Compose auxiliar para desenvolvimento local
└── project-config.json                # Configuração do projeto Hop e variáveis JDBC padrão
```

---

## 🚀 Como Construir e Executar

### 1. Build da Imagem Docker
Sempre que alterar qualquer arquivo `.hwf`, `.hpl` ou `datasets/`, reconstrua a imagem utilizada pelo `simcc-etl`:

```bash
docker build -t gleidsoncosta/simcc-extrator:latest .
```

### 2. Execução via `simcc-etl` (Recomendado)
O `simcc-etl` monta automaticamente os currículos XML do lote atual (`storage/xml/run_current`) em `/files/jade-extrator/dataset/xml` e injeta as URLs JDBC na rede Docker `simcc-network`:

```bash
# Executar o Seeding inicial (workflows/Seeding.hwf)
poetry -C ../simcc-etl run python -m simcc_etl.cli --routines hop_seed

# Executar a indexação de currículos (workflows/Index.hwf)
poetry -C ../simcc-etl run python -m simcc_etl.cli --routines hop_index
```

---

## ⚙️ Configuração e Variáveis JDBC (`project-config.json`)

As conexões definidas em `metadata/rdbms/` utilizam duas variáveis de ambiente (sobrescritas em tempo de execução pelo `simcc-etl` via flags `-s`):

| Variável no Hop | Conexão RDBMS | Variável correspondente no `simcc-etl` | Papel |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `ApplicationDB` | `HOP_WRITE_JDBC_URL` (`jdbc:postgresql://write_db:5432/simcc_write?...`) | Banco de escrita onde o Hop grava as tabelas extraídas |
| `ADMIN_DATABASE_URL` | `ApplicationAdminDB` | `HOP_ADMIN_JDBC_URL` (`jdbc:postgresql://admin_db:5432/db?...`) | Banco administrativo (`simcc-admin`) de onde o Hop lê `academic.institutions` e `academic.researchers` |
