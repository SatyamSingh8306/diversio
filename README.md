# HRIS Import Preview

A small Django web application that lets a user upload an HRIS CSV and
preview what would be imported, before any employee or reporting data is
written anywhere. Nothing is persisted.

The app surfaces:

- total source rows
- employees accepted for analysis
- row-level validation errors (with source row numbers)
- root employees (no manager)
- managers and their direct-report counts
- employees that participate in a reporting cycle

## Setup

This project targets Python 3.11+ and Django 5+ (developed against
Django 6.1, Python 3.12).

```bash
pip install -r requirements.txt
```

There is no database to provision. `settings.py` declares an in-memory
SQLite database only so Django's test runner can create its test
database without errors; the application writes no employee or
relationship data.

## Run

From the project root (`D:/Assignment/diversio` in this workspace):

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and upload an HRIS CSV. A file is
provided at `sample_hris.csv`.

## Tests

```bash
python manage.py test preview
```

The test suite exercises the parsing, identity validation, manager
resolution, and cycle-detection logic directly (no browser, no Django
test client) so it is fast and focused on behaviour. Nineteen tests
cover:

- CSV parsing (UTF-8 with or without BOM, quoted commas, missing
  headers, unknown headers, non-UTF-8 files)
- identity validation (blank IDs, duplicate IDs, duplicate emails)
- manager resolution (lookup by ID, by email, conflicting references,
  self-management, missing manager)
- cycle detection (simple cycle, node reporting into a cycle, acyclic
  graph)
- end-to-end analysis on a small sample, plus a malformed-upload guard

## Project layout

```
manage.py
requirements.txt
hrispreview/        Django project (settings, root URLs, WSGI)
preview/
    analysis.py     framework-free parsing and hierarchy logic
    views.py        thin Django view that calls analyze()
    urls.py         app URLs
    tests.py        unit tests for the analysis pipeline
    templates/
        preview/
            index.html
sample_hris.csv     sample file for manual testing
```

The `preview.analysis` module is deliberately framework-free. It
exposes dataclasses (`Employee`, `ValidationError`, `ManagerInfo`,
`AnalysisResult`) and a single `analyze(bytes)` entry point, so it can
be exercised from a plain `unittest` runner without spinning up Django.

## Assumptions

- The CSV is small enough to hold in memory as text. The Python `csv`
  module reads the whole file at once; for files approaching 100,000
  employees this is the main scaling concern (see "Complexity" below).
- Headers can appear in any order, but every header in
  `EXPECTED_HEADERS` must be present. Extra columns are ignored.
- `employee_id` is the case-sensitive primary identifier. `email` is
  the lowercase secondary identifier. The two are not required to
  share a namespace; an ID `DIV-1001` and an email `div-1001@x.com`
  are not the same person.
- An employee with a manager error stays accepted (counted in "employees
  accepted") but is not a root and contributes no reporting edge. This
  matches the spec.
- Reporting cycles are reported at the level of individual employees
  who are *members* of a cycle. A person who reports *into* a cycle is
  not counted as cyclic.

## Known limitations and trade-offs

- The whole CSV is decoded into memory. For files approaching 100k
  rows this is fine on a developer laptop (a few tens of MB), but a
  truly large import would benefit from streaming.
- Cycle detection runs the classic three-colour walk on the manager
  graph, which is `O(V + E)` and (with out-degree ≤ 1) effectively
  `O(N)` over employees.
- Identity validation flags every row that shares a duplicated ID or
  email as invalid, including the first occurrence. There is no way to
  pick a canonical row without external context, so this is the safer
  choice.
- Manager error messages are written to be useful for a human reviewer.
  They are not localised and not stable across versions, so a future
  automation layer should not parse them.
- A duplicate `DIV-1113` row with whitespace (`" DIV-1113 "`) is treated
  as a *different* employee ID from `DIV-1113`, because trimming applies
  only to surrounding whitespace within a single field. This matches
  the spec ("trim surrounding whitespace from every value"); if a
  stricter ID canonicalisation is required, it can be added in
  `_normalize_row`.

## Complexity (for files approaching 100,000 employees)

- Parsing: `O(N)` time, `O(N)` memory in the row buffer.
- Identity validation: one pass to collect duplicates plus one pass to
  flag rows, both `O(N)` time, `O(U)` memory where `U` is the number of
  unique IDs and emails (bounded by `N`).
- Manager resolution: builds two dictionaries keyed by ID and email,
  `O(N)` time and memory, then one pass over employees, `O(N)`.
- Cycle detection: a three-colour walk over a functional graph,
  `O(V + E)` time, `O(V)` memory — and because each employee has at
  most one outgoing manager edge, `E ≤ V`, so this is effectively
  `O(N)`.
- Total: `O(N)` time and `O(N)` memory. The memory peak is dominated
  by the list of normalised rows and the two manager dictionaries,
  which together should stay well under 100 MB for 100k employees.

## Time spent

Approximately 60 minutes on the implementation (parsing, validation,
manager resolution, cycle detection, view, template, and tests), plus
time for review and this README. The bulk of the work was the analysis
pipeline and the cycle-detection walk.

## AI tools used

GitHub Copilot / a code-generation LLM was used to draft the cycle
detection walk and to scaffold the Django project layout. Suggestions
were reviewed line-by-line. The three-colour walk was kept because it
is the standard, easy-to-explain approach; an alternative
"parent-pointer" union-find was considered and rejected for being
heavier and less transparent for a problem of this size.
