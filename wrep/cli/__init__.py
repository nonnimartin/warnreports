from __future__ import annotations

from . import etl, frontend, migrations, orm, pipeline, search
from .base import BaseCommand

__all__ = [
    'Command',
    'etl',
    'frontend',
    'migrations',
    'orm',
    'pipeline',
    'search']

class Command(BaseCommand):
    prog = __package__
    commands = dict(
        pipeline=pipeline.Command,
        search=search.Command,
        migrations=migrations.Command,
        etl=etl.Command,
        orm=orm.Command,
        frontend=frontend.Command)
