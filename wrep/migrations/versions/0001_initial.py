"""Initial

Revision ID: 164b111b7023
Revises: 
Create Date: 2024-05-24 09:39:51.828424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def drop_indexes(table: str, *indexes: str):
    for index in indexes:
        op.drop_index(f'{table}_{index}', table, if_exists=True)

def upgrade() -> None:
    from wrep.backends.orm import Base
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    rewrite_artifactreport = 'artifactreport' in tables
    rewrite_naicsreport = 'naicsreport' in tables
    rewrite_company = 'company' in tables
    artifactreport_tmp = f'artifactreport_{uuid.uuid4().hex[:8]}'
    naicsreport_tmp = f'naicsreport_{uuid.uuid4().hex[:8]}'
    company_tmp = f'company_{uuid.uuid4().hex[:8]}'
    if rewrite_company:
        for col in tables['company'].columns:
            if col.name == 'company':
                company_namecol = 'company'
                break
        else:
            company_namecol = 'name'
    else:
        company_namecol = None

    if 'artifact' in tables:
        drop_indexes('artifact', 'created', 'modified', 'path')
    else:
        op.create_table('artifact',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('path', sa.String(length=2083), nullable=False),
            sa.Column('url', sa.String(length=2083), nullable=False),
            sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('modified', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('mimetype', sa.String(length=255), nullable=False),
            sa.Column('size', sa.BigInteger(), nullable=False),
            sa.Column('sha1', sa.String(length=40), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('path'))

    if 'naics' in tables:
        drop_indexes('naics', 'code', 'title')
    else:
        op.create_table('naics',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('code', sa.String(length=32), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_naics_code'), 'naics', ['code'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_naics_title'), 'naics', ['title'], unique=False, if_not_exists=True)

    if 'report' in tables:
        drop_indexes('company', 'company_norm', 'created', 'reported', 'state')
    else:
        op.create_table('report',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('company', sa.String(length=512), nullable=False),
            sa.Column('company_norm', sa.String(length=512), nullable=False),
            sa.Column('reported', sa.DateTime(timezone=True), nullable=False),
            sa.Column('state', sa.String(length=2), nullable=False),
            sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('location', sa.String(length=255), nullable=True),
            sa.Column('starting', sa.DateTime(timezone=True), nullable=True),
            sa.Column('employees', sa.Integer(), nullable=True),
            sa.Column('action', sa.String(length=64), nullable=True),
            sa.Column('url', sa.String(length=2083), nullable=True),
            sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_report_company'), 'report', ['company'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_report_company_norm'), 'report', ['company_norm'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_report_state'), 'report', ['state'], unique=False, if_not_exists=True)

    if 'statestat' not in tables:
        op.create_table('statestat',
            sa.Column('id', sa.String(length=2), nullable=False),
            sa.Column('last_reported', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reports_count', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('id'))

    if rewrite_artifactreport:
        drop_indexes('artifactreport', 'artifact_id', 'artifact_id_report_id', 'report_id')
        op.execute(f'DROP TABLE IF EXISTS {artifactreport_tmp}')
        op.rename_table('artifactreport', artifactreport_tmp)
    op.create_table('artifactreport',
        sa.Column('artifact_id', sa.Uuid(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['artifact.id']),
        sa.ForeignKeyConstraint(['report_id'], ['report.id']),
        sa.PrimaryKeyConstraint('artifact_id', 'report_id'))
    if rewrite_artifactreport:
        op.execute(
            'INSERT INTO artifactreport (artifact_id, report_id)'
            f'SELECT artifact_id, report_id from {artifactreport_tmp}')
        op.drop_table(artifactreport_tmp)

    if rewrite_naicsreport:
        drop_indexes('naicsreport', 'naics_id', 'naics_id_report_id', 'report_id')
        op.execute(f'DROP TABLE IF EXISTS {naicsreport_tmp}')
        op.rename_table('naicsreport', naicsreport_tmp)
    op.create_table('naicsreport',
        sa.Column('naics_id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['naics_id'], ['naics.id']),
        sa.ForeignKeyConstraint(['report_id'], ['report.id']),
        sa.PrimaryKeyConstraint('naics_id', 'report_id'))
    if rewrite_naicsreport:
        op.execute(
            'INSERT INTO naicsreport (naics_id, report_id)'
            f'SELECT naics_id, report_id from {naicsreport_tmp}')
        op.drop_table(naicsreport_tmp)

    if rewrite_company:
        drop_indexes('company', 'name', 'name_canon', 'name_norm', 'company', 'state')
        op.execute(f'DROP TABLE IF EXISTS {company_tmp}')
        op.rename_table('company', company_tmp)
    company_table = op.create_table('company',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=512), nullable=False),
        sa.Column('name_norm', sa.String(length=512), nullable=False),
        sa.Column('name_canon', sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'))
    op.create_index(op.f('ix_company_name_canon'), 'company', ['name_canon'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_company_name_norm'), 'company', ['name_norm'], unique=False, if_not_exists=True)
    if rewrite_company:
        from wrep.ref import normls
        from wrep.backends.orm import Company
        conn = op.get_bind()
        res = conn.execute(sa.text(f'SELECT {company_namecol} FROM {company_tmp}'))
        recordmap = {}
        for name, in res.fetchall():
            if name not in recordmap:
                recordmap[name] = dict(
                    id=uuid.uuid5(Company.NS, name),
                    name=name,
                    name_norm=normls.company_name_norm(name),
                    name_canon=normls.company_name_canon(name))
        op.bulk_insert(company_table, list(recordmap.values()))
        op.drop_table(company_tmp)

def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('naicsreport')
    op.drop_table('artifactreport')
    op.drop_table('statestat')
    op.drop_index(op.f('ix_report_state'), table_name='report')
    op.drop_index(op.f('ix_report_company_norm'), table_name='report')
    op.drop_index(op.f('ix_report_company'), table_name='report')
    op.drop_table('report')
    op.drop_index(op.f('ix_naics_title'), table_name='naics')
    op.drop_index(op.f('ix_naics_code'), table_name='naics')
    op.drop_table('naics')
    op.drop_index(op.f('ix_company_name_norm'), table_name='company')
    op.drop_index(op.f('ix_company_name_canon'), table_name='company')
    op.drop_table('company')
    op.drop_table('artifact')
    # ### end Alembic commands ###
