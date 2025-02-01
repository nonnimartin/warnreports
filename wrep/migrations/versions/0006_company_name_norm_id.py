"""company_name_norm_id

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-31 15:43:06.320160

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = '0005'


def upgrade() -> None:
    import uuid

    from sqlalchemy.orm import Session
    
    from wrep.orm import Company, Report
    from wrep.ref import normls
    op.add_column('company', sa.Column('name_norm_id', sa.UUID(), nullable=True))
    op.add_column('report', sa.Column('company_norm_id', sa.UUID(), nullable=True))
    conn = op.get_bind()
    if type(conn).__name__ != 'MockConnection':
        with Session(conn) as session:
            for company in session.scalars(sa.select(Company)):
                company.name_norm_id = uuid.uuid5(Company.NS, company.name_norm)
                session.add(company)
            session.commit()
            for report in session.scalars(sa.select(Report)):
                name_norm = getattr(report, 'company_norm', None) or normls.company_name_norm(report.company)
                report.company_norm_id = uuid.uuid5(Company.NS, name_norm)
                session.add(report)
            session.commit()
    op.alter_column('company', 'name_norm_id', nullable=False)
    op.create_index(op.f('ix_report_company_norm_id'), 'report', ['company_norm_id'], unique=False)
    op.alter_column('report', 'company_norm_id', nullable=False)
    op.create_index(op.f('ix_company_name_norm_id'), 'company', ['name_norm_id'], unique=False)
    op.drop_index('ix_report_company_norm', table_name='report')
    op.drop_column('report', 'company_norm')
    # ### end Alembic commands ###


def downgrade() -> None:
    from sqlalchemy.sql import table, column
    from sqlalchemy import String, UUID
    from sqlalchemy.orm import Session   
    from wrep.orm import Report
    from wrep.ref import normls
    conn = op.get_bind()
    op.add_column('report', sa.Column('company_norm', sa.VARCHAR(length=512), autoincrement=False, nullable=True))
    tbl = table('report', column('id', UUID()), column('company_norm', String(512)))
    if type(conn).__name__ != 'MockConnection':
        with Session(conn) as session:
            for report in session.scalars(sa.select(Report)):
                op.execute(tbl.update().where(tbl.c.id == report.id).values({'company_norm': op.inline_literal(normls.company_name_norm(report.company))}))
    op.alter_column('report', 'company_norm', nullable=False)
    op.create_index('ix_report_company_norm', 'report', ['company_norm'], unique=False)
    op.drop_index(op.f('ix_company_name_norm_id'), table_name='company')
    op.drop_column('company', 'name_norm_id')
    op.drop_index(op.f('ix_report_company_norm_id'), table_name='report')
    op.drop_column('report', 'company_norm_id')
    # ### end Alembic commands ###
