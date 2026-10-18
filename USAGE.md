# Using Tallowmark

Five walkthroughs, one per surface, all with real output. Set a store first if you
want to try them side by side:

```bash
export TALLOWMARK_FILE=/tmp/tallowmark-demo.json
```

## 1. Wax batches (`batch`)

Create batches. Identity is case-folded, so casing can never split a batch in two,
but the display name keeps the casing you typed first.

```console
$ tallowmark batch new Lavender
created batch: Lavender
$ tallowmark batch new Beeswax
created batch: Beeswax
$ tallowmark batch new lavender
batch already exists: lavender        # exit 1
$ tallowmark batch new "   "
batch name required                   # exit 1
$ tallowmark batch list
Lavender
Beeswax
```

Look one up in any casing:

```console
$ tallowmark batch show LaVeNdEr
Lavender
────────────────────────
created: 2026-10-18T19:14:52Z
dips: 2
cure: 2d 0h left
notes: 1
```

Empty store:

```console
$ tallowmark batch list
no batches yet
```

A batch that does not exist:

```console
$ tallowmark batch show Ghost
unknown batch: Ghost                  # exit 1
```

## 2. Dip counting (`dip`)

Every `dip add` records a timestamp and prints the running count.

```console
$ tallowmark dip add Lavender
Lavender: 1 dip
$ tallowmark dip add Lavender
Lavender: 2 dips
$ tallowmark dip list Lavender
[2026-10-18T19:14:53Z] dip 2
[2026-10-18T19:14:53Z] dip 1
```

`dip list` is newest-first; `dip add` on a batch with no dips yet is a normal add, and
`dip list` on a batch with no dips prints:

```console
$ tallowmark dip list Beeswax
no dips yet
```

Dips are append-only: there is no edit or delete, which is the point of a counter you
can trust.

## 3. Wax batch notes (`note`)

Notes are free text joined from the rest of the command line, stamped in UTC, and
read back oldest-first.

```console
$ tallowmark note add Lavender poured at 60C, 6% fragrance
note added to Lavender
$ tallowmark note add Lavender top-up pour at 58C
note added to Lavender
$ tallowmark note list Lavender
[2026-10-18T19:14:53Z] poured at 60C, 6% fragrance
[2026-10-18T19:14:53Z] top-up pour at 58C
```

```console
$ tallowmark note list Beeswax
no notes yet
$ tallowmark note add Lavender
note text required                    # exit 1
```

Both `note add` and `note list` reject a batch that does not exist with the same
message -- `unknown batch: Ghost`, exit 1 -- so a typo never silently reads as "no
notes".

## 4. Cure countdown (`cure`)

```console
$ tallowmark cure set Lavender 48
cure set: Lavender 48h
$ tallowmark cure status Lavender
Lavender: 2d 0h left
```

Remaining seconds are rounded **up** to whole hours, so a just-set 48-hour cure reads
`2d 0h left`. Fractional hours are accepted:

```console
$ tallowmark cure set Lavender 1.5
cure set: Lavender 1.5h
$ tallowmark cure status Lavender
Lavender: 0d 2h left
```

Once the time is up (or past) the status becomes `cured`:

```console
$ tallowmark cure status Lavender
Lavender: cured
```

Every bad hours value prints the same single line and exits 1 -- never an argparse
traceback and never exit 2:

```console
$ tallowmark cure set Lavender 0
hours must be a positive number       # exit 1
$ tallowmark cure set Lavender abc
hours must be a positive number       # exit 1
$ tallowmark cure set Lavender -5
hours must be a positive number       # exit 1
$ tallowmark cure set Lavender
hours must be a positive number       # exit 1
```

Clear it and the batch reports `no cure set` again:

```console
$ tallowmark cure clear Lavender
cure cleared: Lavender
$ tallowmark cure status Lavender
Lavender: no cure set
```

## 5. Status overview (`list`)

The one command that answers "where is every batch right now". Every batch gets a
cure status, including the ones that never had a cure.

```console
$ tallowmark list
Lavender: 2 dips | 2d 0h left
Beeswax: 1 dip | no cure set
Cedar & Fig: 0 dips | cured
```

```console
$ tallowmark list
no batches yet                        # exit 0
```

## Errors and exit codes

| Situation | Message (one line, stderr) | Exit |
| --- | --- | --- |
| Batch does not exist | `unknown batch: <name>` | 1 |
| Duplicate batch | `batch already exists: <name>` | 1 |
| Blank batch name | `batch name required` | 1 |
| Empty note text | `note text required` | 1 |
| Bad cure hours | `hours must be a positive number` | 1 |
| Corrupt / unreadable store | `cannot read store: <path>` | 1 |
| Unknown subcommand or flag | argparse usage | 2 |
| Success | the command's own line(s) on stdout | 0 |

Results go to stdout, errors to stderr, and there is no ANSI colour, so
`tallowmark list | grep Beeswax` behaves.

## Poking the store by hand

The store is a single JSON document, so you can read or adjust it with any JSON
tool. It is re-validated on load; if it cannot be parsed or a batch is malformed,
every command prints `cannot read store: <path>` and exits 1 instead of guessing.

```console
$ tallowmark batch list
cannot read store: /tmp/tallowmark-demo.json   # exit 1
```
