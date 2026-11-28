"""The data-layer deploy runner, without a database (docs/DB_DDL_PLANNING.md §15, §19).

The SQL itself is tested against PostgreSQL by `make db-test` (tests/sql/*_test.sql), locally and in CI.
"""

from __future__ import annotations

import argparse
import re

import pytest

from src.db import deploy


def test_sql_files_are_numbered_and_ordered():
    names = [p.name for p in deploy.sql_files()]
    assert names[0] == "00_extensions.sql"
    assert names[-1] == "95_seed_reference.sql"
    assert names == sorted(names)
    assert all(re.match(r"^\d\d_[a-z0-9_]+\.sql$", n) for n in names)


def test_every_sql_file_has_the_header():
    for path in deploy.sql_files():
        head = path.read_text(encoding="utf-8")[:2000]
        assert "-- Doc: docs/DB_DDL_PLANNING.md" in head, path.name
        assert "-- PREREQUISITE:" in head, path.name


def test_no_secret_or_password_in_sql():
    for path in deploy.sql_files():
        text = path.read_text(encoding="utf-8").lower()
        assert "password '" not in text and "password=" not in text, path.name


def test_includes_are_inlined(tmp_path):
    (tmp_path / "_inc.sql").write_text("SELECT 1;\n", encoding="utf-8")
    main = tmp_path / "a_test.sql"
    main.write_text("BEGIN;\n\\ir _inc.sql\nROLLBACK;\n", encoding="utf-8")
    assert deploy.expand_includes(main) == "BEGIN;\nSELECT 1;\n\nROLLBACK;\n"


def test_include_cycle_is_refused(tmp_path):
    a, b = tmp_path / "a.sql", tmp_path / "b.sql"
    a.write_text("\\ir b.sql\n", encoding="utf-8")
    b.write_text("\\ir a.sql\n", encoding="utf-8")
    with pytest.raises(ValueError, match="include cycle"):
        deploy.expand_includes(a)


def test_script_stops_on_first_error():
    script = deploy.script_for(deploy.sql_files()[:1])
    assert script.startswith("\\set ON_ERROR_STOP on")
    assert "== 00_extensions.sql" in script


def test_reset_needs_confirmation(capsys):
    args = argparse.Namespace(yes=False, discard_authored=False, compose=False, url="postgresql://unused")
    assert deploy.cmd_reset(args) == 2
    assert "--yes" in capsys.readouterr().err


def test_tests_include_the_fixture():
    files = deploy.test_files()
    assert files, "tests/sql has no *_test.sql"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("--") and "BEGIN;" in text and text.rstrip().endswith("ROLLBACK;"), path.name
