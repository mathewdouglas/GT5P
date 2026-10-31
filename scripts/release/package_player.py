"""Package an already-built BCUS98158 game and native launcher; never build/run them.

Strict allowlist: no game files, saves, cache, settings or local logs are copied.
Run only after the game build has completed. See docs/player-setup.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


def template_files():
    from pipeline_template import read,renderer_contract
    from pipeline_asset_map import read as read_map
    folder=ROOT/'assets/pipeline-templates/gt5p-disc-v2'
    document=read(folder)
    if document['compatibility']['renderer_sha256']!=renderer_contract():
        raise ValueError('Template renderer contract differs from this release')
    wanted={(s,r[s]['sha256'],r[s]['size']) for r in document['records'] for s in ('vp','fp')}
    locations=read_map(folder/'player-map.json')
    if {(r['stage'],r['id'],r['size']) for r in locations['records']}!=wanted:
        raise ValueError('Player location map must cover exactly the bundled programs')
    read_map(folder/'asset-map.json')
    index=json.loads((folder/'index.json').read_text())
    names={'README.md','index.json','asset-map.json','player-map.json'}|{p['file'] for p in index['parts']}
    if {p.name for p in folder.iterdir()}!=names:raise ValueError('Unreviewed template file')
    return {'assets/pipeline-templates/gt5p-disc-v2/'+n:regular(folder/n) for n in names}


def preparation_files(folder):
    manifest=json.loads(regular(folder/'files.json').read_text())
    if (set(manifest)!={'schema','files'} or manifest['schema']!=1 or
            not isinstance(manifest['files'],dict) or not 1<=len(manifest['files'])<=512):
        raise ValueError('Invalid standalone preparer manifest')
    files={};total=0
    required={'GT5P-Prepare.exe','decoder.dll','licenses/Python-LICENSE.txt','licenses/PyInstaller-COPYING.txt'}
    if not required<=manifest['files'].keys():raise ValueError('Incomplete standalone preparer')
    for name,digest in manifest['files'].items():
        if (not isinstance(name,str) or '\\' in name or ':' in name or
                any(p in ('','..','.') for p in name.split('/')) or PurePosixPath(name).is_absolute()):
            raise ValueError('Unsafe preparer filename')
        path=regular(folder/name)
        for parent in path.parents:
            if parent==folder.parent:break
            if parent.is_symlink() or parent.is_junction():raise ValueError('Redirected preparer input')
        if path.suffix.lower() not in ('.exe','.dll','.pyd','.zip','.json','.patch','.txt'):
            raise ValueError('Unreviewed preparer content')
        if not re.fullmatch('[0-9a-f]{64}',digest) or sha(path)!=digest:raise ValueError('Preparer manifest mismatch')
        total+=path.stat().st_size
        if total>128*1024**2:raise ValueError('Standalone preparer exceeds size budget')
        if path.suffix.lower() in ('.exe','.dll','.pyd'):windows_binary(path)
        files['preparation/'+name]=path
    return files


def port_version():
    version = (ROOT / 'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('VERSION must contain a numeric port version, such as 0.1')
    return version


RUNTIME = ('SDL2.dll', 'avcodec-61.dll', 'avutil-59.dll', 'swresample-5.dll')
VC_REQUIRED = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
VC_OPTIONAL = ('msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll',
               'msvcp140_codecvt_ids.dll', 'concrt140.dll')
NOTICES = ('SDL.txt', 'FFmpeg-LGPL.txt', 'FFmpeg-GPL.txt', 'FFmpeg-SOURCE.md',
           'ps3recomp-LICENSE.txt', 'MSVC-NOTICE.txt')


def digest_stream(f):
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(1024 * 1024), b''):
        h.update(chunk)
    return h.hexdigest()


def sha(path):
    with path.open('rb') as f:
        return digest_stream(f)


def regular(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f'Missing file or unexpected link: {path}')
    return path


def windows_binary(path):
    regular(path)
    with path.open('rb') as f:
        dos = f.read(64)
        if len(dos) != 64 or dos[:2] != b'MZ':
            raise ValueError(f'Expected a native Windows binary: {path}')
        offset = int.from_bytes(dos[60:64], 'little')
        if offset > 16 * 1024 * 1024:
            raise ValueError(f'Invalid PE header: {path}')
        f.seek(offset)
        if f.read(6) != b'PE\0\0\x64\x86':
            raise ValueError(f'Expected a Windows x64 PE binary: {path}')
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', required=True, type=Path)
    ap.add_argument('--engine-exe',type=Path,help='Isolated incrementally relinked engine; defaults to build-dir/gt5p.exe')
    ap.add_argument('--launcher-exe', required=True, type=Path)
    ap.add_argument('--preparer-dir', required=True, type=Path)
    ap.add_argument('--elf', required=True, type=Path,
                    help='Matching local EMAIN.ELF; only its SHA-256 enters the ZIP')
    ap.add_argument('--vc-runtime-dir', required=True, type=Path)
    ap.add_argument('--notices-dir', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    version = port_version()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Refusing to overwrite an existing release ZIP')
    cache = regular(args.build_dir / 'CMakeCache.txt').read_text(encoding='utf-8')
    if not re.search(r'^GT5P_TARGET:STRING=BCUS98158$', cache, re.M):
        raise ValueError('The completed build must target BCUS98158')
    if not re.search(r'^CMAKE_BUILD_TYPE:STRING=(Release|RelWithDebInfo)$', cache, re.M):
        raise ValueError('Only completed Release/RelWithDebInfo builds can be packaged')
    elf = regular(args.elf)
    with elf.open('rb') as f:
        header = f.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x02' or header[18:20] != b'\x00\x15':
        raise ValueError('Expected the matching decrypted big-endian PowerPC64 ELF')
    files = {'tourline-prologue.exe': windows_binary(args.launcher_exe),
             'runtime/gt5p.exe': windows_binary(args.engine_exe or args.build_dir / 'gt5p.exe'),
             'LICENSE.txt': regular(ROOT / 'LICENSE'),
             'START-HERE.txt': regular(ROOT / 'launcher/START-HERE.txt'),
             'Change storage.cmd': regular(ROOT / 'launcher/Change storage.cmd'),
             'Prepare shaders.cmd': regular(ROOT / 'launcher/Prepare shaders.cmd')}
    files.update(preparation_files(args.preparer_dir))
    files.update(template_files())
    for name in RUNTIME:
        files['runtime/' + name] = windows_binary(args.build_dir / name)
    for name in VC_REQUIRED:
        files['runtime/' + name] = windows_binary(args.vc_runtime_dir / name)
    for name in VC_OPTIONAL:
        p = args.vc_runtime_dir / name
        if p.exists():
            files['runtime/' + name] = windows_binary(p)
    # Maintainer-provided notices/source information are named explicitly, not a
    # recursive copy of an arbitrary third_party directory or downloaded ZIP.
    for name in NOTICES:
        p = regular(args.notices_dir / name)
        if p.stat().st_size > 256_000 or b'\0' in p.read_bytes():
            raise ValueError(f'Expected a small text notice: {p}')
        files['licenses/' + name] = p
    source_info = files['licenses/FFmpeg-SOURCE.md'].read_text(encoding='utf-8')
    if 'https://' not in source_info:
        raise ValueError('FFmpeg-SOURCE.md must identify the matching source/build information')
    assets = ROOT / 'assets'
    for p in sorted(assets.rglob('*')):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError(f'Asset links are not distributable: {p}')
        if p.is_file():
            if p.relative_to(assets).parts[0]=='pipeline-templates':
                if 'assets/'+p.relative_to(assets).as_posix() not in files:
                    raise ValueError(f'Unreviewed template asset: {p}')
                continue
            if p.suffix.lower() not in ('.png', '.txt'):
                raise ValueError(f'Unreviewed asset extension: {p}')
            with p.open('rb') as f:
                magic = f.read(8)
            if p.suffix.lower() == '.png' and magic != b'\x89PNG\r\n\x1a\n':
                raise ValueError(f'Invalid PNG asset: {p}')
            if p.suffix.lower() == '.txt' and (p.stat().st_size > 256_000 or b'\0' in p.read_bytes()):
                raise ValueError(f'Invalid text asset: {p}')
            files['assets/' + p.relative_to(assets).as_posix()] = p
    if 'assets/glyphs/textures.txt' not in files or 'assets/glyphs/kenney/License.txt' not in files:
        raise ValueError('Glyph manifest or asset license is missing')
    # Bind both local inputs to this release; never include either user's ELF.
    release = ('[release]\nschema=1\ntarget=BCUS98158\nversion=03.00\n'
               f'port_version={version}\n'
               f'elf_sha256={sha(elf)}\ngame_sha256={sha(files["runtime/gt5p.exe"])}\n'
               f'prepare_sha256={sha(files["preparation/GT5P-Prepare.exe"])}\n')
    # Snapshot files before writing, so a build updating the EXE mid-package is
    # detected rather than producing a manifest for a different binary.
    before = {name: (p.stat().st_size, p.stat().st_mtime_ns) for name, p in files.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + '.partial')
    if partial.exists():
        raise ValueError(f'Previous partial package exists: {partial}')
    try:
        with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr('release.ini', release)
            for name, p in files.items():
                z.write(p, name)
                if before[name] != (p.stat().st_size, p.stat().st_mtime_ns):
                    raise ValueError(f'Input changed while packaging; wait for all builds to finish: {p}')
        # Check the ZIP's actual game bytes against the advertised digest too.
        with zipfile.ZipFile(partial) as z:
            with z.open('runtime/gt5p.exe') as f:
                digest = digest_stream(f)
            if digest != re.search(r'game_sha256=(\w+)', release)[1]:
                raise ValueError('Packaged executable differs from the release manifest')
        partial.rename(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    print(f'Created {output}; {len(files) + 1} explicitly selected files, no game data')
    print(f'SHA-256 {sha(output)}')


if __name__ == '__main__':
    main()
