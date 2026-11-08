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
# Intervals above the LOWEST sounding note. In riff-based music the bottom
# note is the root; searching every rotation for the "fullest" chord invents
# names like C#maj7 for what is plainly an Ab power chord.
STACKS = {
    (0, 7): '5',
    (0, 3, 7): 'm',
    (0, 4, 7): '',
    (0, 3, 6): 'dim',
    (0, 4, 8): 'aug',
    (0, 2, 7): 'sus2',
    (0, 5, 7): 'sus4',
    (0, 5, 10): '7sus4',
    (0, 7, 10): '7sus4',
    (0, 3, 7, 10): 'm7',
    (0, 4, 7, 10): '7',
    (0, 4, 7, 11): 'maj7',
    (0, 3, 7, 11): 'mMaj7',
    (0, 3, 6, 10): 'm7b5',
    (0, 3, 6, 9): 'dim7',
    (0, 4, 7, 9): '6',
    (0, 3, 7, 9): 'm6',
    (0, 2, 4, 7): 'add9',
    (0, 4, 7, 14 % 12): 'add9',
}

PER_LINE = 4          # bars per line in the finished chart
# Tracks that are not rhythm guitar. A vocal line in particular will wreck the
# chord naming, because a single melody note gets mixed in with the harmony.
SKIP_WORDS = ('string', 'orchestr', 'violin', 'cello', 'choir', 'koto',
              'shot', 'canon', 'piano', 'horn', 'trumpet', 'flute',
              'vocal', 'voice', 'vox', 'sing', 'lyric', 'melody')


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


def name_stack(pitches):
    """Name one simultaneous stack of notes, rooted on its lowest."""
    if len(pitches) < 2:
        return None
    root = min(pitches)
    ivals = tuple(sorted({(p - root) % 12 for p in pitches}))
    if len(ivals) < 2:
        return None                      # octaves only
    name = STACKS.get(ivals)
    if name is None:
        if 7 in ivals:                   # a power chord with extra colour
            name = '5'
        else:
            return None                  # a passing shape, not a chord
    return NAMES[root % 12] + name


STANDARD = [64, 59, 55, 50, 45, 40]   # e B G D A E, high string first


def tuning_shift(tracks):
    """How far the guitars are detuned, in semitones, or 0 if standard/odd."""
    for t in tracks:
        values = [s.value for s in t.strings]
        if len(values) != 6:
            continue
        offsets = {v - s for v, s in zip(values, STANDARD)}
        if len(offsets) == 1:
            shift = offsets.pop()
            if shift:
                return shift
    return 0


def rhythm_track(tracks):
    """The guitar carrying the chords: the one playing the most stacks."""
    def stacks(t):
        n = 0
        for m in t.measures:
            for v in m.voices[:1]:
                for b in v.beats:
                    live = [x for x in b.notes
                            if x.type.name not in ('rest', 'dead')]
                    if len(live) > 1:
                        n += 1
        return n
    return max(tracks, key=stacks)


def chords_by_bar(track):
    """{bar number: [chord names in the order they are struck]}"""
    out = {}
    for i, measure in enumerate(track.measures):
        seq = []
        for voice in measure.voices[:1]:
            for beat in voice.beats:
                live = [track.strings[n.string - 1].value + n.value
                        for n in beat.notes
                        if n.type.name not in ('rest', 'dead')]
                name = name_stack(live)
                if name and (not seq or seq[-1] != name):
                    seq.append(name)
        if seq:
            out[i + 1] = seq
    return out


def convert(path, every, collapse=True):
    song = guitarpro.parse(path)
    tracks = guitar_tracks(song)
    lead = rhythm_track(tracks)
    nbars = len(lead.measures)
    bar_chords = chords_by_bar(lead)

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
        for chord in bar_chords.get(i + 1, []):
            if collapse and pending and pending[-1] == chord:
                continue
            pending.append(chord)
    emit()

    while lines and not lines[0].strip():
        lines.pop(0)
    return song, [lead], nbars, '\n'.join(lines)


def title_from(song, path, artist=''):
    """Best available song title: the score's own, else tidied from the name."""
    for candidate in (song.title, song.subtitle):
        if candidate and candidate.strip():
            return candidate.strip()
    stem = os.path.basename(path).rsplit('.', 1)[0]
    # drop bracketed tags these files often carry, e.g. "[总谱]"
    stem = re.sub(r'[\[【(（][^\]】)）]*[\]】)）]', ' ', stem)
    stem = stem.replace('_', ' ').replace('-', ' ')
    # "iced earth devil to pay" -> "devil to pay"
    for name in (artist, song.artist or ''):
        name = (name or '').strip().lower()
        if name and stem.lower().startswith(name):
            stem = stem[len(name):]
    stem = ' '.join(stem.split())
    small = {'to', 'at', 'the', 'a', 'of', 'in', 'on', 'and', 'all'}
    words = [w if (w.lower() in small and i) else w[:1].upper() + w[1:]
             for i, w in enumerate(stem.split())]
    return ' '.join(words) or os.path.basename(path)


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
    ap.add_argument('--note', default='',
                    help='a line of plain text to put at the top of each sheet')
    ap.add_argument('--tuning-note', action='store_true',
                    help='add a note naming the tuning when it is not standard')
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
        notes = []
        if a.note:
            notes.append(a.note)
        if a.tuning_note:
            shift = tuning_shift(tracks)
            if shift:
                notes.append(
                    'Tuned %s a %s. The chords below are the real sounding '
                    'notes, so tune %s and tap KEY %s once to get the shapes '
                    'you actually play.'
                    % ('down' if shift < 0 else 'up',
                       'semitone' if abs(shift) == 1 else '%d semitones' % abs(shift),
                       'down' if shift < 0 else 'up',
                       '+' if shift < 0 else '-'))
        if notes:
            sheet = '\n\n'.join(notes) + '\n\n' + sheet

        title = a.song or title_from(song, path, a.artist)
        entries.append({
            'id': 'gp%d%03d' % (int(time.time() * 1000), n),
            'added': int(time.time() * 1000),
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
