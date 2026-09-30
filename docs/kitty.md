# Kitty integration

`plannotator-tui kitty` opens reviews in Kitty and sends feedback to the originating local
Codex or Claude Code session. It uses Kitty remote control and a bundled native kitten;
Herdr is not required. Kitty 0.49.1 on macOS is the initial runtime target.

## Setup

Use an existing local Kitty remote-control socket. If configuring a new instance:

```conf
allow_remote_control socket-only
listen_on unix:/tmp/kitty-{kitty_pid}
```

Run `plannotator-tui kitty setup`. This installs the versioned helper into
`$XDG_CACHE_HOME/plannotator-tui/kitty` (default `~/.cache`) and prints:

- Kitty keybinding examples and a Markdown `open-actions.conf` rule;
- Codex hook entries for `$CODEX_HOME/hooks.json` (default `~/.codex/hooks.json`);
- Claude hook entries for `$CLAUDE_CONFIG_DIR/settings.json` (default `~/.claude/settings.json`).

Merge the printed entries with your existing configuration; setup does not edit it.
Restart agent sessions after installing hooks. In Codex, review and trust the new hooks
with `/hooks`. Do not disable hook trust to enable the integration.

The helper path is content-versioned. Rerun setup after upgrading and update the printed
keybinding paths. Roll back by removing only these bindings, link rule, and hook entries;
existing annotations remain in the normal Plannotator data directory. This integration
does not use or enable any separate Kitty activity watcher.

## Review

```sh
plannotator-tui kitty open docs/plan.md
plannotator-tui kitty open                       # source window's directory
plannotator-tui kitty last                       # exact session's reply picker
plannotator-tui kitty last --newest
plannotator-tui kitty selection
plannotator-tui kitty terminal --extent all --lines 200
plannotator-tui kitty terminal --extent last_cmd_output --print
```

All four launch actions accept `--source-window ID`, `--to unix:SOCKET`, and
`--placement overlay|split|tab`. A path explicitly passed from the CLI is relative to that
caller's directory. With no path, `open` uses the source window's directory. Keybindings
capture that window directly. No operation falls back to whichever window has focus.

```toml
[kitty]
placement = "overlay"
```

An overlay covers the source pane, not the entire tab. Use `tab` for a full tab, or `split`
for a side-by-side review in an existing `splits` layout. Incompatible split layouts fail
without changing the layout. Terminal captures happen before the review changes geometry.
Command-output extents require Kitty shell integration. Alternate-screen capture cannot
recover output the application has discarded; prefer `last` for full agent replies.

Selections and terminal output use a transient review; they do not form a persistent
snippet inbox. File/folder annotations and feedback history use the existing storage.
`E` sends feedback, reply `S` sends and closes, and file/folder `F` finishes the review.
The new `plannotator-tui-kitty` skill provides the agent-initiated document-review workflow.

## Exact targeting and delivery

Hooks register the host, agent PID, session ID, transcript path, and lifecycle metadata.
Prompt text, tool inputs, and outputs are not forwarded. A hook must descend from the
agent process currently in the window. `last` requires this exact registration; it never
selects the newest transcript by directory. This matters for Codex on macOS, where the
existing Linux-only PID transcript discovery cannot identify the session.

Before sending, the kitten checks the same Kitty instance, window, process, session, and
registration generation, then checks lifecycle state and the live empty-composer surface.
Busy, blocked, unregistered, changed, or unrecognized targets receive no input. Feedback
is copied through OSC 52 and stays pending in the open review. OSC 52 has no clipboard
acknowledgement: a terminal can refuse the copy; the review retains the original feedback.

The native helper queues bracketed paste and the terminal's encoded Enter together and
returns a PTY queue acknowledgement. This proves queued input, not model acceptance or
completion. A missing acknowledgement latches delivery off for that review: inspect the
agent before reopening or manually pasting, to avoid duplicate submissions.

Composer detection is conservative and version-sensitive. Nonstandard agent layouts,
menus, drafts, missing lifecycle events, and unknown terminal modes use clipboard fallback.
A hook `Stop` event alone is not enough to send. Initial sessions without an observed
completion/idle event also use fallback. SSH, TCP/fd transports, other agents, Herdr-style
popups, and native app conversations outside Kitty are outside this version.

## Checks

```sh
cargo test --workspace
cargo clippy --workspace --all-targets
uv run --no-project scripts/test-kitty.py
uv run --no-project scripts/test-kitty-integration.py target/debug/plannotator-tui
```

The pure adapter tests also run in CI. The last check requires macOS with Kitty on PATH
and a graphical login. It creates a separate Kitty instance with no user config and
clipboard writes disabled. It exercises real hook ancestry, exact-session reply loading,
file/selection/output reviews, placement and key entrypoints, draft/dialog refusal, TUI
submission, and large literal payloads for both agent layouts. The fixtures do not run
real Codex/Claude model turns. It closes only the instance it created.
