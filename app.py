import json
import logging
import mimetypes
import os
import random
import re
import hmac
import hashlib
import ast
import time
import tempfile
from queue import Full, Queue
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Dict
from urllib.parse import quote
from zoneinfo import ZoneInfo

import gspread
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from google.oauth2.service_account import Credentials
from werkzeug.utils import secure_filename

from order_system.config import ConfigurationError as OrderSystemConfigurationError
from order_system.models import is_offline_order_email
from order_system.routes import order_blueprint
from order_system.services import OrderService, sync_whatsapp_statuses_from_webhook

load_dotenv()

app = Flask(__name__)
app.register_blueprint(order_blueprint)
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
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "orders")
GOOGLE_DAILY_WORKSHEET_PREFIX = os.getenv("GOOGLE_DAILY_WORKSHEET_PREFIX", "orders")
WHATSAPP_CONTACTS_WORKSHEET_NAME = os.getenv("WHATSAPP_CONTACTS_WORKSHEET_NAME", "WhatsApp Contacts")
WHATSAPP_CONVERSATIONS_WORKSHEET_NAME = os.getenv("WHATSAPP_CONVERSATIONS_WORKSHEET_NAME", "WhatsApp Conversations")
DEFAULT_SUPABASE_URL = "https://hotvabriczbokrcpvmzo.supabase.co"
configured_supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_URL = DEFAULT_SUPABASE_URL if "your_project_ref" in configured_supabase_url.lower() else configured_supabase_url
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_CHAT_ENABLED = os.getenv("SUPABASE_CHAT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
SUPABASE_CONTACTS_TABLE = os.getenv("SUPABASE_CONTACTS_TABLE", "whatsapp_contacts").strip() or "whatsapp_contacts"
SUPABASE_MESSAGES_TABLE = os.getenv("SUPABASE_MESSAGES_TABLE", "whatsapp_messages").strip() or "whatsapp_messages"
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "Asia/Kolkata")
OUTBOUND_CONFIRMATION_SECRET = os.getenv("OUTBOUND_CONFIRMATION_SECRET", VERIFY_TOKEN).strip()
ORDER_CONFIRMATION_TEMPLATE_NAME = os.getenv("ORDER_CONFIRMATION_TEMPLATE_NAME", "order_confirmation").strip() or "order_confirmation"
ORDER_CONFIRMATION_TEMPLATE_LANGUAGE = os.getenv("ORDER_CONFIRMATION_TEMPLATE_LANGUAGE", "en").strip() or "en"
OFFLINE_ORDER_TEMPLATE_NAME = os.getenv("OFFLINE_ORDER_TEMPLATE_NAME", "offline_orders").strip() or "offline_orders"
OFFLINE_ORDER_TEMPLATE_LANGUAGE = os.getenv("OFFLINE_ORDER_TEMPLATE_LANGUAGE", "en").strip() or "en"
OFFLINE_ORDER_HEADER_IMAGE_ID = os.getenv("OFFLINE_ORDER_HEADER_IMAGE_ID", "").strip()
OFFLINE_ORDER_HEADER_IMAGE_URL = os.getenv("OFFLINE_ORDER_HEADER_IMAGE_URL", "").strip()
OFFLINE_ORDER_HEADER_IMAGE_PATH = os.getenv("OFFLINE_ORDER_HEADER_IMAGE_PATH", "assets/order_delivered_header.png").strip()
ORDER_DELIVERED_TEMPLATE_NAME = os.getenv("ORDER_DELIVERED_TEMPLATE_NAME", "order_delivered").strip() or "order_delivered"
ORDER_DELIVERED_TEMPLATE_LANGUAGE = os.getenv("ORDER_DELIVERED_TEMPLATE_LANGUAGE", "en").strip() or "en"
ORDER_DELIVERED_HEADER_IMAGE_ID = os.getenv("ORDER_DELIVERED_HEADER_IMAGE_ID", "").strip()
ORDER_DELIVERED_HEADER_IMAGE_URL = os.getenv("ORDER_DELIVERED_HEADER_IMAGE_URL", "").strip()
ORDER_DELIVERED_HEADER_IMAGE_PATH = os.getenv("ORDER_DELIVERED_HEADER_IMAGE_PATH", "assets/order_delivered_header.png").strip()
INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "https://www.instagram.com/pulpsandleaves/").strip()
GOOGLE_REVIEW_URL = os.getenv("GOOGLE_REVIEW_URL", "https://share.google/KhAJGKpBrOquiVtaE").strip()
BULK_MESSAGE_TEMPLATE_NAME = os.getenv("BULK_MESSAGE_TEMPLATE_NAME", "say_hi").strip() or "say_hi"
BULK_MESSAGE_TEMPLATE_LANGUAGE = os.getenv("BULK_MESSAGE_TEMPLATE_LANGUAGE", "en_US").strip() or "en_US"
SUPPORT_NUMBER = os.getenv("SUPPORT_NUMBER", "919835496666")
DEFAULT_ORDER_STATUS = os.getenv("DEFAULT_ORDER_STATUS", "Order Confirmed")
PRICE_3KG_BOX = int(os.getenv("PRICE_3KG_BOX", "599"))
PRICE_5KG_BOX = int(os.getenv("PRICE_5KG_BOX", "999"))
WHATSAPP_FLOW_3KG_BOX_PRICE = int(os.getenv("WHATSAPP_FLOW_3KG_BOX_PRICE", "569"))
DISCOUNT_PERCENT = int(os.getenv("DISCOUNT_PERCENT", "10"))
DISCOUNT_THRESHOLD = int(os.getenv("DISCOUNT_THRESHOLD", "0"))
DELIVERY_CHARGE_BELOW_THRESHOLD = int(os.getenv("DELIVERY_CHARGE_BELOW_THRESHOLD", "30"))
DELIVERY_FREE_THRESHOLD = int(os.getenv("DELIVERY_FREE_THRESHOLD", "599"))
MESSAGE_REPEAT_COOLDOWN_DAYS = int(os.getenv("MESSAGE_REPEAT_COOLDOWN_DAYS", "10"))
MESSAGE_HISTORY_FILE = os.getenv("MESSAGE_HISTORY_FILE", "message_history.json")
SESSION_STORE_FILE = os.getenv("SESSION_STORE_FILE", "/tmp/user_sessions.json")
SESSION_IDLE_RESET_MINUTES = int(os.getenv("SESSION_IDLE_RESET_MINUTES", "30"))
HUMAN_CHAT_IDLE_MINUTES = int(os.getenv("HUMAN_CHAT_IDLE_MINUTES", str(24 * 60)))
BASE_DIR = Path(__file__).resolve().parent
CART_IMAGE_PATH = os.getenv("CART_IMAGE_PATH", "assets/main.png")
WELCOME_IMAGE_PATH = os.getenv("WELCOME_IMAGE_PATH", "assets/welcome_template.png")
ORDER_WEBSITE_URL = os.getenv("ORDER_WEBSITE_URL", "https://pulpsandleaves.com/")
AUTO_CONFIRMATIONS_ENABLED = os.getenv("AUTO_CONFIRMATIONS_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
AUTO_CONFIRMATIONS_INTERVAL_SECONDS = max(60, int(os.getenv("AUTO_CONFIRMATIONS_INTERVAL_SECONDS", "300")))
SHEETS_RATE_LIMIT_BACKOFF_SECONDS = max(120, int(os.getenv("SHEETS_RATE_LIMIT_BACKOFF_SECONDS", "300")))
AUTO_CONFIRMATION_BATCH_LIMIT = max(1, int(os.getenv("AUTO_CONFIRMATION_BATCH_LIMIT", "3")))
AUTO_STATUS_UPDATE_BATCH_LIMIT = max(1, int(os.getenv("AUTO_STATUS_UPDATE_BATCH_LIMIT", "5")))
AUTO_CUSTOM_MESSAGE_BATCH_LIMIT = max(1, int(os.getenv("AUTO_CUSTOM_MESSAGE_BATCH_LIMIT", "5")))
WEBHOOK_QUEUE_MAX_SIZE = max(10, int(os.getenv("WEBHOOK_QUEUE_MAX_SIZE", "200")))
GOOGLE_CHAT_SUMMARY_QUEUE_MAX_SIZE = max(10, int(os.getenv("GOOGLE_CHAT_SUMMARY_QUEUE_MAX_SIZE", "500")))
CHAT_CONTACT_CACHE_SECONDS = max(60, int(os.getenv("CHAT_CONTACT_CACHE_SECONDS", "60")))
CHAT_MESSAGE_CACHE_SECONDS = max(15, int(os.getenv("CHAT_MESSAGE_CACHE_SECONDS", "15")))
SUPABASE_CHAT_CONTACT_CACHE_SECONDS = max(1, int(os.getenv("SUPABASE_CHAT_CONTACT_CACHE_SECONDS", "5")))
SUPABASE_CHAT_MESSAGE_CACHE_SECONDS = max(1, int(os.getenv("SUPABASE_CHAT_MESSAGE_CACHE_SECONDS", "3")))
SUPABASE_CHAT_CONTACT_BACKFILL_SECONDS = max(60, int(os.getenv("SUPABASE_CHAT_CONTACT_BACKFILL_SECONDS", "900")))
RECENT_INBOUND_CHAT_TTL_SECONDS = max(3600, int(os.getenv("RECENT_INBOUND_CHAT_TTL_SECONDS", str(24 * 60 * 60))))
ORDER_CHAT_CACHE_SECONDS = max(300, int(os.getenv("ORDER_CHAT_CACHE_SECONDS", "300")))
OPERATOR_MEDIA_UPLOAD_MAX_BYTES = max(
    1_000_000,
    int(
        os.getenv(
            "OPERATOR_MEDIA_UPLOAD_MAX_BYTES",
            os.getenv("OPERATOR_IMAGE_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024)),
        )
    ),
)

uploaded_media_ids: Dict[str, str] = {}
applied_checkbox_validations: set[str] = set()
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
WHATSAPP_CONTACT_HEADERS = [
    "Phone Number",
    "Profile Name",
    "First Message At",
    "First Enquiry Text",
    "Last Message At",
    "Last Message Direction",
    "Message Count",
    "Last Message Text",
    "Last Message Type",
    "Last Message ID",
    "Conversation Gist",
    "Enquiry Status",
    "Source",
]
WHATSAPP_CONVERSATION_HEADERS = [
    "Timestamp",
    "Phone Number",
    "Direction",
    "Message Type",
    "Message Text",
    "Message ID",
    "Status",
    "Agent",
    "Template Name",
    "Source",
    "Media ID",
    "Media Mime Type",
    "Media Filename",
]
ORDER_TABLE_RANGE = "A:L"
CONFIRMATION_STATUS_HEADER = "WhatsApp Confirmation Status"
CONFIRMATION_SENT_AT_HEADER = "WhatsApp Confirmation Sent At"
CONFIRMATION_MESSAGE_ID_HEADER = "WhatsApp Confirmation Message ID"
CONFIRMATION_ERROR_HEADER = "WhatsApp Confirmation Error"
CUSTOM_MESSAGE_HEADER = "Custom WhatsApp Message"
CUSTOM_MESSAGE_TRIGGER_HEADER = "Send Custom Message"
CUSTOM_MESSAGE_STATUS_HEADER = "Custom Message Status"
CUSTOM_MESSAGE_SENT_AT_HEADER = "Custom Message Sent At"
CUSTOM_MESSAGE_ERROR_HEADER = "Custom Message Error"
CONFIRMATION_HEADERS = [
    CONFIRMATION_STATUS_HEADER,
    CONFIRMATION_SENT_AT_HEADER,
    CONFIRMATION_MESSAGE_ID_HEADER,
    CONFIRMATION_ERROR_HEADER,
    "Confirmed",
    "Packed",
    "Delivered",
    "Cancelled",
    CUSTOM_MESSAGE_HEADER,
    CUSTOM_MESSAGE_TRIGGER_HEADER,
    CUSTOM_MESSAGE_STATUS_HEADER,
    CUSTOM_MESSAGE_SENT_AT_HEADER,
    CUSTOM_MESSAGE_ERROR_HEADER,
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
    "product": ("Product", "Product Name", "Order Summary", "Items", "Products"),
    "total_amount": ("Total Amount", "Total", "Amount", "Order Total"),
    "address": ("Address", "Delivery Address", "Shipping Address"),
    "payment": ("Payment Method", "Payment Mode", "Payment", "Payment Type"),
    "status": ("Status", "Order Status"),
    "qty_3kg": ("3KG Qty", "3kg Qty", "3KG Quantity", "Qty 3KG"),
    "qty_5kg": ("5KG Qty", "5kg Qty", "5KG Quantity", "Qty 5KG"),
}
STATUS_UPDATE_STEPS = [
    {
        "key": "confirmed",
        "label": "Confirmed",
        "headers": ("Confirmed",),
        "message": "Your Pulps & Leaves order has been confirmed.",
    },
    {
        "key": "packed",
        "label": "Packed",
        "headers": ("Packed",),
        "message": "Your mangoes have been packed and are getting ready for dispatch.",
    },
    {
        "key": "delivered",
        "label": "Delivered",
        "headers": ("Delivered",),
        "message": "Your order has been marked as delivered. We hope you enjoy the mangoes.",
    },
    {
        "key": "cancelled",
        "label": "Cancelled",
        "headers": ("Cancelled", "Canceled"),
        "message": "Your order has been marked as cancelled. Please reply here if you need help.",
    },
]
PRE_CART_PROMO_TEXT = (
    "🛒 Your cart is feeling lonely… add some mango magic to it 🥭😄\n\n"
    "Choose your favorite Mangoes and let’s make this order juicy 🚚✨\n\n"
    "https://pulpsandleaves.com/"
)

MESSAGES = {
    "welcome": (
        "We are Currently offering fresh, premium-quality Malda Mangoes directly sourced from farms !!\n"
        "How may we assist you today?"
    ),
    "invalid_main_menu": (
        "Kindly Choose the Relevant Option -\n\n"
        "1️⃣ - Order Malda Mangoes 🥭🚚\n"
        "2️⃣ - Track Your Aam 🔍\n"
        "3️⃣ - Talk To A Mango Agent 💬"
    ),
    "order_redirect": (
        "🛒 Your cart is feeling lonely… add some mango magic to it 🥭😄\n\n"
        "Choose your favorite Mangoes and let’s make this order juicy 🚚✨"
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
        "1️⃣ - Continue & Place New Order 🚚✨\n"
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
        "Allow us a moment, will connect you to a Real Human Before the Mangoes Take Over👨‍💼😂"
    ),
    "support_busy": (
        "🥭 Our team is currently busy serving fresh aam orders!\n"
        "Please call us at +91 9835496666 between 9 AM – 8 PM, and we’ll take care of your query right away."
    ),
    "tracking_prompt": (
        "Track Your Aam 🔍\n"
        "Where are your mangoes? 🥭👀\n"
        "Let’s find them!\n\n"
        "Send the last 4 characters of your Order ID 🔢\n"
        "Ex: P435 or 4821"
    ),
    "tracking_invalid": (
        "Track Your Aam 🔍\n\n"
        "Please send exactly 4 characters from your Order ID.\n\n"
        "Example: P435 or 4821"
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
GLOBAL_ORDER_TRIGGER_TEXTS = {
    "main_order",
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
}
GLOBAL_TRACKING_TRIGGER_TEXTS = (TRACKING_TRIGGER_TEXTS | {"main_track"}) - {"2"}
GLOBAL_SUPPORT_TRIGGER_TEXTS = (HUMAN_SUPPORT_TRIGGER_TEXTS | {"main_support"}) - {"3"}
CITY_OPTIONS = {
    "1": {
        "name": "Bangalore",
        "code": "BLR",
        "image_path": "assets/city-bangalore.png",
        "aliases": {"1", "bangalore", "bengaluru", "city_blr"},
        "delivery_message": (
            "📦🥭 Good news, Namma Bengaluru !!\n\n"
            "Your next mango delivery slot is scheduled between *10th – 14th June ’26* 🚚✨\n\n"
            "Our mangoes are already warming up for their Bengaluru trip 🌦️🥭—planning a chill walk in Cubbon Park and cheering for RCB on the way 😄🏏"
        ),
    },
    "2": {
        "name": "Hyderabad",
        "code": "HYD",
        "image_path": "assets/city-hyderabad.png",
        "aliases": {"2", "hyderabad", "hyd", "city_hyd"},
        "delivery_message": (
            "📦🥭 Hello Hyderabad!\n\n"
            "Your next mango delivery slot is scheduled between *10th – 14th June ’26* 🚚✨\n\n"
            "Our mangoes are crossing the lanes of Charminar with full Hyderabadi swag and can’t wait to reach your doorstep 🕌🍗🥭😄"
        ),
    },
    "3": {
        "name": "Pune",
        "code": "PUN",
        "image_path": "assets/city-pune.png",
        "aliases": {"3", "pune", "city_pun"},
        "delivery_message": (
            "📦🥭 Hey Pune!\n\n"
            "Your mango delivery is arriving between 10th – 14th June ’26 🚚✨\n"
            "Our mangoes are cruising through Maharashtra with full Puneri swag – stopped for misal pav, judging traffic, and saying\n"
            "“काय मग, पुणे… थांबा जरा!” ☕🥭\n"
            "Don’t worry, they’ll reach before you lose patience 😄\n"
            "Get ready… sweetness is loading! ⏳🥭"
        ),
    },
    "4": {
        "name": "Mumbai",
        "code": "MUM",
        "image_path": "assets/city-mumbai.png",
        "aliases": {"4", "mumbai", "bombay", "city_mum"},
        "delivery_message": (
            "📦🥭 Hello Mumbai!\n\n"
            "Your next mango delivery slot is scheduled between *10th – 14th June ’26* 🚚✨\n\n"
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
chat_cache_lock = RLock()
confirmation_worker_lock = RLock()
confirmation_worker_thread: Thread | None = None
confirmation_worker_stop = Event()
webhook_worker_lock = RLock()
webhook_worker_thread: Thread | None = None
webhook_processing_queue: Queue[Dict[str, Any]] = Queue(maxsize=WEBHOOK_QUEUE_MAX_SIZE)
google_chat_summary_worker_lock = RLock()
google_chat_summary_worker_thread: Thread | None = None
google_chat_summary_queue: Queue[Dict[str, Any]] = Queue(maxsize=GOOGLE_CHAT_SUMMARY_QUEUE_MAX_SIZE)
chat_contacts_cache: Dict[str, Any] = {"expires_at": 0.0, "contacts": []}
chat_messages_cache: Dict[str, Dict[str, Any]] = {}
recent_inbound_contacts: Dict[str, Dict[str, Any]] = {}
recent_inbound_messages: Dict[str, list[Dict[str, Any]]] = {}
order_chat_cache: Dict[str, Any] = {"expires_at": 0.0, "contacts": {}, "records_by_phone": {}}
supabase_contact_backfill_state: Dict[str, Any] = {"last_attempt": 0.0}

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

    daily_prefix = GOOGLE_DAILY_WORKSHEET_PREFIX.strip()
    if date_text:
        parsed_date = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        date_value = parsed_date.isoformat()
        return f"{daily_prefix} {date_value}" if daily_prefix else date_value

    today = local_today_iso()
    return f"{daily_prefix} {today}" if daily_prefix else today


def is_orders_worksheet_title(title: str) -> bool:
    normalized_title = (title or "").strip()
    daily_prefix = GOOGLE_DAILY_WORKSHEET_PREFIX.strip()
    if not daily_prefix:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized_title))
    return normalized_title.lower().startswith(f"{daily_prefix.lower()} ")


def worksheet_sort_key(worksheet) -> tuple[int, str]:
    title = getattr(worksheet, "title", "")
    daily_prefix = GOOGLE_DAILY_WORKSHEET_PREFIX.strip()
    date_part = title[len(daily_prefix) :].strip() if daily_prefix and title.startswith(daily_prefix) else title
    try:
        return (1, datetime.strptime(date_part, "%Y-%m-%d").date().isoformat())
    except ValueError:
        return (0, title)


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
        return {"processed_messages": {}, "contacts": {}}

    try:
        with history_path.open("r", encoding="utf-8") as history_file:
            data = json.load(history_file)
            if isinstance(data, dict):
                data.setdefault("processed_messages", {})
                data.setdefault("contacts", {})
                return data
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load message history. Starting with empty state.")

    return {"processed_messages": {}, "contacts": {}}


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


def get_contact_profile(user_phone: str) -> Dict[str, Any]:
    contacts = message_history.setdefault("contacts", {})
    return dict(contacts.get(normalize_whatsapp_recipient(user_phone), {}))


def remember_contact(user_phone: str, profile_name: str = "") -> bool:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    now = utcnow().isoformat(timespec="seconds")
    with history_lock:
        contacts = message_history.setdefault("contacts", {})
        existing_contact = contacts.get(normalized_phone, {})
        was_known = bool(existing_contact)
        contact_name = (profile_name or existing_contact.get("name") or "").strip()
        contacts[normalized_phone] = {
            "name": contact_name,
            "first_seen_at": existing_contact.get("first_seen_at") or now,
            "last_seen_at": now,
            "message_count": int(existing_contact.get("message_count", 0)) + 1,
        }
        save_message_history()
        return was_known


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


def format_confirmation_total(amount_text: str) -> str:
    digits = re.sub(r"[^\d]", "", amount_text or "")
    return f"Rs {digits}" if digits else "Rs -"


def build_product_confirmation_label(product: str, qty_3kg: int = 0, qty_5kg: int = 0) -> str:
    normalized_product = (product or "").strip()
    if normalized_product:
        return normalized_product
    if qty_3kg > 0 and qty_5kg <= 0:
        return f"Malda Mango 3Kg Box x {qty_3kg}"
    if qty_5kg > 0 and qty_3kg <= 0:
        return f"Malda Mango 5Kg Box x {qty_5kg}"

    parts: list[str] = []
    if qty_3kg > 0:
        parts.append(f"Malda Mango 3Kg Box x {qty_3kg}")
    if qty_5kg > 0:
        parts.append(f"Malda Mango 5Kg Box x {qty_5kg}")
    return ", ".join(parts) if parts else "Malda Mango Box x 1"


def build_customer_confirmation_message(
    *,
    customer_name: str,
    order_id: str,
    product: str,
    quantity: int,
    total_amount: str,
    address: str,
    status: str,
    payment_mode: str = "COD",
) -> str:
    safe_name = customer_name.strip() or "Customer"
    safe_status = status.strip() or "Received"
    safe_payment_mode = payment_mode.strip() or "COD"
    safe_address = address.strip() or "-"
    safe_product = product.strip() or "Malda Mango Box x 1"
    safe_total_amount = format_confirmation_total(total_amount)

    lines = [
        f"Namaskar {safe_name} !! 🙏",
        "",
        "🥭 Your mango order is confirmed! Our mangoes are currently getting VIP treatment before reaching your home.",
        "",
        "🧾 Order Details",
        "",
        f"Order ID: {order_id or '-'}",
        f"Product: {safe_product}",
        f"Quantity: {quantity if quantity > 0 else 1} Boxes",
        f"Total Amount: {safe_total_amount}",
        "",
        "📍 Delivery Address",
        f"{safe_address}",
        "",
        "⏳ Current Status",
        f"{safe_status}",
        "",
        f"📳 Payment Mode {safe_payment_mode}",
        "",
        "Thank you for choosing Pulps & Leaves !! 🥰 🥭",
    ]
    return "\n".join(lines)


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
    session_step = session.get("step", "idle")
    if session_step == "idle":
        return False

    updated_at = session.get("updated_at")
    if not updated_at:
        return True

    try:
        last_update = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return True

    idle_minutes = HUMAN_CHAT_IDLE_MINUTES if session_step == "human_chat" else SESSION_IDLE_RESET_MINUTES
    return utcnow() - last_update > timedelta(minutes=idle_minutes)


def reset_session(user_phone: str) -> None:
    with session_lock:
        user_sessions[user_phone] = build_default_session()
        save_user_sessions()


def mark_human_chat_session(user_phone: str, *, source: str = "") -> None:
    update_session(
        user_phone,
        step="human_chat",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
        human_chat_source=source,
        automation_source="",
    )


def mark_automation_session(user_phone: str, *, source: str = "") -> None:
    update_session(
        user_phone,
        step="idle",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
        human_chat_source="",
        automation_source=source,
    )


def touch_session(user_phone: str) -> None:
    update_session(user_phone)


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
            worksheet = next(
                (
                    existing_worksheet
                    for existing_worksheet in spreadsheet.worksheets()
                    if existing_worksheet.title.strip().lower() == target_worksheet_name.strip().lower()
                ),
                None,
            )
            if worksheet is None:
                raise
        else:
            worksheet = next(
                (
                    existing_worksheet
                    for existing_worksheet in spreadsheet.worksheets()
                    if existing_worksheet.title.strip().lower() == target_worksheet_name.strip().lower()
                ),
                None,
            )
            if worksheet is None:
                worksheet = spreadsheet.add_worksheet(title=target_worksheet_name, rows=1000, cols=len(WORKSHEET_HEADERS))
    ensure_worksheet_headers(worksheet)
    return worksheet


def load_daily_orders_worksheet(date_text: str | None = None, worksheet_name: str | None = None):
    target_worksheet_name = resolve_orders_worksheet_name(date_text=date_text, worksheet_name=worksheet_name)
    return load_worksheet(target_worksheet_name)


def load_order_lookup_worksheets():
    spreadsheet = load_spreadsheet()
    worksheets = [worksheet for worksheet in spreadsheet.worksheets() if is_orders_worksheet_title(worksheet.title)]
    worksheets.sort(key=worksheet_sort_key, reverse=True)
    return worksheets


def load_all_spreadsheet_worksheets():
    spreadsheet = load_spreadsheet()
    worksheets = spreadsheet.worksheets()
    worksheets.sort(key=worksheet_sort_key, reverse=True)
    return worksheets


def load_active_orders_worksheets():
    worksheets = load_order_lookup_worksheets()
    seen_ids: set[int] = set()
    unique_selection = []
    for worksheet in worksheets:
        if worksheet.id in seen_ids:
            continue
        seen_ids.add(worksheet.id)
        unique_selection.append(worksheet)
    return unique_selection


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

    ensure_checkbox_columns(worksheet, updated_headers)
    return updated_headers


def first_available_worksheet_row(worksheet, headers: list[str]) -> int:
    rows = worksheet.get_all_values()[1:]
    order_id_index = headers.index("Order ID") if "Order ID" in headers else 0

    for offset, values in enumerate(rows, start=2):
        padded_values = values + [""] * max(0, len(headers) - len(values))
        order_id = str(padded_values[order_id_index] if order_id_index < len(padded_values) else "").strip()
        if order_id:
            continue
        return offset

    return len(rows) + 2


def ensure_checkbox_columns(worksheet, headers: list[str]) -> None:
    checkbox_headers = [
        header
        for header in headers
        if header in {"Confirmed", "Packed", "Delivered", "Cancelled", CUSTOM_MESSAGE_TRIGGER_HEADER}
    ]
    if not checkbox_headers:
        return

    validation_key = f"{worksheet.id}:{'|'.join(sorted(checkbox_headers))}:{worksheet.row_count}"
    if validation_key in applied_checkbox_validations:
        return

    requests_payload = []
    end_row_index = max(worksheet.row_count, 1000)
    for header in checkbox_headers:
        column_index = headers.index(header)
        requests_payload.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": worksheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": end_row_index,
                        "startColumnIndex": column_index,
                        "endColumnIndex": column_index + 1,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            }
        )

    if requests_payload:
        try:
            worksheet.spreadsheet.batch_update({"requests": requests_payload})
        except gspread.exceptions.APIError as exc:
            if "typed columns" not in str(exc).lower():
                raise
            logger.debug(
                "Skipping checkbox validation for %s because Google Sheets typed table columns do not allow it.",
                worksheet.title,
            )
        applied_checkbox_validations.add(validation_key)


def count_existing_orders_for_today(city_code: str) -> int:
    worksheet = load_daily_orders_worksheet()
    today_prefix = f"PL{local_now().strftime('%d%m%y')}{city_code}"
    order_ids = worksheet.col_values(2)[1:]
    return sum(1 for order_id in order_ids if order_id.startswith(today_prefix))


def load_existing_order_ids() -> set[str]:
    order_ids: set[str] = set()
    for worksheet in load_order_lookup_worksheets():
        headers = worksheet.row_values(1)
        if "Order ID" not in headers:
            continue
        order_id_col = headers.index("Order ID") + 1
        order_ids.update(order_id for order_id in worksheet.col_values(order_id_col)[1:] if order_id)
    return order_ids


def generate_order_id(city_code: str) -> str:
    today_key = local_now().strftime("%d%m%y")
    prefix = f"PL{today_key}{city_code}"
    load_daily_orders_worksheet()
    existing_ids = load_existing_order_ids()
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
    worksheet = load_daily_orders_worksheet()
    headers = ensure_confirmation_columns(worksheet)
    delivery_slot = get_delivery_slot(city)
    order_summary = f"{build_order_summary(qty_3kg, qty_5kg)} | Total {format_inr(calculate_order_bill(qty_3kg, qty_5kg)['total'])}"
    row_by_header: Dict[str, Any] = {
        "Timestamp": local_now().isoformat(timespec="seconds"),
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
    target_row = first_available_worksheet_row(worksheet, headers)
    worksheet.update(
        f"A{target_row}:{column_index_to_letter(len(headers))}{target_row}",
        [row],
        value_input_option="USER_ENTERED",
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


def ensure_contacts_worksheet_headers(worksheet) -> list[str]:
    headers = worksheet.row_values(1)
    if not headers:
        worksheet.update(f"A1:{column_index_to_letter(len(WHATSAPP_CONTACT_HEADERS))}1", [WHATSAPP_CONTACT_HEADERS])
        return list(WHATSAPP_CONTACT_HEADERS)

    updated_headers = list(headers)
    for required_header in WHATSAPP_CONTACT_HEADERS:
        if required_header not in updated_headers:
            updated_headers.append(required_header)

    if worksheet.col_count < len(updated_headers):
        worksheet.add_cols(len(updated_headers) - worksheet.col_count)

    if updated_headers != headers:
        worksheet.update(f"A1:{column_index_to_letter(len(updated_headers))}1", [updated_headers])

    return updated_headers


def load_contacts_worksheet():
    spreadsheet = load_spreadsheet()
    target_worksheet_name = WHATSAPP_CONTACTS_WORKSHEET_NAME.strip() or "WhatsApp Contacts"
    try:
        worksheet = spreadsheet.worksheet(target_worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = next(
            (
                existing_worksheet
                for existing_worksheet in spreadsheet.worksheets()
                if existing_worksheet.title.strip().lower() == target_worksheet_name.lower()
            ),
            None,
        )
        if worksheet is None:
            worksheet = spreadsheet.add_worksheet(
                title=target_worksheet_name,
                rows=1000,
                cols=len(WHATSAPP_CONTACT_HEADERS),
            )
    ensure_contacts_worksheet_headers(worksheet)
    return worksheet


def invalidate_chat_cache(phone: str = "") -> None:
    normalized_phone = normalize_whatsapp_recipient(phone)
    with chat_cache_lock:
        chat_contacts_cache["expires_at"] = 0.0
        if normalized_phone:
            chat_messages_cache.pop(normalized_phone, None)
        else:
            chat_messages_cache.clear()


def parse_message_count(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


def compact_summary_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def build_simple_conversation_gist(
    *,
    first_enquiry_text: str = "",
    last_message_text: str = "",
    last_message_direction: str = "",
    message_count: int = 0,
    enquiry_status: str = "",
) -> str:
    first_enquiry = compact_summary_text(first_enquiry_text, 160)
    last_message = compact_summary_text(last_message_text, 160)
    direction_label = "customer" if normalize_text(last_message_direction) == "inbound" else "agent"
    status = compact_summary_text(enquiry_status or "open", 80)
    parts = []
    if first_enquiry:
        parts.append(f"First enquiry: {first_enquiry}")
    if last_message:
        parts.append(f"Latest {direction_label}: {last_message}")
    if message_count:
        parts.append(f"Messages: {message_count}")
    if status:
        parts.append(f"Status: {status}")
    return " | ".join(parts)[:500]


def store_inbound_contact_in_sheet(
    user_phone: str,
    *,
    profile_name: str = "",
    message_text: str = "",
    message_type: str = "",
    message_id: str = "",
    direction: str = "inbound",
    first_enquiry_text: str = "",
    conversation_gist: str = "",
    enquiry_status: str = "",
    increment_message_count: bool = True,
    source: str = "WhatsApp Webhook",
) -> None:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    if not normalized_phone:
        return

    worksheet = load_contacts_worksheet()
    headers = ensure_contacts_worksheet_headers(worksheet)
    rows = worksheet.get_all_values()[1:]
    target_row = len(rows) + 2
    existing_record: Dict[str, str] = {}

    for offset, values in enumerate(rows, start=2):
        record = build_row_record(headers, values)
        if normalize_whatsapp_recipient(record.get("Phone Number", "")) == normalized_phone:
            target_row = offset
            existing_record = record
            break

    now = local_now().isoformat(timespec="seconds")
    clean_profile_name = (profile_name or existing_record.get("Profile Name") or "").strip()
    clean_direction = normalize_text(direction) or "inbound"
    message_count = parse_message_count(existing_record.get("Message Count")) + (1 if increment_message_count else 0)
    clean_first_enquiry = (
        existing_record.get("First Enquiry Text")
        or first_enquiry_text
        or (message_text if clean_direction == "inbound" else "")
    )
    clean_status = (
        enquiry_status
        or existing_record.get("Enquiry Status")
        or ("Open" if clean_direction == "inbound" else "Replied")
    )
    clean_gist = conversation_gist or build_simple_conversation_gist(
        first_enquiry_text=clean_first_enquiry,
        last_message_text=message_text,
        last_message_direction=clean_direction,
        message_count=message_count,
        enquiry_status=clean_status,
    )
    row_by_header: Dict[str, Any] = {
        "Phone Number": normalized_phone,
        "Profile Name": clean_profile_name,
        "First Message At": existing_record.get("First Message At") or now,
        "First Enquiry Text": (clean_first_enquiry or "")[:1000],
        "Last Message At": now,
        "Last Message Direction": clean_direction,
        "Message Count": message_count,
        "Last Message Text": (message_text or "")[:1000],
        "Last Message Type": (message_type or "")[:100],
        "Last Message ID": (message_id or "")[:200],
        "Conversation Gist": clean_gist,
        "Enquiry Status": clean_status,
        "Source": source,
    }
    row = [row_by_header.get(header, existing_record.get(header, "")) for header in headers]
    worksheet.update(
        f"A{target_row}:{column_index_to_letter(len(headers))}{target_row}",
        [row],
        value_input_option="USER_ENTERED",
    )
    invalidate_chat_cache(normalized_phone)


def google_chat_summary_queue_worker() -> None:
    logger.info("Google chat summary queue worker started.")
    while True:
        payload = google_chat_summary_queue.get()
        try:
            store_inbound_contact_in_sheet(**payload)
        except Exception as exc:  # noqa: BLE001 - live chat should not be blocked by Sheets
            logger.exception("Failed to sync WhatsApp chat summary to Google Sheets: %s", exc)
        finally:
            google_chat_summary_queue.task_done()


def ensure_google_chat_summary_worker_started() -> None:
    global google_chat_summary_worker_thread

    with google_chat_summary_worker_lock:
        if google_chat_summary_worker_thread and google_chat_summary_worker_thread.is_alive():
            return
        google_chat_summary_worker_thread = Thread(
            target=google_chat_summary_queue_worker,
            name="google-chat-summary-worker",
            daemon=True,
        )
        google_chat_summary_worker_thread.start()


def enqueue_google_chat_summary_update(**payload: Any) -> None:
    ensure_google_chat_summary_worker_started()
    try:
        google_chat_summary_queue.put_nowait(payload)
    except Full:
        logger.warning("Google chat summary queue is full; writing summary synchronously.")
        store_inbound_contact_in_sheet(**payload)


def supabase_chat_configured() -> bool:
    return bool(SUPABASE_CHAT_ENABLED and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def supabase_table_url(table_name: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{quote(table_name, safe='')}"


def supabase_headers(*, prefer: str = "") -> Dict[str, str]:
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_request(
    method: str,
    table_name: str,
    *,
    params: Dict[str, str] | None = None,
    json_payload: Any = None,
    prefer: str = "",
) -> Any:
    if not supabase_chat_configured():
        raise ConfigurationError("Supabase chat is not configured.")

    response = requests.request(
        method,
        supabase_table_url(table_name),
        headers=supabase_headers(prefer=prefer),
        params=params,
        json=json_payload,
        timeout=10,
    )
    if not response.ok:
        logger.error("Supabase %s %s failed: %s", method, table_name, response.text[:1000])
        response.raise_for_status()
    if not response.text:
        return None
    return response.json()


def get_supabase_chat_contact(phone: str) -> Dict[str, Any]:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return {}
    rows = supabase_request(
        "GET",
        SUPABASE_CONTACTS_TABLE,
        params={
            "phone_number": f"eq.{normalized_phone}",
            "select": "*",
            "limit": "1",
        },
    )
    return dict(rows[0]) if isinstance(rows, list) and rows else {}


def resolve_supabase_enquiry_status(direction: str, status: str, existing_status: str = "") -> str:
    clean_direction = normalize_text(direction)
    clean_status = normalize_text(status)
    current_status = compact_summary_text(existing_status or "open", 80)
    if clean_direction == "inbound":
        return "open"
    if clean_status.startswith("failed"):
        return "reply_failed"
    if clean_status == "sending":
        return "replying"
    if clean_status in {"sent", "delivered", "read"}:
        return "replied"
    return current_status


def upsert_supabase_chat_contact(
    phone: str,
    *,
    profile_name: str = "",
    message_text: str = "",
    message_type: str = "",
    message_id: str = "",
    direction: str,
    status: str,
    source: str,
    increment_message_count: bool = True,
) -> Dict[str, Any]:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return {}

    existing = get_supabase_chat_contact(normalized_phone)
    now = local_now().isoformat(timespec="seconds")
    existing_count = int(existing.get("message_count") or 0)
    message_count = existing_count + (1 if increment_message_count else 0)
    clean_direction = normalize_text(direction) or "inbound"
    first_enquiry_text = (
        existing.get("first_enquiry_text")
        or (message_text if clean_direction == "inbound" else "")
        or ""
    )
    enquiry_status = resolve_supabase_enquiry_status(
        clean_direction,
        status,
        str(existing.get("enquiry_status") or ""),
    )
    conversation_gist = build_simple_conversation_gist(
        first_enquiry_text=first_enquiry_text,
        last_message_text=message_text,
        last_message_direction=clean_direction,
        message_count=message_count,
        enquiry_status=enquiry_status,
    )
    payload = {
        "phone_number": normalized_phone,
        "profile_name": (profile_name or existing.get("profile_name") or "").strip(),
        "first_message_at": existing.get("first_message_at") or now,
        "last_message_at": now,
        "message_count": message_count,
        "first_enquiry_text": first_enquiry_text[:2000],
        "last_message_text": (message_text or "")[:4000],
        "last_message_type": (message_type or "")[:100],
        "last_message_id": (message_id or "")[:200],
        "last_message_direction": clean_direction,
        "conversation_gist": conversation_gist,
        "enquiry_status": enquiry_status,
        "source": source,
        "updated_at": now,
    }
    rows = supabase_request(
        "POST",
        SUPABASE_CONTACTS_TABLE,
        params={"on_conflict": "phone_number"},
        json_payload=payload,
        prefer="resolution=merge-duplicates,return=representation",
    )
    invalidate_chat_cache(normalized_phone)
    return dict(rows[0]) if isinstance(rows, list) and rows else payload


def insert_supabase_chat_message(
    phone: str,
    *,
    profile_name: str = "",
    direction: str,
    message_type: str,
    message_text: str,
    message_id: str = "",
    status: str = "",
    agent: str = "",
    template_name: str = "",
    source: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
    error: str = "",
) -> str:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return ""

    upsert_supabase_chat_contact(
        normalized_phone,
        profile_name=profile_name,
        message_text=message_text,
        message_type=message_type,
        message_id=message_id,
        direction=direction,
        status=status,
        source=source,
        increment_message_count=True,
    )
    payload = {
        "phone_number": normalized_phone,
        "direction": direction,
        "message_type": message_type,
        "message_text": (message_text or "")[:4000],
        "message_id": (message_id or "")[:200],
        "status": status,
        "agent": agent,
        "template_name": template_name,
        "source": source,
        "media_id": (media_id or "")[:200],
        "media_mime_type": (media_mime_type or "")[:200],
        "media_filename": (media_filename or "")[:300],
        "error": (error or "")[:1000],
        "created_at": local_now().isoformat(timespec="seconds"),
    }
    try:
        rows = supabase_request(
            "POST",
            SUPABASE_MESSAGES_TABLE,
            json_payload=payload,
            prefer="return=representation",
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409 and message_id:
            logger.info("Skipping duplicate Supabase chat message id=%s", message_id)
            return ""
        raise
    invalidate_chat_cache(normalized_phone)
    return str(rows[0].get("id", "")) if isinstance(rows, list) and rows else ""


def update_supabase_chat_message(
    supabase_message_row_id: str,
    phone: str,
    *,
    message_type: str,
    message_text: str,
    direction: str = "outbound",
    message_id: str = "",
    status: str,
    agent: str = "",
    template_name: str = "",
    source: str = "Operator Panel",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
    error: str = "",
) -> None:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return

    upsert_supabase_chat_contact(
        normalized_phone,
        message_text=message_text,
        message_type=message_type,
        message_id=message_id,
        direction=direction,
        status=status,
        source=source,
        increment_message_count=False,
    )
    payload = {
        "message_id": (message_id or "")[:200],
        "status": status,
        "agent": agent,
        "template_name": template_name,
        "media_id": (media_id or "")[:200],
        "media_mime_type": (media_mime_type or "")[:200],
        "media_filename": (media_filename or "")[:300],
        "error": (error or "")[:1000],
        "updated_at": local_now().isoformat(timespec="seconds"),
    }
    if supabase_message_row_id:
        supabase_request(
            "PATCH",
            SUPABASE_MESSAGES_TABLE,
            params={"id": f"eq.{supabase_message_row_id}"},
            json_payload=payload,
            prefer="return=representation",
        )
    invalidate_chat_cache(normalized_phone)


def supabase_contact_to_chat_contact(row: Dict[str, Any]) -> Dict[str, Any]:
    phone = normalize_whatsapp_recipient(str(row.get("phone_number", "")))
    last_message_at = str(row.get("last_message_at") or "")
    return {
        "phone": phone,
        "name": str(row.get("profile_name") or ""),
        "first_message_at": str(row.get("first_message_at") or ""),
        "last_message_at": last_message_at,
        "message_count": int(row.get("message_count") or 0),
        "last_message_text": str(row.get("last_message_text") or ""),
        "last_message_type": str(row.get("last_message_type") or ""),
        "last_message_id": str(row.get("last_message_id") or ""),
        "last_message_direction": str(row.get("last_message_direction") or ""),
        "conversation_gist": str(row.get("conversation_gist") or ""),
        "enquiry_status": str(row.get("enquiry_status") or "open"),
        "within_reply_window": is_within_reply_window(last_message_at),
        "reply_window_expires_at": reply_window_expires_at(last_message_at),
        "reply_window_seconds_remaining": reply_window_seconds_remaining(last_message_at),
        "source": str(row.get("source") or "Supabase"),
    }


def supabase_message_to_chat_message(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": str(row.get("created_at") or ""),
        "phone": normalize_whatsapp_recipient(str(row.get("phone_number", ""))),
        "direction": str(row.get("direction") or ""),
        "message_type": str(row.get("message_type") or ""),
        "message_text": str(row.get("message_text") or ""),
        "message_id": str(row.get("message_id") or ""),
        "status": str(row.get("status") or ""),
        "agent": str(row.get("agent") or ""),
        "template_name": str(row.get("template_name") or ""),
        "source": str(row.get("source") or "Supabase"),
        "media_id": str(row.get("media_id") or ""),
        "media_mime_type": str(row.get("media_mime_type") or ""),
        "media_filename": str(row.get("media_filename") or ""),
    }


def sheet_backfill_message_id(message: Dict[str, Any]) -> str:
    existing_id = str(message.get("message_id") or "").strip()
    if existing_id:
        return existing_id

    fingerprint = "|".join(
        str(message.get(field, "") or "")
        for field in (
            "timestamp",
            "phone",
            "direction",
            "message_type",
            "message_text",
            "status",
            "agent",
            "template_name",
            "source",
        )
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24]
    return f"sheet:{digest}"


def supabase_timestamp(value: Any) -> str:
    parsed = parse_sheet_datetime(value)
    if parsed is not None:
        return parsed.isoformat(timespec="seconds")
    return local_now().isoformat(timespec="seconds")


def upsert_supabase_contact_from_chat_contact(contact: Dict[str, Any]) -> None:
    phone = normalize_whatsapp_recipient(str(contact.get("phone", "")))
    if not phone:
        return

    now = local_now().isoformat(timespec="seconds")
    first_message_at = supabase_timestamp(contact.get("first_message_at") or contact.get("last_message_at") or now)
    last_message_at = supabase_timestamp(contact.get("last_message_at") or first_message_at)
    first_enquiry_text = str(contact.get("first_enquiry_text") or contact.get("last_message_text") or "")
    last_message_text = str(contact.get("last_message_text") or "")
    last_message_direction = str(contact.get("last_message_direction") or "inbound")
    message_count = parse_message_count(contact.get("message_count"))
    enquiry_status = str(contact.get("enquiry_status") or "open")
    conversation_gist = str(contact.get("conversation_gist") or "") or build_simple_conversation_gist(
        first_enquiry_text=first_enquiry_text,
        last_message_text=last_message_text,
        last_message_direction=last_message_direction,
        message_count=message_count,
        enquiry_status=enquiry_status,
    )

    payload = {
        "phone_number": phone,
        "profile_name": str(contact.get("name") or ""),
        "first_message_at": first_message_at,
        "first_enquiry_text": first_enquiry_text[:2000],
        "last_message_at": last_message_at,
        "last_message_direction": last_message_direction,
        "message_count": message_count,
        "last_message_text": last_message_text[:4000],
        "last_message_type": str(contact.get("last_message_type") or "")[:100],
        "last_message_id": str(contact.get("last_message_id") or "")[:200],
        "conversation_gist": conversation_gist[:500],
        "enquiry_status": enquiry_status[:80],
        "source": str(contact.get("source") or "Google Sheets Backfill"),
        "updated_at": now,
    }
    supabase_request(
        "POST",
        SUPABASE_CONTACTS_TABLE,
        params={"on_conflict": "phone_number"},
        json_payload=payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def insert_supabase_message_from_chat_message(message: Dict[str, Any]) -> bool:
    phone = normalize_whatsapp_recipient(str(message.get("phone", "")))
    if not phone:
        return False

    payload = {
        "phone_number": phone,
        "direction": str(message.get("direction") or "inbound"),
        "message_type": str(message.get("message_type") or "text"),
        "message_text": str(message.get("message_text") or "")[:4000],
        "message_id": sheet_backfill_message_id(message)[:200],
        "status": str(message.get("status") or ""),
        "agent": str(message.get("agent") or ""),
        "template_name": str(message.get("template_name") or ""),
        "source": str(message.get("source") or "Google Sheets Backfill"),
        "media_id": str(message.get("media_id") or "")[:200],
        "media_mime_type": str(message.get("media_mime_type") or "")[:200],
        "media_filename": str(message.get("media_filename") or "")[:300],
        "created_at": supabase_timestamp(message.get("timestamp")),
        "updated_at": local_now().isoformat(timespec="seconds"),
    }
    try:
        supabase_request(
            "POST",
            SUPABASE_MESSAGES_TABLE,
            json_payload=payload,
            prefer="return=minimal",
        )
        return True
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            return False
        raise


def sync_sheet_contacts_to_supabase(limit: int = 300) -> list[Dict[str, Any]]:
    contacts = list_sheet_chat_contacts(limit=limit)
    synced = 0
    for contact in contacts:
        try:
            upsert_supabase_contact_from_chat_contact(contact)
            synced += 1
        except Exception as exc:  # noqa: BLE001 - keep returning the Sheet contacts for the UI
            logger.warning("Failed to backfill Supabase chat contact %s: %s", contact.get("phone"), exc)
    if synced:
        logger.info("Backfilled %s Google Sheet chat contact(s) into Supabase.", synced)
        invalidate_chat_cache()
    return contacts


def should_top_up_supabase_contacts(current_count: int, requested_limit: int) -> bool:
    if current_count <= 0:
        return True
    if current_count >= requested_limit:
        return False

    now = time.monotonic()
    last_attempt = float(supabase_contact_backfill_state.get("last_attempt", 0.0))
    if now - last_attempt < SUPABASE_CHAT_CONTACT_BACKFILL_SECONDS:
        return False

    supabase_contact_backfill_state["last_attempt"] = now
    return True


def merge_chat_contacts(*contact_lists: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    contacts_by_phone: Dict[str, Dict[str, Any]] = {}
    for contacts in contact_lists:
        for contact in contacts:
            phone = normalize_whatsapp_recipient(str(contact.get("phone", "")))
            if not phone:
                continue
            existing = contacts_by_phone.get(phone, {})
            existing_sort = sheet_datetime_sort_value(existing.get("last_message_at")) if existing else -1
            contact_sort = sheet_datetime_sort_value(contact.get("last_message_at"))
            if not existing or contact_sort >= existing_sort:
                contacts_by_phone[phone] = {**existing, **contact, "phone": phone}
            else:
                contacts_by_phone[phone] = {**contact, **existing, "phone": phone}

    contacts = list(contacts_by_phone.values())
    contacts.sort(key=lambda contact: sheet_datetime_sort_value(contact.get("last_message_at")), reverse=True)
    return contacts


def remember_recent_inbound_chat(
    phone: str,
    *,
    profile_name: str = "",
    message_type: str = "",
    message_text: str = "",
    message_id: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
) -> None:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return

    timestamp = local_now().isoformat(timespec="seconds")
    clean_message_id = (message_id or "").strip()
    message = {
        "timestamp": timestamp,
        "phone": normalized_phone,
        "direction": "inbound",
        "message_type": message_type or "text",
        "message_text": message_text or "",
        "message_id": clean_message_id,
        "status": "received",
        "agent": "",
        "template_name": "",
        "source": "Recent inbound",
        "media_id": (media_id or "")[:200],
        "media_mime_type": (media_mime_type or "")[:200],
        "media_filename": (media_filename or "")[:300],
    }
    now = time.monotonic()
    with chat_cache_lock:
        messages = recent_inbound_messages.setdefault(normalized_phone, [])
        if clean_message_id:
            messages[:] = [existing for existing in messages if existing.get("message_id") != clean_message_id]
        messages.append(message)
        del messages[:-50]

        existing = recent_inbound_contacts.get(normalized_phone, {})
        message_count = parse_message_count(existing.get("message_count")) + 1
        first_enquiry_text = str(existing.get("first_enquiry_text") or message_text or "")
        enquiry_status = "open"
        recent_inbound_contacts[normalized_phone] = {
            "phone": normalized_phone,
            "name": profile_name or existing.get("name", ""),
            "first_message_at": existing.get("first_message_at") or timestamp,
            "first_enquiry_text": first_enquiry_text,
            "last_message_at": timestamp,
            "message_count": message_count,
            "last_message_text": message_text or existing.get("last_message_text", ""),
            "last_message_type": message_type or existing.get("last_message_type", "text"),
            "last_message_id": clean_message_id or existing.get("last_message_id", ""),
            "last_message_direction": "inbound",
            "conversation_gist": build_simple_conversation_gist(
                first_enquiry_text=first_enquiry_text,
                last_message_text=message_text,
                last_message_direction="inbound",
                message_count=message_count,
                enquiry_status=enquiry_status,
            ),
            "enquiry_status": enquiry_status,
            "within_reply_window": True,
            "reply_window_expires_at": reply_window_expires_at(timestamp),
            "reply_window_seconds_remaining": reply_window_seconds_remaining(timestamp),
            "source": "Recent inbound",
            "_remembered_at": now,
        }
        chat_contacts_cache["expires_at"] = 0.0
        chat_messages_cache.pop(normalized_phone, None)


def get_recent_inbound_contacts() -> list[Dict[str, Any]]:
    now = time.monotonic()
    contacts: list[Dict[str, Any]] = []
    expired: list[str] = []
    with chat_cache_lock:
        for phone, contact in recent_inbound_contacts.items():
            remembered_at = float(contact.get("_remembered_at", 0.0))
            if now - remembered_at > RECENT_INBOUND_CHAT_TTL_SECONDS:
                expired.append(phone)
                continue

            clean_contact = dict(contact)
            clean_contact.pop("_remembered_at", None)
            last_message_at = clean_contact.get("last_message_at", "")
            clean_contact["within_reply_window"] = is_within_reply_window(last_message_at)
            clean_contact["reply_window_expires_at"] = reply_window_expires_at(last_message_at)
            clean_contact["reply_window_seconds_remaining"] = reply_window_seconds_remaining(last_message_at)
            contacts.append(clean_contact)

        for phone in expired:
            recent_inbound_contacts.pop(phone, None)
            recent_inbound_messages.pop(phone, None)

    contacts.sort(key=lambda contact: sheet_datetime_sort_value(contact.get("last_message_at")), reverse=True)
    return contacts


def merge_recent_inbound_contacts(contacts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return merge_chat_contacts(contacts, get_recent_inbound_contacts())


def get_recent_inbound_messages(phone: str) -> list[Dict[str, Any]]:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return []

    now = time.monotonic()
    with chat_cache_lock:
        contact = recent_inbound_contacts.get(normalized_phone)
        remembered_at = float(contact.get("_remembered_at", 0.0)) if contact else 0.0
        if not contact or now - remembered_at > RECENT_INBOUND_CHAT_TTL_SECONDS:
            recent_inbound_contacts.pop(normalized_phone, None)
            recent_inbound_messages.pop(normalized_phone, None)
            return []
        return [dict(message) for message in recent_inbound_messages.get(normalized_phone, [])]


def merge_recent_inbound_messages(phone: str, messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    merged_by_key: Dict[str, Dict[str, Any]] = {}
    for message in [*messages, *get_recent_inbound_messages(phone)]:
        message_id = str(message.get("message_id") or "").strip()
        key = message_id or "|".join(
            str(message.get(field, "") or "")
            for field in ("timestamp", "phone", "direction", "message_type", "message_text")
        )
        merged_by_key[key] = dict(message)

    merged = list(merged_by_key.values())
    merged.sort(key=lambda message: sheet_datetime_sort_value(message.get("timestamp")))
    return merged


def sync_sheet_messages_to_supabase(phone: str, limit: int = 200) -> list[Dict[str, Any]]:
    messages = list_sheet_chat_messages(phone, limit=limit)
    return sync_chat_messages_to_supabase(phone, messages)


def sync_chat_messages_to_supabase(phone: str, messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not messages:
        return messages

    normalized_phone = normalize_whatsapp_recipient(phone)
    latest_message = messages[-1]
    contact = find_chat_contact(normalized_phone) or {
        "phone": normalized_phone,
        "last_message_at": latest_message.get("timestamp", ""),
        "last_message_text": latest_message.get("message_text", ""),
        "last_message_type": latest_message.get("message_type", ""),
        "last_message_direction": latest_message.get("direction", ""),
        "message_count": len(messages),
        "source": "Google Sheets Backfill",
    }
    contact["message_count"] = max(parse_message_count(contact.get("message_count")), len(messages))
    contact["last_message_at"] = latest_message.get("timestamp", contact.get("last_message_at", ""))
    contact["last_message_text"] = latest_message.get("message_text", contact.get("last_message_text", ""))
    contact["last_message_type"] = latest_message.get("message_type", contact.get("last_message_type", ""))
    contact["last_message_id"] = latest_message.get("message_id", contact.get("last_message_id", ""))
    contact["last_message_direction"] = latest_message.get("direction", contact.get("last_message_direction", ""))
    upsert_supabase_contact_from_chat_contact(contact)

    synced = 0
    for message in messages:
        try:
            if insert_supabase_message_from_chat_message(message):
                synced += 1
        except Exception as exc:  # noqa: BLE001 - keep returning Sheet messages for the UI
            logger.warning("Failed to backfill Supabase chat message for %s: %s", normalized_phone, exc)
    if synced:
        logger.info("Backfilled %s Google Sheet chat message(s) for %s into Supabase.", synced, normalized_phone)
        invalidate_chat_cache(normalized_phone)
    return messages


def list_supabase_chat_contacts(limit: int = 100) -> list[Dict[str, Any]]:
    rows = supabase_request(
        "GET",
        SUPABASE_CONTACTS_TABLE,
        params={
            "select": "*",
            "order": "last_message_at.desc.nullslast",
            "limit": str(limit),
        },
    )
    contacts = [supabase_contact_to_chat_contact(row) for row in rows or []]
    return [contact for contact in contacts if contact.get("phone")]


def list_supabase_chat_messages(user_phone: str, limit: int = 80) -> list[Dict[str, Any]]:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    if not normalized_phone:
        return []
    rows = supabase_request(
        "GET",
        SUPABASE_MESSAGES_TABLE,
        params={
            "phone_number": f"eq.{normalized_phone}",
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        },
    )
    messages = [supabase_message_to_chat_message(row) for row in rows or []]
    messages.reverse()
    return messages


def sync_supabase_chat_statuses_from_webhook(payload: Dict[str, Any]) -> None:
    if not supabase_chat_configured():
        return

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status_event in value.get("statuses", []):
                message_id = str(status_event.get("id", "")).strip()
                status = str(status_event.get("status", "")).strip()
                if not message_id or not status:
                    continue

                error = ""
                errors = status_event.get("errors") or []
                if errors and isinstance(errors[0], dict):
                    error = str(errors[0].get("title") or errors[0].get("message") or "")[:1000]

                supabase_request(
                    "PATCH",
                    SUPABASE_MESSAGES_TABLE,
                    params={"message_id": f"eq.{message_id}"},
                    json_payload={
                        "status": status,
                        "error": error,
                        "updated_at": local_now().isoformat(timespec="seconds"),
                    },
                    prefer="return=minimal",
                )


def ensure_conversations_worksheet_headers(worksheet) -> list[str]:
    headers = worksheet.row_values(1)
    if not headers:
        worksheet.update(
            f"A1:{column_index_to_letter(len(WHATSAPP_CONVERSATION_HEADERS))}1",
            [WHATSAPP_CONVERSATION_HEADERS],
        )
        return list(WHATSAPP_CONVERSATION_HEADERS)

    updated_headers = list(headers)
    for required_header in WHATSAPP_CONVERSATION_HEADERS:
        if required_header not in updated_headers:
            updated_headers.append(required_header)

    if worksheet.col_count < len(updated_headers):
        worksheet.add_cols(len(updated_headers) - worksheet.col_count)

    if updated_headers != headers:
        worksheet.update(f"A1:{column_index_to_letter(len(updated_headers))}1", [updated_headers])

    return updated_headers


def load_conversations_worksheet():
    spreadsheet = load_spreadsheet()
    target_worksheet_name = WHATSAPP_CONVERSATIONS_WORKSHEET_NAME.strip() or "WhatsApp Conversations"
    try:
        worksheet = spreadsheet.worksheet(target_worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = next(
            (
                existing_worksheet
                for existing_worksheet in spreadsheet.worksheets()
                if existing_worksheet.title.strip().lower() == target_worksheet_name.lower()
            ),
            None,
        )
        if worksheet is None:
            worksheet = spreadsheet.add_worksheet(
                title=target_worksheet_name,
                rows=1000,
                cols=len(WHATSAPP_CONVERSATION_HEADERS),
            )
    ensure_conversations_worksheet_headers(worksheet)
    return worksheet


def append_chat_message_to_sheet(
    user_phone: str,
    *,
    direction: str,
    message_type: str,
    message_text: str,
    message_id: str = "",
    status: str = "",
    agent: str = "",
    template_name: str = "",
    source: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
) -> None:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    if not normalized_phone:
        return

    worksheet = load_conversations_worksheet()
    headers = ensure_conversations_worksheet_headers(worksheet)
    row_by_header: Dict[str, Any] = {
        "Timestamp": local_now().isoformat(timespec="seconds"),
        "Phone Number": normalized_phone,
        "Direction": direction,
        "Message Type": message_type,
        "Message Text": (message_text or "")[:2000],
        "Message ID": (message_id or "")[:200],
        "Status": status,
        "Agent": agent,
        "Template Name": template_name,
        "Source": source,
        "Media ID": (media_id or "")[:200],
        "Media Mime Type": (media_mime_type or "")[:200],
        "Media Filename": (media_filename or "")[:300],
    }
    worksheet.append_row(
        [row_by_header.get(header, "") for header in headers],
        value_input_option="USER_ENTERED",
    )
    invalidate_chat_cache(normalized_phone)


def parse_sheet_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        try:
            return parsed.replace(tzinfo=ZoneInfo(LOCAL_TIMEZONE))
        except Exception:
            return parsed
    return parsed


def is_within_reply_window(last_message_at: Any) -> bool:
    parsed = parse_sheet_datetime(last_message_at)
    if parsed is None:
        return False

    now = local_now()
    if now.tzinfo is None and parsed.tzinfo is not None:
        now = now.replace(tzinfo=parsed.tzinfo)
    if now.tzinfo is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return now - parsed <= timedelta(hours=24)


def reply_window_expires_at(last_message_at: Any) -> str:
    parsed = parse_sheet_datetime(last_message_at)
    if parsed is None:
        return ""
    expires_at = parsed + timedelta(hours=24)
    return expires_at.isoformat(timespec="seconds")


def reply_window_seconds_remaining(last_message_at: Any) -> int:
    parsed = parse_sheet_datetime(last_message_at)
    if parsed is None:
        return 0

    expires_at = parsed + timedelta(hours=24)
    now = local_now()
    if now.tzinfo is None and expires_at.tzinfo is not None:
        now = now.replace(tzinfo=expires_at.tzinfo)
    if now.tzinfo is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    return max(0, int((expires_at - now).total_seconds()))


def sheet_datetime_sort_value(value: Any) -> float:
    parsed = parse_sheet_datetime(value)
    if parsed is None:
        return 0.0
    try:
        return parsed.timestamp()
    except OSError:
        return 0.0


def build_order_chat_summary(record: Dict[str, str]) -> str:
    order_id = get_record_value(record, "order_id") or "Order"
    status = get_record_value(record, "status") or "Received"
    summary = build_sheet_order_summary(record)
    total = get_record_value(record, "total_amount")
    parts = [f"{order_id}: {status}"]
    if summary:
        parts.append(summary)
    if total:
        parts.append(f"Total {total}")
    return " | ".join(parts)


def copy_order_chat_data(
    contacts: Dict[str, Dict[str, Any]],
    records_by_phone: Dict[str, list[Dict[str, str]]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, list[Dict[str, str]]]]:
    return (
        {phone: dict(contact) for phone, contact in contacts.items()},
        {phone: [dict(record) for record in records] for phone, records in records_by_phone.items()},
    )


def read_order_chat_data() -> tuple[Dict[str, Dict[str, Any]], Dict[str, list[Dict[str, str]]]]:
    contacts: Dict[str, Dict[str, Any]] = {}
    records_by_phone: Dict[str, list[Dict[str, str]]] = {}
    for worksheet in load_order_lookup_worksheets():
        values = worksheet.get_all_values()
        if not values:
            continue

        headers = values[0]
        rows = values[1:]
        for row_values in rows:
            if not any(str(value).strip() for value in row_values):
                continue

            record = build_row_record(headers, row_values)
            phone = normalize_whatsapp_recipient(get_record_value(record, "phone"))
            if not phone:
                continue

            records_by_phone.setdefault(phone, []).append(record)
            timestamp = str(record.get("Timestamp") or record.get("Updated At") or "").strip()
            existing = contacts.get(phone)
            existing_sort = sheet_datetime_sort_value(existing.get("last_message_at")) if existing else -1
            current_sort = sheet_datetime_sort_value(timestamp)
            if existing and existing_sort >= current_sort:
                existing["order_count"] = int(existing.get("order_count", 1)) + 1
                continue

            contacts[phone] = {
                "phone": phone,
                "name": get_record_value(record, "customer_name"),
                "first_message_at": timestamp,
                "last_message_at": timestamp,
                "message_count": 0,
                "last_message_text": build_order_chat_summary(record),
                "last_message_type": "order",
                "within_reply_window": False,
                "reply_window_expires_at": "",
                "reply_window_seconds_remaining": 0,
                "source": "Orders",
                "latest_order_id": get_record_value(record, "order_id"),
                "latest_order_status": get_record_value(record, "status"),
                "order_count": int(existing.get("order_count", 0)) + 1 if existing else 1,
            }

    for records in records_by_phone.values():
        records.sort(
            key=lambda record: sheet_datetime_sort_value(record.get("Timestamp") or record.get("Updated At")),
            reverse=True,
        )
    return contacts, records_by_phone


def cached_order_chat_data() -> tuple[Dict[str, Dict[str, Any]], Dict[str, list[Dict[str, str]]]]:
    now = time.monotonic()
    with chat_cache_lock:
        cached_contacts = order_chat_cache.get("contacts") or {}
        cached_records = order_chat_cache.get("records_by_phone") or {}
        if float(order_chat_cache.get("expires_at", 0.0)) > now:
            return copy_order_chat_data(cached_contacts, cached_records)

    try:
        contacts, records_by_phone = read_order_chat_data()
    except Exception as exc:
        with chat_cache_lock:
            cached_contacts = order_chat_cache.get("contacts") or {}
            cached_records = order_chat_cache.get("records_by_phone") or {}
            order_chat_cache["expires_at"] = now + SHEETS_RATE_LIMIT_BACKOFF_SECONDS
        logger.warning("Using cached order chat contacts after Sheets read failed: %s", exc)
        return copy_order_chat_data(cached_contacts, cached_records)

    with chat_cache_lock:
        order_chat_cache["contacts"] = contacts
        order_chat_cache["records_by_phone"] = records_by_phone
        order_chat_cache["expires_at"] = now + ORDER_CHAT_CACHE_SECONDS
    return copy_order_chat_data(contacts, records_by_phone)


def read_order_chat_contacts() -> Dict[str, Dict[str, Any]]:
    contacts, _ = cached_order_chat_data()
    return contacts


def list_sheet_chat_contacts(limit: int = 100) -> list[Dict[str, Any]]:
    try:
        contacts_by_phone = read_order_chat_contacts()
    except Exception as exc:
        logger.warning("Could not load order contacts for chat list: %s", exc)
        contacts_by_phone = {}

    try:
        worksheet = load_contacts_worksheet()
        headers = ensure_contacts_worksheet_headers(worksheet)
        rows = worksheet.get_all_values()[1:]
    except Exception:
        if contacts_by_phone:
            contacts = list(contacts_by_phone.values())
            contacts.sort(key=lambda contact: sheet_datetime_sort_value(contact.get("last_message_at")), reverse=True)
            return contacts[:limit]
        raise

    for row_values in rows:
        record = build_row_record(headers, row_values)
        phone = normalize_whatsapp_recipient(record.get("Phone Number", ""))
        if not phone:
            continue
        last_message_at = record.get("Last Message At", "")
        existing = contacts_by_phone.get(phone, {})
        within_reply_window = is_within_reply_window(last_message_at)
        contacts_by_phone[phone] = {
            **existing,
            "phone": phone,
            "name": record.get("Profile Name", "") or existing.get("name", ""),
            "first_message_at": record.get("First Message At", "") or existing.get("first_message_at", ""),
            "first_enquiry_text": record.get("First Enquiry Text", "") or existing.get("first_enquiry_text", ""),
            "last_message_at": last_message_at or existing.get("last_message_at", ""),
            "message_count": parse_message_count(record.get("Message Count")),
            "last_message_text": record.get("Last Message Text", "") or existing.get("last_message_text", ""),
            "last_message_type": record.get("Last Message Type", "") or existing.get("last_message_type", ""),
            "last_message_id": record.get("Last Message ID", "") or existing.get("last_message_id", ""),
            "last_message_direction": record.get("Last Message Direction", "") or existing.get("last_message_direction", ""),
            "conversation_gist": record.get("Conversation Gist", "") or existing.get("conversation_gist", ""),
            "enquiry_status": record.get("Enquiry Status", "") or existing.get("enquiry_status", "open"),
            "within_reply_window": within_reply_window,
            "reply_window_expires_at": reply_window_expires_at(last_message_at),
            "reply_window_seconds_remaining": reply_window_seconds_remaining(last_message_at),
            "source": "WhatsApp",
        }

    contacts = list(contacts_by_phone.values())
    contacts.sort(key=lambda contact: sheet_datetime_sort_value(contact.get("last_message_at")), reverse=True)
    return contacts[:limit]


def list_chat_contacts(limit: int = 100) -> list[Dict[str, Any]]:
    if supabase_chat_configured():
        try:
            contacts = list_supabase_chat_contacts(limit=limit)
            if should_top_up_supabase_contacts(len(contacts), limit):
                logger.info(
                    "Supabase chat contacts look partial (%s/%s); backfilling from Google Sheets.",
                    len(contacts),
                    limit,
                )
                sheet_contacts = sync_sheet_contacts_to_supabase(limit=max(limit, 1000))
                return merge_chat_contacts(contacts, sheet_contacts)[:limit]
            return contacts
        except Exception as exc:  # noqa: BLE001 - fall back to the existing Sheets path
            logger.warning("Supabase chat contacts failed; falling back to Google Sheets: %s", exc)
    return list_sheet_chat_contacts(limit=limit)


def list_sheet_chat_messages(user_phone: str, limit: int = 80) -> list[Dict[str, Any]]:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    if not normalized_phone:
        return []

    worksheet = load_conversations_worksheet()
    headers = ensure_conversations_worksheet_headers(worksheet)
    messages: list[Dict[str, Any]] = []

    for row_values in worksheet.get_all_values()[1:]:
        record = build_row_record(headers, row_values)
        if normalize_whatsapp_recipient(record.get("Phone Number", "")) != normalized_phone:
            continue
        messages.append(
            {
                "timestamp": record.get("Timestamp", ""),
                "phone": normalized_phone,
                "direction": record.get("Direction", ""),
                "message_type": record.get("Message Type", ""),
                "message_text": record.get("Message Text", ""),
                "message_id": record.get("Message ID", ""),
                "status": record.get("Status", ""),
                "agent": record.get("Agent", ""),
                "template_name": record.get("Template Name", ""),
                "source": record.get("Source", ""),
                "media_id": record.get("Media ID", ""),
                "media_mime_type": record.get("Media Mime Type", ""),
                "media_filename": record.get("Media Filename", ""),
            }
        )

    if not messages:
        messages = build_chat_history_fallback_messages(normalized_phone)

    return messages[-limit:]


def list_chat_messages(user_phone: str, limit: int = 80) -> list[Dict[str, Any]]:
    if supabase_chat_configured():
        try:
            messages = list_supabase_chat_messages(user_phone, limit=limit)
            if messages:
                return messages
            logger.info("Supabase chat messages are empty for %s; backfilling from Google Sheets.", user_phone)
            return sync_sheet_messages_to_supabase(user_phone, limit=max(limit, 200))[-limit:]
        except Exception as exc:  # noqa: BLE001 - fall back to the existing Sheets path
            logger.warning("Supabase chat messages failed; falling back to Google Sheets: %s", exc)
    return list_sheet_chat_messages(user_phone, limit=limit)


def build_chat_history_fallback_messages(user_phone: str) -> list[Dict[str, Any]]:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    messages: list[Dict[str, Any]] = []

    try:
        worksheet = load_contacts_worksheet()
        headers = ensure_contacts_worksheet_headers(worksheet)
        for row_values in worksheet.get_all_values()[1:]:
            record = build_row_record(headers, row_values)
            if normalize_whatsapp_recipient(record.get("Phone Number", "")) != normalized_phone:
                continue
            last_text = str(record.get("Last Message Text", "")).strip()
            if last_text:
                messages.append(
                    {
                        "timestamp": record.get("Last Message At", ""),
                        "phone": normalized_phone,
                        "direction": "inbound",
                        "message_type": record.get("Last Message Type", "text"),
                        "message_text": last_text,
                        "message_id": record.get("Last Message ID", ""),
                        "status": "latest saved message",
                        "agent": "",
                        "template_name": "",
                        "source": "WhatsApp Contacts",
                        "media_id": "",
                        "media_mime_type": "",
                        "media_filename": "",
                    }
                )
            break
    except Exception as exc:
        logger.warning("Could not build contact fallback history for %s: %s", normalized_phone, exc)

    try:
        for record in latest_order_records_for_phone(normalized_phone, limit=5):
            order_id = get_record_value(record, "order_id") or "-"
            order_status = get_record_value(record, "status") or "Received"
            customer_name = get_record_value(record, "customer_name") or "Customer"
            order_summary = build_sheet_order_summary(record)
            address = get_record_value(record, "address")
            timestamp = str(record.get("Timestamp") or record.get("Updated At") or "").strip()
            order_lines = [
                "Previous order",
                f"Order ID: {order_id}",
                f"Customer: {customer_name}",
                f"Status: {order_status}",
            ]
            if order_summary:
                order_lines.append(f"Items: {order_summary}")
            if address:
                order_lines.append(f"Address: {address}")
            messages.append(
                {
                    "timestamp": timestamp,
                    "phone": normalized_phone,
                    "direction": "system",
                    "message_type": "order",
                    "message_text": "\n".join(order_lines),
                    "message_id": order_id,
                    "status": "order record",
                    "agent": "",
                    "template_name": "",
                    "source": "Orders",
                    "media_id": "",
                    "media_mime_type": "",
                    "media_filename": "",
                }
            )
    except Exception as exc:
        logger.warning("Could not build order fallback history for %s: %s", normalized_phone, exc)

    messages.sort(key=lambda message: sheet_datetime_sort_value(message.get("timestamp")))
    return messages


def latest_order_records_for_phone(phone: str, limit: int = 5) -> list[Dict[str, str]]:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return []

    _, records_by_phone = cached_order_chat_data()
    records = records_by_phone.get(normalized_phone, [])
    return records[:limit]


def cached_list_chat_contacts(limit: int = 100) -> tuple[list[Dict[str, Any]], bool]:
    now = time.monotonic()
    with chat_cache_lock:
        cached_contacts = list(chat_contacts_cache.get("contacts") or [])
        if float(chat_contacts_cache.get("expires_at", 0.0)) > now:
            contacts = merge_recent_inbound_contacts(cached_contacts)
            return contacts[:limit], bool(chat_contacts_cache.get("stale", False))

    try:
        contacts = merge_recent_inbound_contacts(list_chat_contacts(limit=max(limit, 1000)))
    except Exception as exc:
        with chat_cache_lock:
            cached_contacts = list(chat_contacts_cache.get("contacts") or [])
            chat_contacts_cache["expires_at"] = now + SHEETS_RATE_LIMIT_BACKOFF_SECONDS
            chat_contacts_cache["stale"] = True
        logger.warning("Using cached chat contacts after Sheets read failed: %s", exc)
        contacts = merge_recent_inbound_contacts(cached_contacts)
        return contacts[:limit], True

    with chat_cache_lock:
        chat_contacts_cache["contacts"] = contacts
        cache_seconds = SUPABASE_CHAT_CONTACT_CACHE_SECONDS if supabase_chat_configured() else CHAT_CONTACT_CACHE_SECONDS
        chat_contacts_cache["expires_at"] = now + cache_seconds
        chat_contacts_cache["stale"] = False
    return contacts[:limit], False


def cached_list_chat_messages(user_phone: str, limit: int = 80) -> tuple[list[Dict[str, Any]], bool]:
    normalized_phone = normalize_whatsapp_recipient(user_phone)
    now = time.monotonic()
    with chat_cache_lock:
        cached = chat_messages_cache.get(normalized_phone)
        if cached and float(cached.get("expires_at", 0.0)) > now:
            messages = merge_recent_inbound_messages(normalized_phone, list(cached.get("messages") or []))
            return messages[-limit:], bool(cached.get("stale", False))

    try:
        messages = merge_recent_inbound_messages(
            normalized_phone,
            list_chat_messages(normalized_phone, limit=max(limit, 200)),
        )
    except Exception as exc:
        with chat_cache_lock:
            cached = chat_messages_cache.get(normalized_phone)
            if cached:
                cached["expires_at"] = now + SHEETS_RATE_LIMIT_BACKOFF_SECONDS
                cached["stale"] = True
                cached_messages = list(cached.get("messages") or [])
            else:
                chat_messages_cache[normalized_phone] = {
                    "messages": [],
                    "expires_at": now + SHEETS_RATE_LIMIT_BACKOFF_SECONDS,
                    "stale": True,
                }
                cached_messages = []
        if cached_messages and supabase_chat_configured():
            try:
                sync_chat_messages_to_supabase(normalized_phone, cached_messages)
            except Exception as sync_exc:  # noqa: BLE001 - the cached response is still useful to the UI
                logger.warning("Failed to backfill cached chat messages into Supabase: %s", sync_exc)
        logger.warning("Using cached chat messages for %s after Sheets read failed: %s", normalized_phone, exc)
        messages = merge_recent_inbound_messages(normalized_phone, cached_messages)
        return messages[-limit:], True

    with chat_cache_lock:
        cache_seconds = SUPABASE_CHAT_MESSAGE_CACHE_SECONDS if supabase_chat_configured() else CHAT_MESSAGE_CACHE_SECONDS
        chat_messages_cache[normalized_phone] = {
            "messages": messages,
            "expires_at": now + cache_seconds,
            "stale": False,
        }
    return messages[-limit:], False


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
    address = get_record_value(record, "address")
    product = get_record_value(record, "product")
    qty_3kg = get_record_int(record, "qty_3kg")
    qty_5kg = get_record_int(record, "qty_5kg")
    quantity = get_record_int(record, "quantity")
    if quantity <= 0:
        quantity = qty_3kg + qty_5kg
    total_amount = get_record_value(record, "total_amount")
    if not total_amount:
        total_amount = re.sub(r".*Total\s*", "", build_sheet_order_summary(record), flags=re.IGNORECASE).strip()
    status = get_record_value(record, "status") or "Received"
    payment_mode = get_record_value(record, "payment") or "COD"
    product_label = build_product_confirmation_label(product, qty_3kg, qty_5kg)
    return build_customer_confirmation_message(
        customer_name=customer_name,
        order_id=order_id,
        product=product_label,
        quantity=quantity,
        total_amount=total_amount,
        address=address,
        status=status,
        payment_mode=payment_mode,
    )


def build_sheet_confirmation_quantity(record: Dict[str, str]) -> str:
    qty_3kg = get_record_int(record, "qty_3kg")
    qty_5kg = get_record_int(record, "qty_5kg")
    quantity = get_record_int(record, "quantity")
    if quantity <= 0:
        quantity = qty_3kg + qty_5kg
    return str(quantity if quantity > 0 else 1)


def build_sheet_confirmation_amount(record: Dict[str, str]) -> str:
    amount = get_record_value(record, "total_amount")
    if not amount:
        amount = re.sub(r".*Total\s*", "", build_sheet_order_summary(record), flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^\s*(rs\.?|inr|₹)\s*", "", amount or "", flags=re.IGNORECASE).strip()
    return cleaned or "-"


def build_sheet_confirmation_template_params(record: Dict[str, str]) -> list[str]:
    qty_3kg = get_record_int(record, "qty_3kg")
    qty_5kg = get_record_int(record, "qty_5kg")
    product = build_product_confirmation_label(get_record_value(record, "product"), qty_3kg, qty_5kg)
    return [
        get_record_value(record, "customer_name") or "Customer",
        product or "Malda Mangoes",
        build_sheet_confirmation_quantity(record),
        build_sheet_confirmation_amount(record),
        get_record_value(record, "payment") or "COD",
        get_record_value(record, "address") or "-",
        get_record_value(record, "order_id") or "-",
    ]


def build_offline_order_template_params(record: Dict[str, str]) -> list[str]:
    return [
        get_record_value(record, "customer_name") or "Customer",
        GOOGLE_REVIEW_URL or "-",
        INSTAGRAM_URL or "-",
    ]


def latest_order_record_or_empty(phone: str) -> Dict[str, str]:
    records = latest_order_records_for_phone(phone, limit=1)
    return records[0] if records else {}


def build_template_params_for_phone(template_name: str, phone: str) -> list[str]:
    normalized_template = (template_name or "").strip()
    record = latest_order_record_or_empty(phone)
    if normalized_template == ORDER_CONFIRMATION_TEMPLATE_NAME and record:
        return build_sheet_confirmation_template_params(record)
    if normalized_template == ORDER_DELIVERED_TEMPLATE_NAME:
        if record:
            return build_order_delivered_template_params(record)
        contact = find_chat_contact(phone) or {}
        return [
            str(contact.get("name") or "Customer"),
            GOOGLE_REVIEW_URL or "-",
            INSTAGRAM_URL or "-",
        ]
    if normalized_template == OFFLINE_ORDER_TEMPLATE_NAME:
        if record:
            return build_offline_order_template_params(record)
        contact = find_chat_contact(phone) or {}
        return [
            str(contact.get("name") or "Customer"),
            GOOGLE_REVIEW_URL or "-",
            INSTAGRAM_URL or "-",
        ]
    return []


def is_website_order_shortcut(user_text: str) -> bool:
    if "website" not in user_text:
        return False
    return any(
        phrase in user_text
        for phrase in {
            "place order",
            "placed order",
            "order through",
            "order on",
            "ordered through",
            "ordered on",
        }
    )


def find_latest_order_by_phone(phone: str):
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not is_valid_whatsapp_recipient(normalized_phone):
        return None, None, None, None

    for worksheet in load_active_orders_worksheets():
        headers = ensure_confirmation_columns(worksheet)
        rows = worksheet.get_all_values()[1:]
        for row_offset in range(len(rows) - 1, -1, -1):
            row_number = row_offset + 2
            row_values = rows[row_offset]
            if not any(str(value).strip() for value in row_values):
                continue

            record = build_row_record(headers, row_values)
            order_id = get_record_value(record, "order_id")
            record_phone = get_record_value(record, "phone")
            if not order_id or not record_phone:
                continue
            if normalize_whatsapp_recipient(record_phone) == normalized_phone:
                return worksheet, row_number, headers, record

    return None, None, None, None


def send_website_order_shortcut_confirmation(user_phone: str) -> None:
    worksheet, row_number, headers, record = find_latest_order_by_phone(user_phone)
    if not record or not worksheet or not row_number or not headers:
        send_whatsapp_text_message(
            user_phone,
            "We could not find a website order for this WhatsApp number. Please send the last 4 characters of your Order ID.",
        )
        send_tracking_prompt(user_phone)
        return

    recipient = normalize_whatsapp_recipient(user_phone)
    if is_offline_owner_order_record(record):
        try:
            update_confirmation_result(worksheet, row_number, headers, status="Sending", error="")
            response_json = send_offline_order_template_for_record(recipient, record)
            message_id = extract_whatsapp_message_id(response_json)
            update_confirmation_result(
                worksheet,
                row_number,
                headers,
                status="Sent",
                message_id=message_id,
            )
            mark_automation_session(recipient, source="offline_orders")
        except Exception as exc:  # noqa: BLE001 - keep the WhatsApp shortcut graceful
            error = str(exc)
            logger.exception("Failed to send offline order template for %s: %s", recipient, exc)
            update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
            send_whatsapp_text_message(user_phone, "This offline order is saved, but the offline WhatsApp template failed.")
        return

    try:
        update_confirmation_result(worksheet, row_number, headers, status="Sending", error="")
        response_json = send_order_confirmation_for_record(recipient, record)
        message_id = extract_whatsapp_message_id(response_json)
        update_confirmation_result(worksheet, row_number, headers, status="Sent", message_id=message_id)
    except Exception as exc:
        error = str(exc)
        logger.exception("Website order shortcut confirmation failed for row %s in %s: %s", row_number, worksheet.title, exc)
        update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
        raise


def find_order_row(order_id: str | None = None, last_four: str | None = None) -> tuple[int, Dict[str, str]] | tuple[None, None]:
    normalized_order_id = normalize_text(order_id or "")
    normalized_last_four = normalize_text(last_four or "")
    for worksheet in load_all_spreadsheet_worksheets():
        headers = worksheet.row_values(1)
        if "Order ID" not in headers:
            continue
        order_id_col = headers.index("Order ID") + 1
        order_ids = worksheet.col_values(order_id_col)[1:]

        for offset, existing_order_id in enumerate(order_ids, start=2):
            normalized_existing_order_id = normalize_text(existing_order_id)
            if normalized_order_id and normalized_existing_order_id == normalized_order_id:
                return offset, build_row_record(headers, worksheet.row_values(offset))
            if normalized_last_four and normalized_existing_order_id.endswith(normalized_last_four):
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
    customer_name = get_record_value(record, "customer_name") or "Customer"
    order_id = get_record_value(record, "order_id")
    status = get_record_value(record, "status") or DEFAULT_ORDER_STATUS
    status = "Received" if normalize_text(status) == "pending" else status
    city = get_record_value(record, "city")
    delivery_slot = get_sheet_delivery_slot(record)
    order_summary = get_record_value(record, "product") or get_record_value(record, "order_summary")
    address = get_record_value(record, "address")

    lines = [
        "Track Your Aam 🔍",
        "",
        f"Order ID: {order_id}",
        f"Customer Name: {customer_name}",
        f"Status: {status}",
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
    return "10th - 14th June ’26"


def find_city_option(user_text: str, *, include_numeric_aliases: bool = True) -> Dict[str, str] | None:
    for city in CITY_OPTIONS.values():
        aliases = city["aliases"]
        if not include_numeric_aliases:
            aliases = {alias for alias in aliases if not alias.isdigit()}
        city_name = normalize_text(city["name"])
        if user_text in aliases or user_text.startswith(f"{city_name} "):
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
    bill = calculate_order_bill(qty_3kg, qty_5kg)
    return build_customer_confirmation_message(
        customer_name=customer_name or "Customer",
        order_id=order_id,
        product=build_product_confirmation_label("", qty_3kg, qty_5kg),
        quantity=qty_3kg + qty_5kg,
        total_amount=str(bill["total"]),
        address=address,
        status="Received",
        payment_mode="COD",
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
    header_image_id: str = "",
    header_image_url: str = "",
) -> Dict[str, Any]:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")

    clean_template_name = (template_name or "").strip()
    if clean_template_name == ORDER_CONFIRMATION_TEMPLATE_NAME:
        language_code = ORDER_CONFIRMATION_TEMPLATE_LANGUAGE or language_code
    elif clean_template_name == OFFLINE_ORDER_TEMPLATE_NAME:
        language_code = OFFLINE_ORDER_TEMPLATE_LANGUAGE or language_code
        if not header_image_id and not header_image_url:
            header_image_id = OFFLINE_ORDER_HEADER_IMAGE_ID
            header_image_url = OFFLINE_ORDER_HEADER_IMAGE_URL
            if not header_image_id and not header_image_url and OFFLINE_ORDER_HEADER_IMAGE_PATH:
                header_image_id = upload_whatsapp_media(OFFLINE_ORDER_HEADER_IMAGE_PATH)
    elif clean_template_name == ORDER_DELIVERED_TEMPLATE_NAME:
        language_code = ORDER_DELIVERED_TEMPLATE_LANGUAGE or language_code
        if not header_image_id and not header_image_url:
            header_image_id = ORDER_DELIVERED_HEADER_IMAGE_ID
            header_image_url = ORDER_DELIVERED_HEADER_IMAGE_URL
            if not header_image_id and not header_image_url and ORDER_DELIVERED_HEADER_IMAGE_PATH:
                header_image_id = upload_whatsapp_media(ORDER_DELIVERED_HEADER_IMAGE_PATH)

    template: Dict[str, Any] = {
        "name": clean_template_name,
        "language": {"code": language_code},
    }
    components: list[Dict[str, Any]] = []
    if header_image_id or header_image_url:
        image_payload = {"id": header_image_id} if header_image_id else {"link": header_image_url}
        components.append(
            {
                "type": "header",
                "parameters": [{"type": "image", "image": image_payload}],
            }
        )

    if parameters:
        components.append(
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(parameter)[:1024]} for parameter in parameters
                ],
            }
        )
    if components:
        template["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": template,
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


def send_whatsapp_image_media_message(recipient: str, media_id: str, *, caption: str | None = None) -> Dict[str, Any]:
    image_payload: Dict[str, Any] = {"id": media_id}
    if caption:
        image_payload["caption"] = caption[:1024]
    return send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "image",
            "image": image_payload,
        }
    )


def send_whatsapp_document_media_message(
    recipient: str,
    media_id: str,
    *,
    filename: str,
    caption: str | None = None,
) -> Dict[str, Any]:
    document_payload: Dict[str, Any] = {
        "id": media_id,
        "filename": (secure_filename(filename) or "document.pdf")[:240],
    }
    if caption:
        document_payload["caption"] = caption[:1024]
    return send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": document_payload,
        }
    )


def fetch_whatsapp_media_info(media_id: str) -> Dict[str, Any]:
    if not ACCESS_TOKEN:
        raise ConfigurationError("Missing WhatsApp Cloud API credentials in environment.")
    clean_media_id = str(media_id or "").strip()
    if not clean_media_id:
        raise ValueError("Media ID is required.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{clean_media_id}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        params=build_graph_api_params(),
        timeout=30,
    )
    if not response.ok:
        logger.error("WhatsApp media lookup failed: %s", response.text)
        response.raise_for_status()
    return response.json()


def download_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    media_info = fetch_whatsapp_media_info(media_id)
    media_url = str(media_info.get("url") or "").strip()
    if not media_url:
        raise ConfigurationError("WhatsApp media lookup succeeded but no download URL was returned.")

    response = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        timeout=60,
    )
    if not response.ok:
        logger.error("WhatsApp media download failed: %s", response.text[:500])
        response.raise_for_status()
    return response.content, str(media_info.get("mime_type") or response.headers.get("Content-Type") or "image/jpeg")


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


def send_whatsapp_image_message(recipient: str, file_path: str, *, caption: str | None = None) -> bool:
    resolved_path = resolve_runtime_path(file_path)
    if not resolved_path.exists():
        logger.warning("Skipping image send because file was not found: %s", resolved_path)
        return False

    media_id = upload_whatsapp_media(file_path)
    send_whatsapp_image_media_message(recipient, media_id, caption=caption)
    return True


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


def send_url_button_message(
    recipient: str,
    body: str,
    display_text: str,
    url: str,
) -> None:
    send_whatsapp_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": body},
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": display_text,
                        "url": url,
                    },
                },
            },
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


def build_welcome_message(*, is_returning_customer: bool = False, customer_name: str = "") -> str:
    if not is_returning_customer:
        return MESSAGES["welcome"]

    safe_name = (customer_name or "Customer").strip() or "Customer"
    return (
        f"Welcome Back {safe_name}!\n"
        "We are Currently offering fresh, premium-quality Malda Mangoes directly sourced from farms !!\n"
        "How may we assist you today?"
    )


def send_welcome_menu(
    user_phone: str,
    *,
    is_returning_customer: bool = False,
    customer_name: str = "",
) -> None:
    send_button_message(
        user_phone,
        build_welcome_message(is_returning_customer=is_returning_customer, customer_name=customer_name),
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
            {"id": "city_blr", "title": "Bangalore 🌦️", "description": "10th - 14th June ’26"},
            {"id": "city_hyd", "title": "Hyderabad 🥯", "description": "10th - 14th June ’26"},
            {"id": "city_pun", "title": "Pune 🌿", "description": "10th - 14th June ’26"},
            {"id": "city_mum", "title": "Mumbai 🌊", "description": "10th - 14th June ’26"},
        ],
    )


def send_continue_picker(user_phone: str) -> None:
    send_button_message(
        user_phone,
        MESSAGES["continue_order"],
        [
            {"id": "continue_yes", "title": "Place New Order"},
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

    if current_step == "welcome_menu":
        send_main_retry_menu(user_phone)
        return

    if current_step == "select_city":
        send_city_picker(user_phone)
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

    if current_step == "post_tracking_menu":
        send_continue_picker(user_phone)
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


def start_welcome_flow(
    user_phone: str,
    *,
    is_returning_customer: bool | None = None,
    customer_name: str = "",
) -> None:
    contact_profile = get_contact_profile(user_phone)
    if is_returning_customer is None:
        is_returning_customer = bool(contact_profile)
    customer_name = customer_name or str(contact_profile.get("name", ""))
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
    send_welcome_menu(
        user_phone,
        is_returning_customer=is_returning_customer,
        customer_name=customer_name,
    )


def send_order_redirect(user_phone: str, *, include_image: bool = True) -> None:
    reset_session(user_phone)
    if include_image:
        send_whatsapp_image_message(user_phone, CART_IMAGE_PATH)
    send_url_button_message(user_phone, MESSAGES["order_redirect"], "Order Now", ORDER_WEBSITE_URL)


def send_city_delivery_and_order_link(user_phone: str, selected_city: Dict[str, str]) -> None:
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
    city_image_path = selected_city.get("image_path", "")
    if city_image_path:
        image_sent = send_whatsapp_image_message(
            user_phone,
            city_image_path,
            caption=selected_city["delivery_message"],
        )
        if not image_sent:
            logger.warning("City image was not sent for %s; sending delivery message without image.", selected_city["name"])
            send_whatsapp_text_message(user_phone, selected_city["delivery_message"])
    else:
        send_whatsapp_text_message(user_phone, selected_city["delivery_message"])
    send_order_redirect(user_phone, include_image=True)


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
    mark_human_chat_session(user_phone, source="customer_support_request")
    send_whatsapp_text_message(user_phone, MESSAGES["direct_support"])
    time.sleep(15)
    send_whatsapp_text_message(user_phone, MESSAGES["support_busy"])


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
    last_four = re.sub(r"[^A-Za-z0-9]", "", raw_text or "").upper()
    if len(last_four) != 4:
        send_tracking_prompt(user_phone)
        return

    _, record = find_order_row(last_four=last_four)
    if not record:
        send_whatsapp_text_message(user_phone, MESSAGES["tracking_not_found"])
        return

    update_session(
        user_phone,
        step="post_tracking_menu",
        city=None,
        city_code=None,
        order={},
        selected_box=None,
        cart_image_sent=False,
        attempts=0,
    )
    send_whatsapp_text_message(user_phone, build_tracking_details_message(record))
    send_continue_picker(user_phone)


def handle_post_tracking_menu(user_phone: str, user_text: str) -> None:
    if user_text in {
        "1",
        "continue_yes",
        "place new order",
        "continue & place new order",
        "continue and place new order",
        "new order",
    }:
        send_order_redirect(user_phone)
        return

    if user_text in {"2", "continue_no", "exit", "exit for now"}:
        reset_session(user_phone)
        send_whatsapp_text_message(user_phone, MESSAGES["exit"])
        return

    send_invalid_retry_message(user_phone, get_or_create_session(user_phone))


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

    send_city_delivery_and_order_link(user_phone, selected_city)


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


FLOW_ORDER_NAME = "mango_whatsapp_order"
FLOW_CITY_NAMES = {
    "bangalore": "Bangalore",
    "bengaluru": "Bangalore",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "mumbai": "Mumbai",
}


def flow_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("id", "title", "value", "text", "label"):
            nested_value = value.get(key)
            if nested_value not in (None, ""):
                return flow_value(nested_value)
        return ""
    if isinstance(value, list):
        return ", ".join(flow_value(item) for item in value if flow_value(item))
    return str(value or "").strip()


def parse_flow_response_json(raw_value: Any) -> Dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        return {}

    try:
        parsed = json.loads(raw_value)
    except ValueError:
        try:
            parsed = ast.literal_eval(raw_value)
        except (ValueError, SyntaxError):
            logger.warning("Could not parse WhatsApp Flow response_json: %s", raw_value[:500])
            return {}

    return parsed if isinstance(parsed, dict) else {}


def extract_whatsapp_flow_response(message: Dict[str, Any]) -> Dict[str, Any]:
    if message.get("type") != "interactive":
        return {}

    interactive = message.get("interactive", {})
    if interactive.get("type") != "nfm_reply":
        return {}

    nfm_reply = interactive.get("nfm_reply") or {}
    response_json = (
        nfm_reply.get("response_json")
        or nfm_reply.get("response")
        or nfm_reply.get("payload")
        or {}
    )
    response_payload = parse_flow_response_json(response_json)
    response_payload.setdefault("flow_reply_name", flow_value(nfm_reply.get("name")))
    return response_payload


def build_order_payload_from_flow_response(flow_payload: Dict[str, Any], user_phone: str) -> Dict[str, Any] | None:
    flow_name = normalize_text(flow_value(flow_payload.get("flow_name") or flow_payload.get("flow")))
    if flow_name != FLOW_ORDER_NAME:
        return None

    city_key = normalize_text(flow_value(flow_payload.get("city")))
    city = FLOW_CITY_NAMES.get(city_key, flow_value(flow_payload.get("city")).title())
    quantity_text = flow_value(flow_payload.get("quantity"))
    quantity_match = re.search(r"\d+", quantity_text)
    quantity = int(quantity_match.group(0)) if quantity_match else 1
    quantity = max(1, min(quantity, 10))

    total_amount = quantity * WHATSAPP_FLOW_3KG_BOX_PRICE
    return {
        "customer_name": flow_value(flow_payload.get("customer_name")),
        "phone_number": flow_value(flow_payload.get("mobile_number")) or user_phone,
        "city": city,
        "product_name": "Malda Mango 3Kg Box",
        "quantity": quantity,
        "price": WHATSAPP_FLOW_3KG_BOX_PRICE,
        "total_amount": total_amount,
        "delivery_address": flow_value(flow_payload.get("delivery_address")),
        "payment_method": "Cash on Delivery",
        "payment_status": "Received",
        "order_status": "Received",
        "source": "WhatsApp Flow",
        "notes": "Created from WhatsApp Flow submission.",
    }


def process_whatsapp_flow_reply(user_phone: str, message: Dict[str, Any]) -> bool:
    flow_payload = extract_whatsapp_flow_response(message)
    if not flow_payload:
        return False

    order_payload = build_order_payload_from_flow_response(flow_payload, user_phone)
    if not order_payload:
        logger.info("Ignoring unsupported WhatsApp Flow reply: %s", flow_payload)
        return True

    try:
        result = OrderService().create_order(order_payload)
    except ValueError as exc:
        logger.warning("WhatsApp Flow order payload failed validation for %s: %s", user_phone, exc)
        send_whatsapp_text_message(
            user_phone,
            "We could not create your mango order because some required details were missing. Please open the order flow and submit it again.",
        )
        return True
    except OrderSystemConfigurationError as exc:
        logger.exception("WhatsApp Flow order configuration error: %s", exc)
        send_whatsapp_text_message(
            user_phone,
            "Your mango order details were received, but our order system is temporarily unavailable. Please contact +91 9835496666.",
        )
        return True
    except Exception as exc:
        logger.exception("WhatsApp Flow order creation failed for %s: %s", user_phone, exc)
        send_whatsapp_text_message(
            user_phone,
            "Something went wrong while creating your mango order. Please contact +91 9835496666 and our team will help you.",
        )
        return True

    order = result.get("order", {}) if isinstance(result, dict) else {}
    logger.info("WhatsApp Flow order created for %s: %s", user_phone, order.get("order_id", ""))
    reset_session(user_phone)
    return True


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


def extract_contact_message_preview(message: Dict[str, Any]) -> str:
    text = extract_message_text(message).strip()
    if text:
        return text

    message_type = str(message.get("type", "")).strip()
    if message_type == "interactive":
        interactive_type = str(message.get("interactive", {}).get("type", "")).strip()
        if interactive_type == "nfm_reply":
            return "WhatsApp Flow reply"
        if interactive_type:
            return f"Interactive {interactive_type}"

    media_payload = message.get(message_type, {}) if message_type else {}
    if isinstance(media_payload, dict):
        caption = str(media_payload.get("caption", "")).strip()
        if caption:
            return f"{message_type.title()}: {caption}" if message_type in {"image", "video", "document"} else caption

    if message_type in {"image", "video", "audio", "document", "sticker"}:
        return f"{message_type.title()} received"

    return message_type or "Unsupported message"


def extract_message_media_details(message: Dict[str, Any]) -> Dict[str, str]:
    message_type = str(message.get("type", "")).strip()
    media_payload = message.get(message_type, {}) if message_type else {}
    if not isinstance(media_payload, dict):
        return {"media_id": "", "media_mime_type": "", "media_filename": ""}

    filename = str(media_payload.get("filename") or "").strip()
    if not filename and message_type in {"image", "video", "audio", "sticker"}:
        filename = f"{message_type}"

    return {
        "media_id": str(media_payload.get("id") or "").strip(),
        "media_mime_type": str(media_payload.get("mime_type") or "").strip(),
        "media_filename": filename[:300],
    }


def process_user_message(
    user_phone: str,
    raw_text: str,
    *,
    is_returning_customer: bool | None = None,
    customer_name: str = "",
) -> None:
    user_text = normalize_text(raw_text)
    session = get_or_create_session(user_phone)
    current_step = session.get("step", "idle")

    if is_session_stale(session):
        start_welcome_flow(
            user_phone,
            is_returning_customer=is_returning_customer,
            customer_name=customer_name,
        )
        return

    if current_step == "human_chat" and session.get("human_chat_source") == "operator_template":
        mark_automation_session(user_phone, source="operator_template")
        current_step = "idle"

    if current_step == "human_chat":
        touch_session(user_phone)
        logger.info("Suppressing bot automation for active human chat with %s.", user_phone)
        return

    if is_website_order_shortcut(user_text):
        send_website_order_shortcut_confirmation(user_phone)
        return

    if user_text in {"hi", "hello", "hey", "start", "restart"}:
        start_welcome_flow(
            user_phone,
            is_returning_customer=is_returning_customer,
            customer_name=customer_name,
        )
        return

    if user_text in GLOBAL_TRACKING_TRIGGER_TEXTS:
        start_tracking_flow(user_phone)
        return

    if user_text in GLOBAL_SUPPORT_TRIGGER_TEXTS:
        connect_to_human_support(user_phone)
        return

    if user_text in GLOBAL_ORDER_TRIGGER_TEXTS:
        start_city_flow(user_phone)
        return

    global_city_option = find_city_option(user_text, include_numeric_aliases=False)
    if global_city_option:
        send_city_delivery_and_order_link(user_phone, global_city_option)
        return

    if current_step == "idle" and user_text not in HUMAN_SUPPORT_TRIGGER_TEXTS and user_text not in TRACKING_TRIGGER_TEXTS and user_text not in WELCOME_TRIGGER_TEXTS:
        start_welcome_flow(
            user_phone,
            is_returning_customer=is_returning_customer,
            customer_name=customer_name,
        )
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

    if current_step == "post_tracking_menu":
        handle_post_tracking_menu(user_phone, user_text)
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
            start_welcome_flow(
                user_phone,
                is_returning_customer=is_returning_customer,
                customer_name=customer_name,
            )
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

    token = (
        request.headers.get("X-Automation-Token", "")
        or request.args.get("token", "")
        or request.form.get("token", "")
    ).strip()
    if token:
        return token

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return str(payload.get("token", "")).strip()

    return ""


def authorize_outbound_request() -> tuple[bool, str]:
    if not OUTBOUND_CONFIRMATION_SECRET:
        return False, "OUTBOUND_CONFIRMATION_SECRET is not configured."

    request_token = get_outbound_request_token()
    if hmac.compare_digest(request_token, OUTBOUND_CONFIRMATION_SECRET):
        return True, ""

    return False, "Unauthorized."


def chat_request_payload() -> Dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def parse_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return normalize_text(str(value)) in {"1", "true", "yes", "y", "on"}


def chat_api_authorized() -> tuple[bool, tuple[Any, int] | None]:
    authorized, auth_error = authorize_outbound_request()
    if authorized:
        return True, None
    status_code = 500 if "configured" in auth_error else 401
    return False, (jsonify({"error": auth_error}), status_code)


def parse_template_parameters(raw_parameters: Any) -> list[str]:
    if isinstance(raw_parameters, list):
        return [str(value).strip() for value in raw_parameters if str(value).strip()]
    return [line.strip() for line in str(raw_parameters or "").splitlines() if line.strip()]


def find_chat_contact(phone: str) -> Dict[str, Any] | None:
    normalized_phone = normalize_whatsapp_recipient(phone)
    if not normalized_phone:
        return None
    contacts, _ = cached_list_chat_contacts(limit=500)
    for contact in contacts:
        if contact.get("phone") == normalized_phone:
            return contact
    return None


def enqueue_google_summary_for_chat_message(
    phone: str,
    *,
    profile_name: str = "",
    direction: str,
    message_type: str,
    message_text: str,
    message_id: str = "",
    status: str = "",
    source: str,
) -> None:
    clean_direction = normalize_text(direction) or "inbound"
    enqueue_google_chat_summary_update(
        user_phone=phone,
        profile_name=profile_name,
        message_text=message_text,
        message_type=message_type,
        message_id=message_id,
        direction=clean_direction,
        enquiry_status=resolve_supabase_enquiry_status(clean_direction, status, ""),
        source=source,
    )


def record_inbound_chat_message(
    phone: str,
    *,
    profile_name: str = "",
    message_type: str,
    message_text: str,
    message_id: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
) -> None:
    remember_recent_inbound_chat(
        phone,
        profile_name=profile_name,
        message_type=message_type,
        message_text=message_text,
        message_id=message_id,
        media_id=media_id,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
    )
    if supabase_chat_configured():
        try:
            insert_supabase_chat_message(
                phone,
                profile_name=profile_name,
                direction="inbound",
                message_type=message_type,
                message_text=message_text,
                message_id=message_id,
                status="received",
                source="WhatsApp Webhook",
                media_id=media_id,
                media_mime_type=media_mime_type,
                media_filename=media_filename,
            )
            enqueue_google_summary_for_chat_message(
                phone,
                profile_name=profile_name,
                direction="inbound",
                message_type=message_type,
                message_text=message_text,
                message_id=message_id,
                status="received",
                source="WhatsApp Webhook",
            )
            return
        except Exception as exc:  # noqa: BLE001 - keep the original Sheets path alive
            logger.exception("Supabase inbound chat save failed for %s; falling back to Sheets: %s", phone, exc)

    store_inbound_contact_in_sheet(
        phone,
        profile_name=profile_name,
        message_text=message_text,
        message_type=message_type,
        message_id=message_id,
    )
    append_chat_message_to_sheet(
        phone,
        direction="inbound",
        message_type=message_type,
        message_text=message_text,
        message_id=message_id,
        status="received",
        source="WhatsApp Webhook",
        media_id=media_id,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
    )


def start_outgoing_chat_message(
    phone: str,
    *,
    message_type: str,
    message_text: str,
    agent: str,
    template_name: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
) -> str:
    if not supabase_chat_configured():
        return ""
    try:
        return insert_supabase_chat_message(
            phone,
            direction="outbound",
            message_type=message_type,
            message_text=message_text,
            status="sending",
            agent=agent,
            template_name=template_name,
            source="Operator Panel",
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
        )
    except Exception as exc:  # noqa: BLE001 - sending should still be attempted
        logger.exception("Failed to create Supabase outgoing chat message for %s: %s", phone, exc)
        return ""


def finish_outgoing_chat_message(
    supabase_message_row_id: str,
    phone: str,
    *,
    message_type: str,
    message_text: str,
    message_id: str = "",
    status: str,
    agent: str,
    template_name: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
    error: str = "",
) -> bool:
    if not supabase_message_row_id:
        return False
    try:
        update_supabase_chat_message(
            supabase_message_row_id,
            phone,
            message_type=message_type,
            message_text=message_text,
            message_id=message_id,
            status=status,
            agent=agent,
            template_name=template_name,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
            error=error,
        )
        enqueue_google_summary_for_chat_message(
            phone,
            direction="outbound",
            message_type=message_type,
            message_text=message_text,
            message_id=message_id,
            status=status,
            source="Operator Panel",
        )
        return True
    except Exception as exc:  # noqa: BLE001 - keep a fallback record when Supabase update fails
        logger.exception("Failed to update Supabase outgoing chat message for %s: %s", phone, exc)
        return False


def log_outgoing_chat_message(
    phone: str,
    *,
    message_type: str,
    message_text: str,
    message_id: str = "",
    status: str,
    agent: str,
    template_name: str = "",
    media_id: str = "",
    media_mime_type: str = "",
    media_filename: str = "",
) -> None:
    try:
        store_inbound_contact_in_sheet(
            phone,
            message_text=message_text,
            message_type=message_type,
            message_id=message_id,
            direction="outbound",
            enquiry_status=resolve_supabase_enquiry_status("outbound", status, ""),
            source="Operator Panel",
        )
    except Exception as exc:  # noqa: BLE001 - keep the detailed fallback log attempt below
        logger.exception("Failed to update outbound WhatsApp contact summary for %s: %s", phone, exc)

    try:
        append_chat_message_to_sheet(
            phone,
            direction="outbound",
            message_type=message_type,
            message_text=message_text,
            message_id=message_id,
            status=status,
            agent=agent,
            template_name=template_name,
            source="Operator Panel",
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
        )
    except Exception as exc:  # noqa: BLE001 - the message send result matters more than logging
        logger.exception("Failed to log outbound WhatsApp message for %s: %s", phone, exc)


@app.get("/")
@app.get("/admin/chat")
def chat_panel():
    authorized, auth_error = authorize_outbound_request()
    return render_template(
        "chat.html",
        brand_name="Pulps & Leaves",
        authorized=authorized,
        auth_error="" if authorized else auth_error,
        admin_token=get_outbound_request_token(),
        default_template_name=BULK_MESSAGE_TEMPLATE_NAME,
        default_template_language=BULK_MESSAGE_TEMPLATE_LANGUAGE,
        supabase_chat_enabled=supabase_chat_configured(),
    )


@app.get("/api/admin/chat/contacts")
def chat_contacts_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    try:
        requested_limit = int(request.args.get("limit", "1000"))
        limit = max(1, min(requested_limit, 1000))
    except ValueError:
        return jsonify({"error": "Invalid limit."}), 400

    try:
        contacts, stale = cached_list_chat_contacts(limit=limit)
    except Exception as exc:
        logger.exception("Failed to load chat contacts: %s", exc)
        return jsonify({"error": "Failed to load chat contacts.", "details": str(exc)[:300]}), 500

    return jsonify({"contacts": contacts, "stale": stale}), 200


@app.get("/api/admin/chat/messages")
def chat_messages_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    phone = normalize_whatsapp_recipient(request.args.get("phone", ""))
    if not is_valid_whatsapp_recipient(phone):
        return jsonify({"error": "Invalid WhatsApp phone number."}), 400

    try:
        requested_limit = int(request.args.get("limit", "80"))
        limit = max(1, min(requested_limit, 200))
    except ValueError:
        return jsonify({"error": "Invalid limit."}), 400

    try:
        messages, messages_stale = cached_list_chat_messages(phone, limit=limit)
        contact = find_chat_contact(phone)
    except Exception as exc:
        logger.exception("Failed to load chat messages for %s: %s", phone, exc)
        return jsonify({"error": "Failed to load chat messages.", "details": str(exc)[:300]}), 500

    return jsonify({"contact": contact, "messages": messages, "stale": messages_stale}), 200


@app.post("/api/admin/chat/cache/clear")
def chat_cache_clear_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    payload = chat_request_payload()
    phone = normalize_whatsapp_recipient(str(payload.get("phone", request.args.get("phone", ""))))
    invalidate_chat_cache(phone)
    return jsonify({"cleared": True, "phone": phone or ""}), 200


@app.post("/api/admin/chat/reply")
def chat_reply_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    payload = chat_request_payload()
    phone = normalize_whatsapp_recipient(str(payload.get("phone", "")))
    message_text = str(payload.get("message", "")).strip()
    agent = str(payload.get("agent", "Admin")).strip() or "Admin"
    bot_handoff = parse_bool_flag(payload.get("bot_handoff", payload.get("automation_handoff", False)))

    if not is_valid_whatsapp_recipient(phone):
        return jsonify({"error": "Invalid WhatsApp phone number."}), 400
    if not message_text:
        return jsonify({"error": "Message is required."}), 400

    contact = find_chat_contact(phone)
    if contact and not contact.get("within_reply_window"):
        return jsonify({"error": "The 24-hour reply window is closed. Send an approved template instead."}), 400

    supabase_message_row_id = start_outgoing_chat_message(
        phone,
        message_type="text",
        message_text=message_text,
        agent=agent,
    )
    try:
        response_json = send_whatsapp_text_message(phone, message_text)
        message_id = extract_whatsapp_message_id(response_json)
    except Exception as exc:
        error = str(exc)
        logger.exception("Failed to send operator reply to %s: %s", phone, exc)
        if not finish_outgoing_chat_message(
            supabase_message_row_id,
            phone,
            message_type="text",
            message_text=message_text,
            status="failed",
            agent=agent,
            error=error,
        ):
            log_outgoing_chat_message(
                phone,
                message_type="text",
                message_text=message_text,
                status=f"failed: {error[:300]}",
                agent=agent,
            )
        return jsonify({"error": "Failed to send WhatsApp reply.", "details": error[:500]}), 502

    if not finish_outgoing_chat_message(
        supabase_message_row_id,
        phone,
        message_type="text",
        message_text=message_text,
        message_id=message_id,
        status="sent",
        agent=agent,
    ):
        log_outgoing_chat_message(
            phone,
            message_type="text",
            message_text=message_text,
            message_id=message_id,
            status="sent",
            agent=agent,
        )
    if bot_handoff:
        mark_automation_session(phone, source="operator_reply")
    else:
        mark_human_chat_session(phone, source="operator_reply")
    return jsonify({"sent": True, "message_id": message_id}), 200


@app.post("/api/admin/chat/media")
@app.post("/api/admin/chat/image")
def chat_media_upload_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    if request.content_length and request.content_length > OPERATOR_MEDIA_UPLOAD_MAX_BYTES + 1_000_000:
        return jsonify({"error": "Attachment is too large."}), 413

    payload = request.form
    phone = normalize_whatsapp_recipient(str(payload.get("phone", "")))
    caption = str(payload.get("caption", "")).strip()
    agent = str(payload.get("agent", "Admin")).strip() or "Admin"
    bot_handoff = parse_bool_flag(payload.get("bot_handoff", payload.get("automation_handoff", False)))
    media_file = request.files.get("media") or request.files.get("image")

    if not is_valid_whatsapp_recipient(phone):
        return jsonify({"error": "Invalid WhatsApp phone number."}), 400
    if not media_file or not media_file.filename:
        return jsonify({"error": "Image or PDF file is required."}), 400

    contact = find_chat_contact(phone)
    if contact and not contact.get("within_reply_window"):
        return jsonify({"error": "The 24-hour reply window is closed. Send an approved media template instead."}), 400

    original_filename = secure_filename(media_file.filename) or "attachment"
    media_mime_type = (
        media_file.mimetype or mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    ).split(";", 1)[0].lower()
    suffix = Path(original_filename).suffix.lower() or mimetypes.guess_extension(media_mime_type) or ".jpg"
    is_pdf = media_mime_type == "application/pdf" or suffix == ".pdf"
    is_image = media_mime_type.startswith("image/")
    if not is_image and not is_pdf:
        return jsonify({"error": "Only image and PDF uploads are supported."}), 400
    if is_pdf:
        media_mime_type = "application/pdf"
        suffix = ".pdf"

    message_type = "document" if is_pdf else "image"
    if is_pdf:
        message_label = f"PDF: {caption}" if caption else f"PDF sent: {original_filename}"
    else:
        message_label = f"Image: {caption}" if caption else "Image sent"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    temp_file.close()
    media_id = ""
    supabase_message_row_id = ""

    try:
        media_file.save(temp_path)
        if temp_path.stat().st_size > OPERATOR_MEDIA_UPLOAD_MAX_BYTES:
            return jsonify({"error": "Attachment is too large."}), 413
        if is_pdf:
            with temp_path.open("rb") as uploaded_pdf:
                if not uploaded_pdf.read(5).startswith(b"%PDF-"):
                    return jsonify({"error": "The selected file is not a valid PDF."}), 400

        supabase_message_row_id = start_outgoing_chat_message(
            phone,
            message_type=message_type,
            message_text=message_label,
            agent=agent,
            media_mime_type=media_mime_type,
            media_filename=original_filename,
        )
        media_id = upload_whatsapp_media(str(temp_path))
        if is_pdf:
            response_json = send_whatsapp_document_media_message(
                phone,
                media_id,
                filename=original_filename,
                caption=caption,
            )
        else:
            response_json = send_whatsapp_image_media_message(phone, media_id, caption=caption)
        message_id = extract_whatsapp_message_id(response_json)
    except Exception as exc:
        error = str(exc)
        logger.exception("Failed to send operator %s to %s: %s", message_type, phone, exc)
        if not finish_outgoing_chat_message(
            supabase_message_row_id,
            phone,
            message_type=message_type,
            message_text=message_label,
            status="failed",
            agent=agent,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=original_filename,
            error=error,
        ):
            log_outgoing_chat_message(
                phone,
                message_type=message_type,
                message_text=message_label,
                status=f"failed: {error[:300]}",
                agent=agent,
                media_id=media_id,
                media_mime_type=media_mime_type,
                media_filename=original_filename,
            )
        return jsonify({"error": f"Failed to send WhatsApp {message_type}.", "details": error[:500]}), 502
    finally:
        uploaded_media_ids.pop(str(temp_path), None)
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Could not remove temporary operator media upload: %s", temp_path)

    if not finish_outgoing_chat_message(
        supabase_message_row_id,
        phone,
        message_type=message_type,
        message_text=message_label,
        message_id=message_id,
        status="sent",
        agent=agent,
        media_id=media_id,
        media_mime_type=media_mime_type,
        media_filename=original_filename,
    ):
        log_outgoing_chat_message(
            phone,
            message_type=message_type,
            message_text=message_label,
            message_id=message_id,
            status="sent",
            agent=agent,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=original_filename,
        )
    if bot_handoff:
        mark_automation_session(phone, source="operator_media")
    else:
        mark_human_chat_session(phone, source="operator_media")
    return jsonify({"sent": True, "message_id": message_id, "media_id": media_id, "message_type": message_type}), 200


@app.get("/api/admin/chat/media/<media_id>")
def chat_media_api(media_id: str):
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    clean_media_id = str(media_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9:_-]{4,220}", clean_media_id):
        return jsonify({"error": "Invalid media ID."}), 400

    try:
        content, mime_type = download_whatsapp_media(clean_media_id)
    except Exception as exc:
        logger.exception("Failed to proxy WhatsApp media %s: %s", clean_media_id, exc)
        return jsonify({"error": "Failed to load WhatsApp media.", "details": str(exc)[:300]}), 502

    clean_mime_type = mime_type.split(";", 1)[0].strip().lower()
    if not clean_mime_type.startswith("image/") and clean_mime_type != "application/pdf":
        return jsonify({"error": "Only image and PDF media previews are supported."}), 415

    headers = {"Cache-Control": "private, max-age=300"}
    if clean_mime_type == "application/pdf":
        filename = secure_filename(str(request.args.get("name", ""))) or "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        headers["Content-Disposition"] = f'inline; filename="{filename[:240]}"'

    return Response(
        content,
        mimetype=clean_mime_type,
        headers=headers,
    )


@app.post("/api/admin/chat/template")
def chat_template_api():
    authorized, error_response = chat_api_authorized()
    if not authorized:
        return error_response

    payload = chat_request_payload()
    phone = normalize_whatsapp_recipient(str(payload.get("phone", "")))
    template_name = str(payload.get("template_name", BULK_MESSAGE_TEMPLATE_NAME)).strip()
    language_code = str(payload.get("language_code", BULK_MESSAGE_TEMPLATE_LANGUAGE)).strip() or "en_US"
    parameters = parse_template_parameters(payload.get("template_parameters", payload.get("body_parameters", "")))
    agent = str(payload.get("agent", "Admin")).strip() or "Admin"

    if not is_valid_whatsapp_recipient(phone):
        return jsonify({"error": "Invalid WhatsApp phone number."}), 400
    if not template_name:
        return jsonify({"error": "Template name is required."}), 400
    if not parameters:
        parameters = build_template_params_for_phone(template_name, phone)

    template_preview = f"Template: {template_name}"
    if parameters:
        template_preview = f"{template_preview}\n" + "\n".join(parameters)

    supabase_message_row_id = start_outgoing_chat_message(
        phone,
        message_type="template",
        message_text=template_preview,
        agent=agent,
        template_name=template_name,
    )
    try:
        response_json = send_whatsapp_template_message(
            phone,
            template_name,
            parameters,
            language_code=language_code,
        )
        message_id = extract_whatsapp_message_id(response_json)
    except Exception as exc:
        error = str(exc)
        logger.exception("Failed to send operator template %s to %s: %s", template_name, phone, exc)
        if not finish_outgoing_chat_message(
            supabase_message_row_id,
            phone,
            message_type="template",
            message_text=template_preview,
            status="failed",
            agent=agent,
            template_name=template_name,
            error=error,
        ):
            log_outgoing_chat_message(
                phone,
                message_type="template",
                message_text=template_preview,
                status=f"failed: {error[:300]}",
                agent=agent,
                template_name=template_name,
            )
        return jsonify({"error": "Failed to send WhatsApp template.", "details": error[:500]}), 502

    if not finish_outgoing_chat_message(
        supabase_message_row_id,
        phone,
        message_type="template",
        message_text=template_preview,
        message_id=message_id,
        status="sent",
        agent=agent,
        template_name=template_name,
    ):
        log_outgoing_chat_message(
            phone,
            message_type="template",
            message_text=template_preview,
            message_id=message_id,
            status="sent",
            agent=agent,
            template_name=template_name,
        )
    mark_automation_session(phone, source="operator_template")
    return jsonify({"sent": True, "message_id": message_id}), 200


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


def update_custom_message_result(
    worksheet,
    row_number: int,
    headers: list[str],
    *,
    checkbox_value: bool | None = None,
    status: str = "",
    sent_at: str = "",
    error: str = "",
) -> None:
    updates: Dict[str, Any] = {}
    if checkbox_value is not None:
        updates[CUSTOM_MESSAGE_TRIGGER_HEADER] = checkbox_value
    if status:
        updates[CUSTOM_MESSAGE_STATUS_HEADER] = status
    updates[CUSTOM_MESSAGE_SENT_AT_HEADER] = sent_at
    updates[CUSTOM_MESSAGE_ERROR_HEADER] = error[:500]

    for header, value in updates.items():
        if header not in headers:
            continue
        col_number = headers.index(header) + 1
        worksheet.update_cell(row_number, col_number, value)


def row_already_confirmed(record: Dict[str, str]) -> bool:
    status = (record.get(CONFIRMATION_STATUS_HEADER, "") or "").strip().lower()
    sent_at = (record.get(CONFIRMATION_SENT_AT_HEADER, "") or "").strip()
    return status == "sent" or bool(sent_at)


def is_offline_owner_order_record(record: Dict[str, str]) -> bool:
    return is_offline_order_email(get_record_value(record, "email"))


def send_offline_order_template_for_record(recipient: str, record: Dict[str, str]) -> Dict[str, Any]:
    return send_whatsapp_template_message(
        recipient,
        OFFLINE_ORDER_TEMPLATE_NAME,
        build_offline_order_template_params(record),
        language_code=OFFLINE_ORDER_TEMPLATE_LANGUAGE,
    )


def send_order_confirmation_for_record(recipient: str, record: Dict[str, str]) -> Dict[str, Any]:
    try:
        if ORDER_CONFIRMATION_TEMPLATE_NAME:
            return send_whatsapp_template_message(
                recipient,
                ORDER_CONFIRMATION_TEMPLATE_NAME,
                build_sheet_confirmation_template_params(record),
            )

        return send_whatsapp_text_message(recipient, build_sheet_order_confirmation_message(record))
    except requests.HTTPError as exc:
        if not ORDER_CONFIRMATION_TEMPLATE_NAME:
            raise

        response = exc.response
        payload: Dict[str, Any] = {}
        if response is not None:
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = str(error.get("code", "")).strip()
        message = str(error.get("message", "")).lower()
        if code != "131047" and "re-engagement" not in message:
            raise

        logger.warning("Sheet confirmation hit WhatsApp re-engagement rule; retrying with template.")
        return send_whatsapp_template_message(
            recipient,
            ORDER_CONFIRMATION_TEMPLATE_NAME,
            build_sheet_confirmation_template_params(record),
        )


def sheet_checkbox_is_checked(value: str) -> bool:
    return normalize_text(str(value)) in {"true", "yes", "y", "1", "checked"}


def get_status_step(status_key: str) -> Dict[str, Any] | None:
    normalized_status = normalize_text(status_key)
    for step in STATUS_UPDATE_STEPS:
        if normalized_status in {step["key"], normalize_text(step["label"])}:
            return step
    return None


def record_status_is_checked(record: Dict[str, str], step: Dict[str, Any]) -> bool:
    return any(sheet_checkbox_is_checked(record.get(header, "")) for header in step["headers"])


def checkbox_toggle_history_key(worksheet_title: str, row_number: int, header: str, order_id: str) -> str:
    normalized_title = normalize_text(worksheet_title) or "worksheet"
    normalized_header = normalize_text(header) or "checkbox"
    normalized_order_id = normalize_text(order_id) or "order"
    return f"{normalized_title}:{row_number}:{normalized_order_id}:{normalized_header}"


def checkbox_toggle_changed(
    worksheet_title: str,
    row_number: int,
    header: str,
    order_id: str,
    is_checked: bool,
) -> bool:
    key = checkbox_toggle_history_key(worksheet_title, row_number, header, order_id)
    current_state = "true" if is_checked else "false"
    with history_lock:
        toggle_states = message_history.setdefault("checkbox_toggle_states", {})
        previous_state = toggle_states.get(key)
        if previous_state is None:
            toggle_states[key] = current_state
            save_message_history()
            return False
        return previous_state != current_state


def mark_checkbox_toggle_state(
    worksheet_title: str,
    row_number: int,
    header: str,
    order_id: str,
    is_checked: bool,
) -> None:
    with history_lock:
        toggle_states = message_history.setdefault("checkbox_toggle_states", {})
        key = checkbox_toggle_history_key(worksheet_title, row_number, header, order_id)
        toggle_states[key] = "true" if is_checked else "false"
        save_message_history()


def custom_message_signature_key(worksheet_title: str, row_number: int, order_id: str) -> str:
    normalized_title = normalize_text(worksheet_title) or "worksheet"
    normalized_order_id = normalize_text(order_id) or "order"
    return f"{normalized_title}:{row_number}:{normalized_order_id}:custom-message"


def build_custom_message_signature(custom_message: str, is_checked: bool) -> str:
    normalized_message = (custom_message or "").strip()
    checkbox_state = "true" if is_checked else "false"
    return f"{checkbox_state}:{normalized_message}"


def last_custom_message_signature(worksheet_title: str, row_number: int, order_id: str) -> str:
    signatures = message_history.setdefault("custom_message_signatures", {})
    return str(signatures.get(custom_message_signature_key(worksheet_title, row_number, order_id), ""))


def mark_custom_message_signature(
    worksheet_title: str,
    row_number: int,
    order_id: str,
    custom_message: str,
    is_checked: bool,
) -> None:
    with history_lock:
        signatures = message_history.setdefault("custom_message_signatures", {})
        signatures[custom_message_signature_key(worksheet_title, row_number, order_id)] = build_custom_message_signature(
            custom_message,
            is_checked,
        )
        save_message_history()


def status_update_history_key(order_id: str, status_key: str) -> str:
    return f"{order_id}:{status_key}"


def status_update_already_sent(order_id: str, status_key: str) -> bool:
    sent_updates = message_history.setdefault("sent_status_updates", {})
    return status_update_history_key(order_id, status_key) in sent_updates


def mark_status_update_sent(order_id: str, status_key: str, *, message_id: str = "") -> None:
    with history_lock:
        sent_updates = message_history.setdefault("sent_status_updates", {})
        sent_updates[status_update_history_key(order_id, status_key)] = {
            "sent_at": local_now().isoformat(timespec="seconds"),
            "message_id": message_id,
        }
        save_message_history()


def build_order_status_update_message(record: Dict[str, str], step: Dict[str, Any], *, is_checked: bool = True) -> str:
    order_id = get_record_value(record, "order_id") or "-"
    customer_name = get_record_value(record, "customer_name") or "Customer"
    city = get_record_value(record, "city") or "-"
    product = get_record_value(record, "product") or get_record_value(record, "order_summary") or "-"
    total_amount = get_record_value(record, "total_amount") or "-"
    status_line = step["label"] if is_checked else f"{step['label']} Updated"
    intro_message = step["message"] if is_checked else f"Your Pulps & Leaves order update has changed for {step['label']}."

    return (
        f"Track Your Aam 🔍\n\n"
        f"Hello {customer_name},\n"
        f"{intro_message}\n\n"
        f"Order ID: {order_id}\n"
        f"Status: {status_line}\n"
        f"City: {city}\n"
        f"Order Summary: {product}\n"
        f"Total Amount: {total_amount}\n\n"
        "Thank you for choosing Pulps and Leaves."
    )


def build_order_delivered_template_params(record: Dict[str, str]) -> list[str]:
    return [
        get_record_value(record, "customer_name") or "Customer",
        GOOGLE_REVIEW_URL or "-",
        INSTAGRAM_URL or "-",
    ]


def send_order_status_update_for_record(
    recipient: str,
    record: Dict[str, str],
    step: Dict[str, Any],
    *,
    is_checked: bool = True,
) -> Dict[str, Any]:
    if step.get("key") == "delivered" and is_checked and ORDER_DELIVERED_TEMPLATE_NAME:
        return send_whatsapp_template_message(
            recipient,
            ORDER_DELIVERED_TEMPLATE_NAME,
            build_order_delivered_template_params(record),
            language_code=ORDER_DELIVERED_TEMPLATE_LANGUAGE,
        )

    return send_whatsapp_text_message(recipient, build_order_status_update_message(record, step, is_checked=is_checked))


def send_pending_order_confirmations(
    *,
    date_text: str | None = None,
    worksheet_name: str | None = None,
    order_id_filter: str | None = None,
    limit: int = 25,
    dry_run: bool = False,
) -> Dict[str, Any]:
    worksheets = (
        load_active_orders_worksheets()
        if not date_text and not worksheet_name
        else [load_daily_orders_worksheet(date_text=date_text, worksheet_name=worksheet_name)]
    )

    result: Dict[str, Any] = {
        "worksheets": [worksheet.title for worksheet in worksheets],
        "dry_run": dry_run,
        "sent": [],
        "failed": [],
        "skipped": [],
    }
    attempted_count = 0

    for worksheet in worksheets:
        headers = ensure_confirmation_columns(worksheet)
        rows = worksheet.get_all_values()[1:]

        for row_number, row_values in enumerate(rows, start=2):
            record = build_row_record(headers, row_values)
            order_id = get_record_value(record, "order_id")
            phone = get_record_value(record, "phone")

            if not any(str(value).strip() for value in row_values):
                continue
            if not order_id:
                continue

            if order_id_filter and order_id != order_id_filter:
                continue

            if row_already_confirmed(record):
                result["skipped"].append(
                    {"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "reason": "already_sent"}
                )
                continue

            if not phone:
                error = "Missing phone number."
                result["failed"].append({"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "error": error})
                if not dry_run:
                    update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
                continue

            recipient = normalize_whatsapp_recipient(phone)
            if not is_valid_whatsapp_recipient(recipient):
                error = f"Invalid WhatsApp recipient: {phone}"
                result["failed"].append({"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "error": error})
                if not dry_run:
                    update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
                continue

            if attempted_count >= limit:
                result["skipped"].append(
                    {"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "reason": "limit_reached"}
                )
                continue

            attempted_count += 1
            offline_owner_order = is_offline_owner_order_record(record)
            template_source = "offline_orders" if offline_owner_order else "order_confirmation"
            if dry_run:
                result["sent"].append(
                    {
                        "worksheet": worksheet.title,
                        "row": row_number,
                        "order_id": order_id,
                        "recipient": recipient,
                        "template": template_source,
                        "dry_run": True,
                    }
                )
                continue

            try:
                update_confirmation_result(worksheet, row_number, headers, status="Sending")
                response_json = (
                    send_offline_order_template_for_record(recipient, record)
                    if offline_owner_order
                    else send_order_confirmation_for_record(recipient, record)
                )
                message_id = extract_whatsapp_message_id(response_json)
                update_confirmation_result(
                    worksheet,
                    row_number,
                    headers,
                    status="Sent",
                    message_id=message_id,
                )
                mark_automation_session(recipient, source=template_source)
                result["sent"].append(
                    {
                        "worksheet": worksheet.title,
                        "row": row_number,
                        "order_id": order_id,
                        "recipient": recipient,
                        "template": template_source,
                        "message_id": message_id,
                    }
                )
            except Exception as exc:
                error = str(exc)
                logger.exception("Failed to send outbound order confirmation for row %s in %s: %s", row_number, worksheet.title, exc)
                update_confirmation_result(worksheet, row_number, headers, status="Failed", error=error)
                result["failed"].append(
                    {"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "recipient": recipient, "error": error}
                )

    result["sent_count"] = len(result["sent"])
    result["failed_count"] = len(result["failed"])
    result["skipped_count"] = len(result["skipped"])
    if order_id_filter and not result["sent"] and not result["failed"] and not result["skipped"]:
        result["not_found"] = order_id_filter
    return result


def send_pending_custom_messages(
    *,
    date_text: str | None = None,
    worksheet_name: str | None = None,
    order_id_filter: str | None = None,
    limit: int = 25,
    dry_run: bool = False,
) -> Dict[str, Any]:
    worksheets = (
        load_active_orders_worksheets()
        if not date_text and not worksheet_name
        else [load_daily_orders_worksheet(date_text=date_text, worksheet_name=worksheet_name)]
    )

    result: Dict[str, Any] = {
        "worksheets": [worksheet.title for worksheet in worksheets],
        "dry_run": dry_run,
        "sent": [],
        "failed": [],
        "skipped": [],
    }
    attempted_count = 0

    for worksheet in worksheets:
        headers = ensure_confirmation_columns(worksheet)
        rows = worksheet.get_all_values()[1:]

        for row_number, row_values in enumerate(rows, start=2):
            record = build_row_record(headers, row_values)
            order_id = get_record_value(record, "order_id")
            phone = get_record_value(record, "phone")
            custom_message = (record.get(CUSTOM_MESSAGE_HEADER, "") or "").strip()
            is_checked = sheet_checkbox_is_checked(record.get(CUSTOM_MESSAGE_TRIGGER_HEADER, ""))
            custom_message_status = normalize_text(record.get(CUSTOM_MESSAGE_STATUS_HEADER, ""))
            has_unsent_checked_message = is_checked and bool(custom_message) and custom_message_status != "sent"
            current_signature = build_custom_message_signature(custom_message, is_checked)
            signature_changed = last_custom_message_signature(worksheet.title, row_number, order_id) != current_signature

            if not any(str(value).strip() for value in row_values):
                continue
            if order_id_filter and order_id != order_id_filter:
                continue
            if not order_id:
                continue
            has_toggle_change = checkbox_toggle_changed(
                worksheet.title,
                row_number,
                CUSTOM_MESSAGE_TRIGGER_HEADER,
                order_id,
                is_checked,
            )
            if not is_checked:
                if not dry_run and (has_toggle_change or signature_changed):
                    mark_checkbox_toggle_state(
                        worksheet.title,
                        row_number,
                        CUSTOM_MESSAGE_TRIGGER_HEADER,
                        order_id,
                        is_checked,
                    )
                    mark_custom_message_signature(
                        worksheet.title,
                        row_number,
                        order_id,
                        custom_message,
                        is_checked,
                    )
                continue
            if not has_toggle_change and not has_unsent_checked_message and not signature_changed:
                continue

            if not phone:
                error = "Missing phone number."
                if not dry_run:
                    update_custom_message_result(worksheet, row_number, headers, status="Failed", error=error)
                    mark_checkbox_toggle_state(
                        worksheet.title,
                        row_number,
                        CUSTOM_MESSAGE_TRIGGER_HEADER,
                        order_id,
                        is_checked,
                    )
                result["failed"].append({"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "error": error})
                continue

            recipient = normalize_whatsapp_recipient(phone)
            if not is_valid_whatsapp_recipient(recipient):
                error = f"Invalid WhatsApp recipient: {phone}"
                if not dry_run:
                    update_custom_message_result(worksheet, row_number, headers, status="Failed", error=error)
                    mark_checkbox_toggle_state(
                        worksheet.title,
                        row_number,
                        CUSTOM_MESSAGE_TRIGGER_HEADER,
                        order_id,
                        is_checked,
                    )
                result["failed"].append({"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "error": error})
                continue

            if not custom_message:
                error = "Custom WhatsApp Message is empty."
                if not dry_run:
                    update_custom_message_result(worksheet, row_number, headers, status="Failed", error=error)
                    mark_checkbox_toggle_state(
                        worksheet.title,
                        row_number,
                        CUSTOM_MESSAGE_TRIGGER_HEADER,
                        order_id,
                        is_checked,
                    )
                result["failed"].append({"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "error": error})
                continue

            if attempted_count >= limit:
                result["skipped"].append(
                    {"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "reason": "limit_reached"}
                )
                continue

            attempted_count += 1
            if dry_run:
                result["sent"].append(
                    {"worksheet": worksheet.title, "row": row_number, "order_id": order_id, "recipient": recipient, "dry_run": True}
                )
                continue

            try:
                update_custom_message_result(worksheet, row_number, headers, status="Sending", error="")
                send_whatsapp_text_message(recipient, custom_message)
                update_custom_message_result(
                    worksheet,
                    row_number,
                    headers,
                    status="Sent",
                    sent_at=local_now().isoformat(timespec="seconds"),
                    error="",
                )
                mark_checkbox_toggle_state(
                    worksheet.title,
                    row_number,
                    CUSTOM_MESSAGE_TRIGGER_HEADER,
                    order_id,
                    is_checked,
                )
                mark_custom_message_signature(
                    worksheet.title,
                    row_number,
                    order_id,
                    custom_message,
                    is_checked,
                )
                mark_automation_session(recipient, source="sheet_custom_message")
                result["sent"].append(
                    {
                        "worksheet": worksheet.title,
                        "row": row_number,
                        "order_id": order_id,
                        "recipient": recipient,
                        "toggle_state": is_checked,
                    }
                )
            except Exception as exc:
                error = str(exc)
                logger.exception("Failed to send custom WhatsApp message for row %s in %s: %s", row_number, worksheet.title, exc)
                update_custom_message_result(worksheet, row_number, headers, status="Failed", error=error)
                mark_checkbox_toggle_state(
                    worksheet.title,
                    row_number,
                    CUSTOM_MESSAGE_TRIGGER_HEADER,
                    order_id,
                    is_checked,
                )
                result["failed"].append(
                    {
                        "worksheet": worksheet.title,
                        "row": row_number,
                        "order_id": order_id,
                        "recipient": recipient,
                        "toggle_state": is_checked,
                        "error": error,
                    }
                )

    result["sent_count"] = len(result["sent"])
    result["failed_count"] = len(result["failed"])
    result["skipped_count"] = len(result["skipped"])
    return result


def is_sheets_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, gspread.exceptions.APIError):
        return "[429]" in str(exc) or "quota" in str(exc).lower()
    message = str(exc).lower()
    return "quota exceeded" in message or "read requests per minute" in message


def auto_confirmation_worker() -> None:
    logger.info(
        "Auto-confirmation worker started with interval=%ss",
        AUTO_CONFIRMATIONS_INTERVAL_SECONDS,
    )
    while not confirmation_worker_stop.is_set():
        try:
            confirmation_result = send_pending_order_confirmations(limit=AUTO_CONFIRMATION_BATCH_LIMIT, dry_run=False)
            if confirmation_result.get("sent_count"):
                logger.info(
                    "Auto-confirmation worker sent %s confirmation(s).",
                    confirmation_result["sent_count"],
                )
            if confirmation_result.get("failed_count"):
                logger.warning(
                    "Auto-confirmation worker saw %s failed confirmation(s).",
                    confirmation_result["failed_count"],
                )

            status_result = send_pending_order_status_updates(limit=AUTO_STATUS_UPDATE_BATCH_LIMIT, dry_run=False)
            if status_result.get("sent_count"):
                logger.info(
                    "Auto-confirmation worker sent %s status update(s).",
                    status_result["sent_count"],
                )
            if status_result.get("failed_count"):
                logger.warning(
                    "Auto-confirmation worker saw %s failed status update(s).",
                    status_result["failed_count"],
                )

            custom_message_result = send_pending_custom_messages(limit=AUTO_CUSTOM_MESSAGE_BATCH_LIMIT, dry_run=False)
            if custom_message_result.get("sent_count"):
                logger.info(
                    "Auto-confirmation worker sent %s custom message(s).",
                    custom_message_result["sent_count"],
                )
            if custom_message_result.get("failed_count"):
                logger.warning(
                    "Auto-confirmation worker saw %s failed custom message(s).",
                    custom_message_result["failed_count"],
                )
        except Exception as exc:
            if is_sheets_rate_limit_error(exc):
                logger.warning(
                    "Auto-confirmation worker hit Google Sheets rate limit; backing off for %ss.",
                    SHEETS_RATE_LIMIT_BACKOFF_SECONDS,
                )
                confirmation_worker_stop.wait(SHEETS_RATE_LIMIT_BACKOFF_SECONDS)
                continue
            logger.warning("Auto-confirmation worker iteration failed: %s", exc)

        confirmation_worker_stop.wait(AUTO_CONFIRMATIONS_INTERVAL_SECONDS)


def ensure_confirmation_worker_started() -> None:
    global confirmation_worker_thread

    if not AUTO_CONFIRMATIONS_ENABLED:
        logger.info("Auto-confirmation worker disabled by AUTO_CONFIRMATIONS_ENABLED.")
        return

    with confirmation_worker_lock:
        if confirmation_worker_thread and confirmation_worker_thread.is_alive():
            return

        confirmation_worker_stop.clear()
        confirmation_worker_thread = Thread(
            target=auto_confirmation_worker,
            name="order-confirmation-worker",
            daemon=True,
        )
        confirmation_worker_thread.start()


def send_pending_order_status_updates(
    *,
    date_text: str | None = None,
    worksheet_name: str | None = None,
    order_id_filter: str | None = None,
    status_filter: str | None = None,
    limit: int = 25,
    dry_run: bool = False,
) -> Dict[str, Any]:
    selected_step = get_status_step(status_filter or "") if status_filter else None
    if status_filter and not selected_step:
        raise ValueError("Invalid status. Use confirmed, packed, delivered, or cancelled.")

    worksheets = (
        load_active_orders_worksheets()
        if not date_text and not worksheet_name
        else [load_daily_orders_worksheet(date_text=date_text, worksheet_name=worksheet_name)]
    )
    steps = [selected_step] if selected_step else STATUS_UPDATE_STEPS
    result: Dict[str, Any] = {
        "worksheets": [worksheet.title for worksheet in worksheets],
        "dry_run": dry_run,
        "sent": [],
        "failed": [],
        "skipped": [],
    }
    attempted_count = 0

    for worksheet in worksheets:
        headers = ensure_confirmation_columns(worksheet)
        rows = worksheet.get_all_values()[1:]

        for row_number, row_values in enumerate(rows, start=2):
            record = build_row_record(headers, row_values)
            order_id = get_record_value(record, "order_id")
            phone = get_record_value(record, "phone")

            if not order_id or not any(str(value).strip() for value in row_values):
                continue

            if order_id_filter and order_id != order_id_filter:
                continue

            for step in steps:
                header_name = next((header for header in step["headers"] if header in headers), step["headers"][0])
                is_checked = record_status_is_checked(record, step)
                if not checkbox_toggle_changed(worksheet.title, row_number, header_name, order_id, is_checked):
                    continue

                if not phone:
                    result["failed"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "error": "Missing phone number.",
                        }
                    )
                    continue

                recipient = normalize_whatsapp_recipient(phone)
                if not is_valid_whatsapp_recipient(recipient):
                    result["failed"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "error": f"Invalid WhatsApp recipient: {phone}",
                        }
                    )
                    continue

                if attempted_count >= limit:
                    result["skipped"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "reason": "limit_reached",
                        }
                    )
                    continue

                attempted_count += 1
                if dry_run:
                    result["sent"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "recipient": recipient,
                            "dry_run": True,
                        }
                    )
                    continue

                try:
                    response_json = send_order_status_update_for_record(recipient, record, step, is_checked=is_checked)
                    message_id = extract_whatsapp_message_id(response_json)
                    mark_checkbox_toggle_state(worksheet.title, row_number, header_name, order_id, is_checked)
                    mark_automation_session(recipient, source=f"status_update:{step['key']}")
                    result["sent"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "recipient": recipient,
                            "message_id": message_id,
                        }
                    )
                except Exception as exc:
                    error = str(exc)
                    logger.exception(
                        "Failed to send %s update for row %s in %s: %s",
                        step["key"],
                        row_number,
                        worksheet.title,
                        exc,
                    )
                    mark_checkbox_toggle_state(worksheet.title, row_number, header_name, order_id, is_checked)
                    result["failed"].append(
                        {
                            "worksheet": worksheet.title,
                            "row": row_number,
                            "order_id": order_id,
                            "status": step["key"],
                            "toggle_state": is_checked,
                            "recipient": recipient,
                            "error": error,
                        }
                    )

    result["sent_count"] = len(result["sent"])
    result["failed_count"] = len(result["failed"])
    result["skipped_count"] = len(result["skipped"])
    if order_id_filter and not result["sent"] and not result["failed"] and not result["skipped"]:
        result["not_found"] = order_id_filter
    return result


def extract_whatsapp_messages(payload: Dict[str, Any]):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                yield message


def extract_whatsapp_contact_names(payload: Dict[str, Any]) -> Dict[str, str]:
    contact_names: Dict[str, str] = {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for contact in value.get("contacts", []):
                wa_id = normalize_whatsapp_recipient(str(contact.get("wa_id", "")))
                profile = contact.get("profile", {}) if isinstance(contact, dict) else {}
                name = str(profile.get("name", "")).strip() if isinstance(profile, dict) else ""
                if wa_id and name:
                    contact_names[wa_id] = name
    return contact_names


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


def process_webhook_payload(payload: Dict[str, Any]) -> None:
    try:
        logger.info("Processing webhook payload: %s", json.dumps(payload))
        sync_whatsapp_statuses_from_webhook(payload)
        try:
            sync_supabase_chat_statuses_from_webhook(payload)
        except Exception as exc:  # noqa: BLE001 - status sync should not block inbound chat processing
            logger.warning("Failed to sync WhatsApp status webhook to Supabase chat: %s", exc)
        contact_names = extract_whatsapp_contact_names(payload)

        for message in extract_whatsapp_messages(payload):
            user_phone = message.get("from")
            message_id = message.get("id", "")

            if not user_phone:
                logger.info("Skipping unsupported or empty message payload.")
                continue

            if is_duplicate_processed_message(message_id):
                logger.info("Skipping duplicate WhatsApp message id=%s", message_id)
                continue

            profile_name = contact_names.get(normalize_whatsapp_recipient(user_phone), "")
            message_type = str(message.get("type", "")).strip()
            message_preview = extract_contact_message_preview(message)
            media_details = extract_message_media_details(message)
            was_known_contact = remember_contact(user_phone, profile_name)
            try:
                record_inbound_chat_message(
                    user_phone,
                    profile_name=profile_name,
                    message_type=message_type,
                    message_text=message_preview,
                    message_id=message_id,
                    **media_details,
                )
            except Exception as exc:  # noqa: BLE001 - contact logging should not break bot replies
                logger.exception("Failed to store inbound WhatsApp message %s: %s", user_phone, exc)

            if process_whatsapp_flow_reply(user_phone, message):
                mark_message_processed(message_id)
                continue

            message_text = extract_message_text(message)
            if not message_text:
                logger.info("Skipping unsupported or empty message payload.")
                mark_message_processed(message_id)
                continue

            process_user_message(
                user_phone,
                message_text,
                is_returning_customer=was_known_contact,
                customer_name=profile_name,
            )
            mark_message_processed(message_id)
    except ConfigurationError as exc:
        logger.exception("Configuration error: %s", exc)
    except requests.RequestException as exc:
        logger.exception("WhatsApp API error: %s", exc)
    except Exception as exc:
        logger.exception("Unexpected error while processing webhook: %s", exc)


def webhook_queue_worker() -> None:
    logger.info("WhatsApp webhook queue worker started.")
    while True:
        payload = webhook_processing_queue.get()
        try:
            process_webhook_payload(payload)
        finally:
            webhook_processing_queue.task_done()


def ensure_webhook_worker_started() -> None:
    global webhook_worker_thread

    with webhook_worker_lock:
        if webhook_worker_thread and webhook_worker_thread.is_alive():
            return
        webhook_worker_thread = Thread(
            target=webhook_queue_worker,
            name="whatsapp-webhook-worker",
            daemon=True,
        )
        webhook_worker_thread.start()


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    logger.info("Incoming webhook payload queued.")
    ensure_webhook_worker_started()

    try:
        webhook_processing_queue.put_nowait(payload)
    except Full:
        logger.error("WhatsApp webhook queue is full; asking Meta to retry.")
        return jsonify({"error": "Webhook queue is full. Please retry."}), 503

    return jsonify({"status": "queued"}), 200


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
    order_id = (request.args.get("order_id") or "").strip()

    try:
        result = send_pending_order_confirmations(
            date_text=date_text,
            worksheet_name=worksheet_name,
            order_id_filter=order_id or None,
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


@app.post("/send-order-status-updates")
def send_order_status_updates_endpoint():
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
    order_id = (request.args.get("order_id") or "").strip()
    status = (request.args.get("status") or "").strip()

    try:
        result = send_pending_order_status_updates(
            date_text=date_text,
            worksheet_name=worksheet_name,
            order_id_filter=order_id or None,
            status_filter=status or None,
            limit=limit,
            dry_run=dry_run,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except gspread.WorksheetNotFound:
        target_worksheet_name = resolve_orders_worksheet_name(date_text=date_text, worksheet_name=worksheet_name)
        return jsonify({"error": f"Worksheet '{target_worksheet_name}' was not found."}), 404
    except ConfigurationError as exc:
        logger.exception("Configuration error while sending order status updates: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.exception("Unexpected error while sending order status updates: %s", exc)
        return jsonify({"error": "Failed to send order status updates"}), 500

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


ensure_confirmation_worker_started()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
