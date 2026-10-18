#!/usr/bin/env python3
"""Tallowmark -- candle dip counts, wax batch notes and cure countdowns.

A single-user, offline command line tool for a candlemaker. Everything lives in
one JSON document at $TALLOWMARK_FILE (default ~/.tallowmark/store.json), which
is replaced atomically on every write.

Standard library only; Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

STORE_VERSION = 1
SECONDS_PER_HOUR = 3600.0
HOURS_PER_DAY = 24
MIN_SEPARATOR_WIDTH = 24
DEFAULT_STORE_PATH = "~/.tallowmark/store.json"

HOURS_ERROR = "hours must be a positive number"
NAME_ERROR = "batch name required"

Handler = Callable[[argparse.Namespace], int]


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


class UserError(Exception):
    """A failure the user can act on: one stderr line, exit code 1."""


class StoreError(UserError):
    """The store file is unreadable or malformed."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"cannot read store: {path}")


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


def store_path() -> Path:
    """Resolve the store location: $TALLOWMARK_FILE, else ~/.tallowmark/store.json."""
    override = os.environ.get("TALLOWMARK_FILE", "")
    if override.strip():
        return Path(override.strip()).expanduser()
    return Path(DEFAULT_STORE_PATH).expanduser()


def empty_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "batches": {}}


def _normalise_batch(key: str, raw: Any, path: Path) -> None:
    """Validate one batch in place, filling in fields a hand-edited store omits."""
    if not isinstance(raw, dict):
        raise StoreError(path)
    display_name = raw.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise StoreError(path)
    raw["slug"] = key
    if not isinstance(raw.get("created_at"), str):
        raw["created_at"] = ""
    for field in ("dips", "notes"):
        entries = raw.get(field)
        if not isinstance(entries, list):
            entries = []
        raw[field] = [entry for entry in entries if isinstance(entry, dict)]
    cure = raw.get("cure")
    raw["cure"] = None if cure is None else _normalise_cure(cure, path)


def _normalise_cure(raw: Any, path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StoreError(path)
    hours = raw.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        raise StoreError(path)
    if not math.isfinite(float(hours)) or float(hours) <= 0:
        raise StoreError(path)
    started_at = raw.get("started_at")
    if not isinstance(started_at, str):
        raise StoreError(path)
    try:
        from_iso(started_at)
    except ValueError:
        raise StoreError(path) from None
    return {"hours": hours, "started_at": started_at}


def normalise_store(raw: Any, path: Path) -> dict[str, Any]:
    """Validate a parsed store document in place, tolerating sane hand-edited files."""
    if not isinstance(raw, dict):
        raise StoreError(path)
    if raw.get("version", STORE_VERSION) != STORE_VERSION:
        raise StoreError(path)
    batches = raw.get("batches")
    if not isinstance(batches, dict):
        raise StoreError(path)
    rekeyed: dict[str, Any] = {}
    for key, batch in batches.items():
        slug = str(key).casefold()
        _normalise_batch(slug, batch, path)
        rekeyed.setdefault(slug, batch)
    raw["batches"] = rekeyed
    return raw


def load_store(path: Path) -> dict[str, Any]:
    """Read the store, creating an empty one on first use."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        store = empty_store()
        save_store(path, store)
        return store
    except OSError:
        raise StoreError(path) from None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise StoreError(path) from None
    return normalise_store(raw, path)


def save_store(path: Path, store: dict[str, Any]) -> None:
    """Write the store atomically: temp file in the same directory + os.replace."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise StoreError(path) from None
    payload = json.dumps(store, ensure_ascii=False) + "\n"
    handle = None
    tmp_name = ""
    try:
        descriptor, tmp_name = tempfile.mkstemp(prefix=".tallowmark-", suffix=".tmp", dir=str(path.parent))
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(tmp_name, path)
    except OSError:
        raise StoreError(path) from None
    finally:
        if handle is not None:
            handle.close()
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def find_batch(store: dict[str, Any], raw_name: str | None) -> dict[str, Any]:
    """Case-insensitive batch lookup; the one shared unknown-batch rejection."""
    name = (raw_name or "").strip()
    batch = store["batches"].get(name.casefold())
    if batch is None:
        raise UserError(f"unknown batch: {name}")
    return batch


# --------------------------------------------------------------------------
# timestamps and cure arithmetic
# --------------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def from_iso(text: str) -> datetime:
    raw = text.strip()
    if raw[-1:] in ("Z", "z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def cure_status(cure: dict[str, Any | None], now: datetime) -> str:
    """Render 'no cure set', 'cured' or '<d>d <h>h left' (ceiling of remaining seconds)."""
    if cure is None:
        return "no cure set"
    deadline = from_iso(cure["started_at"]) + timedelta(hours=float(cure["hours"]))
    remaining = (deadline - now.replace(microsecond=0)).total_seconds()
    if remaining <= 0:
        return "cured"
    hours_left = math.ceil(remaining / SECONDS_PER_HOUR)
    return f"{hours_left // HOURS_PER_DAY}d {hours_left % HOURS_PER_DAY}h left"


def parse_hours(raw: str | None) -> float:
    """Parse cure hours ourselves so every bad value prints one stable message."""
    if raw is None:
        raise UserError(HOURS_ERROR)
    try:
        hours = float(str(raw).strip())
    except (TypeError, ValueError):
        raise UserError(HOURS_ERROR) from None
    if not math.isfinite(hours) or hours <= 0:
        raise UserError(HOURS_ERROR)
    return hours


def format_hours(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else f"{hours:g}"


def dip_phrase(count: int) -> str:
    return f"{count} dip" if count == 1 else f"{count} dips"


def separator(name: str) -> str:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    glyph = "\u2500" if "utf" in encoding else "-"
    return glyph * max(MIN_SEPARATOR_WIDTH, len(name))


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def open_store() -> tuple[dict[str, Any], Path]:
    path = store_path()
    return load_store(path), path


def cmd_batch_new(args: argparse.Namespace) -> int:
    name = (args.name or "").strip()
    if not name:
        raise UserError(NAME_ERROR)
    store, path = open_store()
    slug = name.casefold()
    if slug in store["batches"]:
        raise UserError(f"batch already exists: {name}")
    store["batches"][slug] = {
        "slug": slug,
        "display_name": name,
        "created_at": to_iso(utcnow()),
        "dips": [],
        "notes": [],
        "cure": None,
    }
    save_store(path, store)
    print(f"created batch: {name}")
    return 0


def cmd_batch_show(args: argparse.Namespace) -> int:
    store, _ = open_store()
    batch = find_batch(store, args.name)
    display_name = batch["display_name"]
    print(display_name)
    print(separator(display_name))
    print(f"created: {batch.get('created_at') or 'unknown'}")
    print(f"dips: {len(batch['dips'])}")
    print(f"cure: {cure_status(batch['cure'], utcnow())}")
    print(f"notes: {len(batch['notes'])}")
    return 0


def cmd_batch_list(_args: argparse.Namespace) -> int:
    store, _ = open_store()
    if not store["batches"]:
        print("no batches yet")
        return 0
    for batch in store["batches"].values():
        print(batch["display_name"])
    return 0


def cmd_note_add(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        raise UserError("note text required")
    store, path = open_store()
    batch = find_batch(store, args.batch)
    batch["notes"].append({"id": uuid.uuid4().hex, "text": text, "created_at": to_iso(utcnow())})
    save_store(path, store)
    print(f"note added to {batch['display_name']}")
    return 0


def cmd_note_list(args: argparse.Namespace) -> int:
    store, _ = open_store()
    batch = find_batch(store, args.batch)
    if not batch["notes"]:
        print("no notes yet")
        return 0
    for note in batch["notes"]:
        print(f"[{note.get('created_at', '')}] {note.get('text', '')}")
    return 0


def cmd_cure_set(args: argparse.Namespace) -> int:
    hours = parse_hours(args.hours)
    store, path = open_store()
    batch = find_batch(store, args.batch)
    stored = int(hours) if float(hours).is_integer() else hours
    batch["cure"] = {"hours": stored, "started_at": to_iso(utcnow())}
    save_store(path, store)
    print(f"cure set: {batch['display_name']} {format_hours(hours)}h")
    return 0


def cmd_cure_status(args: argparse.Namespace) -> int:
    store, _ = open_store()
    batch = find_batch(store, args.batch)
    print(f"{batch['display_name']}: {cure_status(batch['cure'], utcnow())}")
    return 0


def cmd_cure_clear(args: argparse.Namespace) -> int:
    store, path = open_store()
    batch = find_batch(store, args.batch)
    batch["cure"] = None
    save_store(path, store)
    print(f"cure cleared: {batch['display_name']}")
    return 0


def cmd_dip_add(args: argparse.Namespace) -> int:
    store, path = open_store()
    batch = find_batch(store, args.batch)
    batch["dips"].append({"id": uuid.uuid4().hex, "created_at": to_iso(utcnow())})
    save_store(path, store)
    print(f"{batch['display_name']}: {dip_phrase(len(batch['dips']))}")
    return 0


def cmd_dip_list(args: argparse.Namespace) -> int:
    store, _ = open_store()
    batch = find_batch(store, args.batch)
    dips = batch["dips"]
    if not dips:
        print("no dips yet")
        return 0
    for index in range(len(dips) - 1, -1, -1):
        print(f"[{dips[index].get('created_at', '')}] dip {index + 1}")
    return 0


def cmd_overview(_args: argparse.Namespace) -> int:
    store, _ = open_store()
    if not store["batches"]:
        print("no batches yet")
        return 0
    now = utcnow()
    for batch in store["batches"].values():
        status = cure_status(batch["cure"], now)
        print(f"{batch['display_name']}: {dip_phrase(len(batch['dips']))} | {status}")
    return 0


# --------------------------------------------------------------------------
# command line interface
# --------------------------------------------------------------------------

EPILOG = """\
examples:
  tallowmark batch new Lavender
  tallowmark dip add Lavender
  tallowmark note add Lavender poured at 60C
  tallowmark cure set Lavender 48
  tallowmark list

store:
  $TALLOWMARK_FILE (default ~/.tallowmark/store.json), replaced atomically
"""

FORMATTER = argparse.RawDescriptionHelpFormatter


def _help_handler(parser: argparse.ArgumentParser) -> Handler:
    """A bare command group prints its own help and exits 0."""

    def handler(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    return handler


def _add_batch_commands(subparsers: Any) -> None:
    batch = subparsers.add_parser(
        "batch",
        help="create and inspect wax batches",
        description="Create a wax batch, show one batch, or list every batch.",
        epilog="example: tallowmark batch new Lavender",
        formatter_class=FORMATTER,
    )
    batch_subs = batch.add_subparsers(dest="batch_command", metavar="<command>", title="batch commands")
    new = batch_subs.add_parser(
        "new",
        help="create a batch (case-insensitive duplicate check)",
        description="Create a wax batch; the typed casing becomes the display name.",
        formatter_class=FORMATTER,
    )
    new.add_argument("name", nargs="?", default=None, metavar="<name>", help="batch name, e.g. Lavender")
    new.set_defaults(handler=cmd_batch_new)
    show = batch_subs.add_parser(
        "show",
        help="show one batch: created, dips, cure, notes",
        description="Show one batch by case-insensitive name.",
        formatter_class=FORMATTER,
    )
    show.add_argument("name", metavar="<name>", help="batch name, e.g. lavender")
    show.set_defaults(handler=cmd_batch_show)
    listing = batch_subs.add_parser(
        "list",
        help="list every batch display name, one per line",
        description="List every batch display name, one per line.",
        formatter_class=FORMATTER,
    )
    listing.set_defaults(handler=cmd_batch_list)
    batch.set_defaults(handler=_help_handler(batch))


def _add_note_commands(subparsers: Any) -> None:
    note = subparsers.add_parser(
        "note",
        help="append and read wax batch notes",
        description="Append timestamped wax notes to a batch and read them back.",
        epilog="example: tallowmark note add Lavender poured at 60C",
        formatter_class=FORMATTER,
    )
    note_subs = note.add_subparsers(dest="note_command", metavar="<command>", title="note commands")
    add = note_subs.add_parser(
        "add",
        help="append a timestamped note to a batch",
        description="Append a timestamped note; the remaining words are joined into one note.",
        formatter_class=FORMATTER,
    )
    add.add_argument("batch", metavar="<batch>", help="batch name")
    add.add_argument("text", nargs="*", metavar="<text>", help="note text, e.g. poured at 60C")
    add.set_defaults(handler=cmd_note_add)
    listing = note_subs.add_parser(
        "list",
        help="show a batch's notes oldest-first",
        description="Show a batch's timestamped notes, oldest first.",
        formatter_class=FORMATTER,
    )
    listing.add_argument("batch", metavar="<batch>", help="batch name")
    listing.set_defaults(handler=cmd_note_list)
    note.set_defaults(handler=_help_handler(note))


def _add_cure_commands(subparsers: Any) -> None:
    cure = subparsers.add_parser(
        "cure",
        help="set, check and clear a cure countdown",
        description="Set a cure duration in hours, read the countdown, or clear it.",
        epilog="example: tallowmark cure set Lavender 48",
        formatter_class=FORMATTER,
    )
    cure_subs = cure.add_subparsers(dest="cure_command", metavar="<command>", title="cure commands")
    setter = cure_subs.add_parser(
        "set",
        help="start a cure countdown for a batch",
        description="Start (or restart) a cure countdown; hours must be a positive number.",
        formatter_class=FORMATTER,
    )
    setter.add_argument("batch", metavar="<batch>", help="batch name")
    setter.add_argument(
        "hours",
        nargs="?",
        default=None,
        metavar="<hours>",
        help="cure length in hours, e.g. 48",
    )
    setter.set_defaults(handler=cmd_cure_set)
    status = cure_subs.add_parser(
        "status",
        help="show time left, 'cured', or 'no cure set'",
        description="Show a batch's cure status: '<d>d <h>h left', 'cured' or 'no cure set'.",
        formatter_class=FORMATTER,
    )
    status.add_argument("batch", metavar="<batch>", help="batch name")
    status.set_defaults(handler=cmd_cure_status)
    clear = cure_subs.add_parser(
        "clear",
        help="remove a batch's cure countdown",
        description="Remove a batch's cure countdown; the batch then reports 'no cure set'.",
        formatter_class=FORMATTER,
    )
    clear.add_argument("batch", metavar="<batch>", help="batch name")
    clear.set_defaults(handler=cmd_cure_clear)
    cure.set_defaults(handler=_help_handler(cure))


def _add_dip_commands(subparsers: Any) -> None:
    dip = subparsers.add_parser(
        "dip",
        help="log candle dips and review the dip history",
        description="Record a candle dip against a batch and read the dip history back.",
        epilog="example: tallowmark dip add Lavender",
        formatter_class=FORMATTER,
    )
    dip_subs = dip.add_subparsers(dest="dip_command", metavar="<command>", title="dip commands")
    add = dip_subs.add_parser(
        "add",
        help="record one dip and print the running count",
        description="Record one dip and print the running count: 'Lavender: 2 dips'.",
        formatter_class=FORMATTER,
    )
    add.add_argument("batch", metavar="<batch>", help="batch name")
    add.set_defaults(handler=cmd_dip_add)
    listing = dip_subs.add_parser(
        "list",
        help="show a batch's dip history newest-first",
        description="Show a batch's timestamped dip history, newest first.",
        formatter_class=FORMATTER,
    )
    listing.add_argument("batch", metavar="<batch>", help="batch name")
    listing.set_defaults(handler=cmd_dip_list)
    dip.set_defaults(handler=_help_handler(dip))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tallowmark",
        description="Track candle dips, wax batch notes and cure countdowns.",
        epilog=EPILOG,
        formatter_class=FORMATTER,
    )
    parser.add_argument("--version", action="version", version=f"tallowmark {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", title="commands")
    _add_batch_commands(subparsers)
    _add_note_commands(subparsers)
    _add_cure_commands(subparsers)
    _add_dip_commands(subparsers)
    overview = subparsers.add_parser(
        "list",
        help="status overview: dips and cure state for every batch",
        description="One line per batch: '<DisplayName>: <n> dip|dips | <cure status>'.",
        formatter_class=FORMATTER,
    )
    overview.set_defaults(handler=cmd_overview)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args))
    except UserError as error:
        print(str(error), file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
