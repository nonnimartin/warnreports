from __future__ import annotations

import glob
import shutil
from typing import Iterator

from .. import settings, utils

logger = utils.get_logger('frontend')

class FrontentBuilder:

    def __init__(self) -> None:
        import jinja2
        self.src = settings.FRONTEND_SRC
        self.dist = settings.FRONTEND_DIST
        self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(self.src))

    async def build(self) -> None:
        await self.clean()
        await self.init()
        await self.copy_assets()
        await self.build_html()
        await self.build_scss()

    async def clean(self) -> None:
        if self.dist.exists():
            shutil.rmtree(self.dist)

    async def init(self) -> None:
        self.dist.mkdir(parents=True, exist_ok=True)

    async def copy_assets(self) -> None:
        for path in self.glob('**/*.js', '**/*.css'):
            dest = self.dist/'assets'/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.src/path, dest)

    async def build_html(self) -> None:
        from ..routers.frontend import routes
        htmltmpl = self.jinja.get_template('frontend.jinja')
        for routepath in dict.fromkeys(routes.values()):
            htmlpath = f'{routepath[1:]}.html'
            logger.info(f'building {htmlpath}')
            htmldest = self.dist/htmlpath
            htmldest.parent.mkdir(parents=True, exist_ok=True)
            htmldest.write_text(htmltmpl.render(path=routepath))

    async def build_scss(self) -> None:
        import sass
        context = dict(bootstrap_dir=settings.BOOTSTRAP_DIR)
        for path in self.glob('**/*.scss'):
            base = path.removesuffix('.scss')
            logger.info(f'Building {base}.css')
            tmpl = self.jinja.get_template(path)
            content = tmpl.render(context)
            dest = self.dist/'assets'/f'{base}.css'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(sass.compile(string=content))
            logger.info(f'Building {base}.min.css')
            dest = self.dist/'assets'/f'{base}.min.css'
            dest.write_text(sass.compile(string=content, output_style='compressed'))

    def glob(self, *globs: str) -> Iterator[str]:
        for pat in globs:
            yield from glob.glob(pat, root_dir=self.src, recursive=True)

async def frontend_build() -> None:
    'Build frontend web assets'
    await FrontentBuilder().build()

class Command(utils.BaseCommand):
    commands = dict(build=utils.FuncCommand(frontend_build))
