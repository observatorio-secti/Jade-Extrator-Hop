"""Camada 1: Validação estática de integridade estrutural de .hpl e .hwf."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT, get_all_hpl_paths, get_all_hwf_paths

pytestmark = pytest.mark.static

HPL_PATHS = get_all_hpl_paths()
HWF_PATHS = get_all_hwf_paths()


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


@pytest.mark.parametrize('hpl_path', HPL_PATHS, ids=_rel)
def test_hpl_hops_and_error_handling_reference_existing_transforms(
    hpl_path: Path,
):
    """Todo hop e error handler deve apontar para transforms válidos."""
    root = ET.parse(hpl_path).getroot()
    transforms = {t.findtext('name'): t for t in root.findall('transform')}
    assert transforms, f'Pipeline {_rel(hpl_path)} não possui transforms'

    for hop in root.findall('./order/hop'):
        src = hop.findtext('from')
        dst = hop.findtext('to')
        assert src in transforms, (
            f'{_rel(hpl_path)}: hop <from>{src}</from> não existe'
        )
        assert dst in transforms, (
            f'{_rel(hpl_path)}: hop <to>{dst}</to> não existe'
        )

    for err in root.findall('./transform_error_handling/error'):
        src = err.findtext('source_transform')
        tgt = err.findtext('target_transform')
        assert src in transforms, (
            f'{_rel(hpl_path)}: source_transform "{src}" não existe'
        )
        if tgt:
            assert tgt in transforms, (
                f'{_rel(hpl_path)}: target_transform "{tgt}" não existe'
            )


@pytest.mark.parametrize('hpl_path', HPL_PATHS, ids=_rel)
def test_hpl_rdbms_connections_exist_in_metadata(
    hpl_path: Path, valid_rdbms_connections: set[str]
):
    """Toda conexão RDBMS usada deve existir em metadata/rdbms/."""
    root = ET.parse(hpl_path).getroot()
    used_connections = {
        el.text.strip()
        for el in root.findall('.//connection')
        if el.text and el.text.strip()
    }
    invalid = used_connections - valid_rdbms_connections
    assert not invalid, (
        f'{_rel(hpl_path)} usa conexões inexistentes: {sorted(invalid)}. '
        f'Válidas: {sorted(valid_rdbms_connections)}'
    )


@pytest.mark.parametrize('hpl_path', HPL_PATHS, ids=_rel)
def test_hpl_active_get_file_names_use_datasets_folder(hpl_path: Path):
    """Transforms GetFileNames ativos devem ler da pasta datasets/."""
    root = ET.parse(hpl_path).getroot()
    transforms = {t.findtext('name'): t for t in root.findall('transform')}
    active_sources = {
        h.findtext('from')
        for h in root.findall('./order/hop')
        if h.findtext('enabled') == 'Y'
    }

    for name, transform in transforms.items():
        if (
            transform.findtext('type') == 'GetFileNames'
            and name in active_sources
        ):
            paths = [
                el.text.strip()
                for el in transform.findall('./file/name')
                if el.text and el.text.strip()
            ]
            assert paths, (
                f'{_rel(hpl_path)}: GetFileNames "{name}" sem caminho definido'
            )
            for p in paths:
                assert p.startswith('${PROJECT_HOME}/datasets/'), (
                    f'{_rel(hpl_path)}: GetFileNames "{name}" aponta para '
                    f'caminho fora de datasets/: {p}'
                )


@pytest.mark.parametrize('hpl_path', HPL_PATHS, ids=_rel)
def test_hpl_merge_joins_have_matching_sorted_inputs(hpl_path: Path):
    """Todo MergeJoin ativo deve receber SortRows ordenados pelas chaves."""
    root = ET.parse(hpl_path).getroot()
    transforms = {t.findtext('name'): t for t in root.findall('transform')}
    active_sources = {
        h.findtext('from')
        for h in root.findall('./order/hop')
        if h.findtext('enabled') == 'Y'
    }

    for name, transform in transforms.items():
        if (
            transform.findtext('type') != 'MergeJoin'
            or name not in active_sources
        ):
            continue

        t1_name = transform.findtext('transform1')
        t2_name = transform.findtext('transform2')
        assert t1_name in transforms, (
            f'{_rel(hpl_path)}: MergeJoin "{name}" referencia '
            f'transform1 inexistente "{t1_name}"'
        )
        assert t2_name in transforms, (
            f'{_rel(hpl_path)}: MergeJoin "{name}" referencia '
            f'transform2 inexistente "{t2_name}"'
        )

        t1 = transforms[t1_name]
        t2 = transforms[t2_name]
        assert t1.findtext('type') == 'SortRows', (
            f'{_rel(hpl_path)}: transform1 "{t1_name}" de "{name}" '
            'deve ser SortRows'
        )
        assert t2.findtext('type') == 'SortRows', (
            f'{_rel(hpl_path)}: transform2 "{t2_name}" de "{name}" '
            'deve ser SortRows'
        )

        k1 = [k.text for k in transform.findall('./keys_1/key') if k.text]
        k2 = [k.text for k in transform.findall('./keys_2/key') if k.text]
        assert k1, f'{_rel(hpl_path)}: MergeJoin "{name}" sem keys_1'
        assert len(k1) == len(k2), (
            f'{_rel(hpl_path)}: MergeJoin "{name}" com chaves incompatíveis: '
            f'keys_1={k1}, keys_2={k2}'
        )

        s1 = [f.findtext('name') for f in t1.findall('./fields/field')]
        s2 = [f.findtext('name') for f in t2.findall('./fields/field')]
        assert s1[: len(k1)] == k1, (
            f'{_rel(hpl_path)}: SortRows "{t1_name}" ordena {s1}, '
            f'mas MergeJoin "{name}" exige prefixo {k1}'
        )
        assert s2[: len(k2)] == k2, (
            f'{_rel(hpl_path)}: SortRows "{t2_name}" ordena {s2}, '
            f'mas MergeJoin "{name}" exige prefixo {k2}'
        )


@pytest.mark.parametrize('hpl_path', HPL_PATHS, ids=_rel)
def test_hpl_xml_streams_do_not_join_without_researcher_identifier(
    hpl_path: Path,
):
    """Proíbe MergeJoin entre fluxos XML sem identificador de pesquisador."""
    root = ET.parse(hpl_path).getroot()
    transforms = {t.findtext('name'): t for t in root.findall('transform')}
    preds: dict[str, set[str]] = {name: set() for name in transforms}

    for hop in root.findall('./order/hop'):
        if hop.findtext('enabled') == 'Y':
            src, dst = hop.findtext('from'), hop.findtext('to')
            if src in transforms and dst in transforms:
                preds[dst].add(src)

    def has_ancestor_type(
        node: str, target_type: str, visited: set[str] | None = None
    ) -> bool:
        if visited is None:
            visited = set()
        if node in visited:
            return False
        visited.add(node)
        if transforms[node].findtext('type') == target_type:
            return True
        return any(
            has_ancestor_type(p, target_type, visited) for p in preds[node]
        )

    active_sources = {
        h.findtext('from')
        for h in root.findall('./order/hop')
        if h.findtext('enabled') == 'Y'
    }
    id_keys = {
        'NUMERO-IDENTIFICADOR',
        'IDENTIFICADOR',
        'lattes_id',
        'researcher_id',
    }

    for name, transform in transforms.items():
        if (
            transform.findtext('type') != 'MergeJoin'
            or name not in active_sources
        ):
            continue
        t1 = transform.findtext('transform1') or ''
        t2 = transform.findtext('transform2') or ''
        both_from_xml_only = (
            has_ancestor_type(t1, 'getXMLData')
            and not has_ancestor_type(t1, 'TableInput')
            and has_ancestor_type(t2, 'getXMLData')
            and not has_ancestor_type(t2, 'TableInput')
        )
        if both_from_xml_only:
            k1 = {k.text for k in transform.findall('./keys_1/key') if k.text}
            k2 = {k.text for k in transform.findall('./keys_2/key') if k.text}
            has_id_key = bool((k1 & id_keys) and (k2 & id_keys))
            assert has_id_key, (
                f'{_rel(hpl_path)}: MergeJoin "{name}" une dois fluxos XML '
                f'sem identificador de pesquisador (produto cartesiano!): '
                f'keys_1={sorted(k1)}, keys_2={sorted(k2)}'
            )


@pytest.mark.parametrize('hwf_path', HWF_PATHS, ids=_rel)
def test_hwf_hops_and_referenced_files_exist(hwf_path: Path):
    """Todo workflow deve referenciar actions e arquivos existentes."""
    root = ET.parse(hwf_path).getroot()
    actions = {a.findtext('name'): a for a in root.findall('./actions/action')}
    assert actions, f'Workflow {_rel(hwf_path)} não possui actions'

    for hop in root.findall('./hops/hop'):
        src = hop.findtext('from')
        dst = hop.findtext('to')
        assert src in actions, (
            f'{_rel(hwf_path)}: hop <from>{src}</from> não existe'
        )
        assert dst in actions, (
            f'{_rel(hwf_path)}: hop <to>{dst}</to> não existe'
        )

    for name, action in actions.items():
        filename = action.findtext('filename')
        if filename and filename.startswith('${PROJECT_HOME}/'):
            rel_target = filename.removeprefix('${PROJECT_HOME}/')
            target_path = PROJECT_ROOT / rel_target
            assert target_path.exists(), (
                f'{_rel(hwf_path)}: action "{name}" aponta para arquivo '
                f'inexistente: {rel_target}'
            )


def test_import_professional_experience_static_contract():
    """Contrato estático da pipeline ImportProfessionalExperience."""
    hpl_path = (
        PROJECT_ROOT
        / 'pipelines'
        / 'ResearcherData'
        / 'ImportProfessionalExperience.hpl'
    )
    root = ET.parse(hpl_path).getroot()
    transforms = {t.findtext('name'): t for t in root.findall('transform')}

    # 1. Apenas 1 leitor getXMLData (sem leitura dupla + Merge join 2)
    xml_readers = [
        name
        for name, t in transforms.items()
        if t.findtext('type') == 'getXMLData'
    ]
    assert len(xml_readers) == 1, (
        f'Esperado apenas 1 transform getXMLData, encontrado(s): {xml_readers}'
    )

    xml_reader = transforms[xml_readers[0]]
    assert xml_reader.findtext('encoding') == 'ISO-8859-1', (
        'getXMLData deve usar encoding ISO-8859-1 para currículos Lattes'
    )
    xml_fields = {
        f.findtext('name'): f.findtext('type')
        for f in xml_reader.findall('./fields/field')
    }
    for int_field in ('ANO-INICIO', 'ANO-FINAL', 'CARGA-HORARIA-SEMANAL'):
        assert xml_fields.get(int_field) == 'Integer', (
            f'Campo {int_field} em getXMLData deve ser Integer, '
            f'atual: {xml_fields.get(int_field)}'
        )

    # 2. Select to create e Select to update convertem FLAG-DEDICACAO-EXCLUSIVA
    # para Boolean via <meta> (evita ClassCastException no transform Update)
    for sel_name in ('Select to create', 'Select to update'):
        sel = transforms.get(sel_name)
        assert sel is not None, f'Transform "{sel_name}" deve existir'
        metas = {
            m.findtext('name'): m.findtext('type')
            for m in sel.findall('./fields/meta')
        }
        assert metas.get('FLAG-DEDICACAO-EXCLUSIVA') == 'Boolean', (
            f'Transform "{sel_name}" deve converter FLAG-DEDICACAO-EXCLUSIVA '
            'para Boolean em <fields><meta>'
        )

    # 3. Sort rows 2 e Sort professional_experience devem ter unique_rows=Y
    for sort_name in ('Sort rows 2', 'Sort professional_experience '):
        st = transforms.get(sort_name)
        assert st is not None, f'Transform "{sort_name}" deve existir'
        assert st.findtext('unique_rows') == 'Y', (
            f'Transform "{sort_name}" deve ter <unique_rows>Y</unique_rows>'
        )

    # 4. Update deve usar batch
    upd = transforms.get('Update')
    assert upd is not None, 'Transform "Update" deve existir'
    assert upd.findtext('use_batch') == 'Y', (
        'Transform "Update" deve ter <use_batch>Y</use_batch>'
    )

    # 5. Deve estar integrada em workflows/ImportResearcherData.hwf
    hwf_path = PROJECT_ROOT / 'workflows' / 'ImportResearcherData.hwf'
    hwf_root = ET.parse(hwf_path).getroot()
    action_files = {
        a.findtext('filename') for a in hwf_root.findall('./actions/action')
    }
    assert (
        '${PROJECT_HOME}/pipelines/ResearcherData/'
        'ImportProfessionalExperience.hpl'
    ) in action_files, (
        'ImportProfessionalExperience.hpl deve estar registrada em '
        'ImportResearcherData.hwf'
    )
