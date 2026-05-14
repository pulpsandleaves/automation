from dataclasses import dataclass
from datetime import datetime
from typing import Any

ORDER_HEADERS = [
    "Order ID",
    "Customer Name",
    "Phone Number",
    "Product Name",
    "Quantity",
    "Price",
    "Total Amount",
    "Delivery Address",
    "Payment Method",
    "Order Status",
    "Timestamp",
]

SYSTEM_HEADERS = [
    "WhatsApp Message ID",
    "WhatsApp Status",
    "WhatsApp Sent At",
    "WhatsApp Error",
]

ALL_SHEET_HEADERS = ORDER_HEADERS + SYSTEM_HEADERS


@dataclass
class Order:
    order_id: str
    customer_name: str
    phone_number: str
    product_name: str
    quantity: int
    price: float
    total_amount: float
    delivery_address: str
    payment_method: str
    order_status: str = "Confirmed"
    timestamp: str = ""
    whatsapp_message_id: str = ""
    whatsapp_status: str = "Pending"
    whatsapp_sent_at: str = ""
    whatsapp_error: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any], order_id: str) -> "Order":
        quantity = int(payload.get("quantity") or 1)
        price = float(payload.get("price") or 0)
        total_amount = float(payload.get("total_amount") or quantity * price)
        return cls(
            order_id=order_id,
            customer_name=str(payload.get("customer_name", "")).strip(),
            phone_number=str(payload.get("phone_number", payload.get("phone", ""))).strip(),
            product_name=str(payload.get("product_name", "Premium Malda Mangoes")).strip(),
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            delivery_address=str(payload.get("delivery_address", payload.get("address", ""))).strip(),
            payment_method=str(payload.get("payment_method", "Online Payment")).strip(),
            order_status=str(payload.get("order_status", "Confirmed")).strip() or "Confirmed",
            timestamp=str(payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
        )

    @classmethod
    def from_sheet_record(cls, record: dict[str, Any]) -> "Order":
        def get(*names: str, default: str = "") -> str:
            for name in names:
                value = record.get(name)
                if value not in (None, ""):
                    return str(value).strip()
            return default

        return cls(
            order_id=get("Order ID"),
            customer_name=get("Customer Name"),
            phone_number=get("Phone Number", "Phone", "Mobile Number"),
            product_name=get("Product Name", "Order Summary", default="Premium Malda Mangoes"),
            quantity=int(float(get("Quantity", default="1") or 1)),
            price=float(get("Price", default="0") or 0),
            total_amount=float(get("Total Amount", default="0") or 0),
            delivery_address=get("Delivery Address", "Address"),
            payment_method=get("Payment Method", default="Online Payment"),
            order_status=get("Order Status", "Status", default="Confirmed"),
            timestamp=get("Timestamp", default=datetime.now().isoformat(timespec="seconds")),
            whatsapp_message_id=get("WhatsApp Message ID"),
            whatsapp_status=get("WhatsApp Status", default="Pending"),
            whatsapp_sent_at=get("WhatsApp Sent At"),
            whatsapp_error=get("WhatsApp Error"),
        )

    def validate(self) -> None:
        missing = []
        if not self.customer_name:
            missing.append("customer_name")
        if not self.phone_number:
            missing.append("phone_number")
        if not self.product_name:
            missing.append("product_name")
        if self.quantity <= 0:
            missing.append("quantity")
        if not self.delivery_address:
            missing.append("delivery_address")
        if missing:
            raise ValueError(f"Missing or invalid order fields: {', '.join(missing)}")

    def to_sheet_row(self) -> list[Any]:
        return [
            self.order_id,
            self.customer_name,
            self.phone_number,
            self.product_name,
            self.quantity,
            self.price,
            self.total_amount,
            self.delivery_address,
            self.payment_method,
            self.order_status,
            self.timestamp,
            self.whatsapp_message_id,
            self.whatsapp_status,
            self.whatsapp_sent_at,
            self.whatsapp_error,
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "customer_name": self.customer_name,
            "phone_number": self.phone_number,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "price": self.price,
            "total_amount": self.total_amount,
            "delivery_address": self.delivery_address,
            "payment_method": self.payment_method,
            "order_status": self.order_status,
            "timestamp": self.timestamp,
            "whatsapp_message_id": self.whatsapp_message_id,
            "whatsapp_status": self.whatsapp_status,
            "whatsapp_sent_at": self.whatsapp_sent_at,
            "whatsapp_error": self.whatsapp_error,
        }
