from __future__ import annotations

from .base import AppCommand

class BuildCommand(AppCommand):
    'Build frontend web assets'

    def run(self):
        from ..frontend.build import frontend_build
        frontend_build()

commands = dict(build=BuildCommand)
