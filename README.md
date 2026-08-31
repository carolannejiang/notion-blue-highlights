# notion-blue-highlights

Automatically collects every blue-highlighted piece of text across a Notion
workspace into a single Notion database.

A small dependency-free Python script talks to the official Notion API,
scheduled by `launchd` on macOS. Each run is **incremental**: it only scans
pages edited since the last run.

## How it works

- Finds rich text (and whole blocks) colored `blue_background` on every page
  the integration can access.
- Upserts rows into a Notion database, keyed by `block_id#span_index` — re-runs
  never duplicate, edited highlights update their row in place.
- Highlights deleted from a page get their row flipped to **Removed** instead
  of silently lingering.
- Each row carries: the full highlight text (`Note`), a live mention link to
  the source page (`Page`), an auto-stamped `Captured` time, `Status`, and
  `Last seen`.

## Setup

1. **Create the target database** in Notion with these properties:
   `Highlight` (title), `Note` (text), `Page` (text), `Source page` (URL),
   `Block ID` (text), `Status` (select: Active, Removed), `Last seen` (date),
   `Captured` (created time).
2. **Create an internal integration** at
   [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
   with *Read*, *Insert*, and *Update content* capabilities.
3. **Connect the integration** (page `•••` menu → Connections) to the target
   database's page and to every top-level page you want scanned — connections
   cascade to subpages.
4. **Configure**: `cp config.example.json config.json`, then fill in the
   integration token and the database ID (the 32-hex ID in the database URL).
   `exclude_pages` takes page IDs to skip. Keep `config.json` private
   (`chmod 600`); it is gitignored.
5. **Run the first backfill**: `/usr/bin/python3 sync.py`
   (use the system Python — some python.org builds lack SSL certificates).

## Scheduling (macOS)

Edit the paths in `com.notion-blue-highlights.plist` to match your machine,
then:

```bash
cp com.notion-blue-highlights.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.notion-blue-highlights.plist
```

The included schedule runs at 3 PM, 6 PM, and 12 AM local time
(`StartCalendarInterval`); swap in `StartInterval` with a number of seconds
for fixed-interval runs instead. Output goes to `sync.log`.

## Notes

- To collect a different color, change `blue_background` in `sync.py`
  (Notion colors: `yellow_background`, `green_background`, etc.).
- Delete `state.json` to force a full rescan.
- Coverage is exactly the set of pages connected to the integration.
