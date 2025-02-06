from __future__ import annotations

import glob
import shutil

from .. import settings, utils

logger = utils.get_logger('frontend')

class FrontentBuilder:
    def __init__(self):
        import jinja2
        import sass

        from ..routers.frontend import routes
        self.routepaths = set(routes.values())
        self.src = settings.FRONTEND_SRC
        self.dist = settings.FRONTEND_DIST
        self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(self.src))
        self.scss_context = dict(bootstrap_dir=settings.BOOTSTRAP_DIR)
        self.sass = sass

    async def build(self):
        await self.clean()
        self.dist.mkdir(parents=True, exist_ok=True)
        htmltmpl = self.jinja.get_template('frontend.jinja')
        for path in self.glob('**/*.js', '**/*.css'):
            dest = self.dist/'assets'/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.src/path, dest)
            if path.endswith('.js'):
                routepath = '/' + path.removesuffix('.js').removeprefix('js/')
                if routepath in self.routepaths:
                    htmlpath = f'{routepath[1:]}.html'
                    logger.info(f'building {htmlpath}')
                    htmldest = self.dist/htmlpath
                    htmldest.parent.mkdir(parents=True, exist_ok=True)
                    htmldest.write_text(htmltmpl.render(path=routepath))
        for path in self.glob('**/*.scss'):
            logger.info(f'Building {path}')
            tmpl = self.jinja.get_template(path)
            content = tmpl.render(self.scss_context)
            base = path.removesuffix('.scss')
            dest = self.dist/'assets'/f'{base}.css'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(self.sass.compile(string=content))
            dest = self.dist/'assets'/f'{base}.min.css'
            dest.write_text(self.sass.compile(string=content, output_style='compressed'))

    async def clean(self):
        if self.dist.exists():
            shutil.rmtree(self.dist)

    def glob(self, *globs: str):
        for pat in globs:
            yield from glob.glob(pat, root_dir=self.src, recursive=True)

async def frontend_build():
    'Build frontend web assets'
    await FrontentBuilder().build()


class Command(utils.BaseCommand):
    commands = dict(build=utils.FuncCommand(frontend_build))
