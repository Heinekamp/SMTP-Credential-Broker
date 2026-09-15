"""Shared CSV-building helper for the /api/exports/* routes — read-only
admin-triggered downloads (senders, local users, the permission matrix),
not a data interchange format anything re-imports."""

import csv
import io

from fastapi.responses import Response


def csv_response(filename: str, header: list[str], rows: list[list[object]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
