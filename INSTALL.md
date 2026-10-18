# Installing Tallowmark

Tallowmark is one Python file plus packaging metadata. It has **no third-party
runtime dependencies** -- the only declared dependency is the test runner.

## Prerequisites (installed by you, once)

| Requirement | Notes |
| --- | --- |
| Python 3.9 or newer | `python3 --version`. Standard library only; nothing to compile. |
| pip | Ships with Python: `python3 -m pip --version`. |

There is no database, no service and no system package to install. If you have a
Python 3.9+ interpreter you already have everything the tool needs.

**Package manager:** pip only (the lockfile-equivalent is `requirements.txt`; the
console script is declared in `pyproject.toml`).

## Step 1 -- run the installer

```bash
bash install.sh
```

It performs, in order, and then **exits** (it never starts the tool):

1. `python3 -m pip install --upgrade pip setuptools wheel` -- fresh packaging
   tooling, so the modern editable install works.
2. `python3 -m pip install -r requirements.txt` -- pytest, used only by the tests.
3. `python3 -m pip install -e .` -- puts the `tallowmark` console script on your
   PATH (declared in `pyproject.toml`).
4. Imports the module as a self-check, so a broken environment fails here instead
   of at first use.

The script uses no `sudo` and installs no system packages. It is safe to re-run.

## Step 2 -- confirm it is installed

```bash
tallowmark --version      # tallowmark 1.0.0
tallowmark --help         # every command group, one line each
```

If you prefer not to install anything, the tool runs straight from the checkout:

```bash
python3 tallowmark.py --help
```

## Step 3 -- run it

```bash
tallowmark batch new Lavender
tallowmark dip add Lavender
tallowmark list
```

There is nothing to seed and nothing to configure: the store file is created on the
first command.

## Step 4 -- try the demo (optional)

```bash
bash demo.sh
```

Walks every command against a throwaway store in `mktemp -d`, including the error
paths, and exits 0. Your own store is never touched.

## Store location

| Environment | Path |
| --- | --- |
| Default | `~/.tallowmark/store.json` |
| Override | `export TALLOWMARK_FILE=/path/to/store.json` |

The parent directory is created automatically. Every write is atomic (temp file plus
`os.replace`), so an interrupted command cannot truncate your batches.

## Run the tests

```bash
python3 -m pytest
```

Uses only pytest plus the standard library, needs no network and no fixtures beyond
the ones it writes into pytest's `tmp_path`.

## Upgrading / uninstalling

```bash
python3 -m pip install -e . --upgrade     # upgrade in place
python3 -m pip uninstall tallowmark       # remove the console script
```

Your data stays in `$TALLOWMARK_FILE` either way; delete that file to start fresh.
