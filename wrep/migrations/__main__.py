from __future__ import annotations

from .. import utils

from . import migrate, auto

actions = dict(migrate=migrate, auto=auto)

class Command(utils.BaseCommand):

    @classmethod
    def add_subparsers(cls, subparsers):
        subparsers.add_parser('migrate')
        subparsers.add_parser('auto').add_argument('--message', '-m', default='auto')

    def run(self):
        actions[self.subparser](**vars(self.opts))

if __name__ == '__main__':
    Command.main()
