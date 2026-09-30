---
name: plannotator-tui-kitty
description: Open a Markdown plan or document for human review in Kitty and receive annotations back in the originating Codex or Claude Code session. Use when the user wants to review a document before further work.
---

# Review a document in Kitty

Write the document to a file, then run from the agent's own Kitty window:

```sh
plannotator-tui kitty open /absolute/path/to/plan.md
```

A successful launch prints the review window ID. End your turn so the human can review;
do not poll the review or send input into it. Their submitted annotations arrive as the
next message. Address each item when they return.

The launcher validates `KITTY_WINDOW_ID` against `KITTY_LISTEN_ON`. A stale window ID,
missing socket, or launch error means the review was not opened. Report the error and the
document path. Use `--source-window ID --to unix:SOCKET` only for a source the user has
identified or that you have verified; never substitute the currently focused window.

Feedback sends only when the original agent process/session and an empty composer are
verified. Otherwise the TUI copies feedback and keeps the review open. Hook installation
alone does not prove hooks are running; `plannotator-tui kitty setup` prints integration
instructions. Do not work around a failed send by blindly pasting or pressing Enter.

The first version supports local macOS Codex and Claude Code sessions. An existing review
can still be used with clipboard handoff when agent state is unavailable. This skill does
not authorize changes to Kitty configuration or other agent sessions.
