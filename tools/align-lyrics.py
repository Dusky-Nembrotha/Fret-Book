#!/usr/bin/env python3
"""Put lyric lines against the chords they are sung over.

    python3 align-lyrics.py score.gp4 lyrics.txt --song "..." --backup songs.json

Only works on a score that has a vocal track. The vocal line gives the rhythm
of the singing: where each phrase starts, and how many notes are in it. The
lyrics give a sequence of lines with a syllable count each. Lining those two
sequences up is a sequence alignment problem, solved here with the usual
dynamic programme, allowing a lyric line to be sung over two phrases and two
short lines to share one.

It then reports how well the two sequences actually matched. A poor score
means the vocal track is too rough to trust, and you should fall back to
add-lyrics.py, which simply lists the lyrics under the chords.
"""
import argparse
import json
import re
import sys

import guitarpro

VOWELS = re.compile(r'[aeiouy]+', re.I)
WORD = re.compile(r"[A-Za-z']+")


def syllables(line):
    """Rough syllable count. Good enough to compare line lengths."""
    total = 0
    for word in WORD.findall(line):
        word = word.lower().strip("'")
        if not word:
            continue
        groups = VOWELS.findall(word)
        n = len(groups)
        if word.endswith('e') and n > 1 and not word.endswith(('le', 'ee', 'ye')):
            n -= 1
        total += max(1, n)
    return total


def vocal_phrases(track, gap_beats):
    """(start bar, note count) for each sung phrase."""
    onsets = []
    pos = 0.0
    for i, measure in enumerate(track.measures):
        ts = measure.header.timeSignature
        bar_len = ts.numerator * (4.0 / ts.denominator.value)
        if measure.voices:
            at = pos
            for beat in measure.voices[0].beats:
                dur = 4.0 / beat.duration.value
                if beat.duration.isDotted:
                    dur *= 1.5
                tup = beat.duration.tuplet
                if tup.enters > 1:
                    dur = dur * tup.times / tup.enters
                live = [n for n in beat.notes
                        if n.type.name not in ('rest', 'dead')]
                if live:
                    onsets.append((at, i + 1, len(live)))
                at += dur
        pos += bar_len
    if not onsets:
        return []
    phrases, start, notes = [], onsets[0], 0
    for cur, nxt in zip(onsets, onsets[1:] + [None]):
        notes += cur[2]
        if nxt is None or nxt[0] - cur[0] >= gap_beats:
            phrases.append((start[1], notes))
            start, notes = nxt, 0
    return phrases


def align(lines, phrases):
    """Map each lyric line to a phrase. Returns (mapping, mean error)."""
    n, m = len(lines), len(phrases)
    syl = [syllables(t) for t in lines]
    notes = [p[1] for p in phrases]
    BIG = float('inf')
    # cost[i][j] = best cost having placed i lines into j phrases
    cost = [[BIG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def diff(a, b):
        return abs(a - b) / max(1.0, float(max(a, b)))

    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == BIG:
                continue
            base = cost[i][j]
            if i < n and j < m:                    # one line, one phrase
                c = base + diff(syl[i], notes[j])
                if c < cost[i + 1][j + 1]:
                    cost[i + 1][j + 1] = c; back[i + 1][j + 1] = (i, j, 1, 1)
            if i < n and j + 1 < m:                # one line over two phrases
                c = base + diff(syl[i], notes[j] + notes[j + 1]) + 0.25
                if c < cost[i + 1][j + 2]:
                    cost[i + 1][j + 2] = c; back[i + 1][j + 2] = (i, j, 1, 2)
            if i + 1 < n and j < m:                # two lines in one phrase
                c = base + diff(syl[i] + syl[i + 1], notes[j]) + 0.25
                if c < cost[i + 2][j + 1]:
                    cost[i + 2][j + 1] = c; back[i + 2][j + 1] = (i, j, 2, 1)
            if j < m:                              # instrumental phrase
                c = base + 0.6
                if c < cost[i][j + 1]:
                    cost[i][j + 1] = c; back[i][j + 1] = (i, j, 0, 1)

    best_j, best = None, BIG
    for j in range(m + 1):
        if cost[n][j] < best:
            best, best_j = cost[n][j], j
    if best_j is None or best == BIG:
        return None, BIG

    mapping = {}
    i, j = n, best_j
    while back[i][j]:
        pi, pj, di, dj = back[i][j]
        for k in range(di):
            mapping[pi + k] = phrases[pj][0]
        i, j = pi, pj
    placed = max(1, len([k for k in mapping]))
    return mapping, best / placed


def sibling(filename, name):
    """Import a sibling script whose filename is not a valid module name."""
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_converter():
    """Reuse the chord naming from the sibling converter."""
    return sibling('gp-to-fretbook.py', 'gp2fb')


SPEAKER = re.compile(r'^\s*([A-Z][A-Za-z.\' ]{1,28}):\s*$')
MARKER = re.compile(r"^\s*[\[(]\s*((?:intro|verse|chorus|pre[- ]?chorus|bridge|outro|interlude|solo|refrain|instrumental|coda|tag|hook|break)[A-Za-z0-9 '-]{0,18}?)\s*:?\s*[\])]\s*$", re.I)
# "Chorus", or 'Intro "Brother Against Brother"' - a bare section word
BARE = re.compile(r'^\s*(intro|verse|chorus|pre[- ]?chorus|bridge|outro|interlude|solo|refrain|instrumental|coda|tag|hook|break)\b[^a-zA-Z]{0,3}([A-Za-z0-9\u2018\u2019\u201c\u201d\' .-]{0,40})\s*$', re.I)


def build_sheet(song, gp2fb, raw, mapping, lines, note=''):
    """Lyrics, each preceded by the chords of the bars it is sung over."""
    tracks = gp2fb.guitar_tracks(song)
    nbars = min(len(t.measures) for t in tracks)
    chords = {}
    for i in range(nbars):
        pitches, low = gp2fb.bar_pitches(tracks, i)
        if pitches:
            chords[i + 1] = gp2fb.name_chord(set(pitches), low)

    starts = [mapping.get(i) for i in range(len(lines))]
    out = []
    if note:
        out += [note, '']

    idx = 0
    for raw_line in raw.replace('\r', '').split('\n'):
        text = raw_line.strip()
        if not text:
            if out and out[-1]:
                out.append('')
            continue
        label = SPEAKER.match(text) or MARKER.match(text) or BARE.match(text)
        if label:
            if out and out[-1]:
                out.append('')
            out.append('## ' + label.group(1).strip())
            continue
        if idx >= len(lines) or lines[idx] != text:
            out.append(text)
            continue
        here = starts[idx]
        nxt = next((s for s in starts[idx + 1:] if s), None)
        idx += 1
        if here is None:
            out.append(text)
            continue
        end = (nxt - 1) if nxt and nxt > here else here
        seq = []
        for bar in range(here, min(end, here + 7) + 1):
            c = chords.get(bar)
            if c and (not seq or seq[-1] != c):
                seq.append(c)
        if not seq:
            out.append(text)
        elif len(seq) == 1:
            out.append('[%s]%s' % (seq[0], text))
        else:
            out.append(' | '.join('[%s]' % c for c in seq) + ' |')
            out.append(text)
    while out and not out[-1].strip():
        out.pop()
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score')
    ap.add_argument('lyrics')
    ap.add_argument('--gap', type=float, default=2.0,
                    help='beats of silence that end a phrase')
    ap.add_argument('--backup', help='Fretbook backup JSON to write into')
    ap.add_argument('--song', help='song title in that backup')
    ap.add_argument('--note', default='')
    ap.add_argument('--max-mismatch', type=float, default=0.45)
    ap.add_argument('--by-sections', action='store_true',
                    help='anchor whole stanzas to the score markers')
    a = ap.parse_args()

    song = guitarpro.parse(a.score)
    vocals = [t for t in song.tracks if 'vocal' in (t.name or '').lower()
              or 'voice' in (t.name or '').lower()]

    raw = open(a.lyrics, encoding='utf-8', errors='replace').read()
    raw = sibling('add-lyrics.py', 'addlyr').repair(raw)
    gp2fb = load_converter()

    if not vocals or a.by_sections:
        if not a.by_sections:
            print('No vocal track, so falling back to section anchors.')
        sheet = by_sections(song, gp2fb, raw, a.note)
        if sheet is None:
            sys.exit('That score has neither a vocal track nor section markers.')
        print('placed %d stanzas against the score\'s own section markers'
              % len([x for x in raw.split('\n\n') if x.strip()]))
        if not a.backup:
            print(sheet[:400]); return
        data = json.load(open(a.backup, encoding='utf-8'))
        hits = [e for e in data['imports']
                if (a.song or '').lower() in e['song'].lower()]
        if len(hits) != 1:
            sys.exit('%d songs match %r' % (len(hits), a.song))
        hits[0]['sheet'] = sheet
        json.dump(data, open(a.backup, 'w', encoding='utf-8'), indent=1)
        print('wrote %s into %s' % (hits[0]['song'], a.backup))
        return
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))

    all_lines = [l.strip() for l in raw.replace('\r', '').split('\n')]
    lines = [l for l in all_lines
             if l and not SPEAKER.match(l) and not MARKER.match(l)
             and not BARE.match(l)]

    phrases = vocal_phrases(vocals[0], a.gap)
    mapping, err = align(lines, phrases)
    bars = [mapping[i] for i in sorted(mapping)] if mapping else []
    print('lyric lines:   %d' % len(lines))
    print('vocal phrases: %d  (gap %.1f beats)' % (len(phrases), a.gap))
    print('mean mismatch: %.3f  (0 is perfect, over %.2f is not trusted)'
          % (err, a.max_mismatch))
    print('placed:        %d lines, first at bar %s, last at bar %s'
          % (len(bars), bars[0] if bars else '-', bars[-1] if bars else '-'))
    print('in order:      %s' % all(b <= c for b, c in zip(bars, bars[1:])))

    if err > a.max_mismatch:
        sys.exit('Mismatch too high to trust. Use add-lyrics.py instead.')
    if not a.backup:
        return

    sheet = build_sheet(song, gp2fb, raw, mapping, lines, a.note)
    data = json.load(open(a.backup, encoding='utf-8'))
    needle = (a.song or '').lower()
    hits = [e for e in data['imports'] if needle in e['song'].lower()]
    if len(hits) != 1:
        sys.exit('%d songs match %r' % (len(hits), a.song))
    hits[0]['sheet'] = sheet
    json.dump(data, open(a.backup, 'w', encoding='utf-8'), indent=1)
    print('wrote %s into %s' % (hits[0]['song'], a.backup))




# ---------------------------------------------------------------- sections
# A bridge is normally sung, so it is not in here. Intro is, because a score's
# "Intro" marker is the instrumental opening even when a vocal cue follows it.
INSTRUMENTAL = re.compile(
    r'intro|interlude|outro|solo|instrumental|canon|riff|break',
    re.I)
CHORUS = re.compile(r'chorus', re.I)


def markers(song, gp2fb):
    tracks = gp2fb.guitar_tracks(song)
    nbars = min(len(t.measures) for t in tracks)
    out = []
    for i in range(nbars):
        for t in tracks:
            h = t.measures[i].header
            if h.marker and h.marker.title:
                out.append((i + 1, h.marker.title.strip()))
                break
    return out, nbars, tracks


def by_sections(song, gp2fb, raw, note=''):
    """Interleave whole stanzas with the chords of the section they sit in.

    Used when a score has no vocal track. The anchors are the transcriber's
    own section markers, so this claims nothing finer than "this verse is
    sung over these chords". Instrumental sections are never given lyrics; if
    there are more stanzas than sections, the extra ones carry on under the
    heading they follow.
    """
    marks, nbars, tracks = markers(song, gp2fb)
    if not marks:
        return None

    chords = {}
    for i in range(nbars):
        pitches, low = gp2fb.bar_pitches(tracks, i)
        if pitches:
            chords[i + 1] = gp2fb.name_chord(set(pitches), low)

    def chord_rows(bar):
        nxt = min([b for b, _ in marks if b > bar] + [nbars + 1])
        seq = []
        for b in range(bar, min(nxt, bar + 9)):
            c = chords.get(b)
            if c and (not seq or seq[-1] != c):
                seq.append(c)
        rows = []
        for k in range(0, len(seq), 4):
            rows.append(' | '.join('[%s]' % c for c in seq[k:k + 4]) + ' |')
        return rows

    vocal = [m for m in marks if not INSTRUMENTAL.search(m[1])]
    stanzas = [t for t in raw.replace('\r', '').split('\n\n') if t.strip()]

    # Which stanzas are the chorus? Either they say so, or they are the ones
    # that come round again.
    bodies = [re.sub(r'\s+', ' ', t.strip().lower()) for t in stanzas]
    repeated = {b for b in bodies if bodies.count(b) > 1}
    is_chorus = []
    for t, b in zip(stanzas, bodies):
        head = t.strip().split('\n')[0]
        m = MARKER.match(head) or BARE.match(head)
        is_chorus.append(bool(m and CHORUS.search(head)) or b in repeated)

    chorus_slots = [i for i, m in enumerate(vocal) if CHORUS.search(m[1])]
    chorus_stanzas = [i for i, c in enumerate(is_chorus) if c]

    def norm(t):
        return re.sub(r'[^a-z0-9 ]', '', t.lower()).strip()

    # Transcribers often name a marker after the line sung there. Where that
    # matches a stanza's opening line, it is the strongest anchor available.
    anchors = []
    used_v = set()
    for si, stanza in enumerate(stanzas):
        first = norm(stanza.strip().split('\n')[0])
        if len(first) < 8:
            continue
        for vi, (_, name) in enumerate(vocal):
            if vi in used_v:
                continue
            n = norm(name)
            if len(n) >= 8 and (first.startswith(n) or n.startswith(first)):
                anchors.append((si, vi))
                used_v.add(vi)
                break

    if chorus_slots and len(chorus_slots) == len(chorus_stanzas):
        for si, vi in zip(chorus_stanzas, chorus_slots):
            if si not in dict(anchors) and vi not in used_v:
                anchors.append((si, vi))
                used_v.add(vi)

    # keep only anchors that run in order, then fill the runs between them
    anchors.sort()
    kept, last = [], (-1, -1)
    for si, vi in anchors:
        if si > last[0] and vi > last[1]:
            kept.append((si, vi))
            last = (si, vi)
    anchors = kept

    assigned = dict(anchors)
    bounds = list(zip([(-1, -1)] + anchors, anchors + [(len(stanzas), len(vocal))]))
    for (s0, v0), (s1, v1) in bounds:
        free = [v for v in range(v0 + 1, v1) if v not in assigned.values()]
        n = 0
        for si in range(s0 + 1, s1):
            if si in assigned:
                continue
            if n < len(free):
                assigned[si] = free[n]
                n += 1

    out = [note, ''] if note else []
    for si, stanza in enumerate(stanzas):
        lines = [l.strip() for l in stanza.split('\n') if l.strip()]
        label = None
        m0 = MARKER.match(lines[0]) or BARE.match(lines[0]) if lines else None
        if m0:
            label = ' '.join(g.strip(' \u201c\u201d\u2018\u2019\'"')
                             for g in m0.groups() if g and g.strip()).strip()
            lines = lines[1:]
        if not lines:
            continue
        vi = assigned.get(si)
        if vi is not None:
            slot = vocal[vi]
            out.append('')
            out.append('## ' + (label or slot[1]).rstrip('. '))
            out.extend(chord_rows(slot[0]))
        else:
            out.append('')          # carries on under the previous heading
        out.extend(lines)
    while out and not out[0].strip():
        out.pop(0)
    return '\n'.join(out)


if __name__ == '__main__':
    main()
