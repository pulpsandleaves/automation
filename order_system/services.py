import logging
from datetime import datetime
from typing import Any

from .config import ConfigurationError
from .google_sheets import GoogleSheetsClient
from .models import Order
from .storage import OrderStorage
from .utils import generate_order_id, retry
from .whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)


class OrderService:
    """Coordinates website orders, Sheets, SQLite backup, and WhatsApp sends."""

    def __init__(
        self,
        *,
        sheets: GoogleSheetsClient | None = None,
        storage: OrderStorage | None = None,
        whatsapp: WhatsAppClient | None = None,
    ) -> None:
        self.sheets = sheets or GoogleSheetsClient()
        self.storage = storage or OrderStorage()
        self.whatsapp = whatsapp or WhatsAppClient()

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_id = str(payload.get("order_id") or generate_order_id())
        order = Order.from_payload(payload, order_id)
        order.validate()

        existing = self.storage.get_order(order.order_id)
        if existing and existing.get("whatsapp_status") in {"Sent", "delivered", "read"}:
            return {"status": "duplicate", "order": existing}

        self.storage.upsert_order(order)

        sheet_row = retry(lambda: self.sheets.append_order(order), attempts=3, delay_seconds=1)
        self.storage.update_sheet_row(order.order_id, sheet_row)

        latest_row, latest_order = self.sheets.latest_order()
        order_to_confirm = latest_order if latest_order and latest_order.order_id == order.order_id else order

        try:
            self.send_confirmation(order_to_confirm, sheet_row=latest_row or sheet_row)
            status = "created"
            warning = ""
        except Exception as exc:  # noqa: BLE001 - order is already saved; surface a graceful warning
            status = "created_confirmation_failed"
            warning = str(exc)

        return {"status": status, "order": order_to_confirm.to_dict(), "sheet_row": sheet_row, "warning": warning}

    def send_confirmation(self, order: Order, *, sheet_row: int | None = None) -> None:
        try:
            self.storage.update_whatsapp_status(order.order_id, status="Sending")
            message_id, sent_at = self.whatsapp.send_order_confirmation(order)
            self.storage.update_whatsapp_status(
                order.order_id,
                message_id=message_id,
                status="Sent",
                sent_at=sent_at,
            )
            if sheet_row:
                self.sheets.update_whatsapp_status(
                    sheet_row,
                    message_id=message_id,
                    status="Sent",
                    sent_at=sent_at,
                    order_id=order.order_id,
                )
            try:
                self.whatsapp.send_admin_alert(order)
            except Exception as exc:  # noqa: BLE001 - admin alert should not fail order creation
                logger.warning("Admin WhatsApp alert failed for order %s: %s", order.order_id, exc)
        except Exception as exc:
            error = str(exc)
            logger.exception("Order confirmation failed for %s: %s", order.order_id, exc)
            self.storage.update_whatsapp_status(order.order_id, status="Failed", error=error)
            if sheet_row:
                self.sheets.update_whatsapp_status(
                    sheet_row,
                    message_id="",
                    status="Failed",
                    error=error,
                    order_id=order.order_id,
                )
            raise

    def confirm_latest_sheet_order(self) -> dict[str, Any]:
        row_number, order = self.sheets.latest_order()
        if not order or not row_number:
            return {"status": "empty", "message": "No order rows found."}

        existing = self.storage.get_order(order.order_id)
        if existing and existing.get("whatsapp_status") in {"Sent", "delivered", "read"}:
            return {"status": "duplicate", "order": existing}

        self.storage.upsert_order(order, sheet_row=row_number)
        try:
            self.send_confirmation(order, sheet_row=row_number)
            return {"status": "sent", "order": order.to_dict(), "sheet_row": row_number}
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "order": order.to_dict(), "sheet_row": row_number, "error": str(exc)}

    def list_orders(self, *, search: str = "", status: str = "") -> list[dict[str, Any]]:
        return self.storage.list_orders(search=search, status=status)


def sync_whatsapp_statuses_from_webhook(payload: dict[str, Any]) -> None:
    """Store delivery/read/failed status callbacks from Meta webhooks."""
    storage = OrderStorage()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status_event in value.get("statuses", []):
                message_id = status_event.get("id", "")
                status = status_event.get("status", "")
                if not message_id or not status:
                    continue

                order = storage.get_order_by_message_id(message_id)
                order_id = order.get("order_id", "") if order else ""
                storage.add_message_event(
                    message_id=message_id,
                    order_id=order_id,
                    status=status,
                    payload=status_event,
                )
                if order_id:
                    storage.update_whatsapp_status(
                        order_id,
                        message_id=message_id,
                        status=status,
                        sent_at=datetime.now().isoformat(timespec="seconds"),
                        error=status_event.get("errors", [{}])[0].get("title", "") if status == "failed" else "",
                    )
                    sheet_row = order.get("sheet_row")
                    if sheet_row:
                        try:
                            sheets = GoogleSheetsClient()
                            resolved_row, _ = sheets.find_order_row(order_id)
                            sheets.update_whatsapp_status(
                                int(resolved_row or sheet_row),
                                message_id=message_id,
                                status=status,
                                sent_at=datetime.now().isoformat(timespec="seconds"),
                                error=status_event.get("errors", [{}])[0].get("title", "") if status == "failed" else "",
                                order_id=order_id,
                            )
                        except Exception as exc:  # noqa: BLE001 - webhook must still return 200
                            logger.warning("Failed to sync WhatsApp status to Google Sheets: %s", exc)


def build_service() -> OrderService:
    try:
        return OrderService()
    except ConfigurationError:
        raise
