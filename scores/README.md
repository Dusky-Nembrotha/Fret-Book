# Drop Guitar Pro scores here

Put `.gp3`, `.gp4` or `.gp5` files in this folder, then run:

    cd "/media/charlie/Extreme SSD/Claude Code/Fret-Book"
    python3 tools/gp-to-fretbook.py scores/*.gp5 --artist "Iced Earth" -o songs.json

That writes `songs.json`. In Fretbook, tap **Backup & restore**, then
**Restore**, and pick it. Each score becomes a song in the songbook.

Needs `pyguitarpro` installed: `pip install pyguitarpro`

The scores themselves are not committed — this folder is in `.gitignore`.

## The three Iced Earth Gettysburg scores

Free Guitar Pro files, one page each. The download button only works in a real
browser, and may want a free account.

- The Devil To Pay — https://m.jitashe.org/tab/58541/
- Hold At All Costs — https://m.jitashe.org/tab/58562/
- High Water Mark — https://m.jitashe.org/tab/182655/
