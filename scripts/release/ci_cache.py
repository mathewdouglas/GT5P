"""Private, workspace-specific incremental build cache; never upload this data."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SCHEMA = 1  # Bump when changing the ordered lift recipe in ci_build.py.
DERIVED = ('src/gen/ppu_hle_nids.cpp', 'src/gen/spu_workloads_bcus98158.c',
           'config/extra_seeds_bcus98158.json')
LIFT_INPUTS = ('config/targets.json', 'config/extra_seeds_bcus98158.json',
               'scripts/target.py', 'scripts/dis.py', 'scripts/jumptables.py',
               'scripts/gen_hle_stubs.py', 'scripts/lift_spu_jobs.py',
               'scripts/setjmp_patch.py', 'scripts/spin_patch.py',
               'scripts/ui_mask_patch.py', 'scripts/spu_native_patch.py')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def lift_key(root, runtime_identity, elf_hash, dumps, clang):
    inputs = {p: hashlib.sha256((root/p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
              for p in LIFT_INPUTS}
    for name in DERIVED:
        original = subprocess.check_output(['git', 'show', 'HEAD:'+name], cwd=root)
        inputs['tracked:'+name] = hashlib.sha256(original.replace(b'\r\n', b'\n')).hexdigest()
    # The seed file is itself rewritten by jumptables.py; fingerprint its
    # committed input, not the previous invocation's expanded output.
    inputs.pop('config/extra_seeds_bcus98158.json')
    inputs.update({'runtime': runtime_identity, 'elf': elf_hash,
                   'python': sys.version, 'schema': SCHEMA,
                   'capstone': importlib.metadata.version('capstone')})
    inputs['jobs'] = {p.name: digest(p) for p in dumps}
    inputs['compiler'] = {'path': str(Path(clang).resolve()), 'sha256': digest(Path(clang))}
    inputs['toolchain_environment'] = {name: os.environ.get(name, '') for name in
                                      ('VCToolsVersion', 'WindowsSDKVersion', 'INCLUDE', 'LIB',
                                       'CL', '_CL_', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS')}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


class BuildCache:
    def __init__(self, root, base, key):
        self.root, self.base = root.resolve(), base.resolve()
        if self.root == self.base or self.root in self.base.parents or self.base in self.root.parents:
            raise ValueError('Incremental cache must be outside the checkout')
        workspace = hashlib.sha256(str(self.root).lower().encode()).hexdigest()[:16]
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid incremental cache key')
        self.directory = self.base/workspace/key
        self.owner = {'schema': SCHEMA, 'workspace': str(self.root), 'key': key}

    @staticmethod
    def tree(source, destination):
        # No links and no deletion. Copy only changed files, preserving mtimes
        # so Ninja can reuse its normal dependency graph and compiler outputs.
        if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
            raise ValueError('Linked cache root is not accepted')
        for p in source.rglob('*'):
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                raise ValueError(f'Unexpected cache link: {p}')
            target = destination/p.relative_to(source)
            if p.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif p.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or (target.stat().st_size, target.stat().st_mtime_ns) != (p.stat().st_size, p.stat().st_mtime_ns):
                    shutil.copy2(p, target)

    def restore(self):
        manifest = self.directory/'ready.json'
        if not manifest.exists():
            return False
        state = json.loads(manifest.read_text())
        if state['owner'] != self.owner:
            raise ValueError('Incremental cache belongs to a different workspace/recipe')
        for name in ('generated', 'build'):
            if not (self.directory/name).is_dir():
                raise ValueError('Incomplete incremental cache')
            self.tree(self.directory/name, self.root/name)
        for name in DERIVED:
            path = self.directory/name
            (self.root/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, self.root/name)
        # Checkout may refresh mtimes even when bytes are unchanged. Only
        # restore timestamps after checking content, never overwrite new source.
        for name, record in state['tracked'].items():
            path = (self.root/name).resolve()
            if self.root not in path.parents:
                raise ValueError('Unsafe tracked cache path')
            if path.is_file() and digest(path) == record['sha256']:
                os.utime(path, ns=(record['mtime_ns'], record['mtime_ns']))
        print('Incremental cache restored: generated sources and Ninja objects.', flush=True)
        return True

    def save(self, tracked):
        if self.directory.exists() and any(self.directory.iterdir()) and not (self.directory/'owner.json').exists():
            raise ValueError('Refusing to overwrite an unowned cache directory')
        self.directory.mkdir(parents=True, exist_ok=True)
        owner_file = self.directory/'owner.json'
        if owner_file.exists() and json.loads(owner_file.read_text()) != self.owner:
            raise ValueError('Refusing to overwrite a different cache owner')
        owner_file.write_text(json.dumps(self.owner))
        ready = self.directory/'ready.json'
        if ready.exists():
            ready.unlink()  # Single, owned marker; a partial save is never reused.
        for name in ('generated', 'build'):
            self.tree(self.root/name, self.directory/name)
        for name in DERIVED:
            target = self.directory/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root/name, target)
        records = {}
        for name in tracked:
            path = (self.root/name).resolve()
            if self.root not in path.parents:
                raise ValueError('Unsafe tracked source path')
            if path.is_file():
                records[name] = {'sha256': digest(path), 'mtime_ns': path.stat().st_mtime_ns}
        staged = self.directory/'ready.new.json'
        staged.write_text(json.dumps({'owner': self.owner, 'tracked': records}))
        staged.replace(ready)
        print('Incremental cache saved outside the runner checkout.', flush=True)
