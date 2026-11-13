#!/usr/bin/env python3
"""Attach lyrics to a song inside a Fretbook backup JSON.

    python3 add-lyrics.py songs.json --song "Gettysburg 3: High Water Mark" \
        --lyrics lyrics/high-water-mark.txt

The lyrics go in under a "Lyrics" heading, below whatever is already in the
sheet, so an existing chord chart is kept. A line that is just a name followed
by a colon ("Lee:") becomes its own section heading.

Text copied out of Windows often arrives with curly quotes turned into the
replacement character. Those are repaired on the way in: between two letters it
is an apostrophe, at the start or end of a line it is a double quote.
"""
import argparse
import json
import re
import sys

BAD = '�'
# "Lee:" - a speaker label on its own line
SPEAKER = re.compile(r'^\s*([A-Z][A-Za-z.\' ]{1,28}):\s*$')
# "[Chorus:]", "(Verse 2)", "[Bridge]" - a section marker on its own line
MARKER = re.compile(r"^\s*[\[(]\s*((?:intro|verse|chorus|pre[- ]?chorus|bridge|outro|interlude|solo|refrain|instrumental|coda|tag|hook|break)[A-Za-z0-9 '-]{0,18}?)\s*:?\s*[\])]\s*$", re.I)
# "Chorus", or 'Intro "Brother Against Brother"' - a bare section word
BARE = re.compile(r'^\s*(intro|verse|chorus|pre[- ]?chorus|bridge|outro|interlude|solo|refrain|instrumental|coda|tag|hook|break)\b[^a-zA-Z]{0,3}([A-Za-z0-9\u2018\u2019\u201c\u201d\' .-]{0,40})\s*$', re.I)


def repair(text):
    """Put back the quotes that a bad encoding round-trip destroyed.

    Speech here runs across several lines, so whether we are inside a quotation
    has to be tracked over the whole text. Inside one, an ambiguous mark is an
    elision ("'Em") rather than the start of a nested quote.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    in_quote = False
    out = []
    for line in text.split('\n'):
        chars = list(line)
        for i, ch in enumerate(chars):
            if ch != BAD:
                continue
            before = chars[i - 1] if i else ''
            after = chars[i + 1] if i + 1 < len(chars) else ''
            head_blank = not line[:i].strip()
            tail_blank = not line[i + 1:].strip()
            if head_blank:
                chars[i] = '“'           # opens a quotation
                in_quote = True
            elif tail_blank:
                chars[i] = '”'           # closes one
                in_quote = False
            elif before.isalpha() and after.isalpha():
                chars[i] = '’'           # it's, don't
            elif in_quote or before.isalpha():
                chars[i] = '’'           # 'Em, gunnin'
            else:
                chars[i] = '“'
                in_quote = True
        out.append(''.join(chars))
    return '\n'.join(out)


def format_lyrics(text, heading='Lyrics'):
    """Plain lyrics -> Fretbook sheet lines, speakers becoming sections."""
    lines = ['## ' + heading] if heading else []
    blank = False
    for raw in repair(text).split('\n'):
        line = raw.rstrip()
        if not line.strip():
            blank = True
            continue
        label = SPEAKER.match(line) or MARKER.match(line) or BARE.match(line)
        if label:
            lines.append('')
            lines.append('## ' + label.group(1).strip())
            blank = False
            continue
        if blank and lines:
            lines.append('')
        blank = False
        # a lyric line must not start with a chord bracket or a hash
        lines.append(re.sub(r'^([#\[])', r'​\1', line))
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('backup', help='a Fretbook backup JSON')
    ap.add_argument('--song', required=True,
                    help='song title, or any unique part of it')
    ap.add_argument('--lyrics', required=True, help='a plain text file')
    ap.add_argument('--heading', default='Lyrics',
                    help='section heading, or "" for none')
    ap.add_argument('--replace', action='store_true',
                    help='drop any lyrics block already attached')
    a = ap.parse_args()

    data = json.load(open(a.backup, encoding='utf-8'))
    needle = a.song.lower()
    matches = [e for e in data['imports'] if needle in e['song'].lower()]
    if len(matches) != 1:
        sys.exit('%d songs match %r: %s'
                 % (len(matches), a.song, [e['song'] for e in matches]))
    entry = matches[0]

    raw = open(a.lyrics, encoding='utf-8', errors='replace').read()
    block = format_lyrics(raw, a.heading)

    sheet = entry['sheet']
    if a.replace and a.heading:
        sheet = sheet.split('\n## ' + a.heading)[0].rstrip()
    entry['sheet'] = sheet.rstrip() + '\n\n' + block + '\n'

    json.dump(data, open(a.backup, 'w', encoding='utf-8'), indent=1)
    words = len(re.findall(r"[A-Za-z']+", block))
    print('%s: added %d lyric lines (%d words)'
          % (entry['song'], block.count('\n') + 1, words))


if __name__ == '__main__':
    main()
