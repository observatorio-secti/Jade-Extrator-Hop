"""Camada 2: Testes de integração de ImportAcademicDegree.hpl."""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT, DatabaseHarness

pytestmark = pytest.mark.integration

PIPELINE_RELPATH = 'pipelines/ResearcherData/ImportAcademicDegree.hpl'


def _write_lattes_xml(
    target_dir: Path,
    lattes_id: str,
    full_name: str,
    degrees: list[tuple[str, str]],
) -> Path:
    """Gera um XML Lattes mínimo para testes de titulação acadêmica."""
    degree_tags = ''.join(
        f'<{tag} STATUS-DO-CURSO="{status}" />' for tag, status in degrees
    )
    xml_content = (
        '<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>\n'
        f'<CURRICULO-VITAE NUMERO-IDENTIFICADOR="{lattes_id}">'
        f'<DADOS-GERAIS NOME-COMPLETO="{full_name}">'
        f'<FORMACAO-ACADEMICA-TITULACAO>'
        f'{degree_tags}'
        f'</FORMACAO-ACADEMICA-TITULACAO>'
        f'</DADOS-GERAIS>'
        f'</CURRICULO-VITAE>\n'
    )
    xml_path = target_dir / f'{lattes_id}.xml'
    xml_path.write_text(xml_content, encoding='iso-8859-1')
    return xml_path


def _fetch_graduations(pg_test_db: DatabaseHarness) -> list[tuple]:
    return pg_test_db.fetchall(
        """
        SELECT lattes_id, name, graduation
        FROM public.researcher
        ORDER BY lattes_id
        """
    )


def test_clean_load_and_professional_masters(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Valida maior titulação incluindo mestrado profissional concluído."""
    pg_test_db.insert_researcher('1111111111111111', 'Alice Silva')
    pg_test_db.insert_researcher('2222222222222222', 'Bruno Souza')
    pg_test_db.insert_researcher('3333333333333333', 'Carla Dias')
    pg_test_db.insert_researcher('4444444444444444', 'Daniel Lima')
    pg_test_db.insert_researcher('5555555555555555', 'Elena Costa')
    pg_test_db.insert_researcher('6666666666666666', 'Fabio Alves')

    xml_dir = tmp_path / 'xml_clean'
    xml_dir.mkdir()

    # Apenas graduação concluída -> Graduação
    _write_lattes_xml(
        xml_dir,
        lattes_id='1111111111111111',
        full_name='Alice Silva',
        degrees=[('GRADUACAO', 'CONCLUIDO')],
    )
    # Mestrado profissional concluído + doutorado em andamento -> Mestrado
    _write_lattes_xml(
        xml_dir,
        lattes_id='2222222222222222',
        full_name='Bruno Souza',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('DOUTORADO', 'EM_ANDAMENTO'),
            ('MESTRADO-PROFISSIONALIZANTE', 'CONCLUIDO'),
        ],
    )
    # Mestrado acadêmico concluído -> Mestrado
    _write_lattes_xml(
        xml_dir,
        lattes_id='3333333333333333',
        full_name='Carla Dias',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('MESTRADO', 'CONCLUIDO'),
        ],
    )
    # Doutorado concluído -> Doutorado
    _write_lattes_xml(
        xml_dir,
        lattes_id='4444444444444444',
        full_name='Daniel Lima',
        degrees=[
            ('MESTRADO-PROFISSIONALIZANTE', 'CONCLUIDO'),
            ('DOUTORADO', 'CONCLUIDO'),
        ],
    )
    # Pós-doutorado concluído -> Pós-doutorado
    _write_lattes_xml(
        xml_dir,
        lattes_id='5555555555555555',
        full_name='Elena Costa',
        degrees=[
            ('DOUTORADO', 'CONCLUIDO'),
            ('POS-DOUTORADO', 'CONCLUIDO'),
        ],
    )
    # Especialização concluída + mestrado profissional em andamento
    # -> Especialização
    _write_lattes_xml(
        xml_dir,
        lattes_id='6666666666666666',
        full_name='Fabio Alves',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('ESPECIALIZACAO', 'CONCLUIDO'),
            ('MESTRADO-PROFISSIONALIZANTE', 'EM_ANDAMENTO'),
        ],
    )
    # Pesquisador ausente do banco deve ser ignorado pelo INNER JOIN
    _write_lattes_xml(
        xml_dir,
        lattes_id='9999999999999999',
        full_name='Nao Cadastrado',
        degrees=[('MESTRADO-PROFISSIONALIZANTE', 'CONCLUIDO')],
    )

    result = hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir)
    result.assert_success()

    rows = _fetch_graduations(pg_test_db)
    assert rows == [
        ('1111111111111111', 'Alice Silva', 'Graduação'),
        ('2222222222222222', 'Bruno Souza', 'Mestrado'),
        ('3333333333333333', 'Carla Dias', 'Mestrado'),
        ('4444444444444444', 'Daniel Lima', 'Doutorado'),
        ('5555555555555555', 'Elena Costa', 'Pós-Doutorado'),
        ('6666666666666666', 'Fabio Alves', 'Especialização'),
    ]


def test_idempotency_and_xml_duplicates(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Reprocessar os mesmos XMLs mantém estado idêntico sem duplicatas."""
    pg_test_db.insert_researcher('2222222222222222', 'Bruno Souza')

    xml_dir = tmp_path / 'xml_dup'
    xml_dir.mkdir()
    _write_lattes_xml(
        xml_dir,
        lattes_id='2222222222222222',
        full_name='Bruno Souza',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('MESTRADO-PROFISSIONALIZANTE', 'CONCLUIDO'),
        ],
    )

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    rows_after_1 = _fetch_graduations(pg_test_db)
    assert rows_after_1 == [('2222222222222222', 'Bruno Souza', 'Mestrado')]

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    rows_after_2 = _fetch_graduations(pg_test_db)
    assert rows_after_2 == rows_after_1


def test_update_existing_academic_degree(
    pg_test_db: DatabaseHarness, hop_runner, tmp_path: Path
):
    """Conclusão de mestrado profissional atualiza graduation no banco."""
    pg_test_db.insert_researcher('2222222222222222', 'Bruno Souza')

    xml_dir = tmp_path / 'xml_update'
    xml_dir.mkdir()

    _write_lattes_xml(
        xml_dir,
        lattes_id='2222222222222222',
        full_name='Bruno Souza',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('MESTRADO-PROFISSIONALIZANTE', 'EM_ANDAMENTO'),
        ],
    )
    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    assert _fetch_graduations(pg_test_db) == [
        ('2222222222222222', 'Bruno Souza', 'Graduação')
    ]

    _write_lattes_xml(
        xml_dir,
        lattes_id='2222222222222222',
        full_name='Bruno Souza',
        degrees=[
            ('GRADUACAO', 'CONCLUIDO'),
            ('MESTRADO-PROFISSIONALIZANTE', 'CONCLUIDO'),
        ],
    )
    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    assert _fetch_graduations(pg_test_db) == [
        ('2222222222222222', 'Bruno Souza', 'Mestrado')
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
        root = ET.parse(p).getroot()
        dados_gerais = root.find('DADOS-GERAIS')
        raw_name = (
            dados_gerais.attrib.get('NOME-COMPLETO', '')
            if dados_gerais is not None
            else ''
        )
        normalized_name = raw_name.lower().title()
        pg_test_db.insert_researcher(p.stem, normalized_name)

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    first_snapshot = _fetch_graduations(pg_test_db)
    assert any(row[2] is not None for row in first_snapshot)

    hop_runner(PIPELINE_RELPATH, xml_dir=xml_dir).assert_success()
    second_snapshot = _fetch_graduations(pg_test_db)
    assert second_snapshot == first_snapshot
