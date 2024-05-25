from __future__ import annotations

from . import utils

class Command(utils.BaseCommand):

    def run(self):
        from .backends import orm
        orm.migrate()

if __name__ == '__main__':
    Command.main()
