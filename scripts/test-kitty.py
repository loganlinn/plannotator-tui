#!/usr/bin/env python3
"""Pure adapter tests. Run with uv; the isolated integration test covers real Kitty objects."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import sys
sys.dont_write_bytecode = True

ASSETS = Path(__file__).resolve().parents[1] / 'crates/plannotator-tui/src/kitty/assets'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ASSETS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state, views = load('state'), load('views')


class Line(str):
    def cursor_from(self, column):
        return NS(dim=getattr(self, 'dim_from', 1000) <= column)


def window(host='codex', rows=None, cursor=(2, 0)):
    rows = [Line(row) for row in (rows or ['› ', '', '? for shortcuts'])]
    return NS(id=7, child=NS(foreground_processes=[dict(pid=42, cmdline=[host])]),
              screen=NS(in_bracketed_paste_mode=True, cursor_visible=True, scrolled_by=0,
                        cursor=NS(x=cursor[0], y=cursor[1]), lines=len(rows), columns=100,
                        line=lambda y: rows[y]))


def event(w, name, session='session-a', **extra):
    return state.event(w, dict(host='codex', ancestors=[42], event=dict(
        hook_event_name=name, session_id=session, **extra)))


class IdentityTests(unittest.TestCase):
    def test_process_exit_invalidates_the_session(self):
        w = window()
        event(w, 'SessionStart')
        w.child.foreground_processes = [dict(pid=55, cmdline=['zsh'])]
        self.assertIsNone(state.current(w))
        self.assertIsNone(state.target(w)['session'])

    def test_hook_cannot_bind_another_windows_process(self):
        w = window()
        result = state.event(w, dict(host='codex', ancestors=[99], event=dict(
            hook_event_name='SessionStart', session_id='other')))
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(state.current(w))

    def test_exact_session_and_registration_change_on_clear(self):
        w = window()
        event(w, 'SessionStart', transcript_path='/tmp/session-a.jsonl')
        before = state.target(w)
        event(w, 'SessionStart', session='session-b')
        self.assertNotEqual(before, state.target(w))
        self.assertIsNone(state.current(w)['transcript'])
        self.assertEqual(event(w, 'Stop')['status'], 'unavailable')
        self.assertEqual(state.current(w)['session'], 'session-b')

    def test_ended_sessions_need_a_fresh_registration_even_when_resumed(self):
        w = window()
        event(w, 'SessionStart')
        before = state.target(w)
        event(w, 'SessionEnd')
        self.assertEqual(event(w, 'Stop')['status'], 'unavailable')
        self.assertEqual(state.current(w)['state'], 'ended')
        event(w, 'SessionStart')
        self.assertNotEqual(before, state.target(w))
        self.assertEqual(state.current(w)['state'], 'unknown')

    def test_stale_stop_cannot_make_a_new_turn_idle(self):
        w = window()
        event(w, 'SessionStart')
        event(w, 'UserPromptSubmit', turn_id='one')
        event(w, 'UserPromptSubmit', turn_id='two')
        event(w, 'Stop', turn_id='one')
        self.assertEqual(state.current(w)['state'], 'working')

    def test_tool_completion_cannot_clear_a_dialog(self):
        w = window()
        event(w, 'SessionStart')
        event(w, 'PermissionRequest')
        event(w, 'PostToolUse')
        event(w, 'Notification', notification_type='idle_prompt')
        self.assertEqual(state.current(w)['state'], 'blocked')
        event(w, 'Stop')
        self.assertEqual(state.current(w)['state'], 'idle')

    def test_unregistered_stop_is_not_a_session_registration(self):
        w = window()
        self.assertEqual(event(w, 'Stop')['status'], 'unavailable')
        self.assertIsNone(state.current(w))


class ComposerTests(unittest.TestCase):
    def test_only_an_empty_codex_composer_is_ready(self):
        self.assertTrue(views.ready(window(), 'codex'))
        self.assertFalse(views.ready(window(rows=['› unfinished', '', '? for shortcuts']), 'codex'))
        self.assertFalse(views.ready(window(rows=['› ', '  second draft line', '? for shortcuts']), 'codex'))
        self.assertFalse(views.ready(window(rows=['› ', '1. Approve', '2. Cancel']), 'codex'))
        self.assertFalse(views.ready(window(rows=['[Image #1]', '', '› ', '? for shortcuts'], cursor=(2, 2)), 'codex'))

    def test_dim_placeholder_does_not_masquerade_as_typed_text(self):
        w = window(rows=['› Ask Codex to do anything', '', '? for shortcuts'])
        self.assertFalse(views.ready(w, 'codex'))
        w.screen.line(0).dim_from = 2
        self.assertTrue(views.ready(w, 'codex'))
        w.screen.line(0).dim_from = 0
        self.assertFalse(views.ready(w, 'codex'))

    def test_claude_composer_requires_its_boundary_and_known_footer(self):
        w = window('claude', ['────────────', '❯ ', '────────────', '? for shortcuts'], cursor=(2, 1))
        self.assertTrue(views.ready(w, 'claude'))
        self.assertFalse(views.ready(window('claude', ['❯ ', 'draft', '────────────']), 'claude'))
        self.assertFalse(views.ready(window('claude', ['❯ ', 'Approve this command?']), 'claude'))

    def test_terminal_mode_cursor_and_scrollback_are_part_of_readiness(self):
        for key, value in [('in_bracketed_paste_mode', False), ('cursor_visible', False), ('scrolled_by', 1)]:
            w = window()
            setattr(w.screen, key, value)
            self.assertFalse(views.ready(w, 'codex'), key)
        self.assertFalse(views.ready(window(cursor=(3, 0)), 'codex'))


if __name__ == '__main__':
    unittest.main()
