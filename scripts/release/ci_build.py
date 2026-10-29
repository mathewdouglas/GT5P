"""Build a fresh self-hosted checkout using private, pre-provisioned local inputs.

Never point GITHUB_WORKSPACE at a development checkout. See docs/local-release-ci.md.
No decryption/download of game files, game launch, repository push or release publishing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def copy_file(source, destination):
    if not source.is_file() or source.is_symlink():
        raise ValueError(f'Missing private build input or unexpected link: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True, type=Path)
    args = ap.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve() != ROOT:
        raise ValueError('Run only inside the dedicated GitHub Actions checkout')
    if os.environ.get('GITHUB_REPOSITORY') != 'mathewdouglas/GT5P' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Only the trusted origin main branch may build a release')
    if os.environ.get('VSCMD_ARG_TGT_ARCH', '').lower() != 'x64':
        raise ValueError('An x64 VS compiler environment is required')
    sha = os.environ['GITHUB_SHA']
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid build commit')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if actual != sha:
        raise ValueError('Checkout does not match the triggering commit')
    version = (ROOT/'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Invalid port VERSION')
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    paths = {key: Path(cfg[key]).resolve() for key in ('private_inputs', 'runtime_cache', 'vc_runtime_dir', 'notices_dir')}
    for path in paths.values():
        if path == ROOT or ROOT in path.parents or path in ROOT.parents:
            raise ValueError('Private inputs/runtime/notices must be separate from the runner checkout')
    jobs = int(cfg.get('parallel_jobs', 2))
    if jobs < 1 or jobs > 4:
        raise ValueError('parallel_jobs must be 1..4 (2 recommended for 16 GB)')
    for name in ('SDL.txt', 'FFmpeg-LGPL.txt', 'FFmpeg-GPL.txt', 'FFmpeg-SOURCE.md',
                 'ps3recomp-LICENSE.txt', 'MSVC-NOTICE.txt'):
        if not (paths['notices_dir']/name).is_file():
            raise ValueError(f'Prepare dependency notices before enabling CI: {name}')
    for name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
        if not (paths['vc_runtime_dir']/name).is_file():
            raise ValueError(f'Missing app-local MSVC redistributable: {name}')
    # Refuse the development trees and any stale ignored build outputs rather
    # than deleting them here. actions/checkout cleans its own dedicated workspace.
    for name in ('generated', 'build', 'input', 'analysis', 'third_party', 'out'):
        if (ROOT/name).exists():
            raise ValueError(f'Expected a fresh runner checkout; {name}/ already exists')
    run(sys.executable, 'scripts/check_no_game_files.py', '--tracked')
    seed = paths['private_inputs']
    if not (seed/'CI-INPUTS.txt').is_file():
        raise ValueError('Private input directory must contain the CI-INPUTS.txt marker')
    copy_file(seed/'input/EMAIN.ELF', ROOT/'input/EMAIN.ELF')
    with (ROOT/'input/EMAIN.ELF').open('rb') as f:
        elf_hash = hashlib.file_digest(f, 'sha256').hexdigest()
    if elf_hash != cfg.get('elf_sha256'):
        raise ValueError('Private ELF does not match the approved local input digest')
    dumps = sorted((seed/'analysis/spu/dump').glob('spujob_*.bin'))
    if not dumps:
        raise ValueError('Provision the captured SPU job images before enabling CI')
    for blob in dumps:
        copy_file(blob, ROOT/'analysis/spu/dump'/blob.name)
    copy_file(seed/'third_party/SDL2.dll', ROOT/'third_party/SDL2.dll')
    # Only headers and the three explicit FFmpeg DLLs are build inputs.
    headers = seed/'third_party/ffmpeg/include'
    if not (headers/'libavcodec/avcodec.h').is_file():
        raise ValueError('Matching FFmpeg headers are missing')
    for source in headers.rglob('*'):
        if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
            raise ValueError('FFmpeg header links are not accepted')
        if source.is_file():
            copy_file(source, ROOT/'third_party/ffmpeg/include'/source.relative_to(headers))
    for name in ('avcodec-61.dll', 'avutil-59.dll', 'swresample-5.dll'):
        copy_file(seed/'third_party/ffmpeg/bin'/name, ROOT/'third_party/ffmpeg/bin'/name)
    (ROOT/'input/target').write_text('BCUS98158\n', encoding='ascii')
    os.environ['GT5P_TARGET'] = 'BCUS98158'
    # Content-address the patched runtime so a new pin/overlay never edits the
    # development runtime or an older CI runtime with a different patch.
    manifest = json.loads((ROOT/'config/ps3recomp.json').read_text())
    identity = hashlib.sha256((ROOT/'config/ps3recomp.json').read_bytes() + (ROOT/manifest['patch']).read_bytes()).hexdigest()[:20]
    runtime = paths['runtime_cache']/identity
    runtime.parent.mkdir(parents=True, exist_ok=True)
    os.environ['PS3RECOMP_DIR'] = str(runtime)
    run(sys.executable, 'scripts/setup_runtime.py', '--path', runtime)
    tools = runtime/'tools'
    # Dependencies are provisioned once in the runner's external Python venv.
    # Keep each lift deterministic by ignoring developer diagnostic overrides.
    for name in list(os.environ):
        if name.startswith(('PPU_', 'SPU_', 'GT5P_')) and name not in ('GT5P_TARGET',):
            os.environ.pop(name, None)
    (ROOT/'analysis').mkdir(exist_ok=True)
    run(sys.executable, 'scripts/jumptables.py', '--write')
    run(sys.executable, tools/'find_functions.py', 'input/EMAIN.ELF', '--json',
        '--seed-json', 'config/extra_seeds_bcus98158.json', '--output', 'analysis/functions.json')
    functions = json.loads((ROOT/'analysis/functions.json').read_text())
    (ROOT/'analysis/functions_code.json').write_text(json.dumps([x for x in functions if int(x['start'],16) < 0xE3EC24]))
    run(sys.executable, 'scripts/gen_hle_stubs.py', 'input/EMAIN.ELF', 'analysis/hle_stubs.json')
    run(sys.executable, tools/'ppu_lifter.py', 'input/EMAIN.ELF', '--functions',
        'analysis/functions_code.json', '--output', 'generated', '--code-end', '0xE3EC24',
        '--header-name', 'ppu_recomp.h', '--source-name', 'ppu_recomp.c', '--hle-stubs', 'analysis/hle_stubs.json')
    run(sys.executable, 'scripts/lift_spu_jobs.py')
    for script in ('setjmp_patch.py', 'spin_patch.py', 'ui_mask_patch.py', 'spu_native_patch.py'):
        run(sys.executable, Path('scripts')/script)
    run(sys.executable, tools/'gen_hle_nids.py', '--all', '--out', 'src/gen/ppu_hle_nids.cpp')
    clang = cfg.get('clang_cl', 'C:/Program Files/LLVM/bin/clang-cl.exe')
    run('cmake', '-S', ROOT, '-B', ROOT/'build', '-G', 'Ninja',
        '-DGT5P_TARGET=BCUS98158', '-DCMAKE_BUILD_TYPE=Release',
        f'-DPS3RECOMP_DIR={runtime.as_posix()}', f'-DCMAKE_C_COMPILER={clang}', f'-DCMAKE_CXX_COMPILER={clang}')
    run('cmake', '--build', ROOT/'build', '--parallel', jobs)
    launcher = ROOT/'out/launcher'
    # No interpolated command text; the batch file receives a controlled path.
    run('cmd.exe', '/d', '/c', 'scripts\\release\\build_launcher.cmd', launcher)
    run('cl', '/nologo', '/std:c++17', '/O2', '/W4', '/MT', '/EHsc',
        '/Fo'+str(launcher/'probe.obj'), '/Fe'+str(launcher/'probe.exe'), 'scripts/test/launcher_probe.cpp')
    run(sys.executable, 'scripts/test/launcher_native.py', '--launcher', launcher/'GT5P.exe', '--probe', launcher/'probe.exe')
    run(sys.executable, 'scripts/test/player_package.py')
    output = ROOT/'out/ci-player'/f'GT5P-v{version}-windows-x64-{sha}.zip'
    run(sys.executable, 'scripts/release/package_player.py', '--build-dir', ROOT/'build',
        '--launcher-exe', launcher/'GT5P.exe', '--elf', ROOT/'input/EMAIN.ELF',
        '--vc-runtime-dir', paths['vc_runtime_dir'], '--notices-dir', paths['notices_dir'], '--output', output)
    print(f'Player ZIP ready for artifact upload: {output.name}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write(f'release_version=v{version}\n')


if __name__ == '__main__':
    main()
