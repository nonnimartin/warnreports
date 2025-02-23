from __future__ import annotations

from ..frontend.build import frontend_build
from .base import AppCommand, BaseCommand, FuncCommand


class Command(BaseCommand):
    commands = dict(build=FuncCommand(frontend_build, AppCommand))
