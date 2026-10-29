"""Real Ninja build checks for cache reuse and changed-source invalidation.

Run in an x64 VS environment. Compiles only a tiny synthetic C++ program.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_cache', ROOT/'scripts/release/ci_cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run(root, *args):
    return subprocess.check_output([str(x) for x in args], cwd=root, text=True, stderr=subprocess.STDOUT)


def main():
    with tempfile.TemporaryDirectory(prefix='gt5p-ci-cache-') as temp:
        base = Path(temp).resolve()
        root = base/'checkout'
        root.mkdir()
        (root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(cache_probe LANGUAGES CXX)
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)
add_executable(probe main.cpp value.cpp)
''')
        (root/'main.cpp').write_text('#include <stdio.h>\nint value(); int main(){printf("%d",value());}\n')
        (root/'value.cpp').write_text('int value(){return 1;}\n')
        (root/'generated').mkdir()
        (root/'generated/probe.h').write_text('// synthetic generated fixture\n')
        for name in module.DERIVED:
            (root/name).parent.mkdir(parents=True, exist_ok=True)
            (root/name).write_text('// synthetic derived fixture\n')
        tracked = ['CMakeLists.txt', 'main.cpp', 'value.cpp', *module.DERIVED]
        cache = module.BuildCache(root, base/'private-cache', 'a'*64)
        assert not cache.restore()
        print(run(root, 'cmake', '-S', root, '-B', root/'build', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release'))
        print(run(root, 'cmake', '--build', root/'build'))
        assert run(root, root/'build/probe.exe') == '1'
        cache.save(tracked)
        # Simulate checkout cleaning ignored directories; keep originals intact.
        for name in ('build', 'generated'):
            source, destination = root/name, root/('original-'+name)
            assert base in source.resolve().parents and base in destination.resolve().parents
            source.rename(destination)
        future = time.time_ns() + 60_000_000_000
        os.utime(root/'main.cpp', ns=(future, future))
        assert cache.restore()
        output = run(root, 'cmake', '--build', root/'build')
        assert 'no work to do' in output, output
        assert run(root, root/'build/probe.exe') == '1'
        print('Fresh checkout with identical contents: Ninja reuses compiled objects.')
        (root/'value.cpp').write_text('int value(){return 2;}\n')
        os.utime(root/'value.cpp', ns=(future, future))
        assert cache.restore()
        assert 'return 2' in (root/'value.cpp').read_text()
        output = run(root, 'cmake', '--build', root/'build')
        assert 'value.cpp' in output and run(root, root/'build/probe.exe') == '2', output
        print('Changed source survives restore, recompiles and changes executable output.')
        assert not module.BuildCache(root, base/'private-cache', 'b'*64).restore()
        print('Different lift/toolchain key: cache miss.')
        # A partial save cannot be reused even if objects remain.
        (cache.directory/'ready.json').unlink()
        assert not cache.restore()
        print('Incomplete cache: refused.')


if __name__ == '__main__':
    main()
