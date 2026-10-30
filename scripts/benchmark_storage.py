"""Bound storage for disposable, private benchmark game copies.

Never follows junctions and never removes a shadercache. Reports, screenshots,
seed fixtures and native/shader caches live outside the disposable game folder.
"""
import os
from pathlib import Path
import re
import shutil
import stat

ROOT = Path(__file__).resolve().parents[1]


def copy_bytes(path):
    total = 0
    stack = [path]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if getattr(info,'st_file_attributes',0) & 0x400 or entry.is_symlink():
                    raise ValueError('Copied benchmark inputs must not contain links: ' + entry.path)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                else:
                    total += info.st_size
    return total


def require_space(output, fixture, prepared=None):
    needed = copy_bytes(fixture/'gamedata') + copy_bytes(fixture/'assets')
    needed += (fixture/'input/EMAIN.ELF').stat().st_size
    if prepared is not None:
        needed += copy_bytes(prepared)
    # Leave space for logs, screenshots, saves and newly learned shader data.
    needed += 2 * 1024**3
    available = shutil.disk_usage(output).free
    if available < needed:
        raise ValueError(f'Benchmark needs {needed/1024**3:.1f} GiB free; only {available/1024**3:.1f} GiB available. No trial copy started.')


def discard_game_copy(game):
    game = game.absolute()
    scratch = (ROOT/'scratch').resolve()
    trial = game.parent
    if (game.name != 'game' or game.resolve() != game or not game.is_relative_to(scratch) or
            not re.fullmatch(r'\d+-(control|prepared)',trial.name) or
            not (trial/'logs').is_dir() or not (trial/'runner.log').is_file()):
        raise ValueError('Refusing cleanup outside an owned private benchmark trial')
    nodes, stack, total = [], [game], 0
    # Validate the entire tree before deleting anything. Reparse points are
    # removed as links, without opening/traversing their targets.
    while stack:
        folder = stack.pop()
        nodes.append((folder,True,False))
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if path.name.casefold() == 'shadercache':
                    raise ValueError('Protected shadercache found; game copy retained')
                if not path.is_relative_to(game):
                    raise ValueError('Cleanup path escapes owned trial')
                link = bool(getattr(info,'st_file_attributes',0)&0x400) or entry.is_symlink()
                directory = bool(getattr(info,'st_file_attributes',0)&0x10) or entry.is_dir(follow_symlinks=False)
                if link:
                    nodes.append((path,directory,True))
                elif directory:
                    stack.append(path)
                else:
                    if path.stat().st_nlink > 1:
                        raise ValueError('Unexpected hard link; game copy retained')
                    nodes.append((path,False,False))
                    total += info.st_size
    for path,directory,link in sorted(nodes,key=lambda x:len(x[0].parts),reverse=True):
        if directory:
            os.rmdir(path)
        else:
            if not link:
                os.chmod(path,stat.S_IREAD|stat.S_IWRITE)
            os.unlink(path)
    return total
