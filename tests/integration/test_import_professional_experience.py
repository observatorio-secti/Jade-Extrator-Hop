"""Camada 2: Testes de integração de ImportProfessionalExperience.hpl."""

import shutil
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT, DatabaseHarness

pytestmark = pytest.mark.integration

PIPELINE_RELPATH = 'pipelines/ResearcherData/ImportProfessionalExperience.hpl'


def _write_lattes_xml(
    target_dir: Path,
    lattes_id: str,
    full_name: str,
    atuacoes: list[dict],
) -> Path:
    """Gera um XML Lattes mínimo para testes de vínculos profissionais."""
    ap_blocks = []
    for ap in atuacoes:
        inst_name = ap['instituicao']
        vinculos_xml = []
        for idx, v in enumerate(ap.get('vinculos', []), start=1):
            tipo = v.get('tipo_vinculo', 'SERVIDOR_PUBLICO')
            enq = v.get('enquadramento', 'LIVRE')
            ch = v.get('carga_horaria', '')
            ded = v.get('dedicacao_exclusiva', 'NAO')
            ini = v.get('ano_inicio', '')
            fim = v.get('ano_fim', '')
            info = v.get('outras_info', '')
            outro_v = v.get('outro_vinculo', '')
            outro_e = v.get('outro_enquadramento', '')
            seq = v.get('seq', idx)
            vinculos_xml.append(
                f'<VINCULOS '
                f'SEQUENCIA-HISTORICO="{seq}" '
                f'TIPO-DE-VINCULO="{tipo}" '
                f'ENQUADRAMENTO-FUNCIONAL="{enq}" '
                f'CARGA-HORARIA-SEMANAL="{ch}" '
                f'FLAG-DEDICACAO-EXCLUSIVA="{ded}" '
                f'ANO-INICIO="{ini}" '
                f'ANO-FIM="{fim}" '
                f'OUTRAS-INFORMACOES="{info}" '
                f'OUTRO-VINCULO-INFORMADO="{outro_v}" '
                f'OUTRO-ENQUADRAMENTO-FUNCIONAL-INFORMADO="{outro_e}" '
                f'/>'
            )
        ap_blocks.append(
            f'<ATUACAO-PROFISSIONAL NOME-INSTITUICAO="{inst_name}">'
            f'{"".join(vinculos_xml)}'
            f'</ATUACAO-PROFISSIONAL>'
        )

    xml_content = (
        '<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>\n'
        f'<CURRICULO-VITAE NUMERO-IDENTIFICADOR="{lattes_id}">'
        f'<DADOS-GERAIS NOME-COMPLETO="{full_name}">'
        f'<ATUACOES-PROFISSIONAIS>'
        f'{"".join(ap_blocks)}'
        f'</ATUACOES-PROFISSIONAIS>'
        f'</DADOS-GERAIS>'
        f'</CURRICULO-VITAE>\n'
    )
    xml_path = target_dir / f'{lattes_id}.xml'
    xml_path.write_text(xml_content, encoding='iso-8859-1')
    return xml_path


def _fetch_experiences(pg_test_db: DatabaseHarness) -> list[tuple]:
    return pg_test_db.fetchall(
        """
        SELECT
            r.lattes_id,
            rpe.enterprise,
            rpe.start_year,
            rpe.end_year,
            rpe.employment_type,
            rpe.other_employment_type,
            rpe.functional_classification,
            rpe.other_functional_classification,
            rpe.workload_hours_weekly,
            rpe.exclusive_dedication,
            rpe.additional_info
        FROM public.researcher_professional_experience rpe
        INNER JOIN public.researcher r ON r.id = rpe.researcher_id
        ORDER BY
            r.lattes_id,
            rpe.enterprise,
            rpe.start_year,
            rpe.end_year NULLS FIRST
        """
    )


def test_clean_load_and_anti_cartesian_product(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Valida carga limpa, tipos e ausência de produto cartesiano."""
    pg_test_db.insert_researcher('1111111111111111', 'Alice Silva')
    pg_test_db.insert_researcher('2222222222222222', 'Bruno Souza')

    xml_dir = tmp_path / 'xml_clean'
    xml_dir.mkdir()

    # Alice e Bruno atuam na MESMA instituição (UFBA)
    _write_lattes_xml(
        xml_dir,
        lattes_id='1111111111111111',
        full_name='Alice Silva',
        atuacoes=[
            {
                'instituicao': 'Universidade Federal da Bahia',
                'vinculos': [
                    {
                        'tipo_vinculo': 'SERVIDOR_PUBLICO',
                        'enquadramento': 'Professor Titular',
                        'carga_horaria': '40',
                        'dedicacao_exclusiva': 'SIM',
                        'ano_inicio': '2018',
                        'ano_fim': '',
                        'outras_info': 'Docente permanente',
                        'outro_vinculo': '',
                        'outro_enquadramento': '',
                    }
                ],
            }
        ],
    )
    _write_lattes_xml(
        xml_dir,
        lattes_id='2222222222222222',
        full_name='Bruno Souza',
        atuacoes=[
            {
                'instituicao': 'Universidade Federal da Bahia',
                'vinculos': [
                    {
                        'tipo_vinculo': 'COLABORADOR',
                        'enquadramento': 'LIVRE',
                        'carga_horaria': '',
                        'dedicacao_exclusiva': 'NAO',
                        'ano_inicio': '2020',
                        'ano_fim': '2023',
                        'outras_info': 'Pesquisador visitante',
                        'outro_vinculo': 'Bolsista',
                        'outro_enquadramento': 'Pós-Doc',
                    }
                ],
            }
        ],
    )
    # Pesquisador 3 não está no banco: deve ser ignorado pelo INNER JOIN
    _write_lattes_xml(
        xml_dir,
        lattes_id='9999999999999999',
        full_name='Nao Cadastrado',
        atuacoes=[
            {
                'instituicao': 'Universidade Federal da Bahia',
                'vinculos': [
                    {
                        'ano_inicio': '2015',
                        'ano_fim': '2019',
                    }
                ],
            }
        ],
    )

    result = hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir)
    result.assert_success()

    rows = _fetch_experiences(pg_test_db)
    assert rows == [
        (
            '1111111111111111',
            'Universidade Federal Da Bahia',
            2018,
            None,
            'Servidor_Publico',
            None,
            'Professor Titular',
            None,
            40,
            True,
            'Docente Permanente',
        ),
        (
            '2222222222222222',
            'Universidade Federal Da Bahia',
            2020,
            2023,
            'Colaborador',
            'Bolsista',
            'Livre',
            'Pós-Doc',
            None,
            False,
            'Pesquisador Visitante',
        ),
    ]


def test_idempotency_and_xml_duplicates(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Reprocessar os mesmos XMLs não gera duplicatas."""
    pg_test_db.insert_researcher('1111111111111111', 'Alice Silva')

    xml_dir = tmp_path / 'xml_dup'
    xml_dir.mkdir()
    _write_lattes_xml(
        xml_dir,
        lattes_id='1111111111111111',
        full_name='Alice Silva',
        atuacoes=[
            {
                'instituicao': 'Instituto Federal da Bahia',
                'vinculos': [
                    {
                        'seq': 1,
                        'tipo_vinculo': 'LIVRE',
                        'enquadramento': 'LIVRE',
                        'carga_horaria': '20',
                        'dedicacao_exclusiva': 'NAO',
                        'ano_inicio': '2021',
                        'ano_fim': '2022',
                        'outras_info': 'Atividade 1',
                    },
                    {
                        'seq': 2,
                        'tipo_vinculo': 'LIVRE',
                        'enquadramento': 'LIVRE',
                        'carga_horaria': '20',
                        'dedicacao_exclusiva': 'NAO',
                        'ano_inicio': '2021',
                        'ano_fim': '2022',
                        'outras_info': 'Atividade 1',
                    },
                ],
            }
        ],
    )

    run1 = hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir)
    run1.assert_success()
    rows_after_1 = _fetch_experiences(pg_test_db)
    assert len(rows_after_1) == 1

    run2 = hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir)
    run2.assert_success()
    rows_after_2 = _fetch_experiences(pg_test_db)
    assert rows_after_2 == rows_after_1


def test_update_existing_experience(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Alterações em vínculo existente devem atualizar via Update."""
    pg_test_db.insert_researcher('1111111111111111', 'Alice Silva')

    xml_dir = tmp_path / 'xml_update'
    xml_dir.mkdir()

    _write_lattes_xml(
        xml_dir,
        lattes_id='1111111111111111',
        full_name='Alice Silva',
        atuacoes=[
            {
                'instituicao': 'Universidade Estadual de Santa Cruz',
                'vinculos': [
                    {
                        'tipo_vinculo': 'SERVIDOR_PUBLICO',
                        'enquadramento': 'Professor Adjunto',
                        'carga_horaria': '20',
                        'dedicacao_exclusiva': 'NAO',
                        'ano_inicio': '2019',
                        'ano_fim': '2024',
                        'outras_info': 'Texto Inicial',
                    }
                ],
            }
        ],
    )
    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()

    # Atualiza carga horária, enquadramento, dedicação e outras informações
    _write_lattes_xml(
        xml_dir,
        lattes_id='1111111111111111',
        full_name='Alice Silva',
        atuacoes=[
            {
                'instituicao': 'Universidade Estadual de Santa Cruz',
                'vinculos': [
                    {
                        'tipo_vinculo': 'SERVIDOR_PUBLICO',
                        'enquadramento': 'Professor Titular',
                        'carga_horaria': '40',
                        'dedicacao_exclusiva': 'SIM',
                        'ano_inicio': '2019',
                        'ano_fim': '2024',
                        'outras_info': 'Texto Atualizado',
                    }
                ],
            }
        ],
    )
    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()

    rows = _fetch_experiences(pg_test_db)
    assert rows == [
        (
            '1111111111111111',
            'Universidade Estadual De Santa Cruz',
            2019,
            2024,
            'Servidor_Publico',
            None,
            'Professor Titular',
            None,
            40,
            True,
            'Texto Atualizado',
        )
    ]


def test_sample_lattes_xml_batch_idempotency(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Executa 2x sobre amostra real de XMLs garantindo determinismo."""
    sample_dir = PROJECT_ROOT / 'datasets' / 'lattes_xml'
    sample_xmls = sorted(sample_dir.glob('*.xml'))[:3]
    if not sample_xmls:
        pytest.skip('Sem XMLs de amostra em datasets/lattes_xml')

    xml_dir = tmp_path / 'xml_sample'
    xml_dir.mkdir()
    for p in sample_xmls:
        shutil.copy2(p, xml_dir / p.name)
        pg_test_db.insert_researcher(p.stem, f'Pesquisador {p.stem}')

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    first_snapshot = _fetch_experiences(pg_test_db)
    assert len(first_snapshot) > 0

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    second_snapshot = _fetch_experiences(pg_test_db)
    assert second_snapshot == first_snapshot
