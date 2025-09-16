from __future__ import annotations

import argparse
import re

__all__ = ['SmartFormatter']

class SmartFormatter(argparse.HelpFormatter):
    """
    From: https://gist.github.com/panzi/b4a51b3968f67b9ff4c99459fb9c5b3d
    Author: Mathias Panzenböck
    License: Public Domain/CC0
    """

    def _split_lines(self, text: str, width: int) -> list[str]:
        SPACE = re.compile(r'\s')
        NON_SPACE = re.compile(r'\S')
        lines: list[str] = []
        for line_str in text.split('\n'):
            match = NON_SPACE.search(line_str)
            if not match:
                lines.append('')
                continue

            prefix = line_str[:match.start()]

            if len(prefix) >= width:
                lines.append('')
                prefix = ''

            line_len = prefix_len = len(prefix)
            line: list[str] = [prefix]
            pos = match.start()

            while pos < len(line_str):
                match = NON_SPACE.search(line_str, pos)
                if not match:
                    break

                next_pos = match.start()
                space = line_str[pos:next_pos]
                line_len += len(space)

                if line_len >= width:
                    lines.append(''.join(line))
                    line.clear()
                    line.append(prefix)
                    line_len = prefix_len
                else:
                    line.append(space)

                pos = next_pos
                match = SPACE.search(line_str, pos)
                if not match:
                    next_pos = len(line_str)
                else:
                    next_pos = match.start()

                word = line_str[pos:next_pos]
                word_len = len(word)
                line_len += word_len
                if line_len > width:
                    lines.append(''.join(line))
                    line.clear()
                    line.append(prefix)
                    line_len = prefix_len + word_len
                elif word_len >= 3:
                    if all(c == '.' for c in word) and line_str[next_pos:next_pos + 1].isspace():
                        prefix_len = line_len + 1
                        prefix = ' ' * prefix_len
                    elif all(c == ' ' for c in word):
                        prefix_len = line_len
                        prefix = ' ' * prefix_len
                line.append(word)
                pos = next_pos

            lines.append(''.join(line))
        return lines

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        return '\n'.join(indent + line for line in self._split_lines(text, width - len(indent)))
