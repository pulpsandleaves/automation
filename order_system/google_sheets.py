import logging
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from .config import ConfigurationError, parse_service_account_json, settings
from .models import ALL_SHEET_HEADERS, Order
from .utils import retry

logger = logging.getLogger(__name__)


def column_letter(index: int) -> str:
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


class GoogleSheetsClient:
    """Google Sheets live database client."""

    def __init__(self) -> None:
        self._worksheet = None

    def _credentials(self) -> Credentials:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        if settings.google_credentials_json:
            return Credentials.from_service_account_info(
                parse_service_account_json(settings.google_credentials_json),
                scopes=scopes,
            )

        credentials_file = Path(settings.google_credentials_file)
        if not credentials_file.exists():
            raise ConfigurationError("Google credentials not found. Set GOOGLE_CREDENTIALS_JSON or GOOGLE_CREDENTIALS_FILE.")
        return Credentials.from_service_account_file(str(credentials_file), scopes=scopes)

    def worksheet(self):
        if self._worksheet is not None:
            return self._worksheet

        client = gspread.authorize(self._credentials())
        spreadsheet = (
            client.open_by_key(settings.google_sheet_id)
            if settings.google_sheet_id
            else client.open(settings.google_sheet_name)
        )
        try:
            self._worksheet = spreadsheet.worksheet(settings.google_worksheet_name)
        except gspread.WorksheetNotFound:
            self._worksheet = spreadsheet.add_worksheet(
                title=settings.google_worksheet_name,
                rows=1000,
                cols=len(ALL_SHEET_HEADERS),
            )
        self.ensure_headers()
        return self._worksheet

    def ensure_headers(self) -> list[str]:
        worksheet = self._worksheet or self.worksheet()
        headers = worksheet.row_values(1)
        updated = list(headers) if headers else []
        for header in ALL_SHEET_HEADERS:
            if header not in updated:
                updated.append(header)

        if not headers:
            worksheet.append_row(updated)
        elif updated != headers:
            if worksheet.col_count < len(updated):
                worksheet.add_cols(len(updated) - worksheet.col_count)
            worksheet.update(f"A1:{column_letter(len(updated))}1", [updated])
        return updated

    def find_order_row(self, order_id: str) -> tuple[int | None, dict[str, Any] | None]:
        worksheet = self.worksheet()
        headers = self.ensure_headers()
        records = worksheet.get_all_values()[1:]
        for row_number, values in enumerate(records, start=2):
            record = dict(zip(headers, values + [""] * max(0, len(headers) - len(values))))
            if record.get("Order ID") == order_id:
                return row_number, record
        return None, None

    def append_order(self, order: Order) -> int:
        def operation() -> int:
            existing_row, _ = self.find_order_row(order.order_id)
            if existing_row:
                logger.info("Skipping duplicate Google Sheet append for order %s", order.order_id)
                return existing_row

            worksheet = self.worksheet()
            worksheet.append_row(order.to_sheet_row(), value_input_option="USER_ENTERED")
            return len(worksheet.get_all_values())

        return retry(operation, attempts=3, delay_seconds=1)

    def latest_order(self) -> tuple[int | None, Order | None]:
        worksheet = self.worksheet()
        headers = self.ensure_headers()
        rows = worksheet.get_all_values()[1:]
        for offset in range(len(rows) - 1, -1, -1):
            values = rows[offset]
            if not any(str(value).strip() for value in values):
                continue
            record = dict(zip(headers, values + [""] * max(0, len(headers) - len(values))))
            return offset + 2, Order.from_sheet_record(record)
        return None, None

    def update_whatsapp_status(self, row_number: int, *, message_id: str, status: str, sent_at: str = "", error: str = "") -> None:
        headers = self.ensure_headers()
        values = {
            "WhatsApp Message ID": message_id,
            "WhatsApp Status": status,
            "WhatsApp Sent At": sent_at,
            "WhatsApp Error": error[:500],
        }
        worksheet = self.worksheet()
        for header, value in values.items():
            col_number = headers.index(header) + 1
            worksheet.update_cell(row_number, col_number, value)
