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
PASS  --ap is refused with exit 64 and writes nothing, so a prefix of --apply never applies  <-- pinned defect
...
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
149 assertions, 0 failed
```

The full run prints all 149 assertions. Each `...` line above is where this block is cut.

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

A search of GitHub on 2026-10-22 found no repository named `relorphan`. The searches
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

The self-test prints the same 149 assertions, line for line, on Windows (Python 3.13.2) and on
Ubuntu (Python 3.12.3). `coverage run --branch relorphan.py --self-test` reports 100 percent of
lines and branches on Windows. Coverage was not measured on Linux, which has no `coverage`
module. Python 3.9 was not available. The self-test parses the source with the 3.9
grammar (`ast.parse(..., feature_version=(3, 9))`), which proves the syntax and nothing else.

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
| `--sample` | `10` | How many rows to list under each heading. `0` lists none. |
| `--out` | off | Write the child rows that are not `LINKED` to this CSV. Needs `--apply`. |
| `--apply` | off | Actually write. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Column names match without regard to case. A hosted layer exports `rel_globalid`, and the default
finds it. If two columns differ only by case, the run stops with exit 64 and does not guess.

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap` is refused
with exit 64 instead of being read as `--apply`. The self-test pins this for `--ap`, `--app` and
`--appl`, and checks that no file appears.

`--out` must name a new file. A path that is also an input table is refused with exit 64, on a
dry run too. Without that check `--apply` would replace a table with its own findings.

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

## The findings file

`--out findings.csv --apply` writes one row for every child row that is not `LINKED`, in file
order. Use `row_id` to select the rows in whatever tool you trust to delete them.

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

`photos.csv` is the child table. Row 1 is bare and lower case. Row 3 has no hyphens. Row 8 is
bare. Rows 4 and 5 point at a culvert that is not in `assets.csv`. Row 6 has no key. Row 7 holds
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
| 0 | At least one child row was read, and every child row has a parent. |
| 1 | At least one child row is an orphan, has no key, or has a key that is not a GUID. |
| 2 | A file could not be read, or `--out` could not be written. |
| 3 | Refused. The parent table is empty or has a row with no readable GlobalID. |
| 4 | Nothing was compared. The child table has no rows. |
| 64 | Usage error, including a column name that is not in the CSV, an unknown or abbreviated flag, and an output path that is an input. |
| 70 | An unexpected crash. This is a fault in the tool and not a finding. The traceback is on stderr. |

Exit 3 is not exit 1. A job that files a ticket for "photos have no parent" must not file one
for "the parent export is broken". Exit 4 is not exit 0 for the same reason: "I checked and
found nothing" and "I could not check" are different.

## What I checked against the documentation

I read these pages on 2026-10-22. Where a page refused the fetch, the table says so.

| Claim in this README | Source | How it was checked |
|---|---|---|
| An attachment table is named with the dataset name plus `__ATTACH`. Its relationship class ends in `__ATTACHREL`. Global IDs are checked by default. | [Enable attachments](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/enable-attachments.html) | Fetched and read. |
| Global ID and GUID values are "registry-style strings consisting of 36 characters enclosed in curly brackets". | [Inserting a value into a global ID column in SQL Server](https://desktop.arcgis.com/en/arcmap/latest/manage-data/using-sql-with-gdbs/inserting-a-value-into-a-global-id-column-in-sql-server-using-sql.htm) (ArcMap help) | Fetched and read. |
| GlobalIDs from an enterprise geodatabase carry braces and capital letters. GlobalIDs from a hosted layer carry neither. | [Global IDs - The More You Know](https://sspinnovations.com/blog/global-ids-the-more-you-know/) | Fetched and read. This is a third-party post. |
| Esri's own article makes the same point for Portal for ArcGIS and ArcGIS Online. | [Esri support article 000026830](https://support.esri.com/en-us/knowledge-base/how-to-remove-curly-braces-from-the-globalids-in-a-text-000026830) | The page returned 403 to my fetch. I read only a search result summary of it. Treat it as unverified. |
| An attachment table gets a `REL_GLOBALID` field when its parent has a GlobalID field. | [Esri support article 000015632](https://support.esri.com/en/technical-article/000015632) | The page returned 403 to my fetch. I read only a search result summary. Treat it as unverified. |
| The .NET `Guid` formats are N (32 digits), D (hyphens), B (braces), P (parentheses) and X. Digits are written in lower case. | [Guid.ToString](https://learn.microsoft.com/en-us/dotnet/api/system.guid.tostring) | Fetched and read. |
| SQL Server `uniqueidentifier` is a 16-byte GUID. It has comparison operators. A string longer than 36 characters is cut to 36 on conversion. | [uniqueidentifier](https://learn.microsoft.com/en-us/sql/t-sql/data-types/uniqueidentifier-transact-sql) | Fetched and read. Not run: no SQL Server was available. |
| FME 2019 added a "Strip braces" reader option for geodatabases. | [Safe Software thread](https://community.safe.com/architecture-14/uuid-braces-missing-10436) | Fetched and read. |

I did not verify these, and the tool does not depend on them: what the attachment relationship
class does when a parent is deleted by each route, whether an append keeps GlobalIDs, that the
file sits in a blob column named `DATA` with its length in `DATA_SIZE` (I saw this only in
published service metadata returned by a search), and how SQL Server compares a `uniqueidentifier`
with a braced string.

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
| An empty child table exits 4 | Self-test; the `photos-empty.csv` run above |
| A column of ObjectIDs exits 1 with a note | Self-test; the `photos-objectid.csv` run above |
| The storage line, and a size that cannot be read | Self-test; the demo run |
| Only `--apply` writes, and a refused run writes nothing | Self-test; the `--out` runs above |
| `--ap`, `--app` and `--appl` are refused with exit 64 | Self-test, in process for all three, and through a child process for `--ap` |
| `--out` may not be an input table | Self-test; the last run above |
| A BOM, CRLF, blank lines, a quoted line break and a short row read correctly | Self-test |
| Lower case column names from a hosted export match the defaults | Self-test |
| A file that cannot be read exits 2, and so does a cell over the csv limit and a failed write | Self-test |
| A crash exits 70 | Self-test |
| A character the console cannot show prints as `?` | Self-test, in a child process with `PYTHONIOENCODING=ascii` |
| The source is ASCII, has no f-string, parses under the 3.9 grammar, imports no network module, and deletes nothing | Self-test, an `ast` walk of its own source |
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
- Only UTF-8 CSV is supported. Other encodings are decoded lossily without a warning, and a UTF-16
  file is rejected only because its column names are garbled, with exit 64. In Excel, save as
  "CSV UTF-8 (Comma delimited)".
- A cell over 131072 characters exits 2, because that is the csv module's limit.
- A key that starts with `=`, `+`, `-` or `@` is written to `--out` as it came. Open the file as
  text, or quote it first. A spreadsheet may read it as a formula.
- Output files are written in place, not through a temporary file. A failed write can leave a
  partial file, and the exit code is 2. Read the printed `VERDICT`, which is above the error.
- There is no `--fix` and no delete. Deciding that a photo is not wanted is a decision somebody
  signs for.
- `--self-test` ignores every other valid flag. It writes only to a temporary directory, which it
  removes at the end, even when an assertion raises.
- Coverage was measured on Windows with Python 3.13 only. It reports no missed line and no
  missed branch.

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
- [fcload](https://github.com/uhsear/fcload) - load a dataset into a geodatabase. Run this tool
  on the attachment table after a reload.
- [nalmatch](https://github.com/uhsear/nalmatch) - reconcile two tables on an identifier and
  refuse an ID rule that would merge two records into one key.
