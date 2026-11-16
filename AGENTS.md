# AGENTS.md — Guia de Desenvolvimento e Metodologia de Testes (`Jade-Extrator-Hop`)

Este documento define a arquitetura, as regras de engenharia e a metodologia obrigatória de **Test-Driven Development (TDD)** em **2 Camadas** para agentes de IA (LLMs) e desenvolvedores que trabalham nas pipelines (`.hpl`) e workflows (`.hwf`) do **Jade-Extrator-Hop**.

---

## 1. Visão Geral do Projeto

O `Jade-Extrator-Hop` é o extrator de currículos Lattes (XML) e bases auxiliares (CSV/XLSX) do ecossistema SIMCC, construído sobre **Apache Hop 2.20** e **PostgreSQL**:

- **`workflows/`**: Orquestrações (`.hwf`), tendo [Index.hwf](workflows/Index.hwf) (carga de currículos) e [Seeding.hwf](workflows/Seeding.hwf) (carga inicial de países, estados, JCR e Qualis) como pontos de entrada.
- **`pipelines/`**: Transformações (`.hpl`) divididas em `BasicData/`, `ExpertiseData/`, `ResearcherData/`, `ProductionData/` e `Seeding/`.
- **`metadata/`**: Metadados do Hop, incluindo a conexão única de banco de dados `ApplicationDB` ([metadata/rdbms/ApplicationDB.json](metadata/rdbms/ApplicationDB.json)), parametrizada via `${DATABASE_URL}`.
- **`datasets/`**: Arquivos estáticos de seeding e a pasta `datasets/lattes_xml/` onde os XMLs do Lattes são lidos em tempo de execução.
- **`tests/`**: Suíte automatizada em Python (`pytest` + `psycopg`), gerenciada via **Poetry**.

---

## 2. Ambiente, Git Worktrees e Comandos (Poetry)

- **Gerenciador Python:** Todo o ferramental de testes e lint deste repositório é gerenciado com **Poetry** ([pyproject.toml](pyproject.toml) e [poetry.toml](poetry.toml) com `.venv` local ao projeto).
- **Isolamento em Git Worktrees:** Ao desenvolver correções ou novas features com agentes, crie uma *worktree* dedicada dentro de `.agents/worktrees/<nome-da-tarefa>` a partir de `origin/develop`.

### Comandos principais

```bash
# Instalar dependências no .venv do projeto
poetry install

# Camada 1: Validação estática rápida (< 1s, não requer Docker nem banco)
poetry run task test_static
# ou: poetry run pytest -m static

# Camada 2: Testes de integração caixa-preta (requer Docker + PostgreSQL)
poetry run task test_integration
# ou: poetry run pytest -m integration

# Suíte completa (Camadas 1 + 2)
poetry run task test

# Lint e formatação do código de teste
poetry run task lint
poetry run task format
```

---

## 3. Metodologia de Testes (Camadas 1 e 2)

Arquivos `.hpl` e `.hwf` são grafos serializados em XML sem verificação estática de tipos em tempo de edição. Além disso, o mecanismo nativo de *Unit Tests* do Apache Hop substitui os leitores (`getXMLData`/`TableInput`) e escritores (`TableOutput`/`Update`) por CSVs estáticos, deixando de testar justamente os dois pontos mais críticos deste projeto: **expressões XPath sobre o XML do Lattes** e **persistência/tipagem/idempotência no PostgreSQL**.

Por isso, adotamos exclusivamente as **Camadas 1 e 2** via `pytest`:

### Camada 1 — Validação Estática (`tests/static/test_static_pipelines.py`)
Executa em menos de 1 segundo analisando a árvore XML de todas as 55 pipelines e 10 workflows:
1. **Integridade de Grafo (`<order>` e `<hops>`):** Garante que todo `<from>` e `<to>` referencia um `<transform>` ou `<action>` existente, e que `<transform_error_handling>` não aponta para transforms inexistentes.
2. **Conexão RDBMS Canônica:** Garante que nenhum transform usa conexões legadas/inexistentes (apenas `ApplicationDB` é permitida).
3. **Caminhos de Entrada (`GetFileNames`):** Garante que transforms `GetFileNames` ativos apontam para `${PROJECT_HOME}/datasets/...`.
4. **Invariante de `MergeJoin`:** Garante que todo `MergeJoin` ativo é alimentado por transforms `SortRows` válidos em `transform1` e `transform2`, com a mesma quantidade de chaves (`keys_1` e `keys_2`) e que os `SortRows` ordenam exatamente pelo prefixo dessas chaves.
5. **Anti-Produto-Cartesiano em XML:** Proíbe qualquer `MergeJoin` entre dois fluxos puramente XML (`getXMLData`) que não inclua o identificador do pesquisador (`NUMERO-IDENTIFICADOR` / `IDENTIFICADOR`) nas chaves de junção.
6. **Contratos Estáticos por Pipeline:** Regras específicas da pipeline sob teste (ex.: `test_import_professional_experience_static_contract`).

### Camada 2 — Integração Caixa-Preta (`tests/integration/`)
Executa a pipeline real dentro de um container efêmero do Apache Hop (`apache/hop:latest` via `hop-run.sh`) contra um banco PostgreSQL efêmero (`jade_hop_test_<nome>_<id>`) criado e destruído automaticamente a cada teste pelo fixture `pg_test_db`:
- O fixture `hop_session_env` ([tests/conftest.py](tests/conftest.py)) sobe um único container Hop por sessão do `pytest` e injeta o `DATABASE_URL` do banco de teste no `project-config.json` montado no container, garantindo que o banco principal (`simcc_write`) **nunca** seja tocado.
- Cada pipeline validada deve possuir no mínimo **4 baterias de integração**:
  1. **Carga Limpa + Anti-Produto-Cartesiano:** Múltiplos pesquisadores compartilhando nomes de instituições/eventos/projetos + 1 pesquisador no XML ausente do banco (deve ser filtrado pelo `INNER JOIN`), validando valores e tipos exatos no PostgreSQL (`int`, `bool`, `str`, `None`).
  2. **Idempotência e Duplicatas no XML:** Execução dupla consecutiva (`run1` e `run2`) sobre o mesmo lote de XMLs (incluindo itens duplicados no mesmo currículo), exigindo zero duplicatas e estado idêntico (`rows_after_2 == rows_after_1`).
  3. **Sincronização / Atualização (`Update`):** Execução com XML v1 seguida de XML v2 com atributos modificados, verificando que o registro existente foi atualizado in-place sem duplicar nem lançar erros de cast.
  4. **Amostra Real (`datasets/lattes_xml/`):** Execução dupla sobre currículos reais da pasta `datasets/lattes_xml/` validando determinismo e ausência de erros em currículos grandes.

---

## 4. Ciclo TDD Obrigatório (Red → Green → Refactor)

Sempre que for criar, reativar ou corrigir uma pipeline `.hpl` ou workflow `.hwf`:

1. **Fase RED (Escrever os testes primeiro):**
   - Adicione ou atualize o contrato estático na Camada 1 ([tests/static/test_static_pipelines.py](tests/static/test_static_pipelines.py)).
   - Crie ou atualize o arquivo de integração na Camada 2 (`tests/integration/test_<nome_pipeline>.py`).
   - Se a pipeline usar tabelas que ainda não estão em `BASE_SCHEMA_SQL` ([tests/conftest.py](tests/conftest.py)), adicione o DDL correspondente.
   - Rode `poetry run pytest` e **confirme que os testes falham** pelos motivos esperados.
2. **Fase GREEN (Corrigir o `.hpl` / `.hwf`):**
   - Aplique as alterações no XML da pipeline/workflow.
   - Rode primeiro `poetry run task test_static` (ciclo sub-segundo) até zerar falhas estruturais.
   - Rode `poetry run pytest tests/integration/test_<nome_pipeline>.py` até que todos os cenários de banco passem.
3. **Fase REFACTOR & LINT:**
   - Rode `poetry run task format` e `poetry run task lint`.
   - Rode `poetry run task test` para garantir 100% da suíte verde antes de commitar.

---

## 5. Armadilhas Críticas do Apache Hop para LLMs

Ao editar arquivos `.hpl` diretamente em XML, respeite rigorosamente estas regras:

1. **Nunca faça dois `getXMLData` + `MergeJoin` para ler tags pai e filho do mesmo XML:**
   - Em XPath do `getXMLData`, se o `loopxpath` está no elemento filho (ex.: `.../ATUACAO-PROFISSIONAL/VINCULOS`), leia atributos do pai diretamente com `../@NOME-INSTITUICAO` e da raiz com `/CURRICULO-VITAE/@NUMERO-IDENTIFICADOR`. Criar dois `getXMLData` e uni-los por nome da instituição gera produto cartesiano entre todos os pesquisadores da mesma instituição.
2. **Encoding de currículos Lattes é `ISO-8859-1`:**
   - Todo transform `getXMLData` que lê currículos Lattes deve configurar `<encoding>ISO-8859-1</encoding>`. Da mesma forma, geradores de XML de teste devem gravar arquivos com `<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>` e `encoding='iso-8859-1'`.
3. **Tipagem numérica explícita no `getXMLData`:**
   - Colunas `INTEGER` no PostgreSQL (como `start_year`, `end_year`, `workload_hours_weekly`, `sequence_code`) devem ser lidas no `getXMLData` com `<type>Integer</type>`, `<format>#</format>` e `<trim_type>both</trim_type>`. Assim, atributos vazios (`ANO-FIM=""`) tornam-se `NULL` nativo do tipo `Integer` e funcionam corretamente no `SortRows` e no `MergeJoin`.
   - **Nunca** inclua campos `Integer` ou `Boolean` dentro do transform `StringOperations`.
4. **Conversão para `Boolean` e o bug de `ClassCastException` no `Update`:**
   - No Apache Hop 2.20, configurar `<target_type>Boolean</target_type>` em um `ValueMapper` com `<target_field/>` vazio (substituição *in-place*) coloca um objeto `java.lang.Boolean` na linha mas **mantém o metadado da coluna como `ValueMetaString`**, causando `ClassCastException: class java.lang.Boolean cannot be cast to class java.lang.String` em `SelectValues` ou `Update.lookupValues`.
   - **Padrão correto:** No `ValueMapper`, mantenha `<target_field/>` sem `<target_type>` (mapeando `SIM` → `TRUE` e `NAO`/`NÃO` → `FALSE` como `String`) e faça a conversão de metadado para `Boolean` através de um bloco `<meta>` nos transforms `SelectValues` (`Select to create` e `Select to update`), ou defina um `<target_field>` com novo nome no `ValueMapper`.
5. **Deduplicação obrigatória antes do `MergeJoin` (`unique_rows=Y`):**
   - Currículos Lattes frequentemente possuem registros com a mesma chave natural. Sempre configure `<unique_rows>Y</unique_rows>` no `SortRows` que antecede o `MergeJoin` de sincronização com o banco (tanto no fluxo do XML quanto no fluxo vindo do `TableInput`), evitando duplicatas na carga inicial e multiplicação $N \times N$ no reprocessamento.
6. **Ordem de colunas no `SelectValues`:**
   - Quando dois fluxos são unidos ou quando `SelectValues` renomeia colunas antes de `TableOutput`/`Update`, confira que `<fields>` e `<meta>` referenciam os nomes exatos vindos a montante e que `<select_unspecified>N</select_unspecified>` está definido.

---

## 6. Como Criar Testes para uma Nova Pipeline

1. **Verifique o Schema de Banco em [tests/conftest.py](tests/conftest.py):**
   - Adicione o `CREATE TABLE` da tabela alvo (e eventuais FKs) em `BASE_SCHEMA_SQL` dentro de `tests/conftest.py`.
2. **Adicione o Contrato Estático em [tests/static/test_static_pipelines.py](tests/static/test_static_pipelines.py):**
   - Crie `test_<nome_pipeline>_static_contract()` validando os transforms críticos da pipeline (`getXMLData`, tipos `Integer`/`Boolean`, `unique_rows=Y` nos `SortRows` e registro no workflow `.hwf` pai).
3. **Crie o Arquivo de Integração em `tests/integration/test_<nome_pipeline>.py`:**
   - Marque o módulo com `pytestmark = pytest.mark.integration`.
   - Crie um helper `_write_lattes_xml(...)` gerando apenas o recorte XML usado pela pipeline, codificado em `iso-8859-1`.
   - Implemente os 4 testes padrão:
     - `test_clean_load_and_anti_cartesian_product`
     - `test_idempotency_and_xml_duplicates`
     - `test_update_existing_<entidade>` (ou sincronização de deleção)
     - `test_sample_lattes_xml_batch_idempotency`
4. **Execute a suíte:**
   ```bash
   poetry run task lint
   poetry run task test
   ```
