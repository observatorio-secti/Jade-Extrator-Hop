# AGENTS.md — Jade Extrator Hop (`Jade-Extrator-Hop`)

Este repositório faz parte do **Ecossistema Observatório CT&I Bahia / SimCC**. Ele é versionado de forma independente e contém os **workflows (`.hwf`), pipelines (`.hpl`), metadados JDBC e datasets de semente do Apache Hop**, empacotados na imagem Docker `gleidsoncosta/simcc-extrator:latest` e disparados pelo orquestrador `simcc-etl`.

> Para entender como este extrator é invocado pelo `simcc-etl` e como se conecta ao `admin_db` e `write_db`, consulte [`README.md`](README.md), `../README.md` (`Simcc/README.md`) e `../../AGENTS.md`.

---

## 1. Princípios Arquiteturais e Contratos de Dados

1. **Conexões RDBMS (`metadata/rdbms/` e `project-config.json`)**:
   - **`DATABASE_URL` (`ApplicationDB`)**: Aponta para o banco de escrita/staging do SimCC (`write_db`, porta host `5435`, banco `simcc_write`).
   - **`ADMIN_DATABASE_URL` (`ApplicationAdminDB`)**: Aponta para o banco administrativo do `simcc-admin` (`admin_db`, porta host `5433`, banco `db`).
2. **Sincronização com o Schema `academic` do `simcc-admin`**:
   - `pipelines/ProprietaryData/ImportInstitution.hpl` lê `academic.institutions` do `admin_db` e popula `public.institution` no `write_db`.
   - `pipelines/ProprietaryData/ImportResearcher.hpl` faz `JOIN` entre `academic.researchers`, `academic.researcher_institutions` e `academic.institutions` no `admin_db` e vincula pesquisadores e instituições no `write_db`.
   - Programas de pós-graduação CAPES **não** vêm mais do `admin_db`; são importados pelas rotinas Python do `simcc-etl` após o `Index.hwf`.
3. **Dois Pontos de Entrada Principais (`workflows/`)**:
   - `workflows/Seeding.hwf` (disparado pela rotina `hop_seed` do `simcc-etl`): carrega países, estados, cidades, grandes áreas do CNPq, Qualis, JCR, grupos de pesquisa e fomento a partir de `datasets/`.
   - `workflows/Index.hwf` (disparado pela rotina `hop_index` do `simcc-etl`): processa os currículos XML Lattes montados em `/files/jade-extrator/dataset/xml/` e extrai dados básicos, áreas de atuação, produções bibliográficas/técnicas/artísticas e vínculos institucionais.
4. **Rebuild Obrigatório da Imagem Docker**:
   - Como o `Dockerfile` copia `.` para `/files/jade-extrator` dentro da imagem, qualquer alteração em `.hwf`, `.hpl` ou `datasets/` exige o rebuild da imagem `docker build -t gleidsoncosta/simcc-extrator:latest .` para surtir efeito na execução do `simcc-etl`.

---

## 2. Comandos Padrão de Desenvolvimento

- **Construir a imagem Docker usada pelo `simcc-etl`**:
  ```bash
  docker build -t gleidsoncosta/simcc-extrator:latest .
  ```
- **Testar execução via `simcc-etl` (a partir da raiz `Observatorio/`)**:
  ```bash
  poetry -C Simcc/simcc-etl run python -m simcc_etl.cli --routines hop_seed
  poetry -C Simcc/simcc-etl run python -m simcc_etl.cli --routines hop_index
  ```

---

## 3. Padrão de Documentação e Gatilhos Obrigatórios (Definition of Done)

A documentação deste repositório está em [`README.md`](README.md) e no guia integrado `../README.md` (`Simcc/README.md`).

### Tabela de Atualização Obrigatória

**Nenhuma alteração em workflows, pipelines ou datasets está pronta sem atualizar a documentação correspondente:**

| Se você alterar... | Atualize obrigatoriamente: |
| :--- | :--- |
| Workflows em `workflows/*.hwf` ou pipelines em `pipelines/**/*.hpl` | Seções **🧱 Arquitetura de Workflows** e **📁 Estrutura de Diretórios** no [`README.md`](README.md) e `../README.md` |
| Planilhas/CSVs de referência em `datasets/` | Tabela **🗂️ Datasets de Semente (`datasets/`)** no [`README.md`](README.md) |
| Variáveis JDBC em `project-config.json` ou `metadata/rdbms/` | Seção **⚙️ Configuração e Variáveis JDBC** no [`README.md`](README.md) |
