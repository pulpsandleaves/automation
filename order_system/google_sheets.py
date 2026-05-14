import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
        self._spreadsheet = None
        self._worksheets: dict[str, Any] = {}
        self._order_worksheet_titles: dict[str, str] = {}

    def _today_iso(self) -> str:
        try:
            return datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
        except Exception:
            logger.warning("Invalid LOCAL_TIMEZONE=%s. Falling back to server local time.", settings.local_timezone)
            return datetime.now().date().isoformat()

    def daily_worksheet_name(self, date_text: str | None = None) -> str:
        date_value = date_text or self._today_iso()
        prefix = settings.google_daily_worksheet_prefix.strip()
        return f"{prefix} {date_value}" if prefix else date_value

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

    def spreadsheet(self):
        if self._spreadsheet is not None:
            return self._spreadsheet
        client = gspread.authorize(self._credentials())
        self._spreadsheet = (
            client.open_by_key(settings.google_sheet_id)
            if settings.google_sheet_id
            else client.open(settings.google_sheet_name)
        )
        return self._spreadsheet

    def worksheet(self, worksheet_name: str | None = None):
        target_worksheet_name = worksheet_name or self.daily_worksheet_name()
        if target_worksheet_name in self._worksheets:
            return self._worksheets[target_worksheet_name]

        spreadsheet = self.spreadsheet()
        try:
            worksheet = spreadsheet.worksheet(target_worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=target_worksheet_name,
                rows=1000,
                cols=len(ALL_SHEET_HEADERS),
            )
        self._worksheets[target_worksheet_name] = worksheet
        self.ensure_headers(worksheet)
        return worksheet

    def ensure_headers(self, worksheet=None) -> list[str]:
        worksheet = worksheet or self.worksheet()
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

    def is_orders_worksheet(self, worksheet) -> bool:
        title = getattr(worksheet, "title", "")
        prefix = settings.google_daily_worksheet_prefix.strip()
        if not prefix:
            return bool(title)
        return title.lower().startswith(f"{prefix.lower()} ")

    def order_worksheets(self):
        worksheets = [worksheet for worksheet in self.spreadsheet().worksheets() if self.is_orders_worksheet(worksheet)]
        worksheets.sort(key=lambda worksheet: worksheet.title, reverse=True)
        return worksheets

    def find_order_row(self, order_id: str) -> tuple[int | None, dict[str, Any] | None]:
        for worksheet in self.order_worksheets():
            headers = self.ensure_headers(worksheet)
            records = worksheet.get_all_values()[1:]
            for row_number, values in enumerate(records, start=2):
                record = dict(zip(headers, values + [""] * max(0, len(headers) - len(values))))
                if record.get("Order ID") == order_id:
                    self._order_worksheet_titles[order_id] = worksheet.title
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
            self._order_worksheet_titles[order.order_id] = worksheet.title
            return len(worksheet.get_all_values())

        return retry(operation, attempts=3, delay_seconds=1)

    def latest_order(self) -> tuple[int | None, Order | None]:
        for worksheet in self.order_worksheets():
            headers = self.ensure_headers(worksheet)
            rows = worksheet.get_all_values()[1:]
            for offset in range(len(rows) - 1, -1, -1):
                values = rows[offset]
                if not any(str(value).strip() for value in values):
                    continue
                record = dict(zip(headers, values + [""] * max(0, len(headers) - len(values))))
                order = Order.from_sheet_record(record)
                self._order_worksheet_titles[order.order_id] = worksheet.title
                return offset + 2, order
        return None, None

    def update_whatsapp_status(
        self,
        row_number: int,
        *,
        message_id: str,
        status: str,
        sent_at: str = "",
        error: str = "",
        order_id: str = "",
    ) -> None:
        worksheet_title = self._order_worksheet_titles.get(order_id, "") if order_id else ""
        worksheet = self.worksheet(worksheet_title) if worksheet_title else self.worksheet()
        headers = self.ensure_headers(worksheet)
        values = {
            "WhatsApp Message ID": message_id,
            "WhatsApp Status": status,
            "WhatsApp Sent At": sent_at,
            "WhatsApp Error": error[:500],
        }
        for header, value in values.items():
            col_number = headers.index(header) + 1
            worksheet.update_cell(row_number, col_number, value)
