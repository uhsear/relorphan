#!/usr/bin/env python
"""Flag attachment and related rows whose parent feature is gone.

Reads two CSV exports: the parent table, and the child table (an attachment
table, or any table related by a GlobalID). A child row is an ORPHAN when no
parent row has its GlobalID. The braced, bare, upper case and lower case
spellings of one GlobalID count as one id, because a join on the raw text calls
every row that was exported by a different system an orphan.

A feature class in a geodatabase can have an attachment table, named with the
suffix __ATTACH, whose REL_GLOBALID column holds the GlobalID of the parent
feature. When a parent feature is deleted by a route that skips the
relationship class (a SQL delete, a truncate and reload, an append that mints
new GlobalIDs), its attachment rows can stay behind, and so can their photos.
That is the failure this tool looks for. The README says which parts of that
story were checked against Esri documentation and which were not.

The obvious tools already do the join. A SQL anti-join (LEFT JOIN ... WHERE
parent IS NULL, or NOT EXISTS) finds the rows exactly, and on a uniqueidentifier
column it compares the 16 byte value, not the text. This tool is for the
cases where the ids reach you as text: a CSV export, a hosted layer, a column
that was cast to a string. Then it reads every spelling as one id, refuses to
call a run clean when the parent export is empty or has a row it cannot read,
and adds up the bytes the orphans hold.

    python relorphan.py --self-test
    python relorphan.py parents.csv children.csv
    python relorphan.py parents.csv children.csv --parent-field GLOBALID --child-field REL_GLOBALID
    python relorphan.py parents.csv children.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE
    python relorphan.py parents.csv children.csv --out findings.csv --apply

Nothing is written without --apply, and the tool never deletes a row.

Exit codes: 0 every child row has a parent, 1 at least one child row has no
parent or no readable key, 2 a file could not be read or written, 3 refused
(the parent export cannot prove an orphan), 4 nothing was compared (the child
table has no rows), 64 usage error, 70 an unexpected crash, which is never a
finding.
"""

from __future__ import print_function

import argparse
import ast
import collections
import contextlib
import csv
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

# =============================================================================
# CONFIGURATION. Deliberately not flags. Change here, not at the call site.
# =============================================================================

# The GlobalID column of the parent table, and the column of the child table
# that holds the parent's GlobalID. REL_GLOBALID is the name an attachment
# table gets when its parent has a GlobalID field. Column names are matched
# without regard to case, because a hosted layer exports them in lower case.
DEFAULT_PARENT_FIELD = "GLOBALID"
DEFAULT_CHILD_FIELD = "REL_GLOBALID"

# How many rows are listed under each heading. The count is the finding; the
# sample is there so somebody can open one row and agree.
DEFAULT_SAMPLE = 10

# =============================================================================
# End of CONFIGURATION.
# =============================================================================

# The four classes every child row lands in, exactly one each.
LINKED = "LINKED"
ORPHAN = "ORPHAN"
UNKEYED = "UNKEYED"
MALFORMED = "MALFORMED"

CLASSES = (LINKED, ORPHAN, UNKEYED, MALFORMED)

# The classes that fail the gate: a child row not shown to have a parent.
FINDINGS = (ORPHAN, UNKEYED, MALFORMED)

# What normalize_guid says about a cell.
KEY_OK = "ok"
KEY_BLANK = "blank"
KEY_NULL = "null"
KEY_BAD = "bad"

# A GUID is 32 hex digits, written bare (.NET format N) or in the 8-4-4-4-12
# groups (format D). Braces (format B) and parentheses (format P) wrap either
# form. Only the ASCII digits 0-9 count.
# Matched with fullmatch, not "$": "$" also matches before a final line break,
# so "{guid<LF>}" would pass as a GUID whose canonical form ends in a newline.
_DASHED = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                     r"-[0-9a-f]{12}", re.IGNORECASE)
_BARE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)
_WRAPPERS = {"{": "}", "(": ")"}

# At most 18 digits, so a byte count fits a 64 bit integer. A longer cell is
# unreadable on every Python: int() refuses more than 4300 digits on 3.11 and
# later, and would raise outside the column-error handler.
_DIGITS = re.compile(r"[0-9]{1,18}")

# The columns --out writes: one row per child row that is not LINKED.
OUT_COLUMNS = ("csv_line", "row_id", "raw_key", "class", "size", "reason")
OUT_HEADER = ",".join(OUT_COLUMNS)

Child = collections.namedtuple("Child", "line raw row_id size_text")
Result = collections.namedtuple("Result", "child key cls size reason")

NO_PARENTS = ("the parent table has no rows, so every child row would look "
              "orphaned. An empty export and an emptied layer look the same, "
              "and this tool cannot tell which one it was given.")
BAD_PARENTS = ("%d parent row(s) have no readable GlobalID. A parent that "
               "cannot be matched could be the one an orphan points at, so "
               "nothing was compared.")


# ---------------------------------------------------------------- decision core

def normalize_guid(text):
    """Return (canonical, state) for one cell.

    canonical is the lower case 8-4-4-4-12 form, or None when the cell holds
    no usable GUID. state says why: KEY_OK, KEY_BLANK (empty), KEY_NULL (the
    all-zero GUID, which no GlobalID ever is) or KEY_BAD (not a GUID).
    """
    value = text.strip()
    if not value:
        return None, KEY_BLANK
    closer = _WRAPPERS.get(value[0])
    if closer is not None:
        if value[-1] != closer:
            return None, KEY_BAD
        value = value[1:-1]
    if not (_DASHED.fullmatch(value) or _BARE.fullmatch(value)):
        return None, KEY_BAD
    digits = value.replace("-", "").lower()
    if digits == "0" * 32:
        return None, KEY_NULL
    return "-".join((digits[:8], digits[8:12], digits[12:16], digits[16:20],
                     digits[20:])), KEY_OK


def to_size(text):
    """A byte count from a cell, or None when it is not a plain integer of at
    most 18 digits."""
    value = text.strip()
    return int(value) if _DIGITS.fullmatch(value) else None


class Report(object):
    """What reconcile found. Plain data, so describe() and gate() stay pure."""

    def __init__(self, parent_rows, child_rows, sized):
        self.parent_rows = parent_rows
        self.child_rows = child_rows
        self.sized = sized
        self.refused = []
        self.bad_parents = []
        self.results = []
        self.aliased = 0
        self.bytes = 0
        self.unsized = 0

    def count(self, cls):
        return sum(1 for r in self.results if r.cls == cls)

    def findings(self):
        return sum(self.count(cls) for cls in FINDINGS)


def reconcile(parents, children, sized=False):
    """Classify every child row against the parent table.

    parents is a list of (csv_line, cell). children is a list of Child. sized
    says the children carry a size column worth adding up.
    """
    report = Report(len(parents), len(children), sized)
    spellings = {}
    for line, raw in parents:
        key, state = normalize_guid(raw)
        if key is None:
            report.bad_parents.append((line, raw, state))
        else:
            spellings.setdefault(key, set()).add(raw)
    if not parents:
        report.refused.append(NO_PARENTS)
    if report.bad_parents:
        report.refused.append(BAD_PARENTS % len(report.bad_parents))
    if report.refused:
        return report

    for child in children:
        key, state = normalize_guid(child.raw)
        if state == KEY_OK:
            seen = spellings.get(key)
            if seen is None:
                cls = ORPHAN
                reason = "no parent row has the GlobalID %s" % key
            else:
                cls = LINKED
                reason = ""
                # A verbatim join would have missed this row.
                if child.raw not in seen:
                    report.aliased += 1
        elif state == KEY_BAD:
            cls = MALFORMED
            reason = ("%a is not a GUID in the bare, hyphenated, braced or "
                      "parenthesised form" % child.raw)
        else:
            cls = UNKEYED
            reason = ("the key is blank" if state == KEY_BLANK
                      else "the key is the all-zero GUID")
        size = to_size(child.size_text) if sized else None
        if sized and cls in (ORPHAN, UNKEYED):
            if size is None:
                report.unsized += 1
            else:
                report.bytes += size
        report.results.append(Result(child, key, cls, size, reason))
    return report


def gate(report):
    """The exit status of the verdict."""
    if report.refused:
        return 3
    if report.child_rows == 0:
        return 4
    if report.findings():
        return 1
    return 0


def verdict(report):
    if report.refused:
        return "REFUSED"
    if report.child_rows == 0:
        return ("NOTHING COMPARED. The child table has no rows, so no key "
                "was checked. This is not a clean run: a failed export "
                "looks the same.")
    found = report.findings()
    if found:
        text = "%d child row(s) are not attached to a parent." % found
        if report.count(ORPHAN):
            # Only an orphan depends on the parent export being whole.
            text += (" Check that the parent export is complete before you "
                     "delete anything.")
        return text
    return "clean. All %d child row(s) have a parent." % report.child_rows


def _cap(lines, sample):
    shown = lines[:sample]
    if len(lines) > sample:
        shown.append("  ... and %d more" % (len(lines) - sample))
    return shown


def _section(report, cls, heading, sample):
    rows = [r for r in report.results if r.cls == cls]
    if not rows:
        return []
    # Largest first: the bytes are the reason anybody opens the list.
    rows.sort(key=lambda r: (r.size is None, -(r.size or 0), r.child.line))
    lines = []
    for r in rows:
        parts = ["line %d" % r.child.line]
        if r.child.row_id:
            parts.append("id %s" % r.child.row_id)
        if r.size is not None:
            parts.append("%d byte(s)" % r.size)
        lines.append("  %s: %s" % (", ".join(parts), r.reason))
    return [""] + [heading] + _cap(lines, sample)


def describe(report, sample=DEFAULT_SAMPLE):
    """The lines the tool prints after its header line."""
    lines = []
    if report.refused:
        for message in report.refused:
            lines.append("REFUSED   %s" % message)
        listed = ["  parent line %d: %a" % (line, raw)
                  for line, raw, _ in report.bad_parents]
        lines.extend(_cap(listed, sample))
    else:
        lines.append("rows classified: %d of %d"
                     % (len(report.results), report.child_rows))
        for cls in CLASSES:
            lines.append("  %-10s %d" % (cls, report.count(cls)))
        lines.append("parents: %d row(s), every GlobalID readable"
                     % report.parent_rows)
        if report.aliased:
            lines.append("spelling: %d child row(s) match a parent only after "
                         "braces, case or hyphens are normalised. A verbatim "
                         "join calls them orphans." % report.aliased)
        if report.sized:
            note = ""
            if report.unsized:
                note = " (%d row(s) had no readable size)" % report.unsized
            lines.append("storage: %d byte(s) sit in the ORPHAN and UNKEYED "
                         "rows%s" % (report.bytes, note))
        matched = report.count(LINKED) + report.count(ORPHAN)
        if report.child_rows and not matched:
            lines.append("NOTE no child key was read as a GUID, so nothing "
                         "was matched against the parent. Check that "
                         "--child-field names a GUID column and not an "
                         "ObjectID column.")
        lines.extend(_section(report, ORPHAN,
                              "orphans: the parent is gone, largest first:",
                              sample))
        lines.extend(_section(report, UNKEYED,
                              "rows with no key, so no parent can exist:",
                              sample))
        lines.extend(_section(report, MALFORMED,
                              "rows whose key is not a GUID, not checked:",
                              sample))
    lines.append("")
    lines.append("VERDICT: %s" % verdict(report))
    return lines


def findings_rows(report):
    """The rows --out writes: every child row that is not LINKED."""
    rows = []
    for r in report.results:
        if r.cls != LINKED:
            rows.append((r.child.line, r.child.row_id, r.child.raw, r.cls,
                         "" if r.size is None else r.size, r.reason))
    return rows


# ------------------------------------------------------------------------- I/O

def _no_nul(handle):
    """Yield the lines of handle, and raise csv.Error on a NUL byte.

    The csv module reads a NUL as data on Python 3.11 and later and refuses it
    on 3.9 and 3.10. A UTF-16 file is full of them. This makes the answer the
    same on every version: the file is unreadable, exit 2.
    """
    for line in handle:
        if "\0" in line:
            raise csv.Error("line contains NUL")
        yield line


def read_csv(path):
    """Return (header, [(start_line, record), ...]).

    A blank line is skipped, except in a one-column file. There it is a row
    whose only cell is empty, which is how an export writes a NULL key.

    start_line is the line the record begins on, so a quoted cell that holds a
    line break does not move the numbers that follow it. The reader is strict:
    a quote that is opened and never closed would otherwise swallow the rest of
    the file as one cell, and the rows after it would silently not exist.
    """
    header = None
    records = []
    with io.open(path, "r", encoding="utf-8-sig", errors="replace",
                 newline="") as handle:
        reader = csv.reader(_no_nul(handle), strict=True)
        while True:
            start = reader.line_num + 1
            try:
                record = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                raise csv.Error("%s: the record that starts on line %d: %s"
                                % (path, start, exc))
            if not record:
                if header is None or len(header) != 1:
                    continue
                record = [""]
            if header is None:
                header = record
            else:
                records.append((start, record))
    return header or [], records


def column_index(header, name, path):
    """The one column called name, without regard to case. Raises ValueError."""
    wanted = name.strip().lower()
    hits = [i for i, h in enumerate(header) if h.strip().lower() == wanted]
    if not hits:
        raise ValueError("%s: no column named %s. It has: %s"
                         % (path, name,
                            ", ".join(header) if header else "(no columns)"))
    if len(hits) > 1:
        raise ValueError("%s: %d columns are named %s, so the tool cannot "
                         "tell which one to read." % (path, len(hits), name))
    return hits[0]


def _cell(record, index):
    return record[index] if index < len(record) else ""


def load_table(path, names):
    """Rows of (csv_line, cell, cell, ...), one cell per column name."""
    header, records = read_csv(path)
    indexes = [column_index(header, name, path) for name in names]
    return [(line,) + tuple(_cell(rec, i) for i in indexes)
            for line, rec in records]


def load_parents(path, args):
    return [(row[0], row[1]) for row in load_table(path, [args.parent_field])]


def load_children(path, args):
    names = [args.child_field]
    if args.row_id_field:
        names.append(args.row_id_field)
    if args.size_field:
        names.append(args.size_field)
    children = []
    for row in load_table(path, names):
        cells = list(row[1:])
        raw = cells.pop(0)
        row_id = cells.pop(0) if args.row_id_field else ""
        size_text = cells.pop(0) if args.size_field else ""
        children.append(Child(row[0], raw, row_id, size_text))
    return children


def may_replace(path):
    """True when --out can be written without destroying somebody's file.

    That is a path with nothing at it, an empty file, or a findings file from
    an earlier run of this tool. Any other file, an input table reached by a
    hard link or a symbolic link included, is refused.
    """
    if not os.path.exists(path):
        return True
    try:
        with io.open(path, "r", encoding="utf-8-sig", errors="replace",
                     newline="") as handle:
            head = handle.readline(len(OUT_HEADER) + 8)
    except (IOError, OSError):
        return False
    return head == "" or head.rstrip("\r\n") == OUT_HEADER


def write_findings(path, report):
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(OUT_COLUMNS)
        for row in findings_rows(report):
            writer.writerow(row)


# ------------------------------------------------------------------- self-test

def self_test():
    """Run the assertions in a temp directory that is removed even when one
    of them raises, so a crash never leaves relorphan-selftest-* behind."""
    tmp = tempfile.mkdtemp(prefix="relorphan-selftest-")
    try:
        return _self_test(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _self_test(tmp):
    """Assertions over the decision core and the CLI. No network, no
    credentials. The only files are the ones written under tmp."""
    passed = [0]
    failed = []

    def check(cond, label):
        if cond:
            passed[0] += 1
            print("PASS  %s" % label)
        else:
            failed.append(label)
            print("FAIL  %s" % label)

    def raises(fn, label):
        try:
            fn()
        except ValueError:
            check(True, label)
        except Exception as exc:
            check(False, "%s (wrong exception %r)" % (label, exc))
        else:
            check(False, "%s (no error raised)" % label)

    def put(name, text):
        path = os.path.join(tmp, name)
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def put_bytes(name, data):
        path = os.path.join(tmp, name)
        with io.open(path, "wb") as handle:
            handle.write(data)
        return path

    def read(path):
        with io.open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()

    def cli(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def ch(line, raw, row_id="", size=""):
        return Child(line, raw, row_id, size)

    print("relorphan self-test: temporary files only, no network, no "
          "credentials")
    print("-" * 68)

    import sqlite3  # kept out of the module top so the tool runs without it

    # Four synthetic GlobalIDs that exist as parents, and one that does not.
    g1 = "9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b"
    g2 = "0a1b2c3d-4e5f-4061-8273-94a5b6c7d8e9"
    g3 = "11112222-3333-4444-5555-666677778888"
    g4 = "aaaabbbb-cccc-4ddd-8eee-ffff00001111"
    gone = "c0ffee00-1234-4abc-9def-0123456789ab"
    braced = "{%s}"

    # ---- one id, many spellings
    check(normalize_guid(g1) == (g1, KEY_OK),
          "a lower case hyphenated GUID is its own canonical form")
    check(normalize_guid(g1.upper()) == (g1, KEY_OK),
          "an upper case GUID is the same id")
    check(normalize_guid(g1.replace("-", "").upper()) == (g1, KEY_OK),
          "a bare upper case GUID is the same id")
    check(normalize_guid(braced % g1.upper()) == (g1, KEY_OK),
          "a braced upper case GlobalID is the same id as the bare lower "
          "case one  <-- pinned defect")
    check(normalize_guid(braced % g1) == (g1, KEY_OK),
          "a braced lower case GUID is the same id")
    check(normalize_guid("(%s)" % g1) == (g1, KEY_OK),
          "a parenthesised GUID (.NET format P) is the same id")
    check(normalize_guid(g1.replace("-", "")) == (g1, KEY_OK),
          "a bare GUID with no hyphens (.NET format N) is the same id")
    check(normalize_guid(braced % g1.replace("-", "")) == (g1, KEY_OK),
          "a braced GUID with no hyphens is the same id")
    check(normalize_guid("  %s \t" % braced % g1) == (g1, KEY_OK),
          "spaces and tabs around the cell are not part of the id")
    check(normalize_guid(u"\u00a0" + g1) == (g1, KEY_OK),
          "a no-break space from a web page copy is not part of the id")

    # ---- cells that are not an id
    for cell in ("", "   ", "\t"):
        check(normalize_guid(cell) == (None, KEY_BLANK),
              "the cell %a is blank, not malformed" % cell)
    for cell in ("0" * 32, braced % ("00000000-0000-0000-0000-" + "0" * 12)):
        check(normalize_guid(cell) == (None, KEY_NULL),
              "the all-zero GUID %a is a null key, not an id" % cell)
    bad_cells = [
        (g1[:-1], "a GUID one digit short"),
        (g1 + "x", "a GUID with a character after it, which SQL Server would "
                   "silently cut to 36 characters"),
        (g1[:-1] + "g", "a GUID with a non-hex digit"),
        ("{" + g1, "an opening brace with no closing brace"),
        (g1 + "}", "a closing brace with no opening brace"),
        ("(" + g1 + "}", "a parenthesis closed by a brace"),
        ("{{" + g1 + "}}", "a doubly braced GUID"),
        ("9f1c2a643-b7d-4e58-8a01-5c6d7e8f9a0b", "hyphens in the wrong places"),
        (g1.replace("-", "")[:-1], "31 bare hex digits"),
        (g1.replace("-", "") + "0", "33 bare hex digits"),
        ("{0x9f1c2a64,0x3b7d,0x4e58,{0x8a,0x01,0x5c,0x6d,0x7e,0x8f,0x9a,"
         "0x0b}}", "the .NET format X, which no geodatabase writes"),
        (g1.replace("-", " ", 1), "a space where a hyphen belongs"),
        (u"\u0669" + g1[1:], "an Arabic-Indic digit nine, which int() would "
                             "read as 9"),
        ("104", "an ObjectID in a GlobalID column"),
        ("{}", "empty braces"),
        ("{ %s }" % g1, "spaces inside the braces, which are not the spaces "
                        "around the cell"),
        ("{" + g1 + "\n}", "a line break inside the braces, which a "
                           "dollar-anchored pattern would let through"),
        (g1.replace("-", "")[:16] + "\n" + g1.replace("-", "")[16:],
         "a line break inside a bare GUID"),
        ("{", "a single brace"),
    ]
    for cell, label in bad_cells:
        pin = ("  <-- pinned defect"
               if cell in (g1 + "x", "{" + g1 + "\n}") else "")
        check(normalize_guid(cell) == (None, KEY_BAD),
              "%s is malformed%s" % (label, pin))

    # ---- sizes
    check(to_size("2400000") == 2400000, "a plain byte count is read")
    check(to_size(" 12 ") == 12, "a byte count with spaces is read")
    check(to_size("0") == 0, "zero bytes is a size, not a missing one")
    for cell in ("", "1,024", "12.5", "2400000.0", "-5", u"\u0663", "n/a",
                 "1" * 19):
        check(to_size(cell) is None,
              "the size %a is unknown, never guessed" % cell)
    check(to_size("9" * 18) == 10 ** 18 - 1,
          "a size of 18 digits is the longest that is read")
    check(to_size("1" * 4301) is None,
          "a size of 4301 digits is unknown and does not raise, where int() "
          "refuses it on Python 3.11 and later  <-- pinned defect")
    check(to_size("12\n") == 12 and to_size("1\n2") is None,
          "a line break inside a size makes it unknown")

    # ---- the core, on the layout of the README demo
    parents = [(2, braced % g1.upper()), (3, braced % g2.upper()),
               (4, braced % g3.upper()), (5, braced % g4.upper())]
    children = [
        ch(2, g1, "1", "2400000"),
        ch(3, braced % g2.upper(), "2", "1800000"),
        ch(4, g3.replace("-", ""), "3", "2100000"),
        ch(5, braced % gone.upper(), "4", "3500000"),
        ch(6, braced % gone.upper(), "5", "3300000"),
        ch(7, "", "6", "900000"),
        ch(8, "104", "7", "1500000"),
        ch(9, g4, "8", "2000000"),
    ]
    report = reconcile(parents, children, True)
    counts = dict((cls, report.count(cls)) for cls in CLASSES)
    check(counts == {LINKED: 4, ORPHAN: 2, UNKEYED: 1, MALFORMED: 1},
          "the demo splits 8 child rows into 4 linked, 2 orphans, 1 unkeyed "
          "and 1 malformed")
    check(sum(counts.values()) == len(children) == len(report.results),
          "every child row lands in exactly one class")
    check(report.aliased == 3,
          "three linked rows match only after the spelling is normalised")
    check(report.bytes == 3500000 + 3300000 + 900000,
          "the bytes held by orphans and unkeyed rows are added up")
    check(report.unsized == 0 and report.findings() == 4,
          "the demo has four findings and every size is readable")
    check([r.cls for r in report.results] ==
          [LINKED, LINKED, LINKED, ORPHAN, ORPHAN, UNKEYED, MALFORMED,
           LINKED], "the results keep the order of the child file")
    check(gate(report) == 1, "orphans fail the gate with exit 1")
    check(all(r.size is not None for r in report.results),
          "a size is kept for every row when a size column is named")

    # The plain join the tool replaces, run for real in SQLite.
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE parent (k TEXT)")
    db.execute("CREATE TABLE child (k TEXT)")
    db.executemany("INSERT INTO parent VALUES (?)", [(p[1],) for p in parents])
    db.executemany("INSERT INTO child VALUES (?)", [(c.raw,) for c in children])
    verbatim = db.execute("SELECT COUNT(*) FROM child c LEFT JOIN parent p ON "
                          "c.k = p.k WHERE p.k IS NULL").fetchone()[0]
    db.close()
    check(verbatim == 7 and counts[ORPHAN] == 2,
          "a LEFT JOIN on the raw text calls 7 of 8 rows orphans, and this "
          "tool finds 2  <-- pinned defect")
    check(verbatim - sum(counts[c] for c in (ORPHAN, UNKEYED, MALFORMED))
          == report.aliased,
          "the rows a verbatim join gets wrong are exactly the ones the "
          "spelling line counts")

    plain = reconcile(parents, children, False)
    check(plain.bytes == 0 and plain.unsized == 0 and not plain.sized
          and all(r.size is None for r in plain.results),
          "without a size column no bytes are added and none is invented")

    odd = reconcile(parents, [ch(2, gone, "9", "n/a"), ch(3, g1, "10", "x"),
                              ch(4, "", "11", "12")], True)
    check(odd.unsized == 1 and odd.bytes == 12,
          "an orphan whose size is unreadable is counted apart, not as zero; "
          "a linked row's size is never added")

    zero = reconcile(parents, [ch(2, gone, "1", "0"), ch(3, "", "2", "0")],
                     True)
    check(zero.unsized == 0 and zero.bytes == 0 and zero.findings() == 2,
          "a real zero-byte orphan is sized as zero, not as unreadable  "
          "<-- pinned defect")

    # Parent side: what makes a run unable to prove an orphan.
    empty_parent = reconcile([], children)
    check(empty_parent.refused == [NO_PARENTS] and not empty_parent.results
          and gate(empty_parent) == 3,
          "an empty parent table is refused with exit 3, not reported as "
          "eight orphans  <-- pinned defect")
    hole = reconcile([(2, g1), (3, ""), (4, "junk"), (5, "0" * 32), (6, g2)],
                     [ch(2, g1)])
    check(hole.refused == [BAD_PARENTS % 3] and gate(hole) == 3
          and [state for _, _, state in hole.bad_parents]
          == [KEY_BLANK, KEY_BAD, KEY_NULL] and not hole.results,
          "a parent row with no readable GlobalID refuses the run, because "
          "it could be the one an orphan points at  <-- pinned defect")
    both = reconcile([], [])
    check(gate(both) == 3, "an empty parent table is refused even when the "
                           "child table is empty too")

    # One GlobalID on two parent rows, spelled two ways.
    twice = reconcile([(2, braced % g1.upper()), (3, g1)],
                      [ch(2, g1), ch(3, braced % g1.upper()),
                       ch(4, g1.replace("-", ""))])
    check(twice.count(LINKED) == 3 and twice.aliased == 1,
          "a parent id that appears twice is not an orphan under either "
          "spelling, and only the third spelling counts as normalised")

    # The gate.
    clean = reconcile(parents, [ch(2, g1), ch(3, braced % g2.upper())])
    check(gate(clean) == 0 and clean.findings() == 0,
          "a child table whose every key has a parent exits 0")
    check(gate(reconcile(parents, [ch(2, "")])) == 1,
          "a row with no key fails the gate: it has no parent")
    check(gate(reconcile(parents, [ch(2, "104")])) == 1,
          "a row whose key is not a GUID fails the gate, so a column of "
          "ObjectIDs is never read as clean  <-- pinned defect")
    check(gate(reconcile(parents, [])) == 4,
          "a child table with no rows exits 4, not 0: a failed export looks "
          "the same  <-- pinned defect")
    check("NOTHING COMPARED" in verdict(reconcile(parents, [])),
          "the empty-child verdict says nothing was compared")
    check(verdict(clean).startswith("clean. All 2 child row(s)"),
          "the clean verdict counts the rows it checked")
    check(verdict(report).startswith("4 child row(s) are not attached"),
          "the finding verdict counts the rows without a parent")
    check(verdict(hole) == "REFUSED", "the refused verdict is one word")
    check("parent export is complete" in verdict(report)
          and "parent export" not in verdict(reconcile(parents, [ch(2, "104")])
                                             ),
          "only a verdict with an orphan in it tells you to check the parent "
          "export")

    # ---- describe
    text = "\n".join(describe(report))
    check("rows classified: 8 of 8" in text and "  LINKED     4" in text
          and "  ORPHAN     2" in text and "  UNKEYED    1" in text
          and "  MALFORMED  1" in text,
          "the printout lists every class and the rows add up")
    check("spelling: 3 child row(s) match a parent only after braces, case "
          "or hyphens are normalised" in text,
          "the printout says how many rows a verbatim join would miss")
    check("storage: 7700000 byte(s) sit in the ORPHAN and UNKEYED rows"
          in text, "the printout reports the storage bill")
    check("storage" not in "\n".join(describe(plain)),
          "no storage line is printed when no size column was named")
    check("(1 row(s) had no readable size)" in "\n".join(describe(odd)),
          "the storage line says how many orphans had no readable size")
    exact = reconcile(parents, [ch(2, braced % g2.upper())])
    check("spelling:" not in "\n".join(describe(exact)),
          "the spelling line is left out when no row needed it")
    orphan_lines = [l for l in text.splitlines() if l.startswith("  line ")]
    check(orphan_lines[0].startswith("  line 5, id 4, 3500000 byte(s): no "
                                     "parent row has the GlobalID " + gone)
          and orphan_lines[1].startswith("  line 6, id 5, 3300000"),
          "orphans are listed largest first, with the csv line, the row id, "
          "the size and the canonical id")
    check("VERDICT: 4 child row(s) are not attached to a parent."
          in describe(report)[-1], "the last line is the verdict")
    check("NOTE" not in text, "no note is printed when keys were matched")

    many = reconcile(parents, [ch(i, "{%08x-0000-4000-8000-000000000000}" % i,
                                  str(i), str(i * 10))
                               for i in range(1, 13)], True)
    capped = describe(many, 10)
    check(sum(1 for l in capped if l.startswith("  line ")) == 10
          and "  ... and 2 more" in capped,
          "a long list is cut at the sample size and says how many are left")
    first = [l for l in capped if l.startswith("  line ")][0]
    check(first.startswith("  line 12, id 12, 120 byte(s)"),
          "the cut keeps the largest rows")
    none = describe(many, 0)
    check(not any(l.startswith("  line ") for l in none)
          and "  ... and 12 more" in none,
          "--sample 0 lists no rows and still says how many there are")
    tied = reconcile(parents, [ch(5, gone, "b", "100"), ch(3, gone, "a", "100"),
                               ch(4, gone, "c", "n/a"), ch(6, gone, "d", "7")],
                     True)
    listed = [l for l in describe(tied) if l.startswith("  line ")]
    check([l.split(",")[0] for l in listed] ==
          ["  line 3", "  line 5", "  line 6", "  line 4"],
          "equal sizes list in file order and an unknown size comes last")
    noid = describe(reconcile(parents, [ch(2, gone)]))
    check("  line 2: no parent row has the GlobalID" in "\n".join(noid),
          "a row with no id and no size column is listed by line alone")
    allbad = describe(reconcile(parents, [ch(2, "104"), ch(3, "105")]))
    check(any(l.startswith("NOTE no child key was read as a GUID")
              for l in allbad) and "rows whose key is not a GUID, not "
          "checked:" in allbad,
          "a column that holds no GUID at all gets a note that names the "
          "likely cause")
    refused_text = "\n".join(describe(hole, 1))
    check("REFUSED   3 parent row(s) have no readable GlobalID" in refused_text
          and "  parent line 3: ''" in refused_text
          and "  ... and 2 more" in refused_text
          and refused_text.endswith("VERDICT: REFUSED")
          and "rows classified" not in refused_text,
          "a refusal names the parent lines it could not read and prints no "
          "counts")
    refused_empty = "\n".join(describe(empty_parent))
    check(NO_PARENTS in refused_empty and "parent line" not in refused_empty,
          "an empty parent table is refused with its own message")

    # Lines that must not appear, and counts that must be the right count.
    all_orphans = "\n".join(describe(reconcile(parents, [ch(2, gone),
                                                         ch(3, gone)])))
    check("NOTE" not in all_orphans and "ORPHAN     2" in all_orphans,
          "a run where every child is an orphan gets no note about "
          "ObjectIDs, because its keys were read as GUIDs and matched  "
          "<-- pinned defect")
    check("NOTE" not in "\n".join(describe(reconcile(parents, []))),
          "a run with no child rows gets no note about ObjectIDs  "
          "<-- pinned defect")
    check("parents: 4 row(s), every GlobalID readable" in text
          and "parents: 4 row(s)" in "\n".join(describe(reconcile(
              parents, [ch(2, g1)]))),
          "the parents line counts parent rows, not child rows  "
          "<-- pinned defect")
    three = [ch(i, "{%08x-0000-4000-8000-000000000000}" % i) for i in (1, 2, 3)]
    exact_cut = describe(reconcile(parents, three), 3)
    check(sum(1 for l in exact_cut if l.startswith("  line ")) == 3
          and not any("more" in l for l in exact_cut),
          "a list that is exactly --sample rows long does not say it is "
          "missing 0 more  <-- pinned defect")
    check(DEFAULT_SAMPLE == 10, "the default sample is 10 rows")

    rows = findings_rows(report)
    check(len(rows) == 4 and rows[0] == (5, "4", "{%s}" % gone.upper(),
                                         ORPHAN, 3500000,
                                         "no parent row has the GlobalID "
                                         + gone),
          "--out rows keep the file order and carry the raw key")
    check(findings_rows(plain)[0][4] == "",
          "an unknown size is an empty cell in --out, not a zero")

    # ---- reading a CSV
    check(read_csv(put("empty.csv", "")) == ([], []),
          "an empty file has no header and no rows")
    check(read_csv(put("head.csv", "A,B\n")) == (["A", "B"], []),
          "a header with no rows reads as no rows")
    header, recs = read_csv(put("bom.csv", u"\ufeffGlobalID,N\r\n"
                                           u"{X},1\r\n\r\n\r\n2,3\r\n"))
    check(header == ["GlobalID", "N"] and recs == [(2, ["{X}", "1"]),
                                                   (5, ["2", "3"])],
          "a BOM from Excel does not stay in the first column name, and "
          "blank lines do not move the line numbers  <-- pinned defect")
    header, recs = read_csv(put("quoted.csv",
                                'A,B\n"x\ny",1\n\n2,3\n'))
    check(recs == [(2, ["x\ny", "1"]), (5, ["2", "3"])],
          "a quoted line break does not move the reported line off the file"
          "  <-- pinned defect")
    header, recs = read_csv(put_bytes("latin.csv", b"A,B\n\xff\xfe,1\n"))
    check(recs[0][1][0] == u"\ufffd\ufffd",
          "bytes that are not UTF-8 become U+FFFD and do not stop the read")
    raises(lambda: column_index(["A", "B"], "C", "t.csv"),
           "a column that is not there raises, and names the columns it has")
    raises(lambda: column_index([], "C", "t.csv"),
           "a file with no header raises on any column")
    raises(lambda: column_index(["a", "A"], "A", "t.csv"),
           "two columns that differ only by case are refused, not guessed")
    try:
        column_index(["A", "B"], "C", "t.csv")
    except ValueError as exc:
        check("t.csv: no column named C. It has: A, B" in str(exc),
              "the missing-column message lists the columns that exist")
    check(column_index([" GlobalID "], "GLOBALID", "t.csv") == 0,
          "a column name matches without regard to case or padding")
    check(_cell(["a"], 0) == "a" and _cell(["a"], 1) == "",
          "a short row reads its missing cells as blank")

    # ---- the demo files, read through the CLI
    assets = put("assets.csv",
                 "OBJECTID,GlobalID,CULVERT_NO\n"
                 "1,{%s},C-101\n2,{%s},C-102\n3,{%s},C-103\n4,{%s},C-104\n"
                 % (g1.upper(), g2.upper(), g3.upper(), g4.upper()))
    photos = put("photos.csv",
                 "ATTACHMENTID,REL_GLOBALID,ATT_NAME,DATA_SIZE\n"
                 "1,%s,c101_a.jpg,2400000\n"
                 "2,{%s},c102_a.jpg,1800000\n"
                 "3,%s,c103_a.jpg,2100000\n"
                 "4,{%s},c999_a.jpg,3500000\n"
                 "5,{%s},c999_b.jpg,3300000\n"
                 "6,,c000.jpg,900000\n"
                 "7,104,c104.jpg,1500000\n"
                 "8,%s,c104_a.jpg,2000000\n"
                 % (g1, g2.upper(), g3.replace("-", ""), gone.upper(),
                    gone.upper(), g4))
    code, out, err = cli(assets, photos, "--row-id-field", "ATTACHMENTID",
                         "--size-field", "DATA_SIZE")
    check(code == 1 and err == ""
          and out.startswith("relorphan: %s 4 row(s), %s 8 row(s)\n"
                             % (assets, photos))
          and "rows classified: 8 of 8" in out
          and "VERDICT: 4 child row(s) are not attached to a parent." in out,
          "the demo exits 1 with the four findings and no stderr")
    check("line 5, id 4, 3500000 byte(s)" in out
          and "line 7, id 6, 900000 byte(s): the key is blank" in out
          and "line 8, id 7, 1500000 byte(s): '104' is not a GUID" in out,
          "the demo lists each class with the line the row is on")
    code, out2, err = cli(assets, photos)
    check(code == 1 and "storage" not in out2 and "byte(s)" not in out2
          and "line 5: no parent row" in out2,
          "without --size-field and --row-id-field the lists show the line "
          "alone")

    lower = put("hosted-assets.csv", "objectid,globalid\n1,%s\n" % g1)
    lowerc = put("hosted-photos.csv", "attachmentid,rel_globalid\n1,%s\n"
                 % braced % g1.upper())
    code, out, err = cli(lower, lowerc)
    check(code == 0 and "VERDICT: clean. All 1 child row(s)" in out
          and "spelling: 1 child row(s)" in out,
          "lower case column names from a hosted export match the default "
          "fields, and a braced upper case key matches a bare lower case "
          "parent  <-- pinned defect")

    # ---- --out and --apply
    target = os.path.join(tmp, "findings.csv")
    code, out, err = cli(assets, photos, "--out", target)
    check(code == 1 and not os.path.exists(target)
          and "Check only. %s was not written. Re-run with --apply." % target
          in out, "--out alone writes nothing")
    code, out, err = cli(assets, photos, "--out", target, "--apply",
                         "--row-id-field", "ATTACHMENTID",
                         "--size-field", "DATA_SIZE")
    written = read(target)
    check(code == 1 and out.endswith("\nwrote %s\n" % target)
          and written.splitlines()[0] ==
          "csv_line,row_id,raw_key,class,size,reason"
          and len(written.splitlines()) == 5
          and "5,4,{%s},ORPHAN,3500000," % gone.upper() in written
          and "7,6,,UNKEYED,900000,the key is blank" in written
          and "LINKED" not in written,
          "--apply writes the four findings and no linked row")
    check(chr(13) not in written and written.count(chr(10)) == 5,
          "the findings file ends every line with LF, on every platform")
    for flag in ("--ap", "--app", "--appl"):
        stray = os.path.join(tmp, "stray%s.csv" % flag[2:])
        code, out, err = cli(assets, photos, "--out", stray, flag)
        check(code == 64 and not os.path.exists(stray) and out == ""
              and "unrecognized arguments: %s" % flag in err,
              "%s is refused with exit 64 and writes nothing, so a prefix of "
              "--apply never applies  <-- pinned defect" % flag)
    for flag in ("--ou", "--sam", "--row", "--size", "--child", "--self",
                 "--delete"):
        code, out, err = cli(assets, photos, flag, "1")
        check(code == 64 and out == "",
              "%s is refused with exit 64, not read as another flag" % flag)
    code, out, err = cli(assets, photos, "--apply")
    check(code == 64 and "--apply needs --out" in err and out == "",
          "--apply with no --out is a usage error")
    keep = read(assets)
    for victim in (assets, photos, os.path.join(tmp, ".", "assets.csv")):
        code, out, err = cli(assets, photos, "--out", victim, "--apply")
        check(code == 64 and "is also an input table" in err and out == "",
              "--out naming an input table is refused, so --apply cannot "
              "replace a table with its own findings  <-- pinned defect")
    check(read(assets) == keep, "the refused run left the parent table as it "
                                "was")
    code, out, err = cli(assets, photos, "--out", assets)
    check(code == 64, "the same refusal applies on a dry run")

    # --out may replace nothing but an empty file or an earlier findings file.
    notes = put("notes.txt", "precious\n")
    for extra in ((), ("--apply",)):
        code, out, err = cli(assets, photos, "--out", notes, *extra)
        check(code == 64 and "already exists and is not an empty file" in err
              and out == "" and read(notes) == "precious\n",
              "--out naming some other existing file is refused, on a dry run "
              "too, and the file keeps its content  <-- pinned defect")
    hard = os.path.join(tmp, "hard.csv")
    os.link(assets, hard)
    code, out, err = cli(assets, photos, "--out", hard, "--apply")
    check(code == 64 and out == "" and read(assets) == keep,
          "--out that is a hard link to an input table is refused, which a "
          "comparison of paths cannot see  <-- pinned defect")
    folder = os.path.join(tmp, "folder")
    os.mkdir(folder)
    code, out, err = cli(assets, photos, "--out", folder, "--apply")
    check(code == 64 and out == "", "--out naming a folder is refused")
    check(may_replace(os.path.join(tmp, "nothing-here.csv")),
          "a path with nothing at it may be written")
    check(may_replace(put("zero.csv", "")),
          "an empty file may be replaced")
    check(may_replace(put("crlf-findings.csv", OUT_HEADER + "\r\nrow\r\n"))
          and may_replace(put("bom-findings.csv", u"\ufeff" + OUT_HEADER
                              + "\n")),
          "a findings file saved again by a spreadsheet, with CRLF or a BOM, "
          "may be replaced")
    check(not may_replace(put("blank-first.csv", "\n" + OUT_HEADER + "\n")),
          "a file that opens with a blank line is not an empty file")
    code, out, err = cli(assets, photos, "--out", target, "--apply")
    again = read(target)
    check(code == 1 and out.endswith("\nwrote %s\n" % target)
          and again.splitlines()[0] == OUT_HEADER
          and len(again.splitlines()) == 5 and again != written,
          "--out may replace the findings file an earlier run wrote, so a "
          "scheduled job can reuse one path")
    check(_same_file(os.path.join(tmp, "a.csv"), os.path.join(tmp, "b.csv"))
          is False, "two paths with nothing in common are not the same file")
    real_realpath = os.path.realpath
    try:
        os.path.realpath = lambda p: assets if p == "link-to-assets" else p
        check(_same_file("link-to-assets", assets)
              and not _same_file("link-to-photos", assets),
              "a path is compared after its links are resolved  "
              "<-- pinned defect")
    finally:
        os.path.realpath = real_realpath
    code, out, err = cli(assets)
    check(code == 64 and "two CSV tables are required" in err,
          "one table is a usage error")
    code, out, err = cli()
    check(code == 64, "no tables is a usage error")
    code, out, err = cli(assets, photos, "--sample", "-1")
    check(code == 64 and "--sample cannot be negative" in err,
          "a negative --sample is a usage error")
    code, out, err = cli(assets, photos, "--sample", "1")
    check(code == 1 and "  ... and 1 more" in out,
          "--sample 1 cuts the orphan list at one row")
    code, out, err = cli(assets, photos, "--sample", "0")
    check(code == 1 and err == "" and "  ... and 2 more" in out
          and not any(l.startswith("  line ") for l in out.splitlines()),
          "--sample 0 is accepted on the command line and lists no rows  "
          "<-- pinned defect")
    twelve = put("twelve.csv", "REL_GLOBALID\n" + "".join(
        "{%08x-0000-4000-8000-000000000000}\n" % i for i in range(1, 13)))
    code, out, err = cli(assets, twelve)
    check(code == 1 and "  ... and 2 more" in out
          and sum(1 for l in out.splitlines() if l.startswith("  line ")) == 10,
          "with no --sample, 10 rows are listed under a heading")
    code, out, err = cli(assets, photos, "--child-field", " REL_GLOBALID ")
    check(code == 1 and "rows classified: 8 of 8" in out and err == "",
          "a column name given with spaces around it still finds the column"
          "  <-- pinned defect")
    code, out, err = cli("--help")
    check(code == 0 and "--apply" in out and "usage: relorphan.py" in out,
          "--help prints the usage and exits 0")

    # ---- column and file failures
    code, out, err = cli(assets, photos, "--child-field", "NOPE")
    check(code == 64 and "no column named NOPE" in err
          and "ATTACHMENTID, REL_GLOBALID" in err and out == "",
          "a column that is not in the child file is exit 64 and names the "
          "columns it has")
    code, out, err = cli(assets, photos, "--parent-field", "NOPE")
    check(code == 64 and "no column named NOPE" in err,
          "a column that is not in the parent file is exit 64")
    code, out, err = cli(assets, photos, "--size-field", "NOPE")
    check(code == 64, "a size column that is not there is exit 64")
    dup = put("dup.csv", "GlobalID,GLOBALID\n%s,%s\n" % (g1, g2))
    code, out, err = cli(dup, photos)
    check(code == 64 and "2 columns are named GLOBALID" in err,
          "a duplicated column name is refused, not read as the last one")
    code, out, err = cli(os.path.join(tmp, "missing.csv"), photos)
    check(code == 2 and "missing.csv" in err and out == "",
          "a file that is not there exits 2, not 1")
    big = put("big.csv", "GlobalID,X\n%s,%s\n" % (g1, "x" * 200000))
    code, out, err = cli(big, photos)
    check(code == 2 and "field larger than field limit" in err,
          "a cell over the csv limit exits 2, not a crash")
    quote = put("quote.csv",
                'ATTACHMENTID,REL_GLOBALID,ATT_NAME\n1,%s,"unclosed.jpg\n'
                "2,%s,x\n3,%s,y\n" % (g1, gone, gone))
    code, out, err = cli(assets, quote)
    check(code == 2 and out == "" and "quote.csv" in err
          and "the record that starts on line 2" in err,
          "a quote that is opened and never closed exits 2 and names the "
          "line, instead of reading the rest of the file as one cell and "
          "printing clean  <-- pinned defect")
    nul = put_bytes("nul.csv", b"REL_GLOBALID\n" + g1.encode("ascii")
                    + b"\x00\n")
    code, out, err = cli(assets, nul)
    check(code == 2 and out == "" and "line contains NUL" in err,
          "a NUL byte exits 2 on every Python version, not 2 on 3.10 and "
          "a quiet MALFORMED row on 3.11  <-- pinned defect")
    utf16 = put_bytes("utf16.csv", u"REL_GLOBALID\n".encode("utf-16"))
    code, out, err = cli(assets, utf16)
    check(code == 2 and "line contains NUL" in err,
          "a UTF-16 file exits 2 on every Python version")
    code, out, err = cli(put_bytes("zero-bytes.csv", b""), photos)
    check(code == 64 and "no column named GLOBALID" in err
          and "(no columns)" in err,
          "an empty parent file is a missing column, exit 64")
    semi = put("semi.csv", "ATTACHMENTID;REL_GLOBALID\n1;%s\n" % g1)
    code, out, err = cli(assets, semi)
    check(code == 64 and "no column named REL_GLOBALID" in err
          and "It has: ATTACHMENTID;REL_GLOBALID" in err,
          "a semicolon delimited file is one column and exits 64, never "
          "clean")
    nl_cell = '"{%s\n}"' % g1
    code, out, err = cli(put("nl-parent.csv", "GlobalID\n%s\n" % nl_cell),
                         put("nl-child.csv", "REL_GLOBALID\n%s\n" % g1))
    check(code == 3 and "VERDICT: REFUSED" in out,
          "a parent key with a line break inside its braces refuses the run, "
          "so a real child is never called an orphan of it  "
          "<-- pinned defect")
    code, out, err = cli(assets, put("nl-child2.csv",
                                     "REL_GLOBALID\n%s\n" % nl_cell))
    check(code == 1 and "  MALFORMED  1" in out and "  ORPHAN     0" in out,
          "a child key with a line break inside its braces is malformed")
    hugesize = put("hugesize.csv", "REL_GLOBALID,DATA_SIZE\n%s,%s\n"
                   % (gone, "1" * 4301))
    code, out, err = cli(assets, hugesize, "--size-field", "DATA_SIZE")
    check(code == 1 and "1 row(s) had no readable size" in out
          and "Traceback" not in err,
          "a size cell of 4301 digits is counted as unreadable and does not "
          "crash the run  <-- pinned defect")
    trail = put("trail.csv", "REL_GLOBALID,N\n%s,1\n,,\n" % g1)
    code, out, err = cli(assets, trail)
    check(code == 1 and "  UNKEYED    1" in out,
          "a row of empty cells in the child file is an unkeyed row")
    code, out, err = cli(put("trail-parent.csv", "GlobalID,N\n%s,1\n,,\n"
                             % g1), photos)
    check(code == 3 and "parent line 3: ''" in out,
          "a row of empty cells in the parent file refuses the run")
    zwsp = put("zwsp.csv", u"REL_GLOBALID\n\u200b%s\n" % g1)
    code, out, err = cli(assets, zwsp)
    check(code == 1 and "  MALFORMED  1" in out,
          "a zero width space around a key makes it malformed, never clean")
    code, out, err = cli(assets, photos, "--out",
                         os.path.join(tmp, "no-such-dir", "f.csv"), "--apply")
    check(code == 2 and "could not write" in err
          and "VERDICT: 4 child row(s)" in out,
          "a write that fails exits 2, and the verdict is already printed "
          "above it  <-- pinned defect")

    # ---- the verdicts through the CLI
    head = put("head-only.csv", "ATTACHMENTID,REL_GLOBALID\n")
    code, out, err = cli(assets, head)
    check(code == 4 and "NOTHING COMPARED" in out,
          "a child table with no rows exits 4")
    emptyp = put("empty-parent.csv", "GlobalID\n")
    target2 = os.path.join(tmp, "refused.csv")
    code, out, err = cli(emptyp, photos, "--out", target2, "--apply")
    check(code == 3 and "VERDICT: REFUSED" in out
          and "Refused. %s was not written" % target2 in out
          and not os.path.exists(target2),
          "a refused run exits 3 and --apply writes nothing")
    holes = put("holes.csv", "GlobalID\n%s\n\nnot-a-guid\n" % g1)
    code, out, err = cli(holes, photos)
    check(code == 3 and "  parent line 4: 'not-a-guid'" in out,
          "a parent row with no readable id exits 3 and names its line")
    ids = put("objectids.csv", "REL_GLOBALID\n12\n13\n")
    code, out, err = cli(assets, ids)
    check(code == 1 and "NOTE no child key was read as a GUID" in out,
          "a child column of ObjectIDs exits 1 with the note, not 0")
    linked = put("linked.csv", "REL_GLOBALID\n%s\n" % g1)
    code, out, err = cli(assets, linked)
    check(code == 0 and "VERDICT: clean. All 1 child row(s) have a parent."
          in out, "a clean run exits 0")
    short = put("short.csv", "ATTACHMENTID,REL_GLOBALID,DATA_SIZE\n9\n")
    code, out, err = cli(assets, short, "--size-field", "DATA_SIZE")
    check(code == 1 and "  UNKEYED    1" in out
          and "1 row(s) had no readable size" in out,
          "a short row reads as an unkeyed row with no size, not a crash")
    crlf = put("crlf.csv", "REL_GLOBALID\r\n%s\r\n" % gone)
    code, out, err = cli(assets, crlf)
    check(code == 1 and "line 2: no parent row" in out,
          "CRLF line endings read the same as LF")
    shifted = put("shifted.csv",
                  'ATTACHMENTID,REL_GLOBALID,ATT_NAME\n1,%s,"first\nsecond"'
                  "\n\n2,%s,x\n" % (g1, gone))
    code, out, err = cli(assets, shifted, "--row-id-field", "ATTACHMENTID")
    check(code == 1 and "line 5, id 2: no parent row" in out,
          "an orphan after a quoted line break and a blank line is reported "
          "on the line it is on  <-- pinned defect")

    # A blank line in a one-column export is a NULL key, not a gap.
    nullkey = put("nullkey.csv", "REL_GLOBALID\n%s\n\n%s\n" % (g1, g1))
    code, out, err = cli(assets, nullkey)
    check(code == 1 and "UNKEYED" in out and "line 3: the key is blank" in out,
          "a blank line in a one-column child file is an UNKEYED row, not "
          "a clean run  <-- pinned defect")
    check(read_csv(nullkey)[1][1] == (3, [""]),
          "a blank line in a one-column file reads as one empty cell on its "
          "own line  <-- pinned defect")
    code, out, err = cli(assets, put("nullonly.csv", "REL_GLOBALID\n\n"))
    check(code == 1 and "1 row(s)" in out,
          "a one-column child file of only a blank line is one UNKEYED row, "
          "not NOTHING COMPARED  <-- pinned defect")
    code, out, err = cli(put("nullparent.csv", "GlobalID\n%s\n\n" % g1),
                         nullkey)
    check(code == 3 and "REFUSED" in out,
          "a blank line in a one-column parent file refuses the run  "
          "<-- pinned defect")
    check(read_csv(put("blankhead.csv", "\n\nA\n1\n")) == (["A"], [(4, ["1"])]),
          "blank lines before the header of a one-column file are not rows")

    # ---- crash handling and the console
    real_run = globals()["_run"]

    def boom(argv):
        raise RuntimeError("probe")

    try:
        globals()["_run"] = boom
        code, out, err = cli(assets, photos)
    finally:
        globals()["_run"] = real_run
    check(code == 70 and "unexpected RuntimeError: probe" in err
          and "Traceback" in err and out == "",
          "an unexpected exception exits 70, not the 1 that means an orphan "
          "was found  <-- pinned defect")

    class Stream(object):
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    fake_out, fake_err = Stream(), Stream()
    real_streams = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = fake_out, fake_err
        _tolerate_odd_characters()
    finally:
        sys.stdout, sys.stderr = real_streams
    check(fake_out.calls == [{"errors": "replace"}]
          and fake_err.calls == [{"errors": "replace"}],
          "main reconfigures stdout and stderr to replace what they cannot "
          "encode")
    weird = put("weird.csv", u"ATTACHMENTID,REL_GLOBALID\n\u0141,\u0142x\n")
    child = subprocess.run(
        [sys.executable, os.path.abspath(__file__), assets, weird,
         "--row-id-field", "ATTACHMENTID"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, PYTHONIOENCODING="ascii"))
    check(child.returncode == 1 and b"id ?" in child.stdout
          and b"Traceback" not in child.stderr
          and b"u0142x" in child.stdout
          and b"VERDICT: 1 child row(s)" in child.stdout,
          "a row id the console cannot encode prints as ? and the verdict "
          "still arrives, instead of a traceback  <-- pinned defect")
    child = subprocess.run(
        [sys.executable, os.path.abspath(__file__), assets, photos, "--ap"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(child.returncode == 64 and child.stdout == b"",
          "the real command line refuses --ap with exit 64")

    # ---- what this source file is
    with io.open(os.path.abspath(__file__), "rb") as handle:
        raw_source = handle.read()
    source = raw_source.decode("ascii")
    check(all(b < 128 for b in bytearray(raw_source)),
          "the source is pure ASCII")
    tree = ast.parse(source, feature_version=(3, 9))
    check(tree is not None and not any(isinstance(n, ast.JoinedStr)
                                       for n in ast.walk(tree)),
          "the source parses under the 3.9 grammar and has no f-string")
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_names.add(node.module.split(".")[0])
    network = set(["socket", "ssl", "urllib", "http", "ftplib", "smtplib",
                   "requests", "xmlrpc", "asyncio", "arcpy"])
    check(not (imported_names & network),
          "the tool imports no network module and no arcpy")
    parsers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "ArgumentParser"]
    check(len(parsers) == 1 and all(
        any(k.arg == "allow_abbrev" and getattr(k.value, "value", True)
            is False for k in p.keywords) for p in parsers),
          "every argument parser sets allow_abbrev=False")
    writers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") in ("remove", "unlink",
                                                   "rmtree", "rmdir")]
    check(len(writers) == 1,
          "the only call that deletes anything is the self-test's own "
          "temporary directory")

    # ---- the temp directory goes even when the body raises
    seen = []

    def exploding(path):
        seen.append(path)
        raise RuntimeError("probe")

    real_body = globals()["_self_test"]
    try:
        globals()["_self_test"] = exploding
        try:
            self_test()
        except RuntimeError:
            seen.append("raised")
    finally:
        globals()["_self_test"] = real_body
    check(len(seen) == 2 and seen[1] == "raised"
          and not os.path.exists(seen[0]),
          "a self-test that raises still removes its temp directory  "
          "<-- pinned defect")

    # ---- the harness itself. A check() that cannot record a failure would
    # report every defect above as a pass, which is the one failure no other
    # assertion here could see. The probe's own output is swallowed so a green
    # run prints no FAIL line.
    quiet = sys.stdout
    sys.stdout = io.StringIO()
    mark = len(failed)
    try:
        check(False, "probe: a false condition must be recorded as a failure")
        raises(lambda: None, "probe: a call that raises nothing must fail")
        raises(lambda: [][0], "probe: the wrong exception must fail")
    finally:
        sys.stdout = quiet
    probe = failed[mark:]
    del failed[mark:]
    check(len(probe) == 3,
          "check() and raises() really do record a failure  <-- pinned defect")
    raises(lambda: (_ for _ in ()).throw(ValueError("x")),
           "and raises() accepts the ValueError it is looking for")

    def summary(passed_count, failures):
        print("-" * 68)
        total = passed_count + len(failures)
        if failures:
            print("%d assertions, %d failed" % (total, len(failures)))
            for f in failures:
                print("  FAILED: %s" % f)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0

    # The footer on its red path. A footer that could only print 0 failed
    # would hide every FAIL line above it from anyone who reads the last line.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        red = summary(1, ["probe one", "probe two"])
    check(red == 1 and "3 assertions, 2 failed" in buf.getvalue()
          and "  FAILED: probe two" in buf.getvalue(),
          "the footer reports failures by count and by name, and exits 1"
          "  <-- pinned defect")

    # ---- importing the module runs nothing.
    spec = importlib.util.spec_from_file_location(
        "relorphan_imported", os.path.abspath(__file__))
    imported = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    # No bytecode cache, so the self-test writes nothing outside its own
    # temporary directory.
    cache_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(imported)
    finally:
        sys.dont_write_bytecode = cache_before
    check(buf.getvalue() == "" and imported.gate(imported.reconcile(
        [(2, g1)], [])) == 4, "importing the module prints nothing and "
          "exposes the core")

    return summary(passed[0], failed)


# ------------------------------------------------------------------------- cli

def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="relorphan.py",
        description="Flag attachment and related rows whose parent feature "
                    "is gone. Braced and bare GlobalIDs are one id.",
        epilog="Export the whole parent table, not a filtered view. Nothing "
               "is written without --apply, and nothing is ever deleted.",
        allow_abbrev=False,
    )
    ap.add_argument("parent", nargs="?", metavar="PARENT",
                    help="the parent table as a CSV")
    ap.add_argument("child", nargs="?", metavar="CHILD",
                    help="the attachment or related table as a CSV")
    ap.add_argument("--parent-field", dest="parent_field",
                    default=DEFAULT_PARENT_FIELD,
                    help="the GlobalID column of the parent (default %s)"
                         % DEFAULT_PARENT_FIELD)
    ap.add_argument("--child-field", dest="child_field",
                    default=DEFAULT_CHILD_FIELD,
                    help="the column of the child that holds the parent's "
                         "GlobalID (default %s)" % DEFAULT_CHILD_FIELD)
    ap.add_argument("--row-id-field", dest="row_id_field",
                    help="a child column that names the row, such as "
                         "ATTACHMENTID, for the lists and --out")
    ap.add_argument("--size-field", dest="size_field",
                    help="a child column of byte counts, such as DATA_SIZE. "
                         "The bytes held by orphans are added up.")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="how many rows to list under each heading "
                         "(default %d)" % DEFAULT_SAMPLE)
    ap.add_argument("--out", help="path for the CSV of child rows that are "
                                  "not LINKED")
    ap.add_argument("--apply", action="store_true",
                    help="write --out. Without this nothing is written.")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="run the offline assertions and exit")
    return ap.parse_args(argv)


def _tolerate_odd_characters():
    """Make print() unable to fail on a character the console cannot encode.

    A piped stdout on Windows is cp1252. A column name read from a file that is
    not UTF-8 arrives with U+FFFD in it, which cp1252 cannot write, and the
    UnicodeEncodeError would exit 1 before the VERDICT line. It prints as ?.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def _same_file(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b))


def main(argv=None):
    """Run the CLI. An error this code did not anticipate exits 70, because 1
    is the code a scheduled job reads as 'an orphan was found'."""
    _tolerate_odd_characters()
    try:
        return _run(argv)
    except Exception as exc:
        print("error: unexpected %s: %s. This is a fault in the tool, not a "
              "finding about the data." % (type(exc).__name__, exc),
              file=sys.stderr)
        traceback.print_exc()
        return 70


def _run(argv):
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits 2 on a flag it refuses, and 2 here means a file
        # could not be read. A mistyped --ap is a usage error, so it gets 64.
        return 64 if exc.code == 2 else exc.code

    if args.self_test:
        return self_test()

    if not args.parent or not args.child:
        print("error: two CSV tables are required. Use --self-test to verify "
              "the tool without them.", file=sys.stderr)
        return 64
    if args.sample < 0:
        print("error: --sample cannot be negative.", file=sys.stderr)
        return 64
    if args.apply and not args.out:
        print("error: --apply needs --out.", file=sys.stderr)
        return 64
    if args.out:
        # Checked on a dry run too: the run that would clobber a table should
        # say so before --apply is added, not after.
        for table in (args.parent, args.child):
            if _same_file(args.out, table):
                print("error: --out %s is also an input table. Name a new "
                      "file." % args.out, file=sys.stderr)
                return 64
        if not may_replace(args.out):
            print("error: --out %s already exists and is not an empty file "
                  "or a findings file from this tool. Name a new file."
                  % args.out, file=sys.stderr)
            return 64

    try:
        parents = load_parents(args.parent, args)
        children = load_children(args.child, args)
    except ValueError as exc:
        # A column name the operator got wrong is a usage error, and a file
        # that could not be read is not. Only the exit code tells them apart.
        print("error: %s" % exc, file=sys.stderr)
        return 64
    except (IOError, OSError, csv.Error) as exc:
        # csv.Error too: a cell over csv's 131072 character limit is an
        # unreadable input, not a finding.
        print("error: %s" % exc, file=sys.stderr)
        return 2

    report = reconcile(parents, children, bool(args.size_field))
    print("relorphan: %s %d row(s), %s %d row(s)"
          % (args.parent, len(parents), args.child, len(children)))
    for line in describe(report, args.sample):
        print(line)

    if args.out:
        if not args.apply:
            print("\nCheck only. %s was not written. Re-run with --apply."
                  % args.out)
        elif report.refused:
            print("\nRefused. %s was not written, because nothing was "
                  "classified." % args.out)
        else:
            # A traceback here would exit 1, the code that means "an orphan
            # was found". A write that failed is a different fact.
            try:
                write_findings(args.out, report)
            # ponytail: csv.Error is not reachable offline here (the writer
            # only raises it for an unusable dialect), and OSError alone
            # would pass the self-test. It stays as a guard against a 3.x change.
            except (IOError, OSError, csv.Error) as exc:
                print("error: could not write %s: %s" % (args.out, exc),
                      file=sys.stderr)
                return 2
            print("\nwrote %s" % args.out)
    return gate(report)


if __name__ == "__main__":
    sys.exit(main())
