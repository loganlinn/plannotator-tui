#!/usr/bin/env python3
"""Actual Kitty RPC, hooks and PTY tests in an owned instance; no model or API calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def until(fn, message, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = fn()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError(message)


def test(binary):
    with tempfile.TemporaryDirectory(prefix='plannotator-kitty-') as temporary:
        root = Path(temporary)
        endpoint = 'unix:' + str(root / 'kitty.sock')
        env = dict(os.environ, XDG_CACHE_HOME=str(root / 'cache'), PLANNOTATOR_DATA_DIR=str(root / 'data'),
                   PLANNOTATOR_TUI_THEME='dark', PLANNOTATOR_TUI_CONFIG=str(root / 'absent.toml'))
        binary = str(Path(binary).resolve())
        setup = subprocess.check_output([binary, 'kitty', 'setup'], env=env, text=True)
        helper = setup.splitlines()[0].removeprefix('# Helper installed at ')
        log = (root / 'kitty.log').open('w')
        instance = subprocess.Popen(['kitty', '--config', 'NONE', '--listen-on', endpoint,
            '-o', 'allow_remote_control=socket-only', '-o', 'enabled_layouts=splits,stack',
            '-o', 'confirm_os_window_close=0', '-o', 'clipboard_control=read-clipboard-ask',
            '-o', 'initial_window_width=120c',
            '-o', 'initial_window_height=36c', '/bin/sleep', '300'],
            env=env, stdout=log, stderr=log, cwd=root)

        def rc(*args, check=True):
            return subprocess.run(['kitty', '@', '--to', endpoint, *args], env=env,
                                  capture_output=True, text=True, timeout=15, check=check)

        def tree():
            result = rc('ls', check=False)
            return json.loads(result.stdout) if result.returncode == 0 else None

        def windows():
            return [w for osw in tree() for tab in osw['tabs'] for w in tab['windows']]

        def rpc(window, payload):
            path = root / 'request.json'
            path.write_text(json.dumps(payload))
            path.chmod(0o600)
            return json.loads(rc('kitten', '--match', f'id:{window}', helper, '--request', str(path)).stdout)

        def cli(*args, check=True):
            return subprocess.run([binary, 'kitty', *args, '--source-window', str(source), '--to', endpoint],
                                  env=env, capture_output=True, text=True, check=check, timeout=15)

        def screen(window):
            return rc('get-text', '--match', f'id:{window}').stdout

        def close(window):
            rc('close-window', '--match', f'id:{window}')

        def rendered(window, text):
            return until(lambda: text in screen(window), f'{text!r} did not render in {window}')

        try:
            until(tree, 'Kitty socket did not start')
            root_id = windows()[0]['id']
            doc = root / 'plan ü.md'
            doc.write_text('# Plan\n\nA paragraph for review.\n')
            selection_helper = root / 'select.py'
            selection_helper.write_text('from kittens.tui.handler import result_handler\n'
                'def main(args): pass\n@result_handler(no_ui=True)\n'
                'def handle_result(args, answer, target_window_id, boss):\n'
                '    s = boss.window_id_map[target_window_id].screen\n'
                '    s.start_selection(0, 0)\n    s.update_selection(19, 0)\n')
            for host in ('codex', 'claude'):
                fixture_root = root / host
                fixture_root.mkdir()
                # argv[0] presents the fixture as an agent, while its real executable
                # name stays Python. Hooks must bind ancestry, not executable names.
                source = int(rc('launch', '--match', f'window_id:{root_id}', '--type=window',
                    '/bin/bash', '-c', 'exec -a "$1" "$2" "$3" "$4" "$5" "$1"', 'fixture', host,
                    sys.executable, str(Path(__file__).with_name('kitty_fixture.py').resolve()),
                    str(fixture_root), binary).stdout)
                until(lambda: (fixture_root / 'started').exists(), 'fixture did not start')
                rendered(source, f'Captured {host}')
                assert rpc(source, dict(op='status'))['target']['host'] == host
                assert cli('last', check=False).returncode != 0, 'unregistered last guessed a session'
                assert cli('selection', check=False).returncode != 0, 'empty selection opened a review'
                assert f'Captured {host}' in cli('terminal', '--print').stdout
                rc('kitten', '--match', f'id:{source}', str(selection_helper))
                assert f'Captured {host}' in cli('selection', '--print').stdout
                review = int(cli('selection').stdout)
                rendered(review, f'Captured {host}')
                close(review)
                # Focus elsewhere must not change the destination tab.
                other = int(rc('launch', '--type=tab', '/bin/sleep', '300').stdout)
                review = int(cli('open', doc.as_uri(), '--placement', 'split').stdout)
                source_tab = next(t for o in tree() for t in o['tabs'] if any(w['id'] == source for w in t['windows']))
                assert any(w['id'] == review for w in source_tab['windows'])
                rendered(review, 'Plan')
                close(review)
                close(other)
                rc('goto-layout', '--match', f'id:{source_tab["id"]}', 'stack')
                assert cli('open', str(doc), '--placement', 'split', check=False).returncode != 0
                rc('goto-layout', '--match', f'id:{source_tab["id"]}', 'splits')
                review = int(cli('terminal', '--placement', 'tab').stdout)
                rendered(review, f'Captured {host}')
                close(review)
                # Exercise the native key entrypoint used by Kitty bindings/link actions.
                existing = {w['id'] for w in windows()}
                rc('kitten', '--match', f'id:{source}', helper, 'open', str(doc), '--binary', binary)
                review = until(lambda: next((w['id'] for w in windows() if w['id'] not in existing), None), 'keybinding did not launch')
                rendered(review, 'Plan')
                close(review)
                sequence = 0

                def fixture(**request):
                    nonlocal sequence
                    sequence += 1
                    request['sequence'] = sequence
                    pending = fixture_root / 'pending.json'
                    pending.write_text(json.dumps(request))
                    pending.replace(fixture_root / 'command.json')
                    until(lambda: (fixture_root / 'done').exists() and (fixture_root / 'done').read_text() == str(sequence), 'fixture command failed')

                def event(name, **extra):
                    fixture(event=dict(hook_event_name=name, **dict({'session_id': 'session-a'}, **extra)))

                content = f'# Exact {host} reply\n\nReply text from the registered session.'
                transcript = fixture_root / 'transcript.jsonl'
                row = dict(type='response_item', payload=dict(type='message', role='assistant', id='r1',
                    content=[dict(type='output_text', text=content)])) if host == 'codex' else dict(
                    type='assistant', uuid='r1', isSidechain=False, message=dict(role='assistant',
                    content=[dict(type='text', text=content)]))
                transcript.write_text(json.dumps(row) + '\n')
                event('SessionStart', transcript_path=str(transcript))
                status = rpc(source, dict(op='status'))
                assert status['target']['session'] == 'session-a', status
                target = status['target']
                request = dict(op='deliver', target=target, feedback='literal ü "quotes" \\slashes\nsecond line')
                assert rpc(source, request)['status'] == 'blocked', 'unknown state accepted input'
                review = int(cli('last', '--newest').stdout)
                rendered(review, f'Exact {host} reply')
                # Human annotation -> E -> delivery failure retains the actual review.
                rc('send-text', '--match', f'id:{review}', '--', 'cIntegration feedback\r')
                rendered(review, 'Integration feedback')
                rc('send-text', '--match', f'id:{review}', '--', 'E')
                rendered(review, 'cannot send')
                assert not (fixture_root / 'received').exists(), 'blocked path wrote input'
                event('Stop')
                for mode in ('draft', 'dialog'):
                    fixture(mode=mode)
                    rendered(source, 'unfinished draft' if mode == 'draft' else 'Approve this command?')
                    assert rpc(source, request)['status'] == 'blocked', mode
                fixture(mode='empty')
                event('PermissionRequest')
                event('PostToolUse')
                assert rpc(source, request)['status'] == 'blocked'
                event('Stop')
                # Successful E then S closes only the review; the native source survives.
                rc('send-text', '--match', f'id:{review}', '--', 'S')
                until(lambda: all(w['id'] != review for w in windows()), 'successful reply send did not close')
                received = until(lambda: (fixture_root / 'received').read_bytes() if (fixture_root / 'received').exists() else None, 'no feedback received')
                assert b'Integration feedback' in received and received.startswith(b'\x1b[200~') and received.endswith(b'\x1b[201~\r'), received
                assert rpc(source, request)['status'] == 'blocked', 'second send while working accepted'
                event('Stop')
                # Large feedback goes through a private file, preserving bytes and ordering.
                request['feedback'] *= 5000
                before = received
                expected = before + b'\x1b[200~' + request['feedback'].encode() + b'\x1b[201~\r'
                result = rpc(source, request)
                assert result['status'] == 'ok', result
                until(lambda: len((fixture_root / 'received').read_bytes()) >= len(expected), 'large feedback incomplete')
                assert (fixture_root / 'received').read_bytes() == expected
                event('SessionStart', session_id='session-b')
                event('Stop', session_id='session-b')
                assert rpc(source, request)['status'] == 'unavailable', 'old review followed a new session'
                event('SessionEnd', session_id='session-b')
                event('Stop', session_id='session-b')
                assert rpc(source, dict(op='status'))['state'] == 'ended'
                close(source)
                assert rc('ls', '--match', f'id:{source}', check=False).returncode != 0
            assert not list(Path(helper).parent.glob('review-*.json')), 'consumed contexts leaked'
            print('Kitty integration: both hosts, real hooks, exact replies, selection/output/file views, placements, key entrypoint, refusal states, TUI submission and large literal delivery passed')
        except Exception:
            for window in windows():
                print(f"WINDOW {window['id']}: {screen(window['id'])}", file=sys.stderr)
            print((root / 'kitty.log').read_text(), file=sys.stderr)
            raise
        finally:
            instance.terminate()
            try:
                instance.wait(timeout=5)
            except subprocess.TimeoutExpired:
                instance.kill()
                instance.wait(timeout=5)
            log.close()


if __name__ == '__main__':
    test(sys.argv[1])
