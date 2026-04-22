"""
Cross-platform UTF-8 encoding fix for console output.

On Windows, the default console encoding is often GBK/CP936, which cannot
represent many Unicode characters (emoji, some CJK characters). This module
reconfigures sys.stdout and sys.stderr to use UTF-8 with 'replace' error
handling, so that:
  - On Windows: unrepresentable characters are replaced with '?' instead of
    crashing with UnicodeEncodeError.
  - On Linux/macOS: typically already UTF-8, so this is a no-op or harmless.

Usage:
    import lib.encoding_fix  # Just import at top of script — auto-applies.
"""

import sys
import io


def ensure_utf8_output():
    """
    Ensure sys.stdout and sys.stderr use UTF-8 encoding with 'replace'
    error handling. Safe to call multiple times (idempotent).

    This fixes UnicodeEncodeError on Windows when printing emoji or
    non-ASCII characters to a GBK-encoded console.
    """
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-', '') != 'utf8':
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace',
                line_buffering=sys.stdout.line_buffering,
            )

    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        if sys.stderr.encoding and sys.stderr.encoding.lower().replace('-', '') != 'utf8':
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding='utf-8', errors='replace',
                line_buffering=sys.stderr.line_buffering,
            )


# Auto-apply on import
ensure_utf8_output()
