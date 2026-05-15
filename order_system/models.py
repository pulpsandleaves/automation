from dataclasses import dataclass
from datetime import datetime
import re
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


def parse_numeric_value(raw_value: Any, *, default: float = 0.0) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return default

    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return default
    return float(cleaned)


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
    city: str = ""
    payment_status: str = "Pending"
    razorpay_order_id: str = ""
    razorpay_payment_id: str = ""
    notes: str = ""
    order_status: str = "Confirmed"
    timestamp: str = ""
    source: str = "Website"
    customer_email: str = ""
    google_subject: str = ""
    updated_at: str = ""
    whatsapp_message_id: str = ""
    whatsapp_status: str = "Pending"
    whatsapp_sent_at: str = ""
    whatsapp_error: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any], order_id: str) -> "Order":
        quantity = int(payload.get("quantity") or 1)
        price = float(payload.get("price") or 0)
        total_amount = float(payload.get("total_amount") or quantity * price)
        timestamp = str(payload.get("timestamp") or datetime.now().isoformat(timespec="seconds"))
        return cls(
            order_id=order_id,
            customer_name=str(payload.get("customer_name", "")).strip(),
            phone_number=str(payload.get("phone_number", payload.get("phone", ""))).strip(),
            product_name=str(payload.get("product_name", "Premium Malda Mangoes")).strip(),
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            delivery_address=str(payload.get("delivery_address", payload.get("address", ""))).strip(),
            city=str(payload.get("city", "")).strip(),
            payment_method=str(payload.get("payment_method", "Online Payment")).strip(),
            payment_status=str(payload.get("payment_status", "Pending")).strip() or "Pending",
            razorpay_order_id=str(payload.get("razorpay_order_id", "")).strip(),
            razorpay_payment_id=str(payload.get("razorpay_payment_id", "")).strip(),
            notes=str(payload.get("notes", "")).strip(),
            order_status=str(payload.get("order_status", "Confirmed")).strip() or "Confirmed",
            timestamp=timestamp,
            source=str(payload.get("source", "Website")).strip() or "Website",
            customer_email=str(payload.get("customer_email", payload.get("email", ""))).strip(),
            google_subject=str(payload.get("google_subject", "")).strip(),
            updated_at=str(payload.get("updated_at", timestamp)).strip() or timestamp,
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
            quantity=max(1, int(parse_numeric_value(get("Quantity", default="1"), default=1))),
            price=parse_numeric_value(get("Price", default="0"), default=0),
            city=get("City"),
            total_amount=parse_numeric_value(get("Total Amount", default="0"), default=0),
            delivery_address=get("Delivery Address", "Address"),
            payment_method=get("Payment Method", default="Online Payment"),
            payment_status=get("Payment Status", default="Pending"),
            razorpay_order_id=get("Razorpay Order ID"),
            razorpay_payment_id=get("Razorpay Payment ID"),
            notes=get("Notes"),
            order_status=get("Order Status", "Status", default="Confirmed"),
            timestamp=get("Timestamp", default=datetime.now().isoformat(timespec="seconds")),
            source=get("Source", default="Website"),
            customer_email=get("Customer Email", "Email", default=""),
            google_subject=get("Google Subject"),
            updated_at=get("Updated At", default=""),
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

    def to_sheet_record(self) -> dict[str, Any]:
        return {
            "Order ID": self.order_id,
            "Timestamp": self.timestamp,
            "Customer Name": self.customer_name,
            "Phone": self.phone_number,
            "Phone Number": self.phone_number,
            "Address": self.delivery_address,
            "Delivery Address": self.delivery_address,
            "City": self.city,
            "Product": self.product_name,
            "Product Name": self.product_name,
            "Quantity": self.quantity,
            "Unit Price": self.price,
            "Price": self.price,
            "Total Amount": self.total_amount,
            "Payment Mode": self.payment_method,
            "Payment Method": self.payment_method,
            "Payment Status": self.payment_status,
            "Razorpay Order ID": self.razorpay_order_id,
            "Razorpay Payment ID": self.razorpay_payment_id,
            "Notes": self.notes,
            "Order Status": self.order_status,
            "Source": self.source,
            "Customer Email": self.customer_email,
            "Google Subject": self.google_subject,
            "Updated At": self.updated_at or self.timestamp,
            "WhatsApp Message ID": self.whatsapp_message_id,
            "WhatsApp Status": self.whatsapp_status,
            "WhatsApp Sent At": self.whatsapp_sent_at,
            "WhatsApp Error": self.whatsapp_error,
        }

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
            "city": self.city,
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "razorpay_order_id": self.razorpay_order_id,
            "razorpay_payment_id": self.razorpay_payment_id,
            "notes": self.notes,
            "order_status": self.order_status,
            "timestamp": self.timestamp,
            "source": self.source,
            "customer_email": self.customer_email,
            "google_subject": self.google_subject,
            "updated_at": self.updated_at,
            "whatsapp_message_id": self.whatsapp_message_id,
            "whatsapp_status": self.whatsapp_status,
            "whatsapp_sent_at": self.whatsapp_sent_at,
            "whatsapp_error": self.whatsapp_error,
        }
