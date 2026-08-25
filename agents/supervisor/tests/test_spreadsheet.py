"""Tests for the spreadsheet writers."""

from __future__ import annotations

import csv

import pytest

from agents.supervisor.spreadsheet import CsvWorkbook, Sheet, XlsxWorkbook, build_writer

openpyxl = pytest.importorskip("openpyxl")


def sheets() -> list[Sheet]:
    return [
        Sheet(name="Summary", columns=["Metric", "Value"], rows=[["Decisions", "17"]]),
        Sheet(
            name="Tasks today",
            columns=["ID", "Task"],
            rows=[["t1", "Review: Rückfrage zur Rechnung"], ["t2", "Unblock: outreach"]],
        ),
    ]


# --- CSV ----------------------------------------------------------------


def test_csv_writes_one_file_per_sheet(tmp_path):
    written = CsvWorkbook().write(sheets(), tmp_path)

    assert len(written) == 2
    assert [p.name for p in written] == ["01-summary.csv", "02-tasks-today.csv"]
    assert all(p.exists() for p in written)


def test_csv_round_trips_header_and_rows(tmp_path):
    (summary, _tasks) = CsvWorkbook().write(sheets(), tmp_path)

    with summary.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))

    assert rows[0] == ["Metric", "Value"]
    assert rows[1] == ["Decisions", "17"]


def test_csv_writes_a_bom_so_excel_reads_utf8(tmp_path):
    # Without the BOM, Excel decodes UTF-8 as the local code page and mangles
    # every accented character in the brief.
    (_summary, tasks) = CsvWorkbook().write(sheets(), tmp_path)
    raw = tasks.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Rückfrage" in tasks.read_text(encoding="utf-8-sig")


def test_the_csv_delimiter_is_configurable(tmp_path):
    (summary, _) = CsvWorkbook(delimiter=",").write(sheets(), tmp_path)
    assert "Metric,Value" in summary.read_text(encoding="utf-8-sig")


def test_csv_creates_the_directory_it_needs(tmp_path):
    target = tmp_path / "does" / "not" / "exist"
    assert CsvWorkbook().write(sheets(), target)[0].exists()


def test_a_sheet_with_no_rows_still_writes_its_header(tmp_path):
    empty = [Sheet(name="Tasks today", columns=["ID", "Task"])]
    (path,) = CsvWorkbook().write(empty, tmp_path)

    assert path.read_text(encoding="utf-8-sig").strip() == "ID;Task"


# --- XLSX ---------------------------------------------------------------


def test_xlsx_writes_one_workbook_with_a_tab_per_sheet(tmp_path):
    (path,) = XlsxWorkbook().write(sheets(), tmp_path)

    assert path.suffix == ".xlsx"
    workbook = openpyxl.load_workbook(path)
    assert workbook.sheetnames == ["Summary", "Tasks today"]


def test_xlsx_preserves_the_content(tmp_path):
    (path,) = XlsxWorkbook().write(sheets(), tmp_path)
    worksheet = openpyxl.load_workbook(path)["Tasks today"]

    assert [cell.value for cell in worksheet[1]] == ["ID", "Task"]
    assert worksheet["B2"].value == "Review: Rückfrage zur Rechnung"


def test_xlsx_bolds_and_freezes_the_header(tmp_path):
    (path,) = XlsxWorkbook().write(sheets(), tmp_path)
    worksheet = openpyxl.load_workbook(path)["Summary"]

    assert worksheet["A1"].font.bold is True
    assert worksheet.freeze_panes == "A2"


def test_xlsx_widens_columns_to_fit(tmp_path):
    (path,) = XlsxWorkbook().write(sheets(), tmp_path)
    worksheet = openpyxl.load_workbook(path)["Tasks today"]

    # Unwidened columns show as ### or truncate, which makes the brief look
    # broken before anyone has read a word of it.
    assert worksheet.column_dimensions["B"].width > 10


def test_a_long_sheet_name_is_truncated_to_what_excel_accepts(tmp_path):
    long_name = [Sheet(name="A" * 50, columns=["x"], rows=[["y"]])]
    (path,) = XlsxWorkbook().write(long_name, tmp_path)

    assert openpyxl.load_workbook(path).sheetnames == ["A" * 31]


def test_an_explicit_xlsx_path_is_used_as_given(tmp_path):
    target = tmp_path / "monday.xlsx"
    (path,) = XlsxWorkbook().write(sheets(), target)
    assert path == target


# --- Selection ----------------------------------------------------------


def test_writers_are_selectable_by_name():
    assert isinstance(build_writer("csv"), CsvWorkbook)
    assert isinstance(build_writer("xlsx"), XlsxWorkbook)


def test_an_unknown_format_fails_loudly():
    with pytest.raises(ValueError, match="Unknown spreadsheet format"):
        build_writer("ods")
