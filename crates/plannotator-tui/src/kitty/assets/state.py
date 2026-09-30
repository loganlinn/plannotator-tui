"""Per-window, event-driven agent identity. No timers, user variables, or title inference."""
import os
import secrets

ATTR = '_plannotator_kitty_session_v1'


def foreground(window):
    candidates = []
    for process in window.child.foreground_processes:
        argv = process.get('cmdline') or []
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if name in ('node', 'bun') and len(argv) > 1:
            name = os.path.basename(argv[1])
            if name == 'cli.js' and '/claude-code/' in argv[1]:
                name = 'claude'
        host = {'codex': 'codex', 'codex.js': 'codex', 'claude': 'claude', 'claude.js': 'claude'}.get(name)
        if host:
            candidates.append((host, process['pid']))
    return candidates[0] if len(candidates) == 1 else (None, None)


def current(window):
    host, pid = foreground(window)
    record = getattr(window, ATTR, None)
    if record and (record['host'], record['pid']) != (host, pid):
        delattr(window, ATTR)
        record = None
    return record


def target(window):
    host, pid = foreground(window)
    record = current(window)
    return dict(instance=os.getpid(), window=window.id, host=host, pid=pid,
                session=record['session'] if record else None,
                generation=record['generation'] if record else None)


def event(window, request):
    host, pid = foreground(window)
    if request.get('host') != host or not pid or pid not in request.get('ancestors', []):
        return dict(status='unavailable', message='hook process does not own this window')
    payload = request['event']
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        return dict(status='unavailable', message='hook has no session identity')
    name = payload.get('hook_event_name')
    record = current(window)
    # Only a start event may replace an existing session. Late subagent/old-turn
    # events cannot assign another session or clear a blocked request.
    if record and record['session'] != session and name != 'SessionStart':
        return dict(status='unavailable', message='stale session event')
    if record and record['state'] == 'ended' and name != 'SessionStart':
        return dict(status='unavailable', message='session has ended')
    if record is None or name == 'SessionStart':
        if name != 'SessionStart':
            return dict(status='unavailable', message='waiting for SessionStart; restart the agent')
        record = dict(host=host, pid=pid, session=session, generation=secrets.token_hex(16),
                      transcript=None, state='unknown', turn=None, retired=[], uncertain=False)
        setattr(window, ATTR, record)
    turn = payload.get('turn_id') or payload.get('prompt_id')
    if turn and turn in record['retired']:
        return dict(status='unavailable', message='stale turn event')
    if turn and turn != record['turn']:
        if record['turn'] and name != 'UserPromptSubmit':
            return dict(status='unavailable', message='out-of-order turn event')
        if record['turn']:
            record['retired'] = (record['retired'] + [record['turn']])[-32:]
        record['turn'] = turn
    transcript = payload.get('transcript_path')
    if isinstance(transcript, str) and os.path.isabs(transcript):
        record['transcript'] = transcript
    if name == 'SessionEnd':
        record['state'] = 'ended'
    elif name == 'Stop':
        record['state'] = 'idle'
    elif name in ('PermissionRequest', 'Elicitation', 'StopFailure', 'Interrupt'):
        record['state'] = 'blocked'
    elif name == 'Notification':
        kind = payload.get('notification_type')
        if kind == 'idle_prompt' and record['state'] != 'blocked':
            record['state'] = 'idle'
        elif kind in ('permission_prompt', 'elicitation_dialog'):
            record['state'] = 'blocked'
    elif name == 'PreToolUse' and str(payload.get('tool_name', '')).rsplit('.', 1)[-1] in ('AskUserQuestion', 'ExitPlanMode', 'request_user_input'):
        record['state'] = 'blocked'
    elif name == 'UserPromptSubmit':
        record['state'] = 'working'
    elif name in ('PreToolUse', 'PostToolUse', 'ElicitationResult') and record['state'] != 'blocked':
        record['state'] = 'working'
    return dict(status='ok')
