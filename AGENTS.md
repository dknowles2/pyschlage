# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`pyschlage` is a Python 3 library that talks to the Schlage WiFi cloud
service (Encode/Encode Plus/Sense/Arrive locks). It has no official
relationship with Schlage or Allegion. There is no application to run —
the deliverable is the `pyschlage` package published to PyPI.

## Setup

```sh
uv sync --group dev
uv run pre-commit install
```

(`scripts/setup` does the same thing and is what the devcontainer runs.)

## Commands

Run these before considering any change done — CI runs all of them on
Python 3.11 and 3.12:

```sh
uv run coverage run -m pytest   # tests
uv run coverage report          # enforces the 100% coverage gate, see below
uv run ruff check .             # lint
uv run ruff format --check .    # formatting (use `ruff format .` to fix)
uv run mypy .                   # type checking
```

For quick iteration, `uv run pytest -q` is fine; run the `coverage`
variant before finishing, since `[tool.coverage.report] fail_under = 100`
in `pyproject.toml` means **any uncovered line fails CI**. New code
needs tests, not `# pragma: no cover`, unless the branch is genuinely
unreachable (a handful of existing lines use the pragma for exactly
that reason — don't reach for it as a shortcut).

To build the Sphinx docs locally:

```sh
uv pip install -r docs/requirements.txt
cd docs && python -m sphinx -b html . /tmp/out -W
```

## Conventions

- **Dataclasses, not plain classes**, for anything that models API data
  (`Lock`, `AccessCode`, `User`, `LockLog`, ...). Public fields get a
  docstring on the line right after the field, e.g.:

  ```python
  battery_level: int | None = None
  """The remaining battery level of the lock."""
  ```

  Match this for any new field — the generated API docs
  (`docs/api.rst`) render these via `:undoc-members:`, so an
  undocumented field just silently shows up with no description.

- **Docstring style is Sphinx/reST**, not Google or NumPy style: use
  `:param:`, `:type:`, `:raise:`, `:rtype:`. Methods that exist only to
  support the public API (`from_json`, `to_json`, `request_path`) are
  marked `:meta private:` so they don't clutter the generated reference
  — do the same for any new internal helper that needs a docstring but
  isn't part of the public surface.

- **New public types need an entry in `docs/api.rst`.** It's easy to
  add a new dataclass that's reachable from the public API (e.g. as a
  field on `Lock` or `AccessCode`) and forget it has no
  `.. autoclass::` entry, so it never shows up in the rendered docs.
  Check `docs/api.rst` whenever you add or rename a type that a public
  method or attribute returns.

- **`from __future__ import annotations`** at the top of modules that
  use `X | Y` unions or forward references, for Python 3.11
  compatibility where relevant.

- Methods that hit the network raise `pyschlage.exceptions.NotAuthorizedError`
  or `pyschlage.exceptions.UnknownError`; document both in `:raise:` if
  the method can trigger them (see `pyschlage/lock.py` for examples).
  `NotAuthenticatedError` is also raised for calls made on an object
  that isn't authenticated yet; whether it's documented is inconsistent
  today (`AccessCode.save()`/`delete()` list it, most of `Lock`'s
  methods don't) — match whatever the file you're editing already does
  nearby rather than picking a third convention.

- Import order and formatting are enforced by `ruff format` +
  `ruff check --fix` (isort-style import sorting is on via
  `tool.ruff.lint.extend-select = ["I"]`). Don't hand-format imports —
  just run the tools.

## Commit / PR conventions

- Commit subjects and PR titles follow Conventional Commits:
  `fix(scope): ...`, `docs: ...`, `test: ...`, `ci: ...`, `feat: ...`.
  Look at recent merged PRs (`gh pr list --state merged`) for examples.
- PRs are labeled for release-drafter (`.github/release-drafter.yml`),
  which sorts the changelog by label. Common labels: `bug`,
  `enhancement`, `breaking`, `documentation`, `cleanup`, `dependencies`.
  Apply the label that matches the change when opening a PR.
- Keep PRs well-scoped — one logical change per PR rather than bundling
  unrelated fixes together, even when doing a broader audit or sweep.
