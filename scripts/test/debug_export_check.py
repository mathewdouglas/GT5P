"""Exercise real log forwarding, opt-in, ZIP CRCs, bounds and failure handling."""
import os
from pathlib import Path
import subprocess
import sys
import zipfile

exe, root = map(Path, sys.argv[1:])
for case, value, override, disabled, file_value, effective in (
    ('default', '', None, False, False, False),
    ('on', 'true', None, False, True, True),
    ('override_off', 'true', '0', False, True, False),
    ('override_on', 'false', '1', False, False, True),
    ('invalid', '"yes"', None, False, False, False),
    ('no_settings', 'true', '1', True, False, False),
):
    folder = root / ('warmup_' + case); folder.mkdir()
    settings = folder / 'settings.toml'
    settings.write_text('[video]\n' + ('shader_warmup = ' + value + '\n' if value else ''))
    env = os.environ.copy()
    for key in ('RSX_SHADER_WARMUP', 'GT5P_NO_SETTINGS'): env.pop(key, None)
    env.update(GT5P_SETTINGS=str(settings), TEST_WARMUP_FILE=str(int(file_value)), TEST_WARMUP_EFFECTIVE=str(int(effective)))
    if override is not None: env['RSX_SHADER_WARMUP'] = override
    if disabled: env['GT5P_NO_SETTINGS'] = '1'
    subprocess.run([str(exe), 'warmup-settings'], cwd=folder, env=env, timeout=10, check=True)
    if not disabled:
        assert ('shader_warmup = ' + str(not file_value).lower()) in settings.read_text()
    print('warmup_' + case + ': passed')

for case in ("missing", "off", "force_on", "kill", "no_settings", "enabled", "hitch_off", "epoch", "fault", "hung", "failure"):
    folder = root / case
    folder.mkdir()
    settings = folder / "settings.toml"
    settings.write_text('[debug]\n' + ('' if case == 'missing' else
        'export_enabled = ' + ('false' if case in ('off', 'force_on') else 'true') + '\n'))
    env = os.environ.copy()
    for key in ('GT5P_DEBUG_EXPORT', 'GT5P_NO_SETTINGS', 'GT5P_HITCH_CAPTURE'):
        env.pop(key, None)
    env['GT5P_SETTINGS'] = str(settings)
    diagnostics = {'SPURS_PM_ARG64': '0', 'PS3_SC_CONTEXT': '1', 'GT5P_AUDIO_NATIVE': '0', 'RSX_FP_SOURCE_RANGE': '0', 'RSX_DEPTH_CLEAR_REUSE': '0', 'RSX_TEX3D': '0',
                   'GT5P_STALL_MS': '350', 'GT5P_STALL_STACKS': '1'}
    env.update(diagnostics)
    if case == 'force_on': env['GT5P_DEBUG_EXPORT'] = '1'
    if case == 'kill': env['GT5P_DEBUG_EXPORT'] = '0'
    if case == 'no_settings': env['GT5P_NO_SETTINGS'] = '1'
    if case == 'hitch_off': env['GT5P_HITCH_CAPTURE'] = '0'
    if case == 'failure':
        (folder / 'logs').mkdir()
        (folder / 'logs/debug').write_text('block reports directory')
    mode = 'off' if case in ('missing', 'off', 'force_on', 'kill', 'no_settings') else case
    if case == 'hitch_off': mode = 'enabled'
    with (folder / 'forwarded-out.log').open('wb') as out, (folder / 'forwarded-err.log').open('wb') as err:
        subprocess.run([str(exe), mode], cwd=folder, env=env, stdout=out, stderr=err, timeout=20, check=True)
    archives = sorted((folder / 'logs/debug').glob('*.zip')) if case != 'failure' else []
    expected = 3 if mode == 'enabled' else 1 if case in ('epoch', 'fault', 'hung') else 0
    assert len(archives) == expected, (case, archives)
    for n, archive in enumerate(archives):
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            names = set(z.namelist())
            if case == 'hung': names.discard('game-window.bmp')
            assert names == {'README.txt', 'report.txt', 'hitches.txt', 'stdout.log', 'stderr.log'}
            report = z.read('report.txt')
            assert b'test snapshot marker' in report and b'test frame marker' in report
            for key, value in diagnostics.items():
                assert (key + '=' + value).encode() in report
            history = z.read('hitches.txt')
            assert history.count(b'=== frame 300 ') == (1 if case == 'enabled' and n < 2 else 0)
            if case == 'epoch': assert b'=== frame' not in history
            if case == 'fault': assert b'Snapshot interrupted' in report
            for stream in ('stdout', 'stderr'):
                log = z.read(stream + '.log')
                assert len(log) <= 2 * 1024 * 1024 + 100
                assert b'begin overwritten marker' not in log
                assert b'disabled interval marker' not in log
                if mode == 'enabled' and n == 2:
                    if stream == 'stdout': assert b'fresh capture marker' in log
                    assert b'export stdout tail' not in log
                else: assert ('export ' + stream + ' tail').encode() in log
    out = (folder / 'forwarded-out.log').read_bytes()
    err = (folder / 'forwarded-err.log').read_bytes()
    assert b'shutdown stdout tail' in out and b'shutdown stderr tail' in err
    if mode == 'off':
        assert b'disabled stdout marker' in out and b'disabled stderr marker' in err
    else:
        assert b'begin overwritten marker' in out and b'export stdout tail' in out
        assert b'begin overwritten marker' in err and b'export stderr tail' in err
        assert len(out) >= 3 * 1024 * 1024 and len(err) >= 3 * 1024 * 1024
    assert not list(folder.rglob('*.partial'))
    print(case + ': passed')
