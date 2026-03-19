from datetime import date

from workhours_app.services.payroll_service import fmt_hours, money, get_week_range
from workhours_app.services.clock_service import apply_unpaid_break


def test_payroll_formatters():
    assert money(12) == '12.00'
    assert fmt_hours(8.5) == '8.50'
    start, end = get_week_range(date(2026, 3, 18))
    assert start <= end


def test_break_application():
    assert apply_unpaid_break(5.0) == 5.0
    assert apply_unpaid_break(6.0) == 5.5
