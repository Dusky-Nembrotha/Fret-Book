#!/usr/bin/env python3
"""Turn a Guitar Pro score (.gp3/.gp4/.gp5) into a Fretbook chord sheet.

    python3 gp-to-fretbook.py score.gp5 --song "The Devil To Pay" --artist "Iced Earth"

Writes a Fretbook backup JSON. Open Fretbook, choose Backup & restore, then
Restore, and pick the file.

The chords are worked out from the notes actually in the score, not guessed.
For each bar it gathers every pitch sounding on the guitar tracks, reduces them
to pitch classes and names the chord that fits. Two-note shapes come out as
power chords ("E5") because that is what is being played. Anything that fits no
known shape falls back to the lowest note as a power chord, which is the honest
answer for a riff that is not really a chord at all.

Needs pyguitarpro:  pip install pyguitarpro
"""
import argparse
import json
import os
import re
import sys
import time

import guitarpro

NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

# interval set -> Fretbook quality suffix. Richer shapes are preferred, so a
# four-note set is named as a 7th rather than as the triad hiding inside it.
SHAPES = [
    (frozenset({0, 4, 7, 11}), 'maj7'),
    (frozenset({0, 3, 7, 10}), 'm7'),
    (frozenset({0, 4, 7, 10}), '7'),
    (frozenset({0, 3, 6, 10}), 'm7b5'),
    (frozenset({0, 3, 6, 9}), 'dim7'),
    (frozenset({0, 4, 7, 9}), '6'),
    (frozenset({0, 2, 7}), 'sus2'),
    (frozenset({0, 5, 7}), 'sus4'),
    (frozenset({0, 4, 7}), ''),
    (frozenset({0, 3, 7}), 'm'),
    (frozenset({0, 3, 6}), 'dim'),
    (frozenset({0, 4, 8}), 'aug'),
    (frozenset({0, 7}), '5'),
    (frozenset({0, 5}), '5'),
]

PER_LINE = 4          # bars per line in the finished chart
SKIP_WORDS = ('string', 'orchestr', 'violin', 'cello', 'choir', 'koto',
              'shot', 'canon', 'piano', 'horn', 'trumpet', 'flute')


def guitar_tracks(song):
    """Guitar tracks only: no drums, no bass, no orchestra."""
    out = []
    for t in song.tracks:
        if t.isPercussionTrack:
            continue
        name = (t.name or '').lower()
        if 'bass' in name or any(w in name for w in SKIP_WORDS):
            continue
        out.append(t)
    return out or [t for t in song.tracks if not t.isPercussionTrack]


def name_chord(pitches, bass):
    """Name the chord formed by a set of MIDI pitches."""
    if not pitches:
        return None
    pcs = {p % 12 for p in pitches}
    best = None
    for root in sorted(pcs):
        ivals = frozenset((p - root) % 12 for p in pcs)
        for shape, suffix in SHAPES:
            if shape == ivals:
                # prefer the fuller shape, then the one rooted on the bass note
                score = (len(shape), root == bass % 12)
                if best is None or score > best[0]:
                    best = (score, NAMES[root] + suffix)
    if best:
        return best[1]
    return NAMES[bass % 12] + '5'


def bar_pitches(tracks, i):
    pitches, lowest = [], None
    for t in tracks:
        measure = t.measures[i]
        for voice in measure.voices:
            for beat in voice.beats:
                for note in beat.notes:
                    if note.type.name in ('rest', 'dead'):
                        continue
                    val = t.strings[note.string - 1].value + note.value
                    pitches.append(val)
                    if lowest is None or val < lowest:
                        lowest = val
    return pitches, lowest


def convert(path, every, collapse=True):
    song = guitarpro.parse(path)
    tracks = guitar_tracks(song)
    nbars = min(len(t.measures) for t in tracks)

    lines, pending, current_section = [], [], None

    def emit():
        while pending:
            chunk = pending[:PER_LINE]
            del pending[:PER_LINE]
            lines.append(' | '.join('[%s]' % c for c in chunk) + ' |')

    for i in range(nbars):
        marker = None
        for t in tracks:
            header = t.measures[i].header
            if header.marker and header.marker.title:
                marker = header.marker.title.strip()
                break
        if marker and marker != current_section:
            emit()
            current_section = marker
            if lines:
                lines.append('')
            lines.append('## ' + marker)

        if i % every:
            continue
        pitches, lowest = bar_pitches(tracks, i)
        if not pitches:
            continue
        chord = name_chord(set(pitches), lowest)
        if not chord:
            continue
        if collapse and pending and pending[-1] == chord:
            continue
        pending.append(chord)
    emit()

    while lines and not lines[0].strip():
        lines.pop(0)
    return song, tracks, nbars, '\n'.join(lines)


def title_from(song, path):
    """Best available song title: the score's own, else the file name."""
    for candidate in (song.title, song.subtitle):
        if candidate and candidate.strip():
            return candidate.strip()
    stem = os.path.basename(path).rsplit('.', 1)[0]
    # strip the bracketed Chinese tags these files often carry
    return re.sub(r'[\[【(（][^\])】）]*[\]】)）]', '', stem).strip() or stem


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scores', nargs='+', help='one or more .gp3/.gp4/.gp5 files')
    ap.add_argument('--song', default='',
                    help='song title; only valid with a single score. '
                         'Otherwise each title comes from the score itself.')
    ap.add_argument('--artist', default='')
    ap.add_argument('--source', default='Guitar Pro score')
    ap.add_argument('--url', default='')
    ap.add_argument('--every', type=int, default=1,
                    help='read a chord every N bars (default every bar)')
    ap.add_argument('--keep-repeats', action='store_true',
                    help='do not collapse a chord repeated across bars')
    ap.add_argument('-o', '--out', default='fretbook-import.json')
    a = ap.parse_args()

    if a.song and len(a.scores) > 1:
        sys.exit('--song only makes sense with one score. '
                 'With several, the title is read from each file.')

    entries, failures = [], []
    for n, path in enumerate(a.scores):
        try:
            song, tracks, nbars, sheet = convert(path, a.every,
                                                 not a.keep_repeats)
        except Exception as exc:
            failures.append('%s: %s' % (os.path.basename(path), exc))
            continue
        if not sheet.strip():
            failures.append('%s: no playable notes on any guitar track'
                            % os.path.basename(path))
            continue
        title = a.song or title_from(song, path)
        entries.append({
            'id': 'gp%d%03d' % (int(time.time() * 1000), n),
            'song': title,
            'artist': a.artist or (song.artist or '').strip(),
            'label': 'From score',
            'source': a.source,
            'url': a.url,
            'sheet': sheet,
            'key': '',
            'capo': 0,
            'meta': {},
        })
        print('%-44s %3d bars, %3d chords, tracks: %s'
              % (title, nbars, sheet.count('['),
                 ', '.join(t.name for t in tracks)))

    for f in failures:
        print('SKIPPED  ' + f, file=sys.stderr)
    if not entries:
        sys.exit('Nothing converted.')

    payload = {
        'app': 'fretbook',
        'version': 1,
        'exported': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'imports': entries,
        'prefs': {},
        'settings': {},
    }
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=1)
    print('\n%d song%s written to %s'
          % (len(entries), '' if len(entries) == 1 else 's', a.out))
    print('In Fretbook: Backup & restore, then Restore, and pick that file.')


if __name__ == '__main__':
    main()
