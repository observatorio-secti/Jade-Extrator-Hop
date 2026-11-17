"""Fixtures compartilhadas para as Camadas 1 e 2 de testes."""

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ADMIN_DSN = os.environ.get(
    'TEST_PG_ADMIN_DSN',
    'postgresql://postgres:postgres@localhost:5432/postgres',
)
DEFAULT_HOP_IMAGE = os.environ.get('TEST_HOP_IMAGE', 'apache/hop:latest')

BASE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.researcher (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    lattes_id CHAR(16) NOT NULL UNIQUE,
    graduation VARCHAR
);

CREATE TABLE public.researcher_professional_experience (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    researcher_id UUID NOT NULL
        REFERENCES public.researcher(id) ON DELETE CASCADE,
    enterprise VARCHAR NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER,
    employment_type VARCHAR,
    other_employment_type VARCHAR,
    functional_classification VARCHAR,
    other_functional_classification VARCHAR,
    workload_hours_weekly INTEGER,
    exclusive_dedication BOOLEAN,
    additional_info TEXT
);
"""


def get_all_hpl_paths() -> list[Path]:
    return sorted((PROJECT_ROOT / 'pipelines').rglob('*.hpl'))


def get_all_hwf_paths() -> list[Path]:
    return sorted((PROJECT_ROOT / 'workflows').rglob('*.hwf'))


@pytest.fixture(scope='session')
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope='session')
def valid_rdbms_connections() -> set[str]:
    rdbms_dir = PROJECT_ROOT / 'metadata' / 'rdbms'
    names: set[str] = set()
    for p in rdbms_dir.glob('*.json'):
        data = json.loads(p.read_text(encoding='utf-8'))
        if 'name' in data:
            names.add(data['name'])
    return names


@dataclass
class DatabaseHarness:
    """Helper de acesso ao banco PostgreSQL isolado do teste."""

    dsn: str
    jdbc_url: str
    db_name: str

    def execute(self, sql: str, params=None) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql, params)

    def fetchall(self, sql: str, params=None) -> list[tuple]:
        with psycopg.connect(self.dsn) as conn:
            return conn.execute(sql, params).fetchall()

    def insert_researcher(self, lattes_id: str, name: str) -> str:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            row = conn.execute(
                'INSERT INTO public.researcher (lattes_id, name) '
                'VALUES (%s, %s) RETURNING id::text',
                (lattes_id, name),
            ).fetchone()
            assert row is not None
            return row[0]


def _dsn_to_jdbc(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 5432
    db = parsed.path.lstrip('/')
    user = parsed.username or 'postgres'
    password = parsed.password or 'postgres'
    return (
        f'jdbc:postgresql://{host}:{port}/{db}?user={user}&password={password}'
    )


@pytest.fixture
def pg_test_db(request) -> DatabaseHarness:
    """Cria um database PostgreSQL efêmero e isolado para cada teste."""
    base_dsn = DEFAULT_ADMIN_DSN.rsplit('/', 1)[0]
    slug = re.sub(r'[^a-z0-9_]', '_', request.node.name.lower())[:28]
    short_id = uuid.uuid4().hex[:6]
    db_name = f'jade_hop_test_{slug}_{short_id}'

    with psycopg.connect(DEFAULT_ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')

    test_dsn = f'{base_dsn}/{db_name}'
    try:
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            conn.execute(BASE_SCHEMA_SQL)

        yield DatabaseHarness(
            dsn=test_dsn,
            jdbc_url=_dsn_to_jdbc(test_dsn),
            db_name=db_name,
        )
    finally:
        with psycopg.connect(DEFAULT_ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                'WHERE datname = %s AND pid <> pg_backend_pid()',
                (db_name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


@dataclass
class HopRunResult:
    """Resultado da execução headless de uma pipeline ou workflow no Hop."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return f'{self.stdout}\n{self.stderr}'

    def assert_success(self) -> None:
        has_hop_error = bool(
            re.search(r' - ERROR[: ]', self.combined_output)
            or 'Finished with errors' in self.combined_output
        )
        if self.returncode != 0 or has_hop_error:
            pytest.fail(
                f'Execução do Apache Hop falhou (exit={self.returncode}):\n'
                f'{self.combined_output}'
            )


@pytest.fixture(scope='session')
def hop_session_env(tmp_path_factory):
    """Inicia um container Hop de sessão e registra o projeto uma única vez."""
    (PROJECT_ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / 'datasets' / 'lattes_xml').mkdir(
        parents=True, exist_ok=True
    )
    session_dir = tmp_path_factory.mktemp('hop_session')
    xml_mount_dir = session_dir / 'lattes_xml'
    xml_mount_dir.mkdir(parents=True, exist_ok=True)

    # Remove o shadowing de DATABASE_URL do project-config.json dentro do
    # container de teste para que o banco de cada teste prevaleça.
    raw_cfg = json.loads(
        (PROJECT_ROOT / 'project-config.json').read_text(encoding='utf-8')
    )
    raw_cfg.setdefault('config', {})['variables'] = []
    test_project_cfg = session_dir / 'project-config.json'
    test_project_cfg.write_text(
        json.dumps(raw_cfg, indent=2), encoding='utf-8'
    )

    container_name = f'jade_hop_test_runner_{uuid.uuid4().hex[:8]}'
    start_cmd = [
        'docker',
        'run',
        '-d',
        '--rm',
        '--name',
        container_name,
        '--network',
        'host',
        '-e',
        'HOP_OPTIONS=-XX:MaxRAMPercentage=70 -XX:+ExitOnOutOfMemoryError',
        '-v',
        f'{PROJECT_ROOT}:/files/jade-extrator:ro',
        '-v',
        f'{test_project_cfg}:/files/jade-extrator/project-config.json:ro',
        '-v',
        f'{xml_mount_dir}:/files/jade-extrator/datasets/lattes_xml',
        '--tmpfs',
        '/files/jade-extrator/logs:rw,mode=1777',
        '--entrypoint',
        'sleep',
        DEFAULT_HOP_IMAGE,
        'infinity',
    ]
    subprocess.run(start_cmd, check=True, capture_output=True, text=True)

    try:
        reg_cmd = [
            'docker',
            'exec',
            container_name,
            '/opt/hop/hop-conf.sh',
            '--project=Jade-Extrator',
            '--project-create',
            '--project-home=/files/jade-extrator',
            '--project-config-file=project-config.json',
            '--project-keep-config-file',
        ]
        subprocess.run(reg_cmd, check=True, capture_output=True, text=True)
        yield container_name, xml_mount_dir, test_project_cfg
    finally:
        subprocess.run(
            ['docker', 'rm', '-f', container_name],
            check=False,
            capture_output=True,
        )


@pytest.fixture
def hop_runner(pg_test_db: DatabaseHarness, hop_session_env):
    """Executa pipelines/workflows via docker exec no container de sessão."""
    container_name, xml_mount_dir, test_project_cfg = hop_session_env

    def _run(
        relative_target: str,
        xml_dir: Path | None = None,
        log_level: str = 'Basic',
        timeout: int = 120,
    ) -> HopRunResult:
        raw_cfg = json.loads(
            (PROJECT_ROOT / 'project-config.json').read_text(encoding='utf-8')
        )
        raw_cfg.setdefault('config', {})['variables'] = [
            {'name': 'DATABASE_URL', 'value': pg_test_db.jdbc_url}
        ]
        test_project_cfg.write_text(
            json.dumps(raw_cfg, indent=2), encoding='utf-8'
        )

        for existing in xml_mount_dir.glob('*'):
            if existing.is_file() or existing.is_symlink():
                existing.unlink()
            elif existing.is_dir():
                shutil.rmtree(existing)

        if xml_dir is not None:
            for src in xml_dir.glob('*.xml'):
                shutil.copy2(src, xml_mount_dir / src.name)

        cmd = [
            'docker',
            'exec',
            '-e',
            f'DATABASE_URL={pg_test_db.jdbc_url}',
            container_name,
            '/opt/hop/hop-run.sh',
            '-j',
            'Jade-Extrator',
            '-r',
            'local',
            '-l',
            log_level,
            '-f',
            f'/files/jade-extrator/{relative_target}',
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return HopRunResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    return _run
