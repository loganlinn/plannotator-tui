"""Native Kitty entrypoint: keybindings, source snapshots, hooks, and acknowledged input."""
import importlib
import json
import os
from pathlib import Path
import sys
import types
from kittens.tui.handler import result_handler


def location():
    pass


def modules():
    directory = Path(location.__code__.co_filename).resolve().parent
    name = '_plannotator_kitty_' + directory.name.replace('-', '_')
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(directory)]
        sys.modules[name] = package
    return [importlib.import_module(name + '.' + module) for module in ('state', 'views', 'launcher')]


def main(args):
    pass


def deliver(boss, window, request, state, views):
    expected = request['target']
    if state.target(window) != expected:
        return dict(status='unavailable', message='source process or agent session has changed')
    record = state.current(window)
    if not record or record['state'] != 'idle':
        return dict(status='blocked', message='agent readiness is unknown, busy, or blocked')
    if record.get('uncertain'):
        return dict(status='uncertain', message='previous submission was uncertain; inspect the agent')
    if not views.ready(window, record['host']):
        return dict(status='blocked', message='cannot verify an empty agent composer')
    text = request['feedback']
    if not isinstance(text, str) or not text.strip():
        return dict(status='blocked', message='no feedback to send')
    # Reject rather than silently changing feedback containing terminal controls.
    if any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in text):
        return dict(status='blocked', message='feedback contains unsupported terminal control characters')
    from kitty.fast_data_types import GLFW_PRESS, KeyEvent
    from kitty.options.utils import parse_shortcut
    key = window.encoded_key(KeyEvent(key=parse_shortcut("enter").key, action=GLFW_PRESS))
    if not key:
        return dict(status='blocked', message='cannot encode Enter for this terminal')
    # One queue operation preserves paste-before-Enter and gives an actual PTY
    # queue acknowledgement, unlike the fire-and-forget send-text/send-key CLI.
    payload = b'\x1b[200~' + text.encode('utf-8') + b'\x1b[201~' + key
    record['uncertain'] = True
    try:
        accepted = boss.child_monitor.needs_write(window.id, payload)
    except Exception:
        return dict(status='uncertain', message='PTY queue did not acknowledge submission')
    if accepted is not True:
        return dict(status='uncertain', message='PTY queue did not acknowledge submission')
    record['uncertain'] = False
    record['state'] = 'working'
    return dict(status='ok', transport='pty-queued')


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    window = boss.window_id_map.get(target_window_id)
    if window is None:
        return json.dumps(dict(status='unavailable', message='source window has closed'))
    state, views, launcher = modules()
    try:
        if len(args) == 3 and args[1] == '--request':
            path = Path(args[2])
            metadata = path.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                raise ValueError('request file must be private to its owner')
            request = json.loads(path.read_text())
            operation = request.get('op')
            if operation == 'launch':
                result = launcher.launch(boss, window, request)
            elif operation == 'event':
                result = state.event(window, request)
            elif operation == 'deliver':
                result = deliver(boss, window, request, state, views)
            elif operation == 'error':
                boss.show_error('Annotate', request['message'])
                result = dict(status='ok')
            elif operation == 'status':
                record = state.current(window)
                result = dict(status='ok', target=state.target(window), state=record['state'] if record else 'unknown')
            else:
                raise ValueError('unknown Kitty integration operation')
            return json.dumps(result)
        # Keybinding entry: the selected window is supplied by Kitty, never focus
        # inferred later in a child process. CLI owns config parsing and errors.
        options = list(args[1:])
        binary = 'plannotator-tui'
        if '--binary' in options:
            index = options.index('--binary')
            binary = options[index + 1]
            del options[index:index + 2]
        if not options:
            options = ['open']
        if not boss.listening_on.startswith('unix:'):
            raise ValueError('configure a local Kitty listen_on socket first')
        # The key entrypoint reports launch failures back through a Kitty error dialog.
        boss.call_remote_control(window, ('launch', f'--match=window_id:{window.id}',
            f'--source-window=id:{window.id}', '--type=background',
            f'--cwd={window.get_cwd_of_child(oldest=True)}', binary, 'kitty', 'key', *options,
            '--source-window', str(window.id), '--to', boss.listening_on))
        return 'Review requested'
    except Exception as error:
        return json.dumps(dict(status='unavailable', message=str(error)))
