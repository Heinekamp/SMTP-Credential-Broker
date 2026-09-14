import datetime


def utcnow() -> datetime.datetime:
    """Naive UTC datetime — deliberately not timezone-aware.

    SQLite has no native timestamp-with-timezone type; SQLAlchemy round-trips
    aware datetimes through it as naive ones, which then compare unequal /
    raise against aware values elsewhere in the app. Standardizing on naive
    UTC everywhere avoids that class of bug entirely, at the cost of callers
    needing to remember "this is UTC" (all of them do, by convention, in
    this codebase)."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
