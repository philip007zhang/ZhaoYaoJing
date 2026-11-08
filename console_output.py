"""Keep Chinese progress logs usable on redirected Windows consoles."""
import sys


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass
