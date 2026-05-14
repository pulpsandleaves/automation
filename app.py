import json
import logging
import mimetypes
import os
import random
import re
import hmac
import hashlib
import ast
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Dict
from zoneinfo import ZoneInfo

import gspread
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from google.oauth2.service_account import Credentials

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
META_APP_ID = os.getenv("META_APP_ID", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v19.0")
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "PulpsAndLeavesOrders")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Orders")
GOOGLE_DAILY_WORKSHEET_PREFIX = os.getenv("GOOGLE_DAILY_WORKSHEET_PREFIX", "Orders")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "Asia/Kolkata")
OUTBOUND_CONFIRMATION_SECRET = os.getenv("OUTBOUND_CONFIRMATION_SECRET", VERIFY_TOKEN).strip()
ORDER_CONFIRMATION_TEMPLATE_NAME = os.getenv("ORDER_CONFIRMATION_TEMPLATE_NAME", "").strip()
ORDER_CONFIRMATION_TEMPLATE_LANGUAGE = os.getenv("ORDER_CONFIRMATION_TEMPLATE_LANGUAGE", "en_US").strip()
SUPPORT_NUMBER = os.getenv("SUPPORT_NUMBER", "919835496666")
DEFAULT_ORDER_STATUS = os.getenv("DEFAULT_ORDER_STATUS", "Order Confirmed")
PRICE_3KG_BOX = int(os.getenv("PRICE_3KG_BOX", "599"))
PRICE_5KG_BOX = int(os.getenv("PRICE_5KG_BOX", "999"))
DISCOUNT_PERCENT = int(os.getenv("DISCOUNT_PERCENT", "10"))
DISCOUNT_THRESHOLD = int(os.getenv("DISCOUNT_THRESHOLD", "0"))
DELIVERY_CHARGE_BELOW_THRESHOLD = int(os.getenv("DELIVERY_CHARGE_BELOW_THRESHOLD", "30"))
DELIVERY_FREE_THRESHOLD = int(os.getenv("DELIVERY_FREE_THRESHOLD", "599"))
MESSAGE_REPEAT_COOLDOWN_DAYS = int(os.getenv("MESSAGE_REPEAT_COOLDOWN_DAYS", "10"))
MESSAGE_HISTORY_FILE = os.getenv("MESSAGE_HISTORY_FILE", "message_history.json")
SESSION_STORE_FILE = os.getenv("SESSION_STORE_FILE", "/tmp/user_sessions.json")
SESSION_IDLE_RESET_MINUTES = int(os.getenv("SESSION_IDLE_RESET_MINUTES", "30"))
BASE_DIR = Path(__file__).resolve().parent
CART_IMAGE_PATH = os.getenv("CART_IMAGE_PATH", "assets/main.png")
WELCOME_IMAGE_PATH = os.getenv("WELCOME_IMAGE_PATH", "assets/welcome_template.png")
ORDER_WEBSITE_URL = os.getenv("ORDER_WEBSITE_URL", "https://pulpsandleaves.com/")

uploaded_media_ids: Dict[str, str] = {}
TRACKING_TRIGGER_TEXTS = {
    "2",
    "track your aam",
    "track aam",
    "track order",
    "order tracking",
    "tracking",
}
WORKSHEET_HEADERS = [
    "Timestamp",
    "Order ID",
    "Customer Name",
    "Phone",
    "City",
    "Delivery Slot",
    "Order Summary",
    "3KG Qty",
    "5KG Qty",
    "Address",
    "Status",
    "Source",
]
ORDER_TABLE_RANGE = "A:L"
CONFIRMATION_STATUS_HEADER = "WhatsApp Confirmation Status"
CONFIRMATION_SENT_AT_HEADER = "WhatsApp Confirmation Sent At"
CONFIRMATION_MESSAGE_ID_HEADER = "WhatsApp Confirmation Message ID"
CONFIRMATION_ERROR_HEADER = "WhatsApp Confirmation Error"
CONFIRMATION_HEADERS = [
    CONFIRMATION_STATUS_HEADER,
    CONFIRMATION_SENT_AT_HEADER,
    CONFIRMATION_MESSAGE_ID_HEADER,
    CONFIRMATION_ERROR_HEADER,
]
ORDER_FIELD_ALIASES = {
    "order_id": ("Order ID", "Order Id", "OrderID", "Order Number", "Order No", "Order"),
    "customer_name": ("Customer Name", "Name", "Customer", "Full Name"),
    "email": ("Email", "Email Id", "Email ID", "Email Address", "Customer Email"),
    "phone": (
        "Phone",
        "Mobile",
        "Mobile Number",
        "Contact Number",
        "WhatsApp",
        "WhatsApp Number",
        "Whatsapp Number",
        "Phone Number",
    ),
    "city": ("City", "Delivery City", "Shipping City"),
    "delivery_slot": ("Delivery Slot", "Delivery Date", "Delivery Window", "Estimated Delivery"),
    "order_summary": ("Order Summary", "Items", "Products", "Product", "Cart", "Order Details"),
    "address": ("Address", "Delivery Address", "Shipping Address"),
    "status": ("Status", "Order Status"),
    "qty_3kg": ("3KG Qty", "3kg Qty", "3KG Quantity", "Qty 3KG"),
    "qty_5kg": ("5KG Qty", "5kg Qty", "5KG Quantity", "Qty 5KG"),
}
PRE_CART_PROMO_TEXT = (
    "🛒 Your cart is feeling lonely… add some mango magic to it 🥭😄\n\n"
    "Choose your favorite Mangoes and let’s make this order juicy 🚚✨\n\n"
    "https://pulpsandleaves.com/"
)

MESSAGES = {
    "welcome": (
        "We are Currently offering fresh, premium-quality Malda Mangoes directly sourced from farms !!\n"
        "How may we assist you today?\n\n"
        "1️⃣ - Order Malda Mangoes 🥭🚚\n"
        "2️⃣ - Track Your Aam 🔍\n"
        "3️⃣ - Talk to A Mango Agent 💬"
    ),
    "invalid_main_menu": (
        "Kindly Choose the Relevant Option -\n\n"
        "1️⃣ - Order Malda Mangoes 🥭🚚\n"
        "2️⃣ - Track Your Aam 🔍\n"
        "3️⃣ - Talk to A Mango Agent 💬"
    ),
    "order_redirect": (
        "🛒 Your cart is feeling lonely… add some mango magic to it 🥭😄\n\n"
        "Choose your favorite Mangoes and let’s make this order juicy 🚚✨\n\n"
        f"{ORDER_WEBSITE_URL}"
    ),
    "city_selection": (
        "🏙️ Pick your city & let the mango journey begin 🥭🚚\n\n"
        "1️⃣ - Bangalore 🌦️\n"
        "2️⃣ - Hyderabad 🥯\n"
        "3️⃣ - Pune 🌿\n"
        "4️⃣ - Mumbai 🌊"
    ),
    "invalid_city": (
        "Kindly Choose the Relevant Option -\n\n"
        "1️⃣ - Order Malda Mangoes 🥭🚚\n"
        "2️⃣ - Track Your Aam 🔍\n"
        "3️⃣ - Talk to A Mango Agent 💬"
    ),
    "continue_order": (
        "🥭 Please choose an option below 👇\n\n"
        "1️⃣ - Continue & Place Your Order 🚚✨\n"
        "2️⃣ - Exit for Now (We’ll Wait for Your Next Mango Craving 😄)"
    ),
    "exit": (
        "🙏 Thanks for contacting Pulps and Leaves! 🥭✨\n"
        "Please visit again to taste our delicious delicacies and mango magic 😄"
    ),
    "order_collection": (
        "🥭 Please send your order in the format below:\n\n"
        "• Box Size (3KG or 5KG)\n"
        "• Quantity Required\n"
        "• Delivery Address\n"
        "• Contact Number 📱\n\n"
        "Example:\n\n"
        "3KG Box × 2\n"
        "5KG Box × 1\n\n"
        "Whitefield, Bangalore\n"
        "9876543210"
    ),
    "invalid_order": (
        "📍 We couldn't understand the complete order details.\n\n"
        "Please send:\n\n"
        "• Box Size (3KG or 5KG)\n"
        "• Quantity Required\n"
        "• Full Delivery Address\n"
        "• Mobile Number 📱\n\n"
        "Example:\n\n"
        "3KG Box × 2\n"
        "5KG Box × 1\n\n"
        "Whitefield, Bangalore\n"
        "9876543210"
    ),
    "fallback": (
        "Looks like something’s not working smoothly 😅\n"
        "Would you like us to connect you with an agent to help you out?"
    ),
    "human_support": (
        "Looks like something’s not working smoothly 😅\n"
        "Would you like us to connect you with an agent to help you out?"
    ),
    "direct_support": (
        "Dear Customer 🥭,\n"
        "I’m Maya, your mango assistant. How can I help you today?\n\n"
        "2️⃣ - Talk to a Real Human Before the Mangoes Take Over 👨‍💼😂"
    ),
    "tracking_prompt": (
        "Track Your Aam 🔍\n\n"
        "Please send the last 4 digits of your Order ID.\n\n"
        "Example: 4821"
    ),
    "tracking_invalid": (
        "Track Your Aam 🔍\n\n"
        "Please send exactly 4 digits from your Order ID.\n\n"
        "Example: 4821"
    ),
    "tracking_not_found": (
        "Track Your Aam 🔍\n\n"
        "We could not find an order with those last 4 digits.\n\n"
        "Please check and try again."
    ),
}

WELCOME_TRIGGER_TEXTS = {
    "1",
    "order",
    "order & pay online",
    "order and pay online",
    "order online",
    "pay online",
    "payment",
    "website",
    "order malda mangoes",
    "order mangoes",
    "order fresh mangoes",
    "hi",
    "hello",
    "hey",
    "start",
}
WHATSAPP_ORDER_STEPS = {
    "select_city",
    "continue_order",
    "select_quantities",
    "cart_menu",
    "select_box_quantity",
    "collect_name",
    "collect_address",
    "collect_phone",
    "collect_order_details",
}
HUMAN_SUPPORT_TRIGGER_TEXTS = {
    "3",
    "talk to a mango agent",
    "talk to mango agent",
    "mango agent",
    "talk to agent",
    "real human",
    "talk to a real human before the mangoes take over",
    "talk to a real human",
    "talk to support",
    "human",
    "agent",
    "support",
}
CITY_OPTIONS = {
    "1": {
        "name": "Bangalore",
        "code": "BLR",
        "aliases": {"1", "bangalore", "bengaluru", "city_blr"},
        "delivery_message": (
            "📦🥭 Good news, Namma Bengaluru !!\n\n"
            "Your next mango delivery slot is scheduled between *2nd – 4th June ’26* 🚚✨\n\n"
            "Our mangoes are already warming up for their Bengaluru trip 🌦️🥭—planning a chill walk in Cubbon Park and cheering for RCB on the way 😄🏏"
        ),
    },
    "2": {
        "name": "Hyderabad",
        "code": "HYD",
        "aliases": {"2", "hyderabad", "hyd", "city_hyd"},
        "delivery_message": (
            "📦🥭 Hello Hyderabad!\n\n"
            "Your next mango delivery slot is scheduled between *2nd – 4th June ’26* 🚚✨\n\n"
            "Our mangoes are crossing the lanes of Charminar with full Hyderabadi swag and can’t wait to reach your doorstep 🕌🍗🥭😄"
        ),
    },
    "3": {
        "name": "Pune",
        "code": "PUN",
        "aliases": {"3", "pune", "city_pun"},
        "delivery_message": (
            "📦🥭 Hey Pune!\n\n"
            "Your mango delivery is arriving between 10th – 12th June ’26 🚚✨\n"
            "Our mangoes are cruising through Maharashtra with full Puneri swag – stopped for misal pav, judging traffic, and saying\n"
            "“काय मग, पुणे… थांबा जरा!” 😏☕🥭\n"
            "Don’t worry, they’ll reach before you lose patience 😄\n"
            "Get ready… sweetness is loading! ⏳🥭"
        ),
    },
    "4": {
        "name": "Mumbai",
        "code": "MUM",
        "aliases": {"4", "mumbai", "bombay", "city_mum"},
        "delivery_message": (
            "📦🥭 Hello Mumbai!\n\n"
            "Your next mango delivery slot is scheduled between *10th – 12th June ’26* 🚚✨\n\n"
            "Our mangoes are already practicing their “Mumbai local” survival skills before reaching your doorstep fresh, juicy, and full of sweetness 😄🥭"
        ),
    },
}

user_sessions: Dict[str, Dict[str, Any]] = {}
order_sequence_by_key: Dict[str, int] = {}
message_history: Dict[str, Any] = {}
session_lock = RLock()
sequence_lock = RLock()
history_lock = RLock()

SAMPLE_LOCALITIES = {
    "Bangalore": [
        "Whitefield", "Indiranagar", "HSR Layout", "Koramangala",
    ],
    "Hyderabad": [
        "Gachibowli", "Madhapur", "Kondapur", "Banjara Hills",
    ],
    "Pune": [
        "Baner", "Kothrud", "Wakad", "Viman Nagar",
    ],
    "Mumbai": [
        "Andheri West", "Powai", "Bandra", "Navi Mumbai",
    ],
}

COMBINED_QUANTITY_OPTIONS = [
    {"id": "combo_1_0", "qty_3kg": 1, "qty_5kg": 0},
    {"id": "combo_2_0", "qty_3kg": 2, "qty_5kg": 0},
    {"id": "combo_0_1", "qty_3kg": 0, "qty_5kg": 1},
    {"id": "combo_0_2", "qty_3kg": 0, "qty_5kg": 2},
    {"id": "combo_1_1", "qty_3kg": 1, "qty_5kg": 1},
    {"id": "combo_1_2", "qty_3kg": 1, "qty_5kg": 2},
    {"id": "combo_2_1", "qty_3kg": 2, "qty_5kg": 1},
    {"id": "combo_2_2", "qty_3kg": 2, "qty_5kg": 2},
    {"id": "combo_3_0", "qty_3kg": 3, "qty_5kg": 0},
    {"id": "combo_0_3", "qty_3kg": 0, "qty_5kg": 3},
]


class ConfigurationError(RuntimeError):
    pass


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def utcnow() -> datetime:
    return datetime.utcnow()


def local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(LOCAL_TIMEZONE))
    except Exception:
        logger.warning("Invalid LOCAL_TIMEZONE=%s. Falling back to server local time.", LOCAL_TIMEZONE)
        return datetime.now()


def local_today_iso() -> str:
    return local_now().date().isoformat()


def resolve_orders_worksheet_name(date_text: str | None = None, worksheet_name: str | None = None) -> str:
    if worksheet_name:
        return worksheet_name.strip()

    if date_text:
        parsed_date = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        return f"{GOOGLE_DAILY_WORKSHEET_PREFIX} {parsed_date.isoformat()}"

    return f"{GOOGLE_DAILY_WORKSHEET_PREFIX} {local_today_iso()}"


def resolve_runtime_path(path_value: str) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return BASE_DIR / candidate


def parse_google_credentials_json(raw_value: str) -> Dict[str, Any]:
    cleaned_value = raw_value.strip()
    parse_errors: list[Exception] = []

    for candidate in (cleaned_value, cleaned_value.strip("'\"")):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, json.JSONDecodeError) as exc:
            parse_errors.append(exc)

    try:
        parsed = ast.literal_eval(cleaned_value)
        if isinstance(parsed, dict):
            return parsed
    except (SyntaxError, ValueError) as exc:
        parse_errors.append(exc)

    raise ConfigurationError("GOOGLE_CREDENTIALS_JSON is not valid JSON.") from parse_errors[-1]


def load_google_credentials(scopes: list[str]) -> Credentials:
    if GOOGLE_CREDENTIALS_JSON:
        service_account_info = parse_google_credentials_json(GOOGLE_CREDENTIALS_JSON)
        return Credentials.from_service_account_info(service_account_info, scopes=scopes)

    credentials_path = resolve_runtime_path(GOOGLE_CREDENTIALS_FILE)
    if not credentials_path.exists():
        raise ConfigurationError(
            "Google credentials were not found. Set GOOGLE_CREDENTIALS_JSON or provide GOOGLE_CREDENTIALS_FILE."
        )

    return Credentials.from_service_account_file(str(credentials_path), scopes=scopes)


def load_message_history() -> Dict[str, Any]:
    history_path = resolve_runtime_path(MESSAGE_HISTORY_FILE)
    if not history_path.exists():
        return {"processed_messages": {}}

    try:
        with history_path.open("r", encoding="utf-8") as history_file:
            data = json.load(history_file)
            if isinstance(data, dict):
                data.setdefault("processed_messages", {})
                return data
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load message history. Starting with empty state.")

    return {"processed_messages": {}}


def save_message_history() -> None:
    history_path = resolve_runtime_path(MESSAGE_HISTORY_FILE)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8") as history_file:
        json.dump(message_history, history_file, ensure_ascii=True, indent=2)


def load_user_sessions() -> Dict[str, Dict[str, Any]]:
    session_path = resolve_runtime_path(SESSION_STORE_FILE)
    if not session_path.exists():
        return {}

    try:
        with session_path.open("r", encoding="utf-8") as session_file:
            data = json.load(session_file)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load saved user sessions. Starting with empty session state.")

    return {}


def save_user_sessions() -> None:
    session_path = resolve_runtime_path(SESSION_STORE_FILE)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with session_path.open("w", encoding="utf-8") as session_file:
        json.dump(user_sessions, session_file, ensure_ascii=True, indent=2)


def prune_processed_messages() -> None:
    cutoff = utcnow() - timedelta(days=MESSAGE_REPEAT_COOLDOWN_DAYS)
    processed_messages = message_history.setdefault("processed_messages", {})
    stale_ids = []

    for message_id, timestamp in processed_messages.items():
        try:
            processed_at = datetime.fromisoformat(timestamp)
        except ValueError:
            stale_ids.append(message_id)
            continue

        if processed_at < cutoff:
            stale_ids.append(message_id)

    for message_id in stale_ids:
        processed_messages.pop(message_id, None)


def is_duplicate_processed_message(message_id: str) -> bool:
    if not message_id:
        return False

    with history_lock:
        prune_processed_messages()
        return message_id in message_history.setdefault("processed_messages", {})


def mark_message_processed(message_id: str) -> None:
    if not message_id:
        return

    with history_lock:
        prune_processed_messages()
        message_history.setdefault("processed_messages", {})[message_id] = utcnow().isoformat(timespec="seconds")
        save_message_history()


def format_inr(amount: int) -> str:
    return f"Rs. {amount}"


def build_graph_api_params() -> Dict[str, str]:
    if not ACCESS_TOKEN or not META_APP_SECRET:
        return {}

    appsecret_proof = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        ACCESS_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"appsecret_proof": appsecret_proof}


def calculate_order_bill(qty_3kg: int, qty_5kg: int) -> Dict[str, int]:
    subtotal = (qty_3kg * PRICE_3KG_BOX) + (qty_5kg * PRICE_5KG_BOX)
    discount = int(round(subtotal * DISCOUNT_PERCENT / 100)) if subtotal > 0 else 0
    delivery_charge = DELIVERY_CHARGE_BELOW_THRESHOLD if 0 < subtotal <= DELIVERY_FREE_THRESHOLD else 0
    total = subtotal - discount + delivery_charge
    return {
        "subtotal": subtotal,
        "discount": discount,
        "delivery_charge": delivery_charge,
        "total": total,
    }


def build_order_line_items(qty_3kg: int, qty_5kg: int) -> list[str]:
    parts = []
    if qty_3kg:
        parts.append(f"3KG Box x {qty_3kg} = {format_inr(qty_3kg * PRICE_3KG_BOX)}")
    if qty_5kg:
        parts.append(f"5KG Box x {qty_5kg} = {format_inr(qty_5kg * PRICE_5KG_BOX)}")
    return parts


def build_order_summary(qty_3kg: int, qty_5kg: int) -> str:
    parts = build_order_line_items(qty_3kg, qty_5kg)
    return ", ".join(parts) if parts else "Custom order"


def build_order_display_summary(qty_3kg: int, qty_5kg: int) -> str:
    parts = build_order_line_items(qty_3kg, qty_5kg)
    if not parts:
        return "Custom order"
    return "\n".join(f"• {part}" for part in parts)


def build_combo_title(qty_3kg: int, qty_5kg: int) -> str:
    return f"3KG x {qty_3kg} | 5KG x {qty_5kg}"


def find_combined_quantity_option(option_id: str) -> Dict[str, int] | None:
    for option in COMBINED_QUANTITY_OPTIONS:
        if option["id"] == option_id:
            return {
                "qty_3kg": int(option["qty_3kg"]),
                "qty_5kg": int(option["qty_5kg"]),
            }
    return None


def build_bill_text(qty_3kg: int, qty_5kg: int) -> str:
    bill = calculate_order_bill(qty_3kg, qty_5kg)
    lines = [
        "Order Summary:",
        build_order_display_summary(qty_3kg, qty_5kg),
        f"Subtotal: {format_inr(bill['subtotal'])}",
    ]
    lines.append(f"Discount ({DISCOUNT_PERCENT}%): -{format_inr(bill['discount'])}")

    if bill["delivery_charge"]:
        lines.append(
            f"Delivery Charge: {format_inr(bill['delivery_charge'])} (free delivery on orders above {format_inr(DELIVERY_FREE_THRESHOLD)})"
        )
    else:
        lines.append("Delivery Charge: Free")

    lines.append(f"Total: {format_inr(bill['total'])}")
    return "\n".join(lines)


def build_cart_text(order: Dict[str, Any]) -> str:
    qty_3kg = int(order.get("qty_3kg", 0))
    qty_5kg = int(order.get("qty_5kg", 0))
    cart_lines = []

    if qty_3kg or qty_5kg:
        quantity_lines = []
        if qty_3kg:
            quantity_lines.append(f"3KG x {qty_3kg}")
        if qty_5kg:
            quantity_lines.append(f"5KG x {qty_5kg}")
        cart_lines.extend(
            [
                "Your cart is ready 🛒",
                "",
                *quantity_lines,
                "",
                build_bill_text(qty_3kg, qty_5kg),
            ]
        )
    else:
        cart_lines.extend(
            [
                "🛒 Your cart is empty",
                "",
                "Choose your favorite Mangoes and let’s make this order juicy 🚚✨",
            ]
        )

    cart_lines.extend(["", "Choose an option below 👇"])
    return "\n".join(cart_lines)


def build_box_quantity_title(box_size: str, quantity: int) -> str:
    return f"{box_size.upper()} x {quantity}"


message_history = load_message_history()
user_sessions = load_user_sessions()


def build_default_session() -> Dict[str, Any]:
    return {
        "step": "idle",
        "city": None,
        "city_code": None,
        "order": {},
        "selected_box": None,
        "cart_image_sent": False,
        "attempts": 0,
        "updated_at": utcnow().isoformat(timespec="seconds"),
    }


def get_or_create_session(user_phone: str) -> Dict[str, Any]:
    with session_lock:
        if user_phone not in user_sessions:
            user_sessions[user_phone] = build_default_session()
        return user_sessions[user_phone]


def is_session_stale(session: Dict[str, Any]) -> bool:
    if session.get("step", "idle") == "idle":
        return False

    updated_at = session.get("updated_at")
    if not updated_at:
        return True

    try:
        last_update = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return True

    return utcnow() - last_update > timedelta(minutes=SESSION_IDLE_RESET_MINUTES)


def reset_session(user_phone: str) -> None:
    with session_lock:
        user_sessions[user_phone] = build_default_session()
        save_user_sessions()


def ensure_worksheet_headers(worksheet) -> list[str]:
    headers = worksheet.row_values(1)
    if not headers:
        worksheet.append_row(WORKSHEET_HEADERS)
        return list(WORKSHEET_HEADERS)

    if worksheet.col_count < len(WORKSHEET_HEADERS):
        worksheet.add_cols(len(WORKSHEET_HEADERS) - worksheet.col_count)

    return list(WORKSHEET_HEADERS)


def build_row_record(headers: list[str], values: list[str]) -> Dict[str, str]:
    padded = values + [""] * max(0, len(headers) - len(values))
    return dict(zip(headers, padded))


def column_index_to_letter(index: int) -> str:
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def increment_attempts(user_phone: str) -> int:
    with session_lock:
        session = get_or_create_session(user_phone)
        session["attempts"] = session.get("attempts", 0) + 1
        session["updated_at"] = utcnow().isoformat(timespec="seconds")
        save_user_sessions()
        return session["attempts"]


def update_session(user_phone: str, **updates: Any) -> Dict[str, Any]:
    with session_lock:
        session = get_or_create_session(user_phone)
        session.update(updates)
        session["updated_at"] = utcnow().isoformat(timespec="seconds")
        save_user_sessions()
        return dict(session)


def load_spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = load_google_credentials(scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(GOOGLE_SHEET_ID) if GOOGLE_SHEET_ID else client.open(SHEET_NAME)


def load_worksheet(worksheet_name: str | None = None, *, create: bool = True):
    spreadsheet = load_spreadsheet()
    target_worksheet_name = worksheet_name or GOOGLE_WORKSHEET_NAME
    try:
        worksheet = spreadsheet.worksheet(target_worksheet_name)
    except gspread.WorksheetNotFound:
        if not create:
            raise
        worksheet = spreadsheet.add_worksheet(title=target_worksheet_name, rows=1000, cols=len(WORKSHEET_HEADERS))
    ensure_worksheet_headers(worksheet)
    return worksheet


def load_daily_orders_worksheet(date_text: str | None = None, worksheet_name: str | None = None):
    target_worksheet_name = resolve_orders_worksheet_name(date_text=date_text, worksheet_name=worksheet_name)
    spreadsheet = load_spreadsheet()
    return spreadsheet.worksheet(target_worksheet_name)


def ensure_confirmation_columns(worksheet) -> list[str]:
    headers = worksheet.row_values(1)
    if not headers:
        headers = list(WORKSHEET_HEADERS)

    updated_headers = list(headers)
    for required_header in CONFIRMATION_HEADERS:
        if required_header not in updated_headers:
            updated_headers.append(required_header)

    if worksheet.col_count < len(updated_headers):
        worksheet.add_cols(len(updated_headers) - worksheet.col_count)

    if updated_headers != headers:
        last_col = column_index_to_letter(len(updated_headers))
        worksheet.update(f"A1:{last_col}1", [updated_headers])

    return updated_headers


def count_existing_orders_for_today(city_code: str) -> int:
    worksheet = load_worksheet()
    today_prefix = f"PL{datetime.now().strftime('%d%m%y')}{city_code}"
    order_ids = worksheet.col_values(2)[1:]
    return sum(1 for order_id in order_ids if order_id.startswith(today_prefix))


def generate_order_id(city_code: str) -> str:
    today_key = datetime.now().strftime("%d%m%y")
    prefix = f"PL{today_key}{city_code}"
    existing_ids = set(load_worksheet().col_values(2)[1:])
    existing_suffixes = {existing_id[-4:] for existing_id in existing_ids if len(existing_id) >= 4}
    for _ in range(200):
        suffix = f"{random.randint(0, 9999):04d}"
        order_id = f"{prefix}{suffix}"
        if order_id not in existing_ids and suffix not in existing_suffixes:
            return order_id
    raise RuntimeError("Unable to generate a unique order id.")


def append_order_to_sheet(
    order_id: str,
    phone: str,
    city: str,
    address: str,
    *,
    customer_name: str = "",
    qty_3kg: int = 0,
    qty_5kg: int = 0,
    source: str = "whatsapp",
) -> None:
    worksheet = load_worksheet()
    headers = ensure_worksheet_headers(worksheet)
    delivery_slot = get_delivery_slot(city)
    order_summary = f"{build_order_summary(qty_3kg, qty_5kg)} | Total {format_inr(calculate_order_bill(qty_3kg, qty_5kg)['total'])}"
    row_by_header: Dict[str, Any] = {
        "Timestamp": datetime.now().isoformat(timespec="seconds"),
        "Order ID": order_id,
        "Customer Name": customer_name,
        "Phone": phone,
        "City": city,
        "Delivery Slot": delivery_slot,
        "Order Summary": order_summary,
        "3KG Qty": qty_3kg,
        "5KG Qty": qty_5kg,
        "Address": address,
        "Status": DEFAULT_ORDER_STATUS,
        "Source": source,
    }
    row = [row_by_header.get(header, "") for header in headers]
    worksheet.append_row(
        row,
        value_input_option="USER_ENTERED",
        insert_data_option="INSERT_ROWS",
        table_range=ORDER_TABLE_RANGE,
    )


def normalize_whatsapp_recipient(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits or value


def is_valid_whatsapp_recipient(value: str) -> bool:
    return bool(re.fullmatch(r"91[6-9]\d{9}", normalize_whatsapp_recipient(value)))


def get_record_value(record: Dict[str, str], field_name: str) -> str:
    normalized_record = {normalize_header(header): value for header, value in record.items()}
    for alias in ORDER_FIELD_ALIASES.get(field_name, (field_name,)):
        value = normalized_record.get(normalize_header(alias), "")
        if value:
            return str(value).strip()
    return ""


def get_record_int(record: Dict[str, str], field_name: str) -> int:
    value = get_record_value(record, field_name)
    if not value:
        return 0

    match = re.search(r"\d+", value)
    return int(match.group()) if match else 0


def build_sheet_order_summary(record: Dict[str, str]) -> str:
    order_summary = get_record_value(record, "order_summary")
    if order_summary:
        return order_summary

    qty_3kg = get_record_int(record, "qty_3kg")
    qty_5kg = get_record_int(record, "qty_5kg")
    return build_order_summary(qty_3kg, qty_5kg)


def get_sheet_delivery_slot(record: Dict[str, str]) -> str:
    delivery_slot = get_record_value(record, "delivery_slot")
    if delivery_slot:
        return delivery_slot

    city = get_record_value(record, "city")
    return get_delivery_slot(city) if city else "your selected delivery slot"


def build_sheet_order_confirmation_message(record: Dict[str, str]) -> str:
    order_id = get_record_value(record, "order_id")
    customer_name = get_record_value(record, "customer_name") or "Customer"
    phone = get_record_value(record, "phone")
    email = get_record_value(record, "email")
    address = get_record_value(record, "address")

    lines = [
        "🥭🎉 *Order Confirmed with Pulps & Leaves!*",
        "",
        f"Customer Name: {customer_name}",
        f"Mobile Number: {normalize_mobile_number(phone) or phone}",
        f"Email Id: {email or '-'}",
        f"Address: {address or '-'}",
        f"Order Number: *{order_id or '-'}*",
        "",
        "Thank you for choosing Pulps & Leaves! 🥭✨",
        "We’ve received your order and our team will keep you updated on WhatsApp.",
    ]
    return "\n".join(lines)


def build_sheet_confirmation_template_params(record: Dict[str, str]) -> list[str]:
    return [
        get_record_value(record, "customer_name") or "Customer",
        normalize_mobile_number(get_record_value(record, "phone")) or get_record_value(record, "phone") or "-",
        get_record_value(record, "email") or "-",
        get_record_value(record, "address") or "-",
        get_record_value(record, "order_id") or "-",
    ]


def find_order_row(order_id: str | None = None, last_four: str | None = None) -> tuple[int, Dict[str, str]] | tuple[None, None]:
    worksheet = load_worksheet()
    headers = ensure_worksheet_headers(worksheet)
    order_id_col = WORKSHEET_HEADERS.index("Order ID") + 1
    order_ids = worksheet.col_values(order_id_col)[1:]

    for offset, existing_order_id in enumerate(order_ids, start=2):
        if order_id and existing_order_id == order_id:
            return offset, build_row_record(headers, worksheet.row_values(offset))
        if last_four and existing_order_id.endswith(last_four):
            return offset, build_row_record(headers, worksheet.row_values(offset))
    return None, None


def build_tracking_status_message(order_id: str, status: str, city: str, delivery_slot: str) -> str:
    return (
        f"Track Your Aam 🔍\n\n"
        f"Order ID: *{order_id}*\n"
        f"Status: *{status or DEFAULT_ORDER_STATUS}*\n"
        f"City: {city}\n"
        f"Delivery Slot: {delivery_slot}"
    )


def build_tracking_details_message(record: Dict[str, str]) -> str:
    customer_name = record.get("Customer Name", "").strip() or "Customer"
    order_id = record.get("Order ID", "")
    status = record.get("Status", DEFAULT_ORDER_STATUS) or DEFAULT_ORDER_STATUS
    city = record.get("City", "")
    delivery_slot = record.get("Delivery Slot", "")
    order_summary = record.get("Order Summary", "")
    address = record.get("Address", "")

    lines = [
        f"Track Your Aam 🔍",
        "",
        f"Order ID: *{order_id}*",
        f"Customer Name: {customer_name}",
        f"Status: *{status}*",
        f"City: {city}",
        f"Delivery Slot: {delivery_slot}",
        f"Order Summary: {order_summary}",
        f"Shipping Address: {address}",
    ]
    return "\n".join(lines)


def validate_address_and_phone(user_message: str) -> bool:
    digits_only = re.sub(r"\D", "", user_message)
    address_text = re.sub(r"\+?\d[\d\s\-()]{7,}", "", user_message).strip()
    has_phone = len(digits_only) >= 10
    has_address = len(address_text) >= 10
    return has_phone and has_address


def validate_order_details(user_message: str) -> bool:
    digits_only = re.sub(r"\D", "", user_message)
    lowered = user_message.lower()
    lines = [line.strip() for line in user_message.splitlines() if line.strip()]

    has_phone = len(digits_only) >= 10
    has_box_size = "3kg" in lowered or "5kg" in lowered
    has_quantity = bool(re.search(r"[x×]\s*\d+|\bquantity\b|\b\d+\b", lowered))
    has_address = len(lines) >= 2 and any(
        token in lowered
        for token in ["road", "street", "nagar", "layout", "block", "sector", "lane", "apartment", "flat", "whitefield", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai"]
    )

    return has_phone and has_box_size and has_quantity and has_address


def extract_phone_number(user_message: str) -> str:
    phone_matches = re.findall(r"(?:\+91[\s\-]?)?[6-9]\d{9}", user_message)
    if phone_matches:
        phone = re.sub(r"\D", "", phone_matches[-1])
        return phone[-10:]

    digits_only = re.sub(r"\D", "", user_message)
    return digits_only[-10:]


def is_valid_indian_mobile_number(value: str) -> bool:
    return bool(re.fullmatch(r"(?:91)?[6-9]\d{9}", re.sub(r"\D", "", value or "")))


def normalize_mobile_number(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    return digits


def is_valid_address(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    has_enough_text = len(cleaned) >= 12
    has_letters = bool(re.search(r"[a-zA-Z]", cleaned))
    has_digits_or_comma = bool(re.search(r"\d|,", cleaned))
    return has_enough_text and has_letters and has_digits_or_comma


def extract_box_quantity(user_message: str, box_size: str) -> int:
    normalized_box_size = box_size.lower()

    for line in user_message.splitlines():
        normalized_line = normalize_text(line).replace("×", "x")
        if normalized_box_size not in normalized_line:
            continue

        quantity_match = re.search(r"(?:box\s*)?[x-]?\s*(\d+)\b", normalized_line)
        if quantity_match:
            return int(quantity_match.group(1))

    return 0


def extract_address(user_message: str) -> str:
    lines = [line.strip() for line in user_message.splitlines() if line.strip()]
    filtered_lines = [
        line
        for line in lines
        if not re.search(r"(?:\+91[\s\-]?)?[6-9]\d{9}", line)
    ]
    return filtered_lines[-1] if filtered_lines else user_message.strip()
def parse_quantity_selection(user_text: str) -> int | None:
    normalized = normalize_text(user_text)
    id_match = re.fullmatch(r"qty_(?:3kg|5kg)_(\d+)", normalized)
    if id_match:
        return int(id_match.group(1))

    multiplier_match = re.search(r"[x×]\s*([0-5])\b", normalized)
    if multiplier_match:
        return int(multiplier_match.group(1))

    digit_match = re.search(r"\b([0-5])\b", normalized)
    if digit_match:
        return int(digit_match.group(1))

    return None


def get_delivery_slot(city: str) -> str:
    if city in {"Bangalore", "Hyderabad"}:
        return "2nd - 5th June ’26"
    return "10th - 12th June ’26"


def find_city_option(user_text: str) -> Dict[str, str] | None:
    for city in CITY_OPTIONS.values():
        if user_text in city["aliases"]:
            return city
    return None


def build_order_confirmation_message(
    order_id: str,
    city: str,
    qty_3kg: int,
    qty_5kg: int,
    *,
    customer_name: str,
    phone: str,
    address: str,
) -> str:
    return (
        f"🥭🎉 *Woohoo!* Your order *{order_id}* is confirmed with *Pulps & Leaves* and will be delivered between *{get_delivery_slot(city)}* 🚚✨\n\n"
        f"{build_bill_text(qty_3kg, qty_5kg)}\n\n"
        f"Customer Name: {customer_name or 'Customer'}\n"
        f"Mobile Number: {phone}\n"
        f"Shipping Address: {address}\n\n"
        "Our team is busy picking, packing & protecting your mangoes from hungry staff 😄📦\n\n"
        "⚠ Warning: May cause happiness, mango fights & “bas ek aur” syndrome! 🥭❤️"
    )


def generate_sample_order_payload(city: str) -> Dict[str, Any]:
    locality = random.choice(SAMPLE_LOCALITIES[city])
    qty_3kg = random.randint(0, 3)
    qty_5kg = random.randint(0, 2)
    if qty_3kg == 0 and qty_5kg == 0:
        qty_3kg = 1

    phone = f"9{random.randint(100000000, 999999999)}"
    address = f"{locality}, {city}"
    summary_lines = []
    if qty_3kg:
        summary_lines.append(f"3KG Box × {qty_3kg}")
    if qty_5kg:
        summary_lines.append(f"5KG Box × {qty_5kg}")

    return {
        "phone": phone,
        "city": city,
        "qty_3kg": qty_3kg,
        "qty_5kg": qty_5kg,
        "address": address,
        "raw_message": "\n".join(summary_lines + ["", address, phone]),
    }


def seed_random_orders(count: int = 10) -> list[Dict[str, Any]]:
    generated_orders = []
    city_names = [city["name"] for city in CITY_OPTIONS.values()]

    for _ in range(count):
        payload = generate_sample_order_payload(random.choice(city_names))
        city_option = next(option for option in CITY_OPTIONS.values() if option["name"] == payload["city"])
        order_id = generate_order_id(city_option["code"])
        append_order_to_sheet(
            order_id,
            payload["phone"],
            payload["city"],
            payload["address"],
            qty_3kg=payload["qty_3kg"],
            qty_5kg=payload["qty_5kg"],
            source="seeded_random_order",
        )
        generated_orders.append(
            {
                "order_id": order_id,
                "city": payload["city"],
                "phone": payload["phone"],
                "address": payload["address"],
                "qty_3kg": payload["qty_3kg"],
                "qty_5kg": payload["qty_5kg"],
            }
        )

    return generated_orders


def send_whatsapp_text_message(recipient: str, body: str) -> Dict[str, Any]:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    logger.info("Sending WhatsApp text to %s: %s", recipient, body)

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        params=build_graph_api_params(),
        timeout=30,
    )
    if not response.ok:
        logger.error("WhatsApp send failed: %s", response.text)
        response.raise_for_status()

    return response.json()


def send_whatsapp_template_message(
    recipient: str,
    template_name: str,
    parameters: list[str],
    *,
    language_code: str = ORDER_CONFIRMATION_TEMPLATE_LANGUAGE,
) -> Dict[str, Any]:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(parameter)[:1024]} for parameter in parameters
                    ],
                }
            ],
        },
    }
    return send_whatsapp_payload(payload)


def send_whatsapp_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    logger.info("Sending WhatsApp payload: %s", json.dumps(payload))

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        params=build_graph_api_params(),
        timeout=30,
    )
    if not response.ok:
        logger.error("WhatsApp send failed: %s", response.text)
        response.raise_for_status()

    return response.json()


def upload_whatsapp_media(file_path: str) -> str:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")

    normalized_path = str(resolve_runtime_path(file_path))
    if normalized_path in uploaded_media_ids:
        return uploaded_media_ids[normalized_path]

    media_file = Path(normalized_path)
    if not media_file.exists():
        raise ConfigurationError(f"Cart image file not found at '{normalized_path}'.")

    mime_type = mimetypes.guess_type(media_file.name)[0] or "application/octet-stream"
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }

    with media_file.open("rb") as file_handle:
        files = {
            "file": (media_file.name, file_handle, mime_type),
        }
        data = {
            "messaging_product": "whatsapp",
        }
        response = requests.post(
            url,
            headers=headers,
            data=data,
            files=files,
            params=build_graph_api_params(),
            timeout=60,
        )

    if not response.ok:
        logger.error("WhatsApp media upload failed: %s", response.text)
        response.raise_for_status()

    media_id = response.json().get("id")
    if not media_id:
        raise ConfigurationError("WhatsApp media upload succeeded but no media id was returned.")

    uploaded_media_ids[normalized_path] = media_id
    return media_id


def send_whatsapp_image_message(recipient: str, file_path: str, *, caption: str | None = None) -> None:
    resolved_path = resolve_runtime_path(file_path)
    if not resolved_path.exists():
        logger.warning("Skipping image send because file was not found: %s", resolved_path)
        return

    media_id = upload_whatsapp_media(file_path)
    image_payload: Dict[str, Any] = {"id": media_id}
    if caption:
        image_payload["caption"] = caption
    send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "image",
            "image": image_payload,
        }
    )


def send_button_message(
    recipient: str,
    body: str,
    buttons: list[Dict[str, str]],
    *,
    header: str | None = None,
) -> None:
    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": button["id"],
                        "title": button["title"],
                    },
                }
                for button in buttons
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}

    send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive,
        }
    )


def send_list_message(
    recipient: str,
    body: str,
    button_text: str,
    rows: list[Dict[str, str]],
    *,
    header: str | None = None,
) -> None:
    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": button_text,
            "sections": [
                {
                    "title": "Choose one",
                    "rows": [
                        {
                            "id": row["id"],
                            "title": row["title"],
                            "description": row.get("description", ""),
                        }
                        for row in rows
                    ],
                }
            ],
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}

    send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive,
        }
    )


def send_main_menu(user_phone: str) -> None:
    send_button_message(
        user_phone,
        MESSAGES["welcome"],
        [
            {"id": "main_order", "title": "Order Malda Mangoes"},
            {"id": "main_track", "title": "Track Your Aam"},
            {"id": "main_support", "title": "Talk to Mango Agent"},
        ],
    )


def send_main_retry_menu(user_phone: str) -> None:
    update_session(
        user_phone,
        step="welcome_menu",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_button_message(
        user_phone,
        MESSAGES["invalid_main_menu"],
        [
            {"id": "main_order", "title": "Order Malda Mangoes"},
            {"id": "main_track", "title": "Track Your Aam"},
            {"id": "main_support", "title": "Talk to Mango Agent"},
        ],
    )


def send_tracking_prompt(user_phone: str) -> None:
    send_whatsapp_text_message(user_phone, MESSAGES["tracking_prompt"])


def send_city_picker(user_phone: str) -> None:
    send_list_message(
        user_phone,
        MESSAGES["city_selection"],
        "Choose city",
        [
            {"id": "city_blr", "title": "Bangalore", "description": "2nd - 4th June ’26"},
            {"id": "city_hyd", "title": "Hyderabad", "description": "2nd - 4th June ’26"},
            {"id": "city_pun", "title": "Pune", "description": "10th - 12th June ’26"},
            {"id": "city_mum", "title": "Mumbai", "description": "10th - 12th June ’26"},
        ],
    )


def send_continue_picker(user_phone: str) -> None:
    send_button_message(
        user_phone,
        MESSAGES["continue_order"],
        [
            {"id": "continue_yes", "title": "Place Order"},
            {"id": "continue_no", "title": "Exit for Now"},
        ],
    )


def send_cart_menu(user_phone: str, order: Dict[str, Any], *, include_image: bool = False) -> None:
    if include_image:
        send_whatsapp_image_message(user_phone, CART_IMAGE_PATH)
        send_whatsapp_text_message(user_phone, PRE_CART_PROMO_TEXT)

    send_button_message(
        user_phone,
        build_cart_text(order),
        [
            {"id": "cart_3kg", "title": "Set 3KG Qty"},
            {"id": "cart_5kg", "title": "Set 5KG Qty"},
            {"id": "cart_checkout", "title": "Checkout"},
        ],
        header="Build Your Cart",
    )


def send_box_quantity_picker(user_phone: str, box_size: str, order: Dict[str, Any]) -> None:
    current_qty = int(order.get(f"qty_{box_size}", 0))
    unit_price = PRICE_3KG_BOX if box_size == "3kg" else PRICE_5KG_BOX
    rows = []

    for quantity in range(0, 6):
        rows.append(
            {
                "id": f"qty_{box_size}_{quantity}",
                "title": build_box_quantity_title(box_size, quantity),
                "description": (
                    "Remove from cart"
                    if quantity == 0
                    else f"{format_inr(unit_price)} each"
                ),
            }
        )

    send_list_message(
        user_phone,
        (
            f"{box_size.upper()} Quantity\n\n"
            f"Select your preferred quantity.\n\n"
            f"Current quantity: {current_qty}\n"
            f"Price: {format_inr(unit_price)} each"
        ),
        "Select quantity",
        rows,
        header=f"{box_size.upper()} Quantity",
    )


def send_address_prompt(user_phone: str, order: Dict[str, Any]) -> None:
    qty_3kg = int(order.get("qty_3kg", 0))
    qty_5kg = int(order.get("qty_5kg", 0))
    send_whatsapp_text_message(
        user_phone,
        (
            "Shipping Address 📍\n\n"
            "Your order summary is ready.\n\n"
            f"{build_bill_text(qty_3kg, qty_5kg)}\n\n"
            "Please send your full delivery address in one message.\n\n"
            "Example:\n"
            "Flat 888, Prestige Lakeside, Whitefield, Bangalore"
        ),
    )


def send_name_prompt(user_phone: str) -> None:
    send_whatsapp_text_message(
        user_phone,
        (
            "Customer Name ✍️\n\n"
            "Please send the customer name for this order.\n\n"
            "Example:\n"
            "Atharv"
        ),
    )


def send_phone_prompt(user_phone: str) -> None:
    send_button_message(
        user_phone,
        (
            "Mobile Number 📱\n\n"
            "Please share the 10-digit mobile number for delivery updates.\n\n"
            "You can type it, or use the WhatsApp number if this chat number is correct."
        ),
        [
            {"id": "phone_use_whatsapp", "title": "Use WhatsApp No."},
            {"id": "phone_type", "title": "I'll Type It"},
        ],
    )


def send_invalid_retry_message(user_phone: str, session: Dict[str, Any]) -> None:
    attempts = increment_attempts(user_phone)
    current_step = session.get("step")

    if current_step in {"welcome_menu", "select_city"}:
        send_main_retry_menu(user_phone)
        return

    if attempts >= 3:
        reset_session(user_phone)
        send_whatsapp_text_message(user_phone, MESSAGES["human_support"])
        return

    if current_step == "continue_order":
        send_continue_picker(user_phone)
        return

    if current_step == "track_order_lookup":
        send_tracking_prompt(user_phone)
        return

    if current_step == "cart_menu":
        send_cart_menu(user_phone, dict(session.get("order") or {}))
        return

    if current_step == "select_box_quantity":
        selected_box = session.get("selected_box")
        if selected_box in {"3kg", "5kg"}:
            send_box_quantity_picker(user_phone, selected_box, dict(session.get("order") or {}))
            return
        send_cart_menu(user_phone, dict(session.get("order") or {}))
        return

    if current_step == "collect_address":
        send_whatsapp_text_message(
            user_phone,
            (
                "Shipping Address 📍\n\n"
                "Please send a fuller delivery address.\n\n"
                "Example:\n"
                "Flat 888, Prestige Lakeside, Whitefield, Bangalore"
            ),
        )
        return

    if current_step == "collect_name":
        send_name_prompt(user_phone)
        return

    if current_step == "collect_phone":
        send_phone_prompt(user_phone)
        return

    if current_step == "collect_order_details":
        send_whatsapp_text_message(user_phone, MESSAGES["invalid_order"])
        return

    send_whatsapp_text_message(user_phone, MESSAGES["fallback"])


def start_welcome_flow(user_phone: str) -> None:
    update_session(
        user_phone,
        step="welcome_menu",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_whatsapp_image_message(user_phone, WELCOME_IMAGE_PATH)
    send_main_menu(user_phone)


def send_order_redirect(user_phone: str, *, include_image: bool = True) -> None:
    reset_session(user_phone)
    if include_image:
        send_whatsapp_image_message(user_phone, CART_IMAGE_PATH)
    send_whatsapp_text_message(user_phone, MESSAGES["order_redirect"])


def start_city_flow(user_phone: str) -> None:
    update_session(
        user_phone,
        step="select_city",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_city_picker(user_phone)


def connect_to_human_support(user_phone: str) -> None:
    reset_session(user_phone)
    send_whatsapp_text_message(user_phone, MESSAGES["direct_support"])


def start_tracking_flow(user_phone: str) -> None:
    update_session(
        user_phone,
        step="track_order_lookup",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_tracking_prompt(user_phone)


def handle_track_order_lookup(user_phone: str, raw_text: str) -> None:
    last_four = re.sub(r"\D", "", raw_text or "")
    if len(last_four) != 4:
        send_whatsapp_text_message(user_phone, MESSAGES["tracking_invalid"])
        return

    _, record = find_order_row(last_four=last_four)
    if not record:
        send_whatsapp_text_message(user_phone, MESSAGES["tracking_not_found"])
        return

    reset_session(user_phone)
    send_whatsapp_text_message(user_phone, build_tracking_details_message(record))


def handle_welcome_menu(user_phone: str, user_text: str) -> None:
    if user_text == "main_order" or user_text == "1" or user_text in {
        "order",
        "order & pay online",
        "order and pay online",
        "order online",
        "pay online",
        "payment",
        "website",
        "order malda mangoes",
        "order mangoes",
        "order fresh mangoes",
    }:
        start_city_flow(user_phone)
        return

    if user_text == "main_track" or user_text == "2" or user_text in TRACKING_TRIGGER_TEXTS:
        start_tracking_flow(user_phone)
        return

    if user_text == "main_support" or user_text == "3" or user_text in HUMAN_SUPPORT_TRIGGER_TEXTS:
        connect_to_human_support(user_phone)
        return

    session = get_or_create_session(user_phone)
    send_invalid_retry_message(user_phone, session)


def handle_city_selection(user_phone: str, user_text: str) -> None:
    selected_city = find_city_option(user_text)
    if not selected_city:
        session = get_or_create_session(user_phone)
        send_invalid_retry_message(user_phone, session)
        return

    update_session(
        user_phone,
        step="select_city",
        city=selected_city["name"],
        city_code=selected_city["code"],
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_whatsapp_text_message(user_phone, selected_city["delivery_message"])
    send_order_redirect(user_phone, include_image=True)


def handle_continue_order(user_phone: str, user_text: str) -> None:
    if user_text in {"1", "continue_yes", "place order", "continue & place your order"}:
        order = {"qty_3kg": 0, "qty_5kg": 0}
        update_session(user_phone, step="cart_menu", order=order, selected_box=None, cart_image_sent=True, attempts=0)
        send_cart_menu(user_phone, order, include_image=True)
        return

    if user_text in {"2", "continue_no", "exit", "exit for now"}:
        reset_session(user_phone)
        send_whatsapp_text_message(user_phone, MESSAGES["exit"])
        return

    session = get_or_create_session(user_phone)
    send_invalid_retry_message(user_phone, session)


def handle_cart_menu(user_phone: str, raw_text: str) -> None:
    user_text = normalize_text(raw_text)
    session = get_or_create_session(user_phone)
    order = dict(session.get("order") or {})

    if user_text == "cart_3kg":
        update_session(user_phone, step="select_box_quantity", selected_box="3kg", attempts=0)
        send_box_quantity_picker(user_phone, "3kg", order)
        return

    if user_text == "cart_5kg":
        update_session(user_phone, step="select_box_quantity", selected_box="5kg", attempts=0)
        send_box_quantity_picker(user_phone, "5kg", order)
        return

    if user_text == "cart_checkout":
        qty_3kg = int(order.get("qty_3kg", 0))
        qty_5kg = int(order.get("qty_5kg", 0))
        if qty_3kg == 0 and qty_5kg == 0:
            send_whatsapp_text_message(user_phone, "Your cart is empty. Please set quantity for at least one box.")
            send_cart_menu(user_phone, order)
            return
        update_session(user_phone, step="collect_name", selected_box=None, attempts=0)
        send_name_prompt(user_phone)
        return

    send_invalid_retry_message(user_phone, session)


def handle_box_quantity_selection(user_phone: str, raw_text: str) -> None:
    user_text = normalize_text(raw_text)
    session = get_or_create_session(user_phone)
    selected_box = session.get("selected_box")
    order = dict(session.get("order") or {})

    quantity_match = re.fullmatch(r"qty_(3kg|5kg)_(\d+)", user_text)
    if not quantity_match:
        send_invalid_retry_message(user_phone, session)
        return

    box_size = quantity_match.group(1)
    quantity = int(quantity_match.group(2))
    if selected_box and box_size != selected_box:
        send_invalid_retry_message(user_phone, session)
        return

    order[f"qty_{box_size}"] = quantity
    update_session(user_phone, step="cart_menu", order=order, selected_box=None, attempts=0)
    send_cart_menu(user_phone, order)


def handle_name_step(user_phone: str, raw_text: str) -> None:
    cleaned_name = raw_text.strip()
    if len(cleaned_name) < 2 or re.search(r"\d", cleaned_name):
        send_invalid_retry_message(user_phone, get_or_create_session(user_phone))
        return

    session = get_or_create_session(user_phone)
    order = dict(session.get("order") or {})
    order["customer_name"] = cleaned_name
    update_session(user_phone, step="collect_address", order=order, attempts=0)
    send_address_prompt(user_phone, order)


def handle_address_step(user_phone: str, raw_text: str) -> None:
    if not is_valid_address(raw_text):
        send_invalid_retry_message(user_phone, get_or_create_session(user_phone))
        return

    session = get_or_create_session(user_phone)
    order = dict(session.get("order") or {})
    order["address"] = raw_text.strip()
    update_session(user_phone, step="collect_phone", order=order, attempts=0)
    send_phone_prompt(user_phone)


def handle_phone_step(user_phone: str, user_text: str) -> None:
    session = get_or_create_session(user_phone)
    order = dict(session.get("order") or {})
    normalized_text = normalize_text(user_text)

    if normalized_text in {"phone_type", "i'll type it", "ill type it", "type it"}:
        send_whatsapp_text_message(user_phone, "Please type the 10-digit mobile number.")
        return

    if normalized_text in {"phone_use_whatsapp", "use whatsapp no.", "use whatsapp no", "use whatsapp number", "use whatsapp"}:
        phone = normalize_mobile_number(user_phone)
    else:
        phone = normalize_mobile_number(user_text)

    if not is_valid_indian_mobile_number(phone):
        send_invalid_retry_message(user_phone, session)
        return

    city = session.get("city")
    city_code = session.get("city_code")
    if not city or not city_code:
        reset_session(user_phone)
        send_whatsapp_text_message(
            user_phone,
            "Your session expired. Please reply hi to start again.",
        )
        return

    order_id = generate_order_id(city_code)
    append_order_to_sheet(
        order_id,
        phone,
        city,
        order["address"],
        customer_name=str(order.get("customer_name", "")),
        qty_3kg=int(order.get("qty_3kg", 0)),
        qty_5kg=int(order.get("qty_5kg", 0)),
    )
    qty_3kg = int(order.get("qty_3kg", 0))
    qty_5kg = int(order.get("qty_5kg", 0))
    customer_name = str(order.get("customer_name", ""))
    shipping_address = str(order.get("address", ""))
    reset_session(user_phone)
    send_whatsapp_text_message(
        user_phone,
        build_order_confirmation_message(
            order_id,
            city,
            qty_3kg,
            qty_5kg,
            customer_name=customer_name,
            phone=phone,
            address=shipping_address,
        ),
    )


def handle_address_collection(user_phone: str, user_text: str) -> None:
    session = get_or_create_session(user_phone)
    if not validate_order_details(user_text):
        send_invalid_retry_message(user_phone, session)
        return

    city = session.get("city")
    city_code = session.get("city_code")
    if not city or not city_code:
        reset_session(user_phone)
        send_whatsapp_text_message(
            user_phone,
            "Your session expired. Please reply with 1 or Order Mangoes to start again.",
        )
        return

    order_id = generate_order_id(city_code)
    qty_3kg = extract_box_quantity(user_text, "3kg")
    qty_5kg = extract_box_quantity(user_text, "5kg")
    address = extract_address(user_text)
    contact_number = extract_phone_number(user_text)
    append_order_to_sheet(
        order_id,
        contact_number or user_phone,
        city,
        address,
        qty_3kg=qty_3kg,
        qty_5kg=qty_5kg,
    )
    reset_session(user_phone)
    send_whatsapp_text_message(
        user_phone,
        build_order_confirmation_message(
            order_id,
            city,
            qty_3kg,
            qty_5kg,
            customer_name="",
            phone=contact_number or user_phone,
            address=address,
        ),
    )


def extract_message_text(message: Dict[str, Any]) -> str:
    message_type = message.get("type")

    if message_type == "text":
        return message.get("text", {}).get("body", "")

    if message_type == "button":
        return message.get("button", {}).get("text", "")

    if message_type == "interactive":
        interactive = message.get("interactive", {})
        button_reply = interactive.get("button_reply", {})
        list_reply = interactive.get("list_reply", {})
        return (
            button_reply.get("id")
            or list_reply.get("id")
            or button_reply.get("title")
            or list_reply.get("title")
            or ""
        )

    return ""


def process_user_message(user_phone: str, raw_text: str) -> None:
    user_text = normalize_text(raw_text)
    session = get_or_create_session(user_phone)
    current_step = session.get("step", "idle")

    if is_session_stale(session):
        start_welcome_flow(user_phone)
        return

    if user_text in {"hi", "hello", "hey", "start", "restart"}:
        start_welcome_flow(user_phone)
        return

    if current_step == "idle" and user_text not in HUMAN_SUPPORT_TRIGGER_TEXTS and user_text not in TRACKING_TRIGGER_TEXTS and user_text not in WELCOME_TRIGGER_TEXTS:
        start_welcome_flow(user_phone)
        return

    if current_step == "welcome_menu":
        handle_welcome_menu(user_phone, user_text)
        return

    if current_step == "select_city":
        handle_city_selection(user_phone, user_text)
        return

    if current_step == "track_order_lookup":
        handle_track_order_lookup(user_phone, raw_text.strip())
        return

    if current_step in WHATSAPP_ORDER_STEPS:
        send_order_redirect(user_phone)
        return

    if user_text in HUMAN_SUPPORT_TRIGGER_TEXTS:
        connect_to_human_support(user_phone)
        return

    if user_text in TRACKING_TRIGGER_TEXTS:
        start_tracking_flow(user_phone)
        return

    if user_text in WELCOME_TRIGGER_TEXTS:
        if user_text in {
            "1",
            "order",
            "order & pay online",
            "order and pay online",
            "order online",
            "pay online",
            "payment",
            "website",
            "order malda mangoes",
            "order mangoes",
            "order fresh mangoes",
        }:
            start_city_flow(user_phone)
        elif user_text in TRACKING_TRIGGER_TEXTS:
            start_tracking_flow(user_phone)
        elif user_text in HUMAN_SUPPORT_TRIGGER_TEXTS:
            connect_to_human_support(user_phone)
        else:
            start_welcome_flow(user_phone)
        return

    send_whatsapp_text_message(user_phone, MESSAGES["fallback"])


def extract_whatsapp_message_id(response_json: Dict[str, Any]) -> str:
    messages = response_json.get("messages") or []
    if messages and isinstance(messages[0], dict):
        return str(messages[0].get("id", ""))
    return ""


def get_outbound_request_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return (
        request.headers.get("X-Automation-Token", "")
        or request.args.get("token", "")
        or request.form.get("token", "")
    ).strip()


def authorize_outbound_request() -> tuple[bool, str]:
    if not OUTBOUND_CONFIRMATION_SECRET:
        return False, "OUTBOUND_CONFIRMATION_SECRET is not configured."

    request_token = get_outbound_request_token()
    if hmac.compare_digest(request_token, OUTBOUND_CONFIRMATION_SECRET):
        return True, ""

    return False, "Unauthorized."


def update_confirmation_result(
    worksheet,
    row_number: int,
    headers: list[str],
    *,
    status: str,
    message_id: str = "",
    error: str = "",
) -> None:
    updates = {
        CONFIRMATION_STATUS_HEADER: status,
        CONFIRMATION_SENT_AT_HEADER: local_now().isoformat(timespec="seconds") if status == "Sent" else "",
        CONFIRMATION_MESSAGE_ID_HEADER: message_id,
        CONFIRMATION_ERROR_HEADER: error[:500],
    }

    for header, value in updates.items():
        col_number = headers.index(header) + 1
        worksheet.update_cell(row_number, col_number, value)


def row_already_confirmed(record: Dict[str, str]) -> bool:
    status = (record.get(CONFIRMATION_STATUS_HEADER, "") or "").strip().lower()
    sent_at = (record.get(CONFIRMATION_SENT_AT_HEADER, "") or "").strip()
    return status == "sent" or bool(sent_at)


def send_order_confirmation_for_record(recipient: str, record: Dict[str, str]) -> Dict[str, Any]:
    if ORDER_CONFIRMATION_TEMPLATE_NAME:
        return send_whatsapp_template_message(
            recipient,
            ORDER_CONFIRMATION_TEMPLATE_NAME,
            build_sheet_confirmation_template_params(record),
        )

    return send_whatsapp_text_message(recipient, build_sheet_order_confirmation_message(record))


def send_pending_order_confirmations(
    *,
    date_text: str | None = None,
    worksheet_name: str | None = None,
    limit: int = 25,
    dry_run: bool = False,
) -> Dict[str, Any]:
    worksheet = load_daily_orders_worksheet(date_text=date_text, worksheet_name=worksheet_name)
    headers = ensure_confirmation_columns(worksheet)
    rows = worksheet.get_all_values()[1:]

    result: Dict[str, Any] = {
        "worksheet": worksheet.title,
        "dry_run": dry_run,
        "sent": [],
        "failed": [],
        "skipped": [],
    }
    attempted_count = 0

    for row_number, row_values in enumerate(rows, start=2):
        record = build_row_record(headers, row_values)
        order_id = get_record_value(record, "order_id")
        phone = get_record_value(record, "phone")

        if not any(str(value).strip() for value in row_values):
            continue

        if row_already_confirmed(record):
            result["skipped"].append({"row": row_number, "order_id": order_id, "reason": "already_sent"})
            continue

        if not phone:
            error = "Missing phone number."
            result["failed"].append({"row": row_number, "order_id": order_id, "error": error})
            if not dry_run:
                update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
            continue

        recipient = normalize_whatsapp_recipient(phone)
        if not is_valid_whatsapp_recipient(recipient):
            error = f"Invalid WhatsApp recipient: {phone}"
            result["failed"].append({"row": row_number, "order_id": order_id, "error": error})
            if not dry_run:
                update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
            continue

        if attempted_count >= limit:
            result["skipped"].append({"row": row_number, "order_id": order_id, "reason": "limit_reached"})
            continue

        attempted_count += 1
        if dry_run:
            result["sent"].append({"row": row_number, "order_id": order_id, "recipient": recipient, "dry_run": True})
            continue

        try:
            update_confirmation_result(worksheet, row_number, headers, status="Sending")
            response_json = send_order_confirmation_for_record(recipient, record)
            message_id = extract_whatsapp_message_id(response_json)
            update_confirmation_result(
                worksheet,
                row_number,
                headers,
                status="Sent",
                message_id=message_id,
            )
            result["sent"].append(
                {
                    "row": row_number,
                    "order_id": order_id,
                    "recipient": recipient,
                    "message_id": message_id,
                }
            )
        except Exception as exc:
            error = str(exc)
            logger.exception("Failed to send outbound order confirmation for row %s: %s", row_number, exc)
            update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
            result["failed"].append({"row": row_number, "order_id": order_id, "recipient": recipient, "error": error})

    result["sent_count"] = len(result["sent"])
    result["failed_count"] = len(result["failed"])
    result["skipped_count"] = len(result["skipped"])
    return result


def extract_whatsapp_messages(payload: Dict[str, Any]):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                yield message


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"}), 200


@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return jsonify({"error": "Verification failed"}), 403


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    logger.info("Incoming webhook payload: %s", json.dumps(payload))

    try:
        for message in extract_whatsapp_messages(payload):
            user_phone = message.get("from")
            message_text = extract_message_text(message)
            message_id = message.get("id", "")

            if not user_phone or not message_text:
                logger.info("Skipping unsupported or empty message payload.")
                continue

            if is_duplicate_processed_message(message_id):
                logger.info("Skipping duplicate WhatsApp message id=%s", message_id)
                continue

            process_user_message(user_phone, message_text)
            mark_message_processed(message_id)
    except ConfigurationError as exc:
        logger.exception("Configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except requests.RequestException as exc:
        logger.exception("WhatsApp API error: %s", exc)
        return jsonify({"error": "Failed to send WhatsApp message"}), 502
    except Exception as exc:
        logger.exception("Unexpected error while processing webhook: %s", exc)
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({"status": "received"}), 200


@app.post("/send-order-confirmations")
def send_order_confirmations_endpoint():
    authorized, auth_error = authorize_outbound_request()
    if not authorized:
        status_code = 500 if "configured" in auth_error else 401
        return jsonify({"error": auth_error}), status_code

    try:
        requested_limit = int(request.args.get("limit", "25"))
        limit = max(1, min(requested_limit, 200))
    except ValueError:
        return jsonify({"error": "Invalid limit. Use a number between 1 and 200."}), 400

    dry_run = normalize_text(request.args.get("dry_run", "")) in {"1", "true", "yes"}
    date_text = request.args.get("date")
    worksheet_name = request.args.get("worksheet")

    try:
        result = send_pending_order_confirmations(
            date_text=date_text,
            worksheet_name=worksheet_name,
            limit=limit,
            dry_run=dry_run,
        )
    except ValueError:
        return jsonify({"error": "Invalid date. Use YYYY-MM-DD, for example 2026-05-14."}), 400
    except gspread.WorksheetNotFound:
        target_worksheet_name = resolve_orders_worksheet_name(date_text=date_text, worksheet_name=worksheet_name)
        return jsonify({"error": f"Worksheet '{target_worksheet_name}' was not found."}), 404
    except ConfigurationError as exc:
        logger.exception("Configuration error while sending order confirmations: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.exception("Unexpected error while sending order confirmations: %s", exc)
        return jsonify({"error": "Failed to send order confirmations"}), 500

    return jsonify(result), 200


@app.post("/seed-orders")
def seed_orders():
    requested_count = request.args.get("count", "10")

    try:
        count = max(1, min(int(requested_count), 100))
    except ValueError:
        return jsonify({"error": "Invalid count. Use a number between 1 and 100."}), 400

    try:
        generated_orders = seed_random_orders(count)
    except ConfigurationError as exc:
        logger.exception("Configuration error while seeding orders: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.exception("Unexpected error while seeding orders: %s", exc)
        return jsonify({"error": "Failed to seed random orders"}), 500

    return jsonify({"seeded": len(generated_orders), "orders": generated_orders}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
