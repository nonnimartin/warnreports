from __future__ import annotations

from . import etl, frontend, migrations, orm, pipeline, search
from .base import BaseCommand

__all__ = ['Command']

class Command(BaseCommand):
    prog = __package__.rsplit('.', 1)[0]
    commands = dict(
        pipeline=pipeline.Command,
        search=search.commands,
        migrations=migrations.commands,
        etl=etl.commands,
        orm=orm.commands,
        frontend=frontend.commands)
