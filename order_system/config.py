import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


def parse_service_account_json(raw_value: str) -> dict[str, Any]:
    """Accept JSON, double-encoded JSON, or Python-dict-like env values."""
    cleaned_value = (raw_value or "").strip()
    if not cleaned_value:
        raise ConfigurationError("GOOGLE_CREDENTIALS_JSON is empty.")

    for _ in range(2):
        parsed = json.loads(cleaned_value)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            cleaned_value = parsed.strip()
            continue
        break

    parsed = ast.literal_eval(cleaned_value)
    if isinstance(parsed, dict):
        return parsed

    raise ConfigurationError("GOOGLE_CREDENTIALS_JSON is not a service-account JSON object.")


@dataclass(frozen=True)
class Settings:
    brand_name: str = os.getenv("BRAND_NAME", "Pulps & Leaves")
    google_sheet_name: str = os.getenv("GOOGLE_SHEET_NAME", "PulpsAndLeavesOrders")
    google_sheet_id: str = os.getenv("GOOGLE_SHEET_ID", "").strip()
    google_worksheet_name: str = os.getenv("ECOMMERCE_ORDERS_WORKSHEET_NAME", os.getenv("GOOGLE_WORKSHEET_NAME", "orders"))
    google_daily_worksheet_prefix: str = os.getenv("GOOGLE_DAILY_WORKSHEET_PREFIX", google_worksheet_name)
    local_timezone: str = os.getenv("LOCAL_TIMEZONE", "Asia/Kolkata")
    google_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
    google_credentials_json: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    sqlite_path: str = os.getenv("ORDER_SQLITE_PATH", os.getenv("SQLITE_DB_PATH", "/tmp/pulps_orders.db"))
    whatsapp_access_token: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    whatsapp_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    whatsapp_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v19.0")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "").strip()
    admin_whatsapp_number: str = os.getenv("ADMIN_WHATSAPP_NUMBER", os.getenv("SUPPORT_NUMBER", "")).strip()
    order_confirmation_template_name: str = os.getenv("ORDER_CONFIRMATION_TEMPLATE_NAME", "").strip()
    order_confirmation_template_language: str = os.getenv("ORDER_CONFIRMATION_TEMPLATE_LANGUAGE", "en_US").strip()
    admin_dashboard_token: str = os.getenv(
        "ADMIN_DASHBOARD_TOKEN",
        os.getenv("OUTBOUND_CONFIRMATION_SECRET", os.getenv("WHATSAPP_VERIFY_TOKEN", "")),
    ).strip()
    order_api_secret: str = os.getenv("ORDER_API_SECRET", "").strip()

    @property
    def sqlite_file(self) -> Path:
        return Path(self.sqlite_path).expanduser()


settings = Settings()
