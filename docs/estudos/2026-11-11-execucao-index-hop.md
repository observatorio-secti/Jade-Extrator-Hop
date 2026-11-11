# Estudo de execução do Index (11/11/2026)

Registro do estudo de desempenho e consistência do `workflows/Index.hwf`. Acompanhamento dos problemas: issue #21.

## Perguntas

1. Quais pontos mais causam lentidão no Apache Hop durante a atualização de um banco já populado?
2. O Hop trava ou falha por erros nessa atualização?
3. Os logs ficam armazenados em algum lugar?
4. Com uma amostra de 2.000 XMLs: a atualização sobre o banco atual chega ao mesmo resultado de uma carga num banco limpo pós-Seeding? Duas cargas limpas dão o mesmo resultado?

## Ambiente e método

- Apache Hop 2.20 (`apache/hop:latest`), imagem construída do `main` em `07ba717`.
- Docker Desktop: 12 CPUs, 7,5 GB de RAM. Hop limitado a 6 GB (`compose.yaml`) e a 12 CPUs (override; o compose pede 16).
- Postgres 17 (`observatorio-db`), o mesmo do `simcc_write` local.
- Disparo igual ao do `simcc-etl`: `GET /hop/execWorkflow` com `DATABASE_URL` apontando para o banco do estudo e log em nível Basic.
- Coleta a cada 15 s: log incremental do Hop Server (`/hop/workflowStatus?from=`), `docker stats` do Hop e do Postgres, `pg_stat_activity` e locks do banco do estudo. Contagem exata e `pg_stat_user_tables` de todas as tabelas antes e depois de cada execução.
- Comparação de bancos: ids `uuid` descartados, cada FK trocada pela linha referenciada (pesquisador → `lattes_id`), só as colunas que algum pipeline do Index escreve. Compara-se o multiconjunto de linhas por tabela.
- Bancos criados (mantidos para inspeção): `simcc_write_hopstudy` (etapa 1), `hopcmp_update`, `hopcmp_clean_1`, `hopcmp_clean_2` (etapa 2).

## Resultado 1: estabilidade

Nenhuma falha nem travamento em 6 execuções (Index completo, 2 Seedings, 3 Index da amostra). Todas terminaram com status `Finished`, sem OOM e sem reinício do container. A memória do container chegou a 4,2 GiB de 6 GiB.

O único ruído são duas linhas `ERROR` no carregamento de pipelines cujo tratamento de erro aponta para transforms que não existem (issue #15). Elas saem no canal `General`, só no stdout do container, e não aparecem no log do workflow que o `simcc-etl` lê.

## Resultado 2: onde está a lentidão

Index completo sobre `simcc_write_hopstudy` (cópia do `simcc_write`, 7,4 GB, 42.300 pesquisadores), 42.300 XMLs (6,9 GB): **64,6 min**.

| Sub-workflow | Duração |
|---|---:|
| ImportBasicData | 3,1 min |
| ImportExpertiseData | 3,9 min |
| ImportResearcherData | 30,3 min |
| ImportProductionData | 27,2 min |
| ↳ Bibliográfica (em paralelo) | 20,1 min |
| ↳ Técnica → Outras (caminho crítico) | 7,3 + 19,8 min |

| Pipeline | Duração | Limitado por | Evidência |
|---|---:|---|---|
| ImportEducation | 22,7 min | Banco | 124.613 `DELETE FROM education WHERE researcher_id = ?`, sem índice: 124.608 seq scans, 15,5 bi linhas lidas (#4) |
| ImportGuidance | 7,7 min | Hop | 8 leitores de XML de 1 cópia; CPU do Hop 1.193% |
| ImportParticipationInEvents | 7,1 min | Hop | 6 leitores de XML de 1 cópia |
| ImportAddressResearcher | 3,8 min | Banco | Insert/update sem índice: 42.683 seq scans, 1,8 bi linhas, 188 updates (#6) |
| 9 pipelines de produção bibliográfica | 1,5–2,7 min cada | Hop | Releitura dos XMLs + ordenação da tabela-alvo inteira |
| Demais 18 pipelines | 0,8–2,2 min cada | Hop | Piso de 45–60 s para listar e parsear os 42.300 XMLs |

- Os dois pipelines limitados pelo banco somam 26,5 min (41%).
- No restante, o Hop fica entre 400% e 1.250% de CPU (média 523%) e o Postgres quase ocioso. O Hop leu **179 GB** do disco: os XMLs são parseados ~47 vezes por execução (#14).
- Amostra de 2.000 XMLs: 4,6 min sobre o banco cheio × 3,1 min em banco limpo. A diferença está quase toda em `ImportEducation` (84 s × 17–19 s) e `ImportAddressResearcher` (16 s × 4–6 s).

## Resultado 3: logs

O projeto não grava log em arquivo (nenhuma ação usa `set_logfile`, não há Execution Information Location). O log existe em três lugares:

| Lugar | Conteúdo | Duração |
|---|---|---|
| Buffer do Hop Server (`/hop/workflowStatus`) | Log do workflow em Basic: ~1.200 linhas por Index completo | Memória; até 100.000 linhas ou 24 h. O `simcc-etl` remove a execução (`removeWorkflow`) depois de ler |
| Stdout do container (`docker logs`) | O mesmo log, mais o canal `General` | Driver `local`; some quando o container é recriado |
| JSONL do `simcc-etl` (`logs/AAAA-MM-DD.jsonl`, `logs/runs/<run_id>.jsonl`) | Cada linha do buffer como evento `hop.log` | Durável; única fonte histórica (execuções de 27 a 31/out) |

O nível Basic mostra a duração de cada pipeline, mas não o tempo por transform (#16).

## Resultado 4: reprocessar sobre o banco populado

Contagem exata antes e depois do Index completo com os mesmos XMLs:

| Tabela | Antes | Depois | Δ | Issue |
|---|---:|---:|---:|---|
| event_organization | 332.354 | 498.255 | +165.901 | #7 |
| researcher_area_expertise | 282.534 | 352.973 | +70.439 | #9 |
| sub_area_expertise | 57.627 | 76.728 | +19.101 | #8 |
| bibliographic_production | 872.950 | 885.274 | +12.324 (1.846 duplicatas) | #12 |
| bibliographic_production_work_in_event | 458.367 | 466.239 | +7.872 | #12 |
| bibliographic_production_article | 267.440 | 271.702 | +4.262 | #12 |
| technical_work_presentation | 470.889 | 472.330 | +1.441 | #12 |
| research_project | 211.370 | 212.259 | +889 | #12 |
| education | 124.606 | 124.599 | −7 | #5 |

## Resultado 5: amostra de 2.000 XMLs

Os dois Seedings geraram o mesmo conteúdo: 249 países, 27 estados, 21.957 JCR e 64.689 revistas. `research_group` e `research_lines` ficam vazios, como no `simcc_write` atual (#17).

### Duas cargas limpas: 39 de 44 tabelas iguais

| Tabela | Limpo 1 | Limpo 2 | Linhas divergentes | Causa |
|---|---:|---:|---:|---|
| researcher_area_expertise | 3.355 | 2.969 | 508 / 122 | Área resolvida só pelo nome (#10) |
| sub_area_expertise | 1.687 | 1.687 | 163 | Idem (#10) |
| area_specialty | 586 | 585 | 102 / 101 | Idem (#10) |
| bibliographic_production_article | 11.895 | 11.895 | 301 | Artigo sem ISSN ligado a revista arbitrária (#11) |
| periodical_magazine | 65.326 | 65.326 | 1 | Idem (#11) |

### Atualização × carga limpa (só os 2.000 pesquisadores): 26 de 44 tabelas iguais

| Tabela | Atualizado | Limpo | Só no atualizado | Só no limpo | Leitura |
|---|---:|---:|---:|---:|---|
| event_organization | 22.641 | 7.520 | 15.121 | 0 | Duplicatas (#7) |
| researcher_area_expertise | 16.841 | 3.355 | 13.870 | 384 | 11.361 duplicatas + #10 |
| bibliographic_production | 39.781 | 39.080 | 701 | 0 | 642 obsoletas + 59 duplicatas (#13, #12) |
| bibliographic_production_article | 12.127 | 11.895 | 619 | 387 | Obsoletas + revista (#13, #11) |
| bibliographic_production_work_in_event | 20.522 | 20.154 | 368 | 0 | 322 obsoletas + 46 duplicatas |
| participation_events | 45.640 | 45.357 | 283 | 0 | Obsoletas (#13) |
| technical_work_presentation | 22.322 | 22.166 | 156 | 0 | Duplicatas (#12) |
| technical_work | 4.956 | 4.896 | 60 | 0 | Duplicatas (#12) |
| research_project | 9.883 | 9.827 | 56 | 0 | Duplicatas (#12) |
| bibliographic_production_book_chapter | 3.790 | 3.748 | 42 | 0 | Obsoletas (#13) |
| guidance | 20.585 | 20.558 | 27 | 0 | Obsoletas (#13) |
| researcher | 2.000 | 2.000 | — | — | Iguais em cidade e instituição (1 exceção); `update_abstract` true × NULL (#20) |

No `simcc_write` atual, **4.530 artigos de 2.988 periódicos diferentes** apontam para "Journal Of Clinical Investigation" (#11).

## Histórico anterior (logs do `simcc-etl`)

- 28 e 30/out: `hop_index` falhou por linhas `Unique rows - ERROR: DUP` (o ETL passou a ignorar essa linha).
- 31/out: execução completa falhou após 83 min em `ImportAdminMapping → Insert / update` (hoje fora do Index).

## Issues abertas

#4, #5, #6, #7, #8, #9, #10, #11, #12, #13, #14, #15, #16, #17, #18, #19, #20. Acompanhamento em #21.
