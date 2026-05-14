import random
import re
import time
from datetime import datetime
from typing import Callable, TypeVar

T = TypeVar("T")


def generate_order_id() -> str:
    today = datetime.now().strftime("%d%m%y")
    suffix = random.randint(1000, 9999)
    return f"PL{today}{suffix}"


def normalize_whatsapp_number(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) > 10 and digits.startswith("91"):
        return digits[-12:]
    return digits


def format_rupees(amount: float) -> str:
    return f"₹{amount:,.0f}"


def retry(operation: Callable[[], T], *, attempts: int = 3, delay_seconds: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - caller wants generic retry handling
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay_seconds * attempt)
    raise last_error or RuntimeError("Retry operation failed.")

