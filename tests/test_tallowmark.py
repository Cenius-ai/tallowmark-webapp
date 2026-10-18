"""End-to-end tests for the Tallowmark CLI.

Every test drives the real program in a separate process against a throwaway
store file, so what is asserted is exactly what a shell transcript shows.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "tallowmark.py"
TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    return tmp_path / "store.json"


def run(store: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "TALLOWMARK_FILE"}
    env["TALLOWMARK_FILE"] = str(store)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(SCRIPT.parent),
        timeout=60,
    )


def ok(store: Path, *args: str) -> str:
    result = run(store, *args)
    assert result.returncode == 0, f"{args} failed: {result.stderr}"
    assert result.stderr == "", f"{args} wrote to stderr: {result.stderr}"
    return result.stdout.rstrip("\n")


def fail(store: Path, *args: str) -> str:
    result = run(store, *args)
    assert result.returncode == 1, f"{args} exited {result.returncode}: {result.stderr}"
    assert result.stdout == "", f"{args} wrote to stdout: {result.stdout}"
    assert "Traceback" not in result.stderr, result.stderr
    lines = result.stderr.splitlines()
    assert len(lines) == 1, f"{args} wrote {len(lines)} stderr lines: {result.stderr}"
    return lines[0]


def write_store(path: Path, batches: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "batches": batches}), encoding="utf-8")


def make_batch(
    display_name: str,
    *,
    dips: int = 0,
    notes: tuple = (),
    cure: dict | None = None,
    created_at: str = "2024-05-01T09:00:00Z",
) -> tuple[str, dict]:
    slug = display_name.casefold()
    return slug, {
        "slug": slug,
        "display_name": display_name,
        "created_at": created_at,
        "dips": [{"id": f"dip{index}", "created_at": created_at} for index in range(dips)],
        "notes": [
            {"id": f"note{index}", "text": text, "created_at": created_at}
            for index, text in enumerate(notes)
        ],
        "cure": cure,
    }


# --------------------------------------------------------------------------
# T1 -- scaffold, store, error envelope
# --------------------------------------------------------------------------


def test_help_lists_every_command_group(store: Path) -> None:
    result = run(store, "--help")
    assert result.returncode == 0
    assert result.stderr == ""
    output = result.stdout
    assert output.startswith("usage: tallowmark")
    for group in ("batch", "note", "cure", "dip", "list"):
        assert re.search(rf"^    {group} +\S", output, re.MULTILINE), group
    assert "examples:" in output
    assert "TALLOWMARK_FILE" in output


def test_version_flag(store: Path) -> None:
    result = run(store, "--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "tallowmark 1.0.0"


def test_bare_invocation_prints_help_and_exits_zero(store: Path) -> None:
    result = run(store)
    assert result.returncode == 0
    assert result.stdout.startswith("usage: tallowmark")


def test_group_help_exits_zero(store: Path) -> None:
    for group in ("batch", "note", "cure", "dip"):
        result = run(store, group, "--help")
        assert result.returncode == 0, group
        assert result.stdout.startswith(f"usage: tallowmark {group}")
    assert run(store, "batch", "new", "--help").returncode == 0
    assert run(store, "cure", "set", "--help").returncode == 0


def test_bare_group_prints_its_own_help(store: Path) -> None:
    result = run(store, "batch")
    assert result.returncode == 0
    assert result.stdout.startswith("usage: tallowmark batch")


def test_first_command_creates_the_store_document(store: Path) -> None:
    assert not store.exists()
    assert ok(store, "batch", "list") == "no batches yet"
    assert store.exists()
    assert store.read_text(encoding="utf-8").strip() == '{"version": 1, "batches": {}}'
    assert json.loads(store.read_text(encoding="utf-8")) == {"version": 1, "batches": {}}


def test_store_is_created_in_a_missing_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deeper" / "store.json"
    assert ok(nested, "batch", "list") == "no batches yet"
    assert nested.exists()


@pytest.mark.parametrize(
    "payload",
    ["{not json", "[]", "", '{"version": 1, "batches": []}', '{"version": 99, "batches": {}}'],
)
def test_unreadable_store_prints_one_line_and_exits_one(tmp_path: Path, payload: str) -> None:
    store = tmp_path / "store.json"
    store.write_text(payload, encoding="utf-8")
    assert fail(store, "batch", "list") == f"cannot read store: {store}"


def test_writes_leave_no_temporary_files_behind(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "dip", "add", "Lavender")
    ok(store, "note", "add", "Lavender", "poured at 60C")
    ok(store, "cure", "set", "Lavender", "48")
    leftovers = sorted(path.name for path in store.parent.iterdir())
    assert leftovers == ["store.json"], leftovers


def test_output_contains_no_ansi_escapes(store: Path) -> None:
    transcript = [
        ok(store, "batch", "new", "Lavender"),
        ok(store, "batch", "show", "Lavender"),
        ok(store, "dip", "add", "Lavender"),
        ok(store, "list"),
        fail(store, "batch", "show", "Ghost"),
    ]
    assert "\x1b" not in "\n".join(transcript)


def test_unknown_subcommand_uses_argparse_usage_exit(store: Path) -> None:
    result = run(store, "nope")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


# --------------------------------------------------------------------------
# T2 -- batch create, show, list
# --------------------------------------------------------------------------


def test_batch_new_then_list(store: Path) -> None:
    assert ok(store, "batch", "new", "Lavender") == "created batch: Lavender"
    assert ok(store, "batch", "list") == "Lavender"


def test_batch_list_is_empty_message_on_empty_store(store: Path) -> None:
    assert ok(store, "batch", "list") == "no batches yet"


def test_duplicate_batch_is_case_insensitive(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert fail(store, "batch", "new", "lavender") == "batch already exists: lavender"
    assert fail(store, "batch", "new", "LAVENDER") == "batch already exists: LAVENDER"
    assert ok(store, "batch", "list") == "Lavender"


def test_blank_batch_name_is_rejected(store: Path) -> None:
    assert fail(store, "batch", "new", "   ") == "batch name required"
    assert fail(store, "batch", "new", "") == "batch name required"
    assert fail(store, "batch", "new") == "batch name required"


def test_batch_show_preserves_display_casing(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    output = ok(store, "batch", "show", "lavender")
    lines = output.splitlines()
    assert lines[0] == "Lavender"
    assert re.fullmatch(rf"created: {TIMESTAMP}", lines[2])
    assert "dips: 0" in lines
    assert "cure: no cure set" in lines
    assert "notes: 0" in lines
    assert ok(store, "batch", "show", "LaVeNdEr").splitlines()[0] == "Lavender"


def test_batch_show_unknown_batch(store: Path) -> None:
    assert fail(store, "batch", "show", "Ghost") == "unknown batch: Ghost"


# --------------------------------------------------------------------------
# T5 -- dips
# --------------------------------------------------------------------------


def test_dip_add_prints_running_count(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "dip", "add", "Lavender") == "Lavender: 1 dip"
    assert ok(store, "dip", "add", "Lavender") == "Lavender: 2 dips"
    assert ok(store, "dip", "add", "lavender") == "Lavender: 3 dips"


def test_dip_list_is_empty_message(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "dip", "list", "Lavender") == "no dips yet"


def test_dip_history_persists_newest_first(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "dip", "add", "Lavender")
    ok(store, "dip", "add", "Lavender")
    lines = ok(store, "dip", "list", "Lavender").splitlines()
    assert len(lines) == 2
    assert re.fullmatch(rf"\[{TIMESTAMP}\] dip 2", lines[0])
    assert re.fullmatch(rf"\[{TIMESTAMP}\] dip 1", lines[1])


def test_batch_show_reports_dip_count(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "dip", "add", "Lavender")
    ok(store, "dip", "add", "Lavender")
    assert "dips: 2" in ok(store, "batch", "show", "Lavender").splitlines()


# --------------------------------------------------------------------------
# T3 -- notes
# --------------------------------------------------------------------------


def test_note_add_joins_multi_word_text(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "note", "add", "Lavender", "poured", "at", "60C") == "note added to Lavender"
    lines = ok(store, "note", "list", "Lavender").splitlines()
    assert len(lines) == 1
    assert re.fullmatch(rf"\[{TIMESTAMP}\] poured at 60C", lines[0])


def test_note_list_is_empty_message(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "note", "list", "Lavender") == "no notes yet"


def test_notes_persist_oldest_first_across_runs(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "note", "add", "Lavender", "first pour at 60C")
    ok(store, "note", "add", "Lavender", "top-up at 58C")
    lines = ok(store, "note", "list", "Lavender").splitlines()
    assert len(lines) == 2
    assert re.fullmatch(rf"\[{TIMESTAMP}\] first pour at 60C", lines[0])
    assert re.fullmatch(rf"\[{TIMESTAMP}\] top-up at 58C", lines[1])


def test_note_add_without_text_is_rejected(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert fail(store, "note", "add", "Lavender") == "note text required"
    assert fail(store, "note", "add", "Lavender", "   ") == "note text required"


def test_batch_show_reports_note_count(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "note", "add", "Lavender", "poured at 60C")
    ok(store, "note", "add", "Lavender", "topped up at 58C")
    assert "notes: 2" in ok(store, "batch", "show", "Lavender").splitlines()


# --------------------------------------------------------------------------
# T4 -- cure countdown
# --------------------------------------------------------------------------


def test_cure_set_and_status_ceiling_rounding(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "cure", "set", "Lavender", "48") == "cure set: Lavender 48h"
    assert ok(store, "cure", "status", "Lavender") == "Lavender: 2d 0h left"


def test_cure_status_without_a_cure(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "cure", "status", "Lavender") == "Lavender: no cure set"


@pytest.mark.parametrize("hours", ["0", "-5", "-1.5", "abc", "nan", "inf", "1e999", ""])
def test_cure_set_rejects_bad_hours(store: Path, hours: str) -> None:
    ok(store, "batch", "new", "Lavender")
    assert fail(store, "cure", "set", "Lavender", hours) == "hours must be a positive number"


def test_cure_set_rejects_missing_hours_with_exit_one(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    result = run(store, "cure", "set", "Lavender")
    assert result.returncode == 1
    assert result.stderr.strip() == "hours must be a positive number"


def test_cure_set_accepts_fractional_hours(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    assert ok(store, "cure", "set", "Lavender", "1.5") == "cure set: Lavender 1.5h"
    assert ok(store, "cure", "status", "Lavender") == "Lavender: 0d 2h left"


def test_elapsed_cure_reports_cured(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    started = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
    slug, batch = make_batch(
        "Lavender",
        cure={"hours": 1, "started_at": started.isoformat().replace("+00:00", "Z")},
    )
    write_store(store, {slug: batch})
    assert ok(store, "cure", "status", "Lavender") == "Lavender: cured"
    assert ok(store, "list") == "Lavender: 0 dips | cured"


def test_cure_clear_returns_to_no_cure_set(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "cure", "set", "Lavender", "48")
    assert ok(store, "cure", "clear", "Lavender") == "cure cleared: Lavender"
    assert ok(store, "cure", "status", "Lavender") == "Lavender: no cure set"


# --------------------------------------------------------------------------
# shared unknown-batch rejection (D7)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("batch", "show", "Ghost"),
        ("note", "add", "Ghost", "test"),
        ("note", "list", "Ghost"),
        ("cure", "set", "Ghost", "10"),
        ("cure", "status", "Ghost"),
        ("cure", "clear", "Ghost"),
        ("dip", "add", "Ghost"),
        ("dip", "list", "Ghost"),
    ],
)
def test_unknown_batch_is_identical_everywhere(store: Path, args: tuple) -> None:
    assert fail(store, *args) == "unknown batch: Ghost"


# --------------------------------------------------------------------------
# T6 -- unified status overview
# --------------------------------------------------------------------------


def test_overview_shows_a_cure_status_for_every_batch(store: Path) -> None:
    ok(store, "batch", "new", "Lavender")
    ok(store, "batch", "new", "Beeswax")
    ok(store, "dip", "add", "Lavender")
    ok(store, "dip", "add", "Lavender")
    ok(store, "dip", "add", "Beeswax")
    ok(store, "cure", "set", "Lavender", "48")
    assert ok(store, "list").splitlines() == [
        "Lavender: 2 dips | 2d 0h left",
        "Beeswax: 1 dip | no cure set",
    ]


def test_overview_empty_store(store: Path) -> None:
    assert ok(store, "list") == "no batches yet"


def test_overview_prints_one_line_per_batch(store: Path) -> None:
    for name in ("Lavender", "Beeswax", "Cedar & Fig"):
        ok(store, "batch", "new", name)
    lines = ok(store, "list").splitlines()
    assert len(lines) == 3
    assert [line.split(":")[0] for line in lines] == ["Lavender", "Beeswax", "Cedar & Fig"]
    assert all(line.endswith("| no cure set") for line in lines)


def test_overview_shows_zero_dips_and_cured(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    started = (datetime.now(timezone.utc) - timedelta(hours=72)).replace(microsecond=0)
    slug, batch = make_batch(
        "Beeswax",
        cure={"hours": 24, "started_at": started.isoformat().replace("+00:00", "Z")},
    )
    write_store(store, {slug: batch})
    assert ok(store, "list") == "Beeswax: 0 dips | cured"


# --------------------------------------------------------------------------
# demo script
# --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_demo_script_runs_end_to_end() -> None:
    result = subprocess.run(
        ["bash", "demo.sh"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "created batch: Lavender" in result.stdout
    assert "Lavender: 3 dips" in result.stdout
    assert "Lavender: 2d 0h left" in result.stdout
    assert "Beeswax: 1 dip | no cure set" in result.stdout


# --------------------------------------------------------------------------
# hand-edited stores
# --------------------------------------------------------------------------


def test_hand_edited_store_keyed_with_original_casing_still_resolves(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    _, batch = make_batch("Lavender")
    write_store(store, {"Lavender": batch})
    assert ok(store, "cure", "status", "lavender") == "Lavender: no cure set"


def test_hand_edited_store_without_optional_fields_is_tolerated(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    write_store(store, {"lavender": {"display_name": "Lavender"}})
    output = ok(store, "batch", "show", "Lavender").splitlines()
    assert output[0] == "Lavender"
    assert "dips: 0" in output
    assert "notes: 0" in output
    assert ok(store, "dip", "list", "Lavender") == "no dips yet"


def test_malformed_cure_makes_the_store_unreadable(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    _, batch = make_batch("Lavender", cure={"hours": 0, "started_at": "2024-05-01T09:00:00Z"})
    write_store(store, {"lavender": batch})
    assert fail(store, "cure", "status", "Lavender") == f"cannot read store: {store}"
