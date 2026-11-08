# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Fretbook — a guitar songbook. You paste a chord sheet copied from a site like
Ultimate Guitar, it strips the page clutter, and you get a clean, transposable
sheet with tappable chord diagrams. Everything is stored in the browser; there
is no account and no server.

## The whole app is one file

`index.html` (~1,600 lines) holds the markup, CSS and JavaScript. There is no
build step, no package manager, no test runner and no dependency other than
Google Fonts over CDN. Open the file in a browser and it runs.

**`fretbook.html` is a byte-identical copy of `index.html`.** Both are committed.
Nothing references `fretbook.html`, and GitHub Pages serves `index.html`. If you
edit one, either edit both or delete the copy — a silent divergence here is the
most likely way to ship a confusing bug.

## Running and deploying

| Task | How |
|---|---|
| Run it | Open `index.html` in a browser, or `python3 -m http.server` in this folder |
| Deploy | Push to `main`. GitHub Pages serves the repo root. |
| Live site | https://dusky-nembrotha.github.io/Fret-Book/ |

Repo is `Dusky-Nembrotha/Fret-Book`, public, default branch `main`.

Both existing commits are "Add files via upload", made through the GitHub web
interface, so git history carries no information about why anything is the way
it is.

## Finding your way around

The JavaScript is one IIFE divided by banner comments. Search for the banner to
jump to a subsystem:

```
/* ---------- music theory ---------- */        note names, chord parsing, transposing
/* ---------- chord shapes ---------- */        OPEN dictionary + FORMS barre templates
/* ---------- diagram ---------- */             chord box as inline SVG
/* ---------- sound ---------- */               Karplus-Strong string synthesis
/* ---------- sheet parsing ---------- */       internal format -> DOM
/* ---------- import ---------- */              foreign chord sheet -> internal format
/* ---------- whole-page paste ---------- */    strip site furniture, pull out title/capo/key
/* ---------- storage ---------- */             localStorage read/write
/* ---------- state + rendering ---------- */   views, song rendering
/* ---------- settings ---------- */            SKINS and preferences
/* ---------- backup & restore ---------- */    JSON export/import
```

CSS has its own banner comments, notably `/* ---- themes ---- */` around line 230.

## The internal sheet format

Songs are stored in a ChordPro-like format, not as the text that was pasted in:

- `[C]` inline before the syllable it lands on
- `## Verse 1` for a section heading
- `@@` prefix, or anything `isTabLine()` recognises, for tab blocks
- a blank line for a gap

`parseSheet()` turns that into blocks; `renderSheet()` turns blocks into HTML and
applies the transpose offset. A line whose text is only bar markers or filler is
rendered "inline" (chords on one line) rather than as chord-over-lyric pairs.

Import goes the other way and is the fiddliest part of the app. `smartImport()`
takes a whole pasted page, guesses where the song starts and ends, harvests
metadata (title, artist, capo, key, tuning, source site), drops navigation junk,
then hands the body to `convertImport()`. The heuristics that decide what is a
chord line live in `isChordTok`, `isChordLine`, `isBarLine`, `isFiller` and
`isTabLine`. Changing any of them affects every future import, so test against
a real pasted page from more than one site.

## Chord rendering

`parseChord()` splits a chord into root, quality and bass note. `normQual()` maps
the many ways people write a quality onto a small internal set; qualities in
`LOSSY` are approximations and the UI is expected to say so.

`voicings()` returns shapes in order of preference: a dedicated entry in `OPEN`
first, then the `FORMS` barre templates transposed up the neck, then a simplified
fallback. `layout()` works out finger numbers and whether there is a barre.
`diagram()` emits the SVG. Results are memoised in `vcache`.

## Storage

Three localStorage keys, all read through `load()` / `save()` which swallow
errors so private browsing degrades rather than crashes:

- `fretbook.imports` — the songbook, an array of song objects
- `fretbook.prefs` — per-song state such as transpose offset
- `fretbook.settings` — theme, text size, left-handed diagrams and so on

`SEED` is deliberately an empty array. The songbook starts empty and is only
ever filled by the user's own imports.

Losing the browser profile loses the songbook, which is why backup and restore
exist. `restoreFrom()` merges rather than replaces, de-duplicating on song id
and on a title-plus-sheet signature.

## It was built as a Claude artifact, and still half assumes it

`IN_CLAUDE` detects the artifact runtime by looking for `window.claude` or for
being in an iframe. The backup button then saves through
`window.claude.use('downloads')` and handles that permission being refused.
Outside the artifact runtime it falls back to `plainDownload()`, an ordinary
blob link.

On GitHub Pages the artifact path is dead code, but the iframe check means any
embedding of the page will take it. If backup downloads ever misbehave on the
live site, that check is the first place to look.

## House style

Charlie is the only user and reads every string in the interface. User-facing
copy is plain English, British spelling, no jargon: "Open Fretbook from claude.ai
in a web browser to download" rather than an error code. Keep it that way.
Error messages say what to do next, not what went wrong internally.
