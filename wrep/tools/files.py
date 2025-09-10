from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from datetime import tzinfo as TzInfo
from itertools import chain
from pathlib import Path
from typing import Any, Iterator, Self

from .. import SaveType

__all__ = [
    'ArtifactStore',
    'cachectx',
    'digestfile',
    'FileCache',
    'jsoncache',
    'mimetype',
    'mtime']

def digestfile(file: Path) -> Path:
    return file.parent/f'.{file.name}.sha1'

def mimetype(file: Path) -> str:
    return mimetypes.guess_type(file)[0] or 'application/octet-stream'

def mtime(file: Path, *, tz: TzInfo|None = timezone.utc) -> datetime:
    return datetime.fromtimestamp(file.stat().st_mtime, tz=tz)

class FileCache:

    def __init__(self, dir: Path) -> None:
        self.dir = Path(dir)
        self.path = str(self.dir)

    def exists(self, key: str) -> bool:
        return Path(self.dir, key).exists()

    def read(self, key: str):
        with open(self/key, newline="") as infile:
            return infile.read()

    def write(self, key: str, content: str) -> None:
        self.mkpdir(key)
        with open(self/key, 'w', newline='') as file:
            file.write(content)

    def delete(self, *keys: str, glob: bool = False) -> None:
        for key in keys:
            if glob and isinstance(key, str):
                paths = self.glob(key)
            else:
                paths = (self.topath(key),)
            for path in paths:
                path.unlink(missing_ok=True)
    
    def topath(self, key: str) -> Path:
        return Path(self.dir, key)

    def tokey(self, file: Path) -> str:
        return str(self.topath(file).relative_to(self.path))

    def open(self, key: str, *args, **kw):
        return self.topath(key).open(*args, **kw)

    def write_json(self, key: str, obj: Any, **kw) -> None:
        self.mkpdir(key)
        with self.open(key, 'w') as file:
            json.dump(obj, file, **kw)

    def read_json(self, key: str, **kw) -> Any:
        with self.open(key) as file:
            return json.load(file, **kw)

    def glob(self, *globs) -> Iterator[Path]:
        return chain.from_iterable(map(self.dir.glob, globs))

    def nuke(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def mkdir(self, key: str|None = None) -> None:
        self.topath(key or '.').mkdir(parents=True, exist_ok=True)

    def mkpdir(self, key: str) -> None:
        (self/key).parent.mkdir(parents=True, exist_ok=True)

    def subcache(self, key: str) -> Self:
        return type(self)(self/key)

    def __truediv__(self, other: str|Path) -> Path:
        return self.dir/other

class ArtifactStore:

    def __init__(self, dir: Path, src: Path):
        self.dir = dir
        self.src = src
        self.metrics = defaultdict(int)

    def add(self, key: str) -> tuple[SaveType, int]:
        key = key.strip('/')
        file = self.src/key
        dest = self.dir/key
        digfile = digestfile(dest)
        sta = file.stat()
        if dest.exists():
            stb = dest.stat()
            a = (int(sta.st_mtime), sta.st_size)
            b = (int(stb.st_mtime), stb.st_size)
            if a == b:
                save = SaveType.Nochange
            elif a[1] == b[1]:
                with file.open('rb') as f:
                    diga = hashlib.file_digest(f, 'sha1').hexdigest()
                if digfile.exists():
                    digb = digfile.read_text().strip()
                else:
                    with dest.open('rb') as f:
                        digb = hashlib.file_digest(f, 'sha1').hexdigest()
                    digfile.write_text(digb)
                    shutil.copystat(file, digfile)
                if diga == digb:
                    save = SaveType.Nochange
                else:
                    save = SaveType.Update
            else:
                save = SaveType.Update
        else:
            save = SaveType.Create
            dest.parent.mkdir(parents=True, exist_ok=True)
        if save is not save.Nochange:
            digfile.unlink(missing_ok=True)
            shutil.copyfile(file, dest)
            shutil.copystat(file, dest)
            with dest.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha1').hexdigest()
            digfile.write_text(digest)
            shutil.copystat(file, digfile)
            self.metrics['bytes_written'] += sta.st_size
        self.metrics[str(save)] += 1
        self.metrics['total'] += 1
        self.metrics['bytes_total'] += sta.st_size
        return save, sta.st_size

@contextmanager
def cachectx(src: Path, dest: Path):
    sta = src.stat()
    if dest.exists():
        stb = dest.stat()
        if int(sta.st_mtime) == int(stb.st_mtime):
            yield dest
            return
    dest.parent.mkdir(parents=True, exist_ok=True)
    yield
    shutil.copystat(src, dest)

@contextmanager
def jsoncache(src: Path, dest: Path):
    with cachectx(src, dest) as saved:
        if saved:
            with saved.open() as f:
                saved = json.load(f)
        yield saved