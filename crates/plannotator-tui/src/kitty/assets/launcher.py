"""Capture source context before changing geometry, then launch a normal TUI process."""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlparse
from . import state


def launch(boss, window, request):
    options = request['options']
    action = options['action']
    tab = window.tabref()
    if tab is None:
        raise ValueError('source tab has closed')
    cwd = window.get_cwd_of_child(oldest=True)
    if not cwd or not os.path.isdir(cwd):
        raise ValueError('source directory is unavailable; only local windows are supported')
    # Shell integration reports remote URLs; never reinterpret their paths locally.
    reported = window.screen.last_reported_cwd
    if reported:
        uri = urlparse(reported.decode('utf-8', 'replace') if isinstance(reported, bytes) else reported)
        import socket
        if uri.hostname and uri.hostname not in ('localhost', socket.gethostname(), socket.getfqdn()):
            raise ValueError('SSH/remote source windows are unsupported')
    identity = state.target(window)
    record = state.current(window)
    context = dict(to=request['to'], helper=request['helper'], target=identity,
                   action=action, cwd=cwd, path=None, text=None, transcript=None,
                   newest=bool(options.get('newest')))
    if action == 'open':
        path = options.get('path')
        if path and path.startswith('file:'):
            uri = urlparse(path)
            if uri.scheme != 'file' or uri.netloc not in ('', 'localhost'):
                raise ValueError('only local file links are supported')
            path = unquote(uri.path)
        target = Path(path or cwd).expanduser()
        if not target.is_absolute():
            target = Path(request['caller_cwd']) / target
        target = target.resolve(strict=True)
        context['path'] = str(target)
    elif action == 'last':
        if not record or record['state'] == 'ended':
            raise ValueError('no exact agent session; install hooks and restart the agent')
        context['transcript'] = record['transcript']
    elif action in ('selection', 'terminal'):
        extent = 'selection' if action == 'selection' else options.get('extent', 'screen')
        text = boss.call_remote_control(window, ('get-text', f'--match=id:{window.id}', f'--extent={extent}'))
        if not isinstance(text, str) or not text.strip():
            raise ValueError('no selected text' if action == 'selection' else 'no terminal output to review')
        if options.get('lines'):
            text = '\n'.join(text.splitlines()[-options['lines']:])
        if options.get('print'):
            return dict(status='ok', text=text)
        context['text'] = text
    else:
        raise ValueError('unknown review source')
    placement = request['placement']
    if placement == 'split' and tab.current_layout.name != 'splits':
        raise ValueError('split placement requires the splits layout; choose overlay or tab')
    # Same-user private file, consumed and removed by the pane entrypoint.
    fd, path = tempfile.mkstemp(prefix='review-', suffix='.json', dir=Path(request['helper']).parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(context, handle)
        argv = ['launch', f'--match=id:{tab.id}', f'--source-window=id:{window.id}',
                f'--next-to=id:{window.id}', '--add-to-session=.', '--title=Annotate',
                f'--cwd={cwd}', f'--var=plannotator_source={window.id}',
                '--env=HERDR_ENV', '--env=PLANNOTATOR_TUI_DELIVER_TO',
                f'--type={"window" if placement == "split" else placement}']
        if placement == 'split':
            argv.append('--location=vsplit')
        argv.extend((request['binary'], 'kitty', 'pane', path))
        review = boss.call_remote_control(window, tuple(argv))
        return dict(status='ok', window_id=int(review))
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
