from __future__ import annotations

from . import frontend, migrations, orm, pipeline, search, utils


class Command(utils.BaseCommand):
    prog = __package__
    commands = dict(
        pipeline=pipeline.Command,
        search=search.Command,
        migrations=migrations.Command,
        orm=orm.Command,
        frontend=frontend.Command)

if __name__ == '__main__':
    Command.main()
