# fix(production): usar lattes_id e INNER JOIN na associação de pesquisadores em produções técnicas e eventos

## Descrição do Problema

Durante a execução das pipelines de produção técnica e outras produções no Apache Hop (`workflows/Index.hwf` -> `ImportProductionData.hwf`), foi identificada uma falha crítica na pipeline `ImportParticipationInEvents.hpl`:

```text
hop-1  | 2026/11/12 00:20:45 - insert table participation_events.0 - ERROR: Unexpected batch update error committing the database connection.
hop-1  | 2026/11/12 00:20:45 - insert table participation_events.0 - Caused by: org.postgresql.util.PSQLException: ERROR: null value in column "researcher_id" of relation "participation_events" violates not-null constraint
hop-1  | 2026/11/12 00:20:45 - insert table participation_events.0 -   Detail: Failing row contains (..., null, 2023, t, 0, 3)
```

## Causa Raiz

Nas pipelines de produções técnicas e eventos, a associação dos registros lidos dos XMLs com os pesquisadores já cadastrados no banco (`public.researcher`) utilizava:

1. **Junção por string de nome:** `researcher_name` = `NOME-COMPLETO`. Essa abordagem é instável devido a homônimos, diferenças de acentuação, casing, espaços em branco ou grafias divergentes entre o XML e o banco.
2. **Uso de `RIGHT OUTER JOIN`:** Como o lado direito eram os registros do XML, quando o nome do pesquisador no XML não encontrava match exato na tabela `researcher`, a linha do XML era mantida com todos os campos da tabela de pesquisadores preenchidos como `NULL`.
3. **Restrição NOT NULL no banco:** As tabelas de destino (ex.: `participation_events`, `brand`, `patent`, `software`, `event_organization`) possuem restrição `researcher_id uuid NOT NULL REFERENCES researcher(id)`. Ao tentar persistir um lote contendo `researcher_id = NULL`, o PostgreSQL aborta a transação em lote, derrubando toda a raia de execução do workflow.

## Pipelines Afetadas

1. `pipelines/ProductionData/ImportParticipationInEvents.hpl`
2. `pipelines/ProductionData/ImportBrand.hpl`
3. `pipelines/ProductionData/ImportPatent.hpl`
4. `pipelines/ProductionData/ImportSoftware.hpl`
5. `pipelines/ProductionData/ImportEventOrganization.hpl`

## Solução Implementada

1. **Extração de Identificador Canônico:**
   - Adicionada a extração do atributo `/CURRICULO-VITAE/@NUMERO-IDENTIFICADOR` (String de 16 dígitos) nos transforms de leitura de XML (`getXMLData`).
2. **Carregamento e Ordenação por `lattes_id`:**
   - Atualizado o transform `Table researcher` para incluir `lattes_id` na query SQL.
   - Atualizado `Select researcher` para repassar `lattes_id`.
   - Atualizados os transforms de ordenação (`Sort researcher` e `Sort rows`) para ordenar por `lattes_id` / `NUMERO-IDENTIFICADOR`.
3. **Junção Segura com `INNER JOIN`:**
   - O transform `Merge join researcher` foi alterado de `RIGHT OUTER` para `INNER`.
   - As chaves de junção foram atualizadas para `lattes_id` = `NUMERO-IDENTIFICADOR`.
   - Garante-se que nenhuma linha sem pesquisador associado seja enviada para inserção/atualização no banco de dados.
