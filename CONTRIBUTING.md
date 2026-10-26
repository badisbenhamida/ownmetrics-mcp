# Contributing

This project is built with spec-driven development: the spec leads, code follows.

## Adding or changing a tool

1. **Requirement first.** Add or edit a row in `SPEC.md` with a new ID, milestone and
   verification method. Changing behavior without changing the spec is a review blocker.
2. **Test second.** Write tests tagged with the ID, using synthetic data only:

   ```python
   @pytest.mark.req("T10")
   def test_new_tool(): ...
   ```

3. **Code third.** Implement until the tests pass.
4. **Check the trace.** `python scripts/traceability.py --check` must pass; it regenerates
   `TRACEABILITY.md` and fails on any in-scope requirement without a test.

## Rules that always apply

Read section 2 of `SPEC.md` (the constitution). In short: read-only, local-only, no stored
data, missing is never zero, never expose the key, no Garmin branding, not medical advice.

## Never commit real data

Fixtures are invented. Never add a real person's Garmin data, FIT files or keys. The
`.gitignore` blocks common cases and CI runs a secret scanner, but review your diff anyway.

## Local checks

```bash
uv pip install -e ".[dev]"
ruff check . && ruff format --check . && pyright && pytest -q
python scripts/traceability.py --check
```
