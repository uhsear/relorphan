# relorphan

Flag attachment rows and related rows whose parent feature is gone. A braced GlobalID and a bare
one count as the same id. Refuses to call a run clean when the parent export is empty or holds a
row it cannot read. Adds up the bytes the orphans hold.

A crew photographs every culvert it inspects. The culvert layer has an attachment table. Each
photo row holds the picture and the GlobalID of its culvert, in the column `REL_GLOBALID`.

Once a year somebody reloads the layer from a clean copy. The old culverts go. The new ones come
in with new GlobalIDs. Nobody touches the photo rows. Each one still holds a well formed GlobalID.
It belongs to a culvert that no longer exists.

No error appears, because no row is broken. The photos pile up, one full size picture per row,
and the storage bill grows. The story is a composite. It names no real layer.

Then somebody writes the check. They export the culvert layer from the enterprise geodatabase,
where GlobalIDs have braces and capital letters. They export the photos from the hosted copy,
where the same ids have no braces and small letters. A join on the text says that nearly every
photo is an orphan. Nobody believes that. The check is called noisy and put away, and the real
orphans stay in the table.

The other failure is quieter and costs more. The culvert export fails and writes a file with a
header and no rows. Now every photo is an orphan, the join is exact, and a clean-up job that
trusts it deletes the whole table.

This tool reads both exports. It reads `{9F1C2A64-...}`, `9f1c2a64-...` and the same id with no
hyphens as one id. It refuses to answer when the parent export cannot support an answer. It
never deletes a row.

```
$ python relorphan.py assets.csv photos.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE
relorphan: assets.csv 4 row(s), photos.csv 8 row(s)
rows classified: 8 of 8
  LINKED     4
  ORPHAN     2
  UNKEYED    1
  MALFORMED  1
parents: 4 row(s), every GlobalID readable
spelling: 3 child row(s) match a parent only after braces, case or hyphens are normalised. A verbatim join calls them orphans.
storage: 7700000 byte(s) sit in the ORPHAN and UNKEYED rows

orphans: the parent is gone, largest first:
  line 5, id 4, 3500000 byte(s): no parent row has the GlobalID c0ffee00-1234-4abc-9def-0123456789ab
  line 6, id 5, 3300000 byte(s): no parent row has the GlobalID c0ffee00-1234-4abc-9def-0123456789ab

rows with no key, so no parent can exist:
  line 7, id 6, 900000 byte(s): the key is blank

rows whose key is not a GUID, not checked:
  line 8, id 7, 1500000 byte(s): '104' is not a GUID in the bare, hyphenated, braced or parenthesised form

VERDICT: 4 child row(s) are not attached to a parent. Check that the parent export is complete before you delete anything.
```

The demo tables are synthetic. They are listed under [The demo tables](#the-demo-tables).

## Self-test

```
$ python relorphan.py --self-test
relorphan self-test: temporary files only, no network, no credentials
--------------------------------------------------------------------
PASS  a lower case hyphenated GUID is its own canonical form
PASS  an upper case GUID is the same id
PASS  a braced upper case GlobalID is the same id as the bare lower case one  <-- pinned defect
...
PASS  a LEFT JOIN on the raw text calls 7 of 8 rows orphans, and this tool finds 2  <-- pinned defect
...
PASS  an empty parent table is refused with exit 3, not reported as eight orphans  <-- pinned defect
PASS  a parent row with no readable GlobalID refuses the run, because it could be the one an orphan points at  <-- pinned defect
...
PASS  a child table with no rows exits 4, not 0: a failed export looks the same  <-- pinned defect
...
PASS  a text cell that starts with a tab gets one apostrophe in front  <-- pinned defect
PASS  the raw_key column is guarded when it starts with a carriage return  <-- pinned defect
PASS  a cell with a bare CR inside it is quoted on every Python, so the record is not split and the file still ends each record with LF  <-- pinned defect
...
PASS  --ap is refused with exit 64 and writes nothing, so a prefix of --apply never applies  <-- pinned defect
...
PASS  an empty child table with --apply exits 4 and writes no findings file, which would read as zero findings  <-- pinned defect
...
PASS  a quote that closes on a later line refuses the run and is not read as one clean row  <-- pinned defect
PASS  a quote that swallows rows and leaves the field count equal to the header's refuses the run, not exit 0 clean  <-- pinned defect
PASS  a child table with fewer rows than --expect-child-rows is refused with exit 3, not read as clean  <-- pinned defect
PASS  a column that holds a URL with a token is not copied to stdout or --out  <-- pinned defect
...
PASS  a blank line in a one-column child file is an UNKEYED row, not a clean run  <-- pinned defect
...
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
263 assertions, 0 failed
```

The full run prints all 263 assertions. The lines above are an excerpt of that run, in run
order. Each `...` line marks where lines of the run were left out.

## What already exists

The join itself is a solved problem. A SQL anti-join finds the child rows that have no parent:

```sql
SELECT COUNT(*) FROM child c LEFT JOIN parent p ON c.k = p.k WHERE p.k IS NULL;
```

`NOT EXISTS` does the same. When both columns are SQL Server `uniqueidentifier` columns, the
database compares 16-byte values and the spelling of the text does not arise. Microsoft documents
the type as "a 16-byte GUID" with comparison operators
([uniqueidentifier](https://learn.microsoft.com/en-us/sql/t-sql/data-types/uniqueidentifier-transact-sql)).
If you can run that query on the live tables, run it. It is exact and it needs no export.

This tool is for the cases where the ids reach you as text: a CSV export, a hosted layer, a
column that was cast to a string. The self-test builds a SQLite table of the demo ids and runs the
join above on the raw text. It calls 7 of the 8 demo rows orphans. The tool finds 2. The other 5
are 3 rows that only a different spelling hid, and 2 rows that are not orphans because their key
is blank or is not a GUID. The tool reports those 2 under their own classes.

Other tools meet the same braces problem from the other side. A thread on the Safe Software
community reports that FME 2019 added a "Strip braces" option to its File and SDE Geodatabase
readers ([thread](https://community.safe.com/architecture-14/uuid-braces-missing-10436)). That
fixes the spelling inside an FME workspace. It does not look for orphans.

A search of GitHub on 2026-10-22 found no repository named `relorphan`. That repository now
exists under this name, so a search today returns it. The searches
`orphan attachments` and `orphaned attachments` returned WordPress, Obsidian and Zotero tools and
nothing for geodatabase attachment tables. The searches `arcgis orphaned attachments`,
`geodatabase orphan attachment REL_GLOBALID`, `arcpy attachments orphan`,
`feature service orphaned attachments`, `globalid braces normalize arcgis`,
`orphan related records geodatabase` and `REL_GLOBALID` returned nothing. Code searches for
`REL_GLOBALID orphan` and `orphaned attachments REL_GLOBALID` returned nothing. That shows only
that the searches found nothing.

## Requirements

Python 3.9 or newer and nothing else. No `arcpy`, no third-party package, no network, no
database. Both tables are CSV files, which every table can be exported as. The self-test also
needs the `sqlite3` module from the standard library. The tool itself does not.

The self-test prints the same 263 assertions, line for line, on Windows (Python 3.13.2) and on
Ubuntu (Python 3.12.3). It also ran green with 263 assertions on Python 3.9.25 on Windows
(`py -V:Astral/CPython3.9.25 relorphan.py --self-test`), and on Ubuntu under Python 3.9, 3.10,
3.11, 3.12 and 3.13 (`uv run --python <version> python relorphan.py --self-test`). The count
does not differ between any two of these runs. `coverage run --branch relorphan.py
--self-test` reports 100 percent of lines and branches (901 statements, 188 branches) on
Windows with Python 3.13 and on Ubuntu with Python 3.12 (`uv run --with coverage`). The
self-test also parses the source with the 3.9 grammar (`ast.parse(..., feature_version=(3, 9))`).

```
git clone https://github.com/uhsear/relorphan.git
```

## Usage

Export the whole parent table and the child table to CSV. Save them as UTF-8.

```
python relorphan.py --self-test
python relorphan.py assets.csv photos.csv
python relorphan.py assets.csv photos.csv --parent-field GLOBALID --child-field REL_GLOBALID
python relorphan.py assets.csv photos.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE
python relorphan.py assets.csv photos.csv --sample 50
python relorphan.py assets.csv photos.csv --out findings.csv --apply
```

| Flag | Default | What it does |
|---|---|---|
| `PARENT` | none | The parent table as a CSV. Required unless `--self-test`. |
| `CHILD` | none | The attachment table, or any table related by a GlobalID, as a CSV. Required unless `--self-test`. |
| `--parent-field` | `GLOBALID` | The GlobalID column of the parent. |
| `--child-field` | `REL_GLOBALID` | The child column that holds the parent's GlobalID. |
| `--row-id-field` | off | A child column that names the row, such as `ATTACHMENTID`. Printed in the lists and written to `--out`. |
| `--size-field` | off | A child column of byte counts, such as `DATA_SIZE`. The bytes held by orphans are added up. |
| `--expect-child-rows` | off | The row count of the child table at its source. A different count is refused with exit 3. See [A child table cut short](#a-child-table-cut-short). |
| `--sample` | `10` | How many rows to list under each heading. `0` lists none. |
| `--out` | off | Write the child rows that are not `LINKED` to this CSV. Needs `--apply`. |
| `--apply` | off | Actually write. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Column names match without regard to case. A hosted layer exports `rel_globalid`, and the default
finds it. If two columns differ only by case, the run stops with exit 64 and does not guess.

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap` is refused
with exit 64 instead of being read as `--apply`. The self-test pins this for `--ap`, `--app` and
`--appl`, and checks that no file appears.

`--out` may name a path that does not exist, an empty file, or a findings file from an earlier run
of this tool. Any other existing file is refused with exit 64, and so is a path that is also an
input table, on a dry run too. Without that check `--apply` would replace a table with its own findings.

## What it checks

Every child row lands in exactly one class. The four counts add up to the number of child rows.

| Class | The child key is | Fails the gate |
|---|---|---|
| `LINKED` | a GUID that a parent row has | no |
| `ORPHAN` | a GUID that no parent row has | yes |
| `UNKEYED` | blank, or the all-zero GUID | yes |
| `MALFORMED` | text that is not a GUID in any accepted form | yes |

`MALFORMED` fails the gate on purpose. A column of ObjectIDs is the usual cause, and a scheduled
job must not read it as clean. When no child key reads as a GUID at all, the run prints a note
that names the likely cause.

**One id, many spellings.** These all read as the id `9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b`:

| Form | Example |
|---|---|
| hyphenated, lower case | `9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b` |
| hyphenated, upper case | `9F1C2A64-3B7D-4E58-8A01-5C6D7E8F9A0B` |
| braced | `{9F1C2A64-3B7D-4E58-8A01-5C6D7E8F9A0B}` |
| parenthesised | `(9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b)` |
| bare, no hyphens | `9f1c2a643b7d4e588a015c6d7e8f9a0b` |

Spaces around the cell are ignored. Anything else is `MALFORMED`: a missing digit, a character
after the 36th, an opening brace with no closing brace, a brace closed by a parenthesis, a
non-hex digit, hyphens in the wrong place, the .NET `X` form, and non-ASCII digits. The 37 character
case matters. SQL Server converts a string that is too long by cutting it to 36 characters
([uniqueidentifier](https://learn.microsoft.com/en-us/sql/t-sql/data-types/uniqueidentifier-transact-sql)),
so a `CONVERT` done there can turn a key that carries junk into a valid id. This tool calls that
key `MALFORMED`.

**The spelling line.** A child row is counted on the `spelling:` line when it is `LINKED` and its
cell is not spelled exactly like any parent cell. A verbatim join misses exactly those rows. The
self-test asserts that the number of rows a raw-text join gets wrong equals this count.

**The storage line.** With `--size-field`, the tool adds up the sizes of the `ORPHAN` and
`UNKEYED` rows. A size that is not a plain integer is not guessed. It is counted as unreadable,
and the line says how many. `MALFORMED` rows are not added, because they may belong to a parent
after all.

## What makes it refuse

A run is refused, with exit 3, before any child row is classified, when:

- the parent table has no rows, or
- any parent row has a blank, all-zero or malformed GlobalID.

A parent row that cannot be matched could be the one an orphan points at. The tool will not call
a child row an orphan while it cannot read every parent. A refusal prints the lines it could not
read.

```
$ python relorphan.py assets-empty.csv photos.csv
relorphan: assets-empty.csv 0 row(s), photos.csv 8 row(s)
REFUSED   the parent table has no rows, so every child row would look orphaned. An empty export and an emptied layer look the same, and this tool cannot tell which one it was given.

VERDICT: REFUSED
$ echo $?
3
$ python relorphan.py assets-hole.csv photos.csv
relorphan: assets-hole.csv 3 row(s), photos.csv 8 row(s)
REFUSED   1 parent row(s) have no readable GlobalID. A parent that cannot be matched could be the one an orphan points at, so nothing was compared.
  parent line 3: ''

VERDICT: REFUSED
```

A refused run writes nothing, even with `--apply`.

A run that read no child rows exits 4, not 0:

```
$ python relorphan.py assets.csv photos-empty.csv
relorphan: assets.csv 4 row(s), photos-empty.csv 0 row(s)
rows classified: 0 of 0
  LINKED     0
  ORPHAN     0
  UNKEYED    0
  MALFORMED  0
parents: 4 row(s), every GlobalID readable

VERDICT: NOTHING COMPARED. The child table has no rows, so no key was checked. This is not a clean run: a failed export looks the same.
```

A child column of ObjectIDs is reported, not passed:

```
$ python relorphan.py assets.csv photos-objectid.csv
relorphan: assets.csv 4 row(s), photos-objectid.csv 2 row(s)
rows classified: 2 of 2
  LINKED     0
  ORPHAN     0
  UNKEYED    0
  MALFORMED  2
parents: 4 row(s), every GlobalID readable
NOTE no child key was read as a GUID, so nothing was matched against the parent. Check that --child-field names a GUID column and not an ObjectID column.

rows whose key is not a GUID, not checked:
  line 2: '1' is not a GUID in the bare, hyphenated, braced or parenthesised form
  line 3: '2' is not a GUID in the bare, hyphenated, braced or parenthesised form

VERDICT: 2 child row(s) are not attached to a parent.
```

A table with a row whose field count differs from its header is refused with exit 2, before any
comparison. The usual cause is a quote that opens in one cell and closes on a later line. The
`csv` reader then joins the rows in between into one cell, and those child rows would not exist
for the rest of the run. This `photos-swallow.csv` holds three photo rows, two of which point at
a parent that does not exist:

```
$ cat photos-swallow.csv
ATTACHMENTID,REL_GLOBALID,ATT_NAME
1,9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b,"abc
2,c0ffee00-1234-4abc-9def-0123456789ab,c200.jpg
3,c0ffee00-1234-4abc-9def-0123456789ab,c201.jpg",x
$ python relorphan.py assets-one.csv photos-swallow.csv --row-id-field ATTACHMENTID
error: photos-swallow.csv: the record that starts on line 2 has 4 field(s) but the header has 3. A stray quote may have joined rows, or the file is cut short. Fix the file, then run again.
$ echo $?
2
```

`assets-one.csv` holds only the GlobalID `9f1c2a64-...`. A short row is refused the same way.

A quote can also join rows so that the record has exactly the header's field count. The field
count then shows nothing. The tool looks inside every cell that holds a line break. If a line
after the first splits into as many fields as the header has, the cell is taken as joined rows
and the run is refused with exit 2. A line break in a cell that holds prose passes. This
`photos-exact-swallow.csv` hides two orphans in one cell:

```
$ cat photos-exact-swallow.csv
ATTACHMENTID,REL_GLOBALID,ATT_NAME
1,9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b,"abc
2,c0ffee00-1234-4abc-9def-0123456789ab,c200.jpg
3,c0ffee00-1234-4abc-9def-0123456789ab,c201.jpg"
$ python relorphan.py assets-one.csv photos-exact-swallow.csv --row-id-field ATTACHMENTID
error: photos-exact-swallow.csv: the record that starts on line 2 holds a cell with a line break, and the text '<47 characters, not a GUID, not shown>' inside it has the 3 fields of a row. A stray quote may have joined rows. Fix the file, then run again.
$ echo $?
2
```

## A child table cut short

A file that is cut in the middle of a line is caught, because the last record has too few fields
and the run exits 2. A file that is cut exactly at a line break is a smaller, valid table. The
tool cannot see the rows that are missing, and they may be the orphans. `photos-cut-boundary.csv`
is the first three rows of `photos.csv`:

```
$ python relorphan.py assets.csv photos-cut-boundary.csv --row-id-field ATTACHMENTID
relorphan: assets.csv 4 row(s), photos-cut-boundary.csv 3 row(s)
rows classified: 3 of 3
  LINKED     3
  ORPHAN     0
  UNKEYED    0
  MALFORMED  0
parents: 4 row(s), every GlobalID readable
spelling: 2 child row(s) match a parent only after braces, case or hyphens are normalised. A verbatim join calls them orphans.

VERDICT: clean. All 3 child row(s) have a parent. The child file was read to its last line. A file cut at a line break looks like a short table, so check the row count against the source or pass --expect-child-rows.
$ echo $?
0
```

A clean run now says so. Read the row count of the child table at its source, in the table
properties or a `SELECT COUNT(*)`, and pass it as `--expect-child-rows`. A different count is
refused with exit 3 and nothing is compared:

```
$ python relorphan.py assets.csv photos-cut-boundary.csv --row-id-field ATTACHMENTID --expect-child-rows 8
relorphan: assets.csv 4 row(s), photos-cut-boundary.csv 3 row(s)
REFUSED   the child table has 3 row(s) and --expect-child-rows says 8. A file cut short at a line break reads as a smaller, valid table, so nothing was compared.

VERDICT: REFUSED
$ echo $?
3
```

When the count matches, the caveat is left out. The tool counts the data rows it parsed. A blank
line in a file with more than one column is not a row, so a source count that includes such
lines will not match.

## The findings file

`--out findings.csv --apply` writes one row for every child row that is not `LINKED`, in file
order. Use `row_id` to select the rows in whatever tool you trust to delete them. Read
[the formula guard](#the-formula-guard) first: a `row_id` that starts with a formula character
carries one added apostrophe.

```
$ python relorphan.py assets.csv photos.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE --out findings.csv
...
Check only. findings.csv was not written. Re-run with --apply.
$ ls findings.csv
ls: cannot access 'findings.csv': No such file or directory
$ python relorphan.py assets.csv photos.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE --out findings.csv --apply
...
wrote findings.csv
$ cat findings.csv
csv_line,row_id,raw_key,class,size,reason
5,4,{C0FFEE00-1234-4ABC-9DEF-0123456789AB},ORPHAN,3500000,no parent row has the GlobalID c0ffee00-1234-4abc-9def-0123456789ab
6,5,{C0FFEE00-1234-4ABC-9DEF-0123456789AB},ORPHAN,3300000,no parent row has the GlobalID c0ffee00-1234-4abc-9def-0123456789ab
7,6,,UNKEYED,900000,the key is blank
8,7,104,MALFORMED,1500000,"'104' is not a GUID in the bare, hyphenated, braced or parenthesised form"
```

`csv_line` is the line the row starts on in the child file. A quoted cell that holds a line
break, or a blank line, does not move it. The self-test pins both.

### A key column that is not a GUID

`--child-field` names the column that is read as a key. If it names the wrong column, the cells
are not GUIDs, and the tool must not copy them to the screen or to the findings file. A cell of
12 characters or fewer, or one made only of GUID characters (40 or fewer), is shown whole. Any
other cell is replaced by its length. `url.csv` has a URL with a token in the `ATT_URL` column:

```
$ python relorphan.py assets.csv url.csv --child-field ATT_URL --row-id-field ATTACHMENTID --out urlout.csv --apply
...
rows whose key is not a GUID, not checked:
  line 2, id 1: 'x' is not a GUID in the bare, hyphenated, braced or parenthesised form
  line 3, id 2: '<44 characters, not a GUID, not shown>' is not a GUID in the bare, hyphenated, braced or parenthesised form

VERDICT: 2 child row(s) are not attached to a parent.

wrote urlout.csv
$ cat urlout.csv
csv_line,row_id,raw_key,class,size,reason
2,1,x,MALFORMED,,"'x' is not a GUID in the bare, hyphenated, braced or parenthesised form"
3,2,"<44 characters, not a GUID, not shown>",MALFORMED,,"'<44 characters, not a GUID, not shown>' is not a GUID in the bare, hyphenated, braced or parenthesised form"
```

The same rule applies to a parent cell in the refusal list. [Limits](#limits) says what it does
not cover.

### The formula guard

A spreadsheet may run a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return as a
formula. OWASP names these characters in its
[CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection) page. The ids and keys in
`--out` come from the input tables, so the tool does not trust them. Every text cell it writes
that starts with one of those six characters gets one apostrophe in front. This is the same rule
as `cell()` in [xwddiff](https://github.com/uhsear/xwddiff). The `csv_line` and `size` columns are numbers and are never changed. The
`class` column holds a fixed word.

This run uses a child table whose ids and keys are formulas. No culvert in the demo
`assets.csv` has the GlobalID `C0FFEE00-...`, so that row is a real orphan:

```
$ cat photos-formula.csv
ATTACHMENTID,REL_GLOBALID,ATT_NAME,DATA_SIZE
1,9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b,c101_a.jpg,2400000
2,=1+1,c102_a.jpg,1800000
"=HYPERLINK(""http://x.invalid"",""y"")",{C0FFEE00-1234-4ABC-9DEF-0123456789AB},c999_a.jpg,3500000
-4,@SUM(1),c104.jpg,1500000
$ python relorphan.py assets.csv photos-formula.csv --row-id-field ATTACHMENTID --size-field DATA_SIZE --out findings.csv --apply
...
wrote findings.csv
$ cat findings.csv
csv_line,row_id,raw_key,class,size,reason
3,2,'=1+1,MALFORMED,1800000,"'=1+1' is not a GUID in the bare, hyphenated, braced or parenthesised form"
4,"'=HYPERLINK(""http://x.invalid"",""y"")",{C0FFEE00-1234-4ABC-9DEF-0123456789AB},ORPHAN,3500000,no parent row has the GlobalID c0ffee00-1234-4abc-9def-0123456789ab
5,'-4,'@SUM(1),MALFORMED,1500000,"'@SUM(1)' is not a GUID in the bare, hyphenated, braced or parenthesised form"
```

The `reason` column of a `MALFORMED` row already starts with the apostrophe of the quoted key, so
it is not guarded a second time. The report on stdout is not changed, because a terminal does
not run formulas.

To read the file back, strip exactly one leading apostrophe from `row_id` and `raw_key`, and only
when a formula character follows it. The self-test does this for each of the six characters and
checks that the original text returns. This tool does not read its findings file as data. It
reads only the first line, to decide whether the file may be replaced, and the header has no
guarded cell. [Limits](#limits) lists what the guard does not cover.

A prefix of the write flag is refused:

```
$ python relorphan.py assets.csv photos.csv --row-id-field ATTACHMENTID --out other.csv --ap
usage: relorphan.py [-h] [--parent-field PARENT_FIELD]
...
relorphan.py: error: unrecognized arguments: --ap
$ echo $?
64
$ ls other.csv
ls: cannot access 'other.csv': No such file or directory
```

And an output that names an input table:

```
$ python relorphan.py assets.csv photos.csv --out assets.csv --apply
error: --out assets.csv is also an input table. Name a new file.
```

## The demo tables

`assets.csv` is the parent table, as a file geodatabase writes GlobalIDs:

```
OBJECTID,GlobalID,CULVERT_NO
1,{9F1C2A64-3B7D-4E58-8A01-5C6D7E8F9A0B},C-101
2,{0A1B2C3D-4E5F-4061-8273-94A5B6C7D8E9},C-102
3,{11112222-3333-4444-5555-666677778888},C-103
4,{AAAABBBB-CCCC-4DDD-8EEE-FFFF00001111},C-104
```

`photos.csv` is the child table. Rows 1 and 8 are hyphenated and lower case. Row 3 is bare, with no hyphens. Rows 4 and 5 point at a culvert that is not in `assets.csv`. Row 6 has no key. Row 7 holds
an ObjectID where a GlobalID belongs.

```
ATTACHMENTID,REL_GLOBALID,ATT_NAME,DATA_SIZE
1,9f1c2a64-3b7d-4e58-8a01-5c6d7e8f9a0b,c101_a.jpg,2400000
2,{0A1B2C3D-4E5F-4061-8273-94A5B6C7D8E9},c102_a.jpg,1800000
3,11112222333344445555666677778888,c103_a.jpg,2100000
4,{C0FFEE00-1234-4ABC-9DEF-0123456789AB},c999_a.jpg,3500000
5,{C0FFEE00-1234-4ABC-9DEF-0123456789AB},c999_b.jpg,3300000
6,,c000.jpg,900000
7,104,c104.jpg,1500000
8,aaaabbbb-cccc-4ddd-8eee-ffff00001111,c104_a.jpg,2000000
```

`assets-empty.csv` is `assets.csv` with only the header. `assets-hole.csv` is `assets.csv` with
the GlobalID of row 2 blank and row 4 removed. `photos-empty.csv` is `photos.csv` with only the
header. `photos-objectid.csv` is the header and two rows, `1,1,c101_a.jpg,2400000` and
`2,2,c102_a.jpg,1800000`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | At least one child row was read, and every child row has a parent. Without `--expect-child-rows` the tool cannot tell a short table from a cut one, and the verdict says so. |
| 1 | At least one child row is an orphan, has no key, or has a key that is not a GUID. |
| 2 | A file could not be read, or `--out` could not be written. A file with a NUL byte, such as a UTF-16 file, is unreadable. So is a file with a row whose field count differs from the header. |
| 3 | Refused. The parent table is empty or has a row with no readable GlobalID, or the child table does not have the row count given with `--expect-child-rows`. |
| 4 | Nothing was compared. The child table has no rows. |
| 64 | Usage error, including a column name that is not in the CSV, an unknown or abbreviated flag, an output path that is an input, and an output path that is an existing file other than an empty file or an earlier findings file. |
| 70 | An unexpected crash. This is a fault in the tool and not a finding. The traceback is on stderr. |

Exit 3 is not exit 1. A job that files a ticket for "photos have no parent" must not file one
for "the parent export is broken". Exit 4 is not exit 0 for the same reason: "I checked and
found nothing" and "I could not check" are different.

## What I checked against the documentation

I read these pages on 2026-10-22, except the OWASP, Python `csv` and Esri Enable attachments
rows, which I read on 2026-11-11. I did not read the older pages again. Where a page refused the fetch, the table
says so.

| Claim in this README | Source | How it was checked |
|---|---|---|
| An attachment table is named with the dataset name plus `__ATTACH`. Its relationship class ends in `__ATTACHREL`. The page says "Global IDs is checked by default, and it is recommended that you leave it checked." It describes the table and class names in words, as the dataset name, a double underscore and the suffix. | [Enable attachments](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/enable-attachments.html) | Fetched and read again on 2026-11-11. The 2026-10-22 read did not find the default sentence. |
| Global ID and GUID values are "registry-style strings consisting of 36 characters enclosed in curly brackets". | [Inserting a value into a global ID column in SQL Server](https://desktop.arcgis.com/en/arcmap/latest/manage-data/using-sql-with-gdbs/inserting-a-value-into-a-global-id-column-in-sql-server-using-sql.htm) (ArcMap help) | Fetched and read. |
| GlobalIDs from an enterprise geodatabase carry braces and capital letters. GlobalIDs from a hosted layer carry neither. | [Global IDs - The More You Know](https://sspinnovations.com/blog/global-ids-the-more-you-know/) | Fetched and read. This is a third-party post. |
| Esri's own article makes the same point for Portal for ArcGIS and ArcGIS Online. | [Esri support article 000026830](https://support.esri.com/en-us/knowledge-base/how-to-remove-curly-braces-from-the-globalids-in-a-text-000026830) | The page returned 403 to my fetch. I read only a search result summary of it. Treat it as unverified. |
| An attachment table gets a `REL_GLOBALID` field when its parent has a GlobalID field. | [Esri support article 000015632](https://support.esri.com/en/technical-article/000015632) | The page returned 403 to my fetch. I read only a search result summary. Treat it as unverified. |
| The .NET `Guid` formats are N (32 digits), D (hyphens), B (braces), P (parentheses) and X. | [Guid.ToString](https://learn.microsoft.com/en-us/dotnet/api/system.guid.tostring) | Fetched and read. The page does not say the digits are lower case. That comes from observed output. |
| SQL Server `uniqueidentifier` is a 16-byte GUID. It has comparison operators. A string longer than 36 characters is cut to 36 on conversion. | [uniqueidentifier](https://learn.microsoft.com/en-us/sql/t-sql/data-types/uniqueidentifier-transact-sql) | Fetched and read. Not run: no SQL Server was available. |
| A cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return may be read as a formula. OWASP also lists a line feed and full-width forms, and says Excel may remove quotes or escape characters when a file is saved and opened again. | [OWASP, CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection) (redirects to community.owasp.org) | Fetched and read on 2026-11-11. Not run in a spreadsheet: none was used. |
| The `csv` writer quotes a field that holds `'\r'` or `'\n'` under `QUOTE_MINIMAL`. | [csv](https://docs.python.org/3/library/csv.html) | Fetched and read on 2026-11-11. The page has no version note, so Python 3.9 and 3.10 were run to find out where it differs. |
| FME 2019 added a "Strip braces" reader option for geodatabases. | [Safe Software thread](https://community.safe.com/architecture-14/uuid-braces-missing-10436) | Fetched and read. |

I did not verify these, and the tool does not depend on them: what the attachment relationship
class does when a parent is deleted by each route, whether an append keeps GlobalIDs, that the
file sits in a blob column named `DATA` with its length in `DATA_SIZE` (I saw this only in
published service metadata returned by a search), and how SQL Server compares a `uniqueidentifier`
with a braced string. The `REL_GLOBALID` default rests on Esri article 000015632, which I could
not fetch, so it is unverified as well.

## What was exercised

Every claim above was run, not only described. The self-test asserts the behaviour, and the
demo transcripts in this README are copies of real runs.

| Claim | Where it ran |
|---|---|
| Braced, bare, upper case, lower case, parenthesised and no-hyphen spellings are one id | Self-test, the `normalize_guid` assertions; the demo run |
| A join on the raw text calls 7 of 8 demo rows orphans | Self-test, the SQLite assertion |
| The spelling line counts exactly the rows a raw join gets wrong | Self-test, the assertion that subtracts the findings from the SQLite count |
| An empty parent table is refused, exit 3 | Self-test; the `assets-empty.csv` run above |
| A parent row with no readable GlobalID is refused, exit 3 | Self-test; the `assets-hole.csv` run above |
| An empty child table exits 4 and, with `--apply`, writes no findings file | Self-test; the `photos-empty.csv` run above |
| A column of ObjectIDs exits 1 with a note | Self-test; the `photos-objectid.csv` run above |
| The storage line, and a size that cannot be read | Self-test; the demo run |
| Only `--apply` writes, and a refused run writes nothing | Self-test; the `--out` runs above |
| `--ap`, `--app` and `--appl` are refused with exit 64 | Self-test, in process for all three, and through a child process for `--ap` |
| `--out` may not be an input table | Self-test; the last run above |
| A BOM, CRLF, blank lines, and a quoted line break read correctly | Self-test |
| A quote that joins rows so the field count matches the header is refused, exit 2 | Self-test; the `photos-exact-swallow.csv` run above |
| Lower case column names from a hosted export match the defaults | Self-test |
| A file that cannot be read exits 2, and so does a cell over the csv limit and a failed write | Self-test |
| A crash exits 70 | Self-test |
| A character the console cannot show prints as `?` | Self-test, in a child process with `PYTHONIOENCODING=ascii` |
| The source is ASCII, has no f-string, parses under the 3.9 grammar, imports no network module, and deletes nothing | Self-test, an `ast` walk of its own source |
| A text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is guarded in `row_id`, `raw_key` and `reason` | Self-test, each character in each column, and the `photos-formula.csv` run above |
| The `csv_line` and `size` columns stay numbers, and `class` is unchanged | Self-test, including a negative number |
| One stripped apostrophe returns the original `row_id` and `raw_key` | Self-test, a round trip through `read_csv` for each character |
| A findings file with guarded cells is still replaceable by a later run | Self-test, the second `--apply` over the same path |
| A clean run says that a table cut at a line break cannot be told from a short one | Self-test; the `photos-cut-boundary.csv` run above |
| `--expect-child-rows` refuses a different count with exit 3 and writes nothing | Self-test; the `photos-cut-boundary.csv` run above |
| A key column that holds a URL with a token is not copied to stdout or `--out` | Self-test, in the findings file, the MALFORMED list and the refusal list; run by hand on `url.csv` |
| A cell over 12 characters that is not GUID shaped is reported by its length | Self-test, `shown_cell` and the CLI runs |
| A cell with a bare CR does not split a record, on Python 3.9 to 3.13 | Self-test on each version; the plain LF writer aborts the self-test on 3.9 and 3.10 |
| A findings file fed back in as a table reads a tab-led key as `MALFORMED` | Run by hand on 2026-11-11, not in the self-test |
| No writer call can skip the guard | Self-test, an `ast` walk of its own source |
| 1,000,000 child rows and 200,000 parent rows | Separate run, see Limits |

The network and credential rules do not apply. The tool opens no socket and reads no credential,
so there was no stub server to run it against. The `ast` assertion above fails the self-test if a
network module is ever imported.

## Limits

- CSV only. No geodatabase, no feature service, no `arcpy`. Export both tables with any tool you
  trust, and keep the GlobalID columns as text.
- The parent export must be the whole table. A definition query, a selection or a clipped
  export leaves out parents, and their children then look orphaned. The tool refuses an empty
  parent table and an unreadable parent row. It cannot see a parent table that is merely
  incomplete. The verdict says to check this before deleting.
- One parent table per run. A related table that points at features in several layers reports
  every child of the other layers as an orphan. Run the tool once per layer and read only the
  rows that no layer claims.
- Only a GlobalID relationship is read. A relationship on an ObjectID or on a text key is not.
- A parent GlobalID that appears on two parent rows is not reported. It does not change any
  child verdict.
- Parents that have no children are not listed. This is not a check for missing photos.
- The tool adds up the integers in the size column as bytes. If the column holds another unit,
  the label is wrong. A size such as `1,024` is counted as unreadable, not as 1024.
- Whole files are read into memory. One run of 1,000,000 child rows and 200,000 parent rows took
  7.0 seconds and 632 MB of memory on the Ubuntu host, and 9.7 seconds on the Windows
  workstation. It found the 20,000 orphans planted in the generated files, and no others. The
  Windows memory use was not measured. These figures come from one workstation and one server.
- Only UTF-8 CSV is supported. Other encodings are decoded lossily without a warning, except that a
  file with a NUL byte, UTF-16 included, exits 2 with "line contains NUL". In Excel, save as
  "CSV UTF-8 (Comma delimited)".
- A cell over 131072 characters exits 2, because that is the csv module's limit.
- A text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is written to
  `--out` with one apostrophe in front. OWASP's page now also lists a line feed and the
  full-width forms of `=`, `+`, `-` and `@`. This tool guards the six characters that the
  portfolio guards and does not guard those. A cell that starts with a space is not guarded
  either, and a cell that starts with an apostrophe is left alone. The same page says
  Excel may remove the quotes or escape characters when a file is saved and opened again,
  and that no one rule fits every spreadsheet. I did not open the file in Excel or any
  other spreadsheet, so the guard is checked as text only.
- The apostrophe is not reversible in one case. A value that began with `'` followed by a
  formula character, such as `'=1`, is not guarded, and a reader that strips one apostrophe
  would turn it into `=1`. Strip only `row_id` and `raw_key`. The `reason` column of a
  `MALFORMED` row starts with an apostrophe of its own.
- A `row_id` that is a negative number, such as `-4`, is a text cell here and is written as
  `'-4`. Strip it before you use it as a key. Feeding the findings file back in as an input
  table is not supported: a key that began with a tab was a valid GlobalID, and with the
  apostrophe in front it reads as `MALFORMED`.
- Output files are written in place, not through a temporary file. A failed write can leave a
  partial file, and the exit code is 2. Read the printed `VERDICT`, which is above the error.
- There is no `--fix` and no delete. Deciding that a photo is not wanted is a decision somebody
  signs for.
- `--self-test` ignores every other valid flag. It writes only to a temporary directory, which it
  removes at the end, even when an assertion raises.
- Coverage was measured on Windows with Python 3.13 and on Ubuntu with Python 3.12, and reports
  no missed line and no missed branch on both. It was not measured under 3.9 to 3.11. The
  `csv.Error` in the except clause of the write step cannot be reached offline, and `OSError`
  alone would pass the self-test. It stays as a guard, with a `ponytail:` comment.
- A blank line is a row only in a one-column file, where it is how an export writes a NULL key. In
  a file with more columns it is skipped. A row of only commas, which a spreadsheet may pad onto
  a sheet, has an empty key. In the child file it counts as one UNKEYED row. In the parent file it
  refuses the whole run with exit 3. Delete trailing empty rows from the exports. A one-column
  file that ends in an extra blank line counts that line as one UNKEYED row.
- A tab-separated or semicolon-separated file is read as one column and exits 64. It is never
  clean. Export as comma-delimited CSV.
- `--out` is not written through a temporary file. A dangling symbolic link named by `--out` is
  followed, and its target is created. An existing file whose first line equals the findings
  header counts as an earlier findings file and is replaced, so a notes file that holds only that
  line would be overwritten. A hard link to an input table is refused only because that table's
  header differs from the findings header. An existing empty special file such as `/dev/null` or
  `NUL` is accepted as an empty file, and the findings then go nowhere.
- The findings file uses LF line endings on every platform. The self-test pins this. The tool
  writes each record with a CRLF terminator and replaces it with LF, because the `csv` writer
  on Python 3.9 and 3.10 does not quote a cell that holds a bare CR unless the terminator
  has one, and an unquoted CR splits the record. Python 3.11 and later quote it. The current
  [csv documentation](https://docs.python.org/3/library/csv.html) says `QUOTE_MINIMAL` quotes
  `'\r'`. It gives no version note, so the 3.9 and 3.10 behaviour comes from running the
  self-test with the plain LF writer on each version. On 3.9.25 and 3.10 that run prints no
  `FAIL` line and stops at the bare CR read-back with an uncaught `csv.Error`, so it never prints
  the footer. On 3.11 and later it passes every assertion. A direct check on Ubuntu, with a
  writer that uses an LF terminator, left the bare CR unquoted on 3.9.25 and 3.10.21 and quoted
  it on 3.11.16.
- With an empty child table, `--out --apply` writes nothing and exits 4, as a refused run does,
  because a header-only file reads as zero findings. The self-test pins this.
- A key cell that is not a GUID is printed whole only when it has 12 characters or fewer (such as
  `N/A` or `None`), or when it is made only of hex digits, hyphens, braces and parentheses and has
  40 characters or fewer (a GUID with a typo). Any other cell, such as a URL with a token in it,
  is replaced by its length in the MALFORMED list, the refusal list, the error for a joined
  record, and the `raw_key` and `reason` columns of `--out`. The self-test pins this for a
  `--child-field` that names a URL column and for a parent column that holds a URL. A token of
  12 characters or fewer, or a token made only of hex digits, would still be printed. The
  `--row-id-field` column is not masked, because a row id is meant to be shown: name only an
  ObjectID or attachment id column there.
- A key cell that is a valid GUID with spaces or a tab around it, such as a trailing space from a
  text column, is classified by its real GUID, so it is `LINKED` or `ORPHAN` as it should be.
  But the orphan list and the `raw_key` column show it as "not a GUID, not shown", because only
  GUID-shaped text is shown and whitespace is not in that set. Use `row_id` and the `reason`
  column to find the row. Such a cell is masked before it reaches the formula guard, so a tab-led
  GUID is masked and not guarded. The guard still applies to every other tab-led or CR-led text.
- The error for a column that is not found lists the header row as it is in the file, so a file
  with no header line prints its first data row to stderr. Do not point the tool at a file that
  holds a URL with a token or another secret.
- A row id that holds terminal escape sequences or control characters is printed unescaped. The
  key itself is shown with `%a`. Read the output of an untrusted CSV in a pipe or a file, not in
  a live terminal.
- A closed stdout pipe, such as `| head -1` on long output, raises `BrokenPipeError` (on Windows it
  is `OSError` with `[Errno 22]`), and the tool
  exits 70 with a traceback. Treat 70 as "the tool failed", not "the data is bad". A shell with
  `pipefail` sees 70 and not the real verdict.
- A GUID with a non-ASCII hyphen, such as an en dash pasted from a document, or one inside a
  spreadsheet text marker such as a leading apostrophe, is MALFORMED and never matched. The run
  exits 1 and lists the row for review.
- The spelling line says "after braces, case or hyphens are normalised" even when the only
  difference is spaces around the cell, so the reason it gives is wrong in that rare case.
- A GUID written in the mixed-endian byte order of a binary layout does not match its text form,
  so the row reads as an orphan. The run exits 1, and the tool does not say that byte order is a
  likely cause. A hosted layer and a `uniqueidentifier` column export the text form.
- A cell that starts with a no-break space is not guarded by the formula rule, like the leading
  space above.
- The strip-on-read round trip of the formula guard is pinned only through a helper in the
  self-test that uses `read_csv`. The tool never reads its findings file as data. It reads the
  first line only, to decide whether `--out` may be replaced.
- The large-run timing figures are not reproducible from this repository.
- A child table cut exactly at a line break reads as a smaller valid table. Without
  `--expect-child-rows` the tool cannot tell, and a clean verdict carries a sentence that says so.
  See [A child table cut short](#a-child-table-cut-short). A blank line in a file with more than
  one column is not a row, so a source count that includes blank lines will not match.
- `--expect-child-rows` is only as good as the count you give it. A count read from a filtered
  view, or from the same cut file, agrees with a short table.
- Windows 8.3 short names were not tested, because short name generation is off on the test
  volume. The `--out` guard rejected case changes, a `./` prefix, forward slashes, a trailing dot,
  a trailing space and the `::$DATA` stream form against an input table. Windows path-alias
  behaviour for `--out`, and `NUL` accepted as an empty file, were observed by hand. The
  self-test does not cover them and no Microsoft documentation is cited for them.
- Timing is one run on one workstation and one server and varies. The 9.7 second Windows figure
  measured 11.3 s, 11.8 s and 12.0 s on later runs of similar generated data, with the same
  20,000 planted orphans found. Treat the figures as approximate. No script in this repository
  generates that data.
- The reload story in the opening is a composite. What the relationship class does on each delete
  route was not verified.
- The Esri page confirms the `__ATTACH` and `__ATTACHREL` names and says Global IDs is checked by
  default when attachments are enabled. The `REL_GLOBALID` default rests on an Esri support article
  that returned 403 to my fetch. The lower case claim for .NET `Guid.ToString` comes from observed output, not from the
  cited page.
- The GitHub searches were run on 2026-10-22. They show only that those searches found nothing.
- A joined record is caught when its field count differs from the header, or when a cell with a
  line break holds a line that splits into as many fields as the header has. The second check
  can refuse a real multi-line cell, such as an address with commas, when a line of it has that
  many fields. Remove the line breaks from the export and run again. It is not applied to a
  one-column file, where the only cell is the key and a key with a line break is reported as
  `MALFORMED`. Swallowed text whose lines do not look like rows is not caught.
- The tool never reads its findings file back as data. It reads only the header line, to decide
  whether `--out` may be replaced. The "strip one apostrophe on read" round trip is pinned only
  through a helper in the self-test that uses `read_csv`.
- The 1,000,000 row timing, the Windows 8.3 short name claim and the `::$DATA` claim come from
  runs outside the self-test, and no script in this repository generates that data. A later run
  of 1,000,000 child rows found the same 20,000 planted orphans in 11.5 seconds.
- A parent file with one blank or all-zero GlobalID refuses the whole run with exit 3, even when
  the rest of the file is good. This is deliberate. That row could be the parent that an orphan
  points at.
- Earlier versions of the self-test could leave `relorphan-selftest-*` folders in the temporary
  directory after a crash. Delete them by hand. The current version leaves none.
- Not checked: Windows symbolic link behaviour for `--out`, how a spreadsheet treats the guarded
  cells, and memory use on Windows.
- The `reason` column is guarded in the writer, but no real run produces a reason that starts
  with a formula character, because reasons start with a letter or a quote. The self-test checks
  that column with hand-built results, so the guard on it is a safeguard and not a case a real
  input reaches.
- A run that exits 3, 4 or 64 leaves any earlier file at `--out` untouched. A job that reads only
  the file can take a stale file as current. Check the exit code first.
- A byte order mark (U+FEFF) or another invisible character at the start of a `row_id` or
  `raw_key` cell is not guarded. A spreadsheet does not read those as the start of a formula.
- A file with no bytes at all, as either table, exits 64 with "no column named", not 3 or 4. It is
  never clean. A job should treat any non-zero code other than 1 as the tool failing.
- A quoted cell whose later line splits into as many comma fields as the header is refused as a
  possible joined row, even when it is only prose.
- `--self-test` exits 1 when an assertion fails, the same code as "findings exist". Run it as a
  separate step.
- The findings file is UTF-8 with no byte order mark, so Excel may show non-ASCII row ids as
  garbled text. Open it through Data, From Text/CSV, and choose UTF-8.
- `relorphan.py a.csv b.csv --self-test` runs only the self-test, exits 0 and does not compare the
  tables. A job that passes `--self-test` by mistake reads that exit 0 as a clean result.

## Contributing

Open an issue or pull request on GitHub.

## Author

Built by [Asir Khan](https://www.linkedin.com/in/asir-khan-310317264/).

## License

MIT.

## Related

Other single-file tools in this portfolio that pair with this one:

- [idreuse](https://github.com/uhsear/idreuse) - the same kind of failure for a join on a shared
  id: the join succeeds, and the evidence that it is wrong sits somewhere the join never looks.
- [safe-republish](https://github.com/uhsear/safe-republish) - refuse to truncate a feature class
  when the staged replacement fails a plausibility check. A truncate and reload is one way a
  layer loses the parents its photos point at.
- [xwddiff](https://github.com/uhsear/xwddiff) - classify the diff between two XML workspace
  documents. Its `cell()` function is the formula guard that `--out` uses here.
- [fcload](https://github.com/uhsear/fcload) - load a dataset into a geodatabase. Run this tool
  on the attachment table after a reload.
- [nalmatch](https://github.com/uhsear/nalmatch) - reconcile two tables on an identifier and
  refuse an ID rule that would merge two records into one key.
