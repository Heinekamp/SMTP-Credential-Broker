"""Shared CSV-building helper for the /api/exports/* routes — read-only
admin-triggered downloads (senders, local users, the permission matrix),
not a data interchange format anything re-imports."""

import csv
import io

from fastapi.responses import Response

# A cell starting with one of these is evaluated as a formula when the CSV
# is opened in Excel/LibreOffice — admin-set names/descriptions must stay
# text (#175). OWASP's recommended neutralization: a leading apostrophe.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _neutralize(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_response(filename: str, header: list[str], rows: list[list[object]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows([_neutralize(cell) for cell in row] for row in rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
