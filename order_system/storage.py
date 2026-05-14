import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .models import Order


class OrderStorage:
    """Small SQLite backup store for orders and WhatsApp status events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.sqlite_file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    total_amount REAL NOT NULL,
                    delivery_address TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    order_status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    sheet_row INTEGER,
                    whatsapp_message_id TEXT,
                    whatsapp_status TEXT DEFAULT 'Pending',
                    whatsapp_sent_at TEXT,
                    whatsapp_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS message_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    order_id TEXT,
                    status TEXT,
                    payload TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def upsert_order(self, order: Order, *, sheet_row: int | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    order_id, customer_name, phone_number, product_name, quantity,
                    price, total_amount, delivery_address, payment_method, order_status,
                    timestamp, sheet_row, whatsapp_message_id, whatsapp_status,
                    whatsapp_sent_at, whatsapp_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    customer_name=excluded.customer_name,
                    phone_number=excluded.phone_number,
                    product_name=excluded.product_name,
                    quantity=excluded.quantity,
                    price=excluded.price,
                    total_amount=excluded.total_amount,
                    delivery_address=excluded.delivery_address,
                    payment_method=excluded.payment_method,
                    order_status=excluded.order_status,
                    timestamp=excluded.timestamp,
                    sheet_row=COALESCE(excluded.sheet_row, orders.sheet_row),
                    updated_at=excluded.updated_at
                """,
                (
                    order.order_id,
                    order.customer_name,
                    order.phone_number,
                    order.product_name,
                    order.quantity,
                    order.price,
                    order.total_amount,
                    order.delivery_address,
                    order.payment_method,
                    order.order_status,
                    order.timestamp,
                    sheet_row,
                    order.whatsapp_message_id,
                    order.whatsapp_status,
                    order.whatsapp_sent_at,
                    order.whatsapp_error,
                    now,
                    now,
                ),
            )

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            return dict(row) if row else None

    def get_order_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE whatsapp_message_id = ?", (message_id,)).fetchone()
            return dict(row) if row else None

    def update_sheet_row(self, order_id: str, sheet_row: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                "UPDATE orders SET sheet_row = ?, updated_at = ? WHERE order_id = ?",
                (sheet_row, now, order_id),
            )

    def update_whatsapp_status(
        self,
        order_id: str,
        *,
        message_id: str = "",
        status: str,
        sent_at: str = "",
        error: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE orders
                SET whatsapp_message_id = COALESCE(NULLIF(?, ''), whatsapp_message_id),
                    whatsapp_status = ?,
                    whatsapp_sent_at = COALESCE(NULLIF(?, ''), whatsapp_sent_at),
                    whatsapp_error = ?,
                    updated_at = ?
                WHERE order_id = ?
                """,
                (message_id, status, sent_at, error, now, order_id),
            )

    def add_message_event(self, *, message_id: str, order_id: str = "", status: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO message_events (message_id, order_id, status, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    order_id,
                    status,
                    json.dumps(payload, ensure_ascii=True),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def list_orders(self, *, search: str = "", status: str = "") -> list[dict[str, Any]]:
        filters = []
        params: list[Any] = []
        if status:
            filters.append("LOWER(order_status) = LOWER(?)")
            params.append(status)
        if search:
            filters.append(
                "(LOWER(order_id) LIKE LOWER(?) OR LOWER(customer_name) LIKE LOWER(?) OR phone_number LIKE ?)"
            )
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM orders {where_clause} ORDER BY timestamp DESC LIMIT 500",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

