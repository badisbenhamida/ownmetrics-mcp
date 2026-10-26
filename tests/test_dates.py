from datetime import date

import pytest

from ownmetrics_mcp.dates import parse_day, parse_range, windows
from ownmetrics_mcp.errors import InvalidInputError

req = pytest.mark.req


@req("R1")
def test_parses_iso_dates():
    assert parse_day("2026-10-25") == date(2026, 10, 25)


@req("R1")
@pytest.mark.parametrize("bad", ["25/10/2026", "yesterday", "", "2026-13-01"])
def test_rejects_non_iso_dates(bad):
    with pytest.raises(InvalidInputError, match="YYYY|2026-10-25"):
        parse_day(bad)


@req("R1")
def test_range_must_not_run_backwards():
    with pytest.raises(InvalidInputError, match="on or after"):
        parse_range("2026-10-10", "2026-10-01")


@req("R1")
def test_range_is_inclusive_and_capped_at_90_days():
    assert parse_range("2026-01-01", "2026-03-31") == (date(2026, 1, 1), date(2026, 3, 31))
    with pytest.raises(InvalidInputError, match="91 days"):
        parse_range("2026-01-01", "2026-04-01")


@req("R2")
def test_windows_cover_range_without_gaps_or_overlap():
    w = windows(date(2026, 1, 1), date(2026, 3, 31), 31)
    assert w[0] == (date(2026, 1, 1), date(2026, 1, 31))
    assert w[-1][1] == date(2026, 3, 31)
    for (_, end), (start, _) in zip(w, w[1:], strict=False):
        assert (start - end).days == 1
    assert all((b - a).days + 1 <= 31 for a, b in w)


@req("R2")
def test_single_day_is_one_window():
    assert windows(date(2026, 5, 5), date(2026, 5, 5), 28) == [(date(2026, 5, 5), date(2026, 5, 5))]
