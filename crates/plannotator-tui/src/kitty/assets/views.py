"""Conservative, fail-closed recognition of empty local agent composers."""
import re


def ready(window, host):
    screen = window.screen
    if not screen.in_bracketed_paste_mode or not screen.cursor_visible or screen.scrolled_by:
        return False
    cursor = screen.cursor
    if not (0 <= cursor.y < screen.lines and 0 < cursor.x < screen.columns):
        return False
    line = screen.line(cursor.y)
    text = str(line).rstrip().ljust(cursor.x)
    # Cursor must be at the beginning of the first composer line. Home inside a
    # draft is caught by its non-dim text; multiline content is checked below.
    prefix = text[:cursor.x]
    pattern = r'\s*›{1,4} ' if host == 'codex' else r'\s*❯ '
    if re.fullmatch(pattern, prefix) is None:
        return False
    prompt_column = next((i for i, c in enumerate(prefix) if not c.isspace()), 0)
    if getattr(line.cursor_from(prompt_column), 'dim', False):
        return False  # disabled input
    suffix = text[cursor.x:]
    if suffix:
        # Codex renders empty-composer placeholders dim. Unknown Claude
        # placeholders remain copy-only rather than confusing them with drafts.
        if host != 'codex' or not all(getattr(line.cursor_from(x), 'dim', False)
                for x in range(cursor.x, len(text)) if not text[x].isspace()):
            return False
    below = [str(screen.line(y)).strip() for y in range(cursor.y + 1, screen.lines)]
    above = [str(screen.line(y)).strip() for y in range(cursor.y)]
    if any(re.search(r'\[Image #\d+\]', row) for row in above):
        return False  # restored image attachments can sit above an empty textarea
    if host == 'codex':
        # Only blank spacing and the standard shortcut/context footer may follow.
        return all(not row or re.fullmatch(r'\? for shortcuts(?:\s+.*)?', row)
                   or re.fullmatch(r'\d+% context left(?:\s+.*)?', row) for row in below)
    # Claude's composer is bounded by a rule; reject multiline drafts before it.
    if not above or re.fullmatch(r'[─━╌-]{5,}', above[-1]) is None:
        return False
    rule = next((i for i, row in enumerate(below) if re.fullmatch(r'[─━╌-]{5,}', row)), None)
    return rule is not None and all(not row for row in below[:rule]) and all(
        not row or row.startswith(('? for shortcuts', '⏵⏵', 'shift+tab', 'ctrl+'))
        for row in below[rule + 1:])
