# notion-blue-highlights

A scheduled script that scans your Notion pages for any text highlighted in a
color you choose and copies each snippet into a single Notion database, with a
link back to its source page, so highlighting becomes a way of clipping.

A single dependency-free Python script talks to the official Notion API and
runs on a schedule. Each run is **incremental**: it only scans pages edited
since the last run, so it stays fast even on a large workspace.

## How it works

- Finds rich text (and whole blocks) highlighted in the configured color on
  every page the integration can access. The default is blue.
- Upserts rows into a Notion database, keyed by `block_id#span_index`. Re-runs
  never duplicate, and edited highlights update their row in place.
- Highlights deleted from a page get their row flipped to **Removed** instead
  of silently lingering.
- Each row carries: the full highlight text (`Note`), a live mention link to
  the source page (`Page`), an auto-stamped `Captured` time, `Status`, and
  `Last seen`.

## Setup

Requires Python 3.8+ (macOS ships one at `/usr/bin/python3`). No packages to
install.

1. **Create an internal integration** at
   [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
   with *Read*, *Insert*, and *Update content* capabilities. Copy its token.
2. **Configure**: `cp config.example.json config.json`, paste the token in,
   then `chmod 600 config.json`. It is gitignored. Set `color` to the
   highlight color to collect: one of `gray`, `brown`, `orange`, `yellow`,
   `green`, `blue`, `purple`, `pink`, or `red`, each with a `_background`
   suffix (for example `yellow_background`). Only one color per database;
   run a second checkout with its own config to collect another.
3. **Create the target database.** Pick (or make) a Notion page to hold it,
   connect the integration to that page (page `•••` menu → Connections), then:

   ```bash
   /usr/bin/python3 sync.py --create-db <page id>
   ```

   The page ID is the 32-hex string at the end of the page URL. This creates a
   "Highlights" database with the right schema and writes its ID into
   `config.json`.

   (To build it by hand instead, the properties are: `Highlight` (title),
   `Note` (text), `Page` (text), `Source page` (URL), `Block ID` (text),
   `Status` (select: Active, Removed), `Last seen` (date), `Captured`
   (created time). Paste the database ID into `config.json`.)
4. **Connect the integration to the pages you want scanned.** Connections
   cascade to subpages, so connecting a few top-level pages usually covers
   everything. This is also your privacy boundary: the script can only read
   pages it has been explicitly connected to, so leave anything you don't
   want scanned unconnected. `exclude_pages` in `config.json` takes page IDs
   to skip within a connected tree.
5. **Run the first backfill**: `/usr/bin/python3 sync.py`
   (use the system Python; some python.org builds lack SSL certificates).

## Scheduling

### macOS (launchd)

```bash
./install.sh
```

This writes the launchd plist with the path to this checkout and loads it.
The schedule runs at 3 PM, 6 PM, and 12 AM local time; edit
`StartCalendarInterval` in `com.notion-blue-highlights.plist` and re-run
`install.sh` to change it (or swap in `StartInterval` with a number of
seconds for fixed-interval runs). Output goes to `sync.log` in the repo.

### Linux or anywhere with cron

```
0 15,18,0 * * * /usr/bin/python3 /path/to/notion-highlights/sync.py >> /path/to/notion-highlights/sync.log 2>&1
```

## Notes

- Changing `color` in `config.json` does not retroactively remove rows of
  the old color; delete `state.json` and rescan, and old rows flip to
  Removed.
- Delete `state.json` to force a full rescan.
- Coverage is exactly the set of pages connected to the integration. A `404`
  in the log for a page means it was deleted, moved, or disconnected.

## License

MIT
