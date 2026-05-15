import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any

import requests

from .config import ConfigurationError, settings
from .locations import city_delivery_slot, city_message
from .models import Order
from .utils import format_rupees, normalize_whatsapp_number

logger = logging.getLogger(__name__)


def is_reengagement_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.HTTPError):
        return False

    response = exc.response
    if response is None:
        return False

    try:
        payload = response.json()
    except ValueError:
        return False

    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = str(error.get("code", "")).strip()
    message = str(error.get("message", "")).lower()
    return code == "131047" or "re-engagement" in message


class WhatsAppClient:
    """Official WhatsApp Cloud API client."""

    def _params(self) -> dict[str, str]:
        if not settings.meta_app_secret or not settings.whatsapp_access_token:
            return {}
        proof = hmac.new(
            settings.meta_app_secret.encode("utf-8"),
            settings.whatsapp_access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"appsecret_proof": proof}

    def _post_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            raise ConfigurationError("Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID.")

        url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
            f"{settings.whatsapp_phone_number_id}/messages"
        )
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.whatsapp_access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            params=self._params(),
            timeout=30,
        )
        if not response.ok:
            logger.error("WhatsApp API send failed: %s", response.text)
            response.raise_for_status()
        return response.json()

    @staticmethod
    def message_id(response_json: dict[str, Any]) -> str:
        messages = response_json.get("messages") or []
        if messages and isinstance(messages[0], dict):
            return str(messages[0].get("id", ""))
        return ""

    def send_text(self, recipient: str, body: str) -> dict[str, Any]:
        return self._post_message(
            {
                "messaging_product": "whatsapp",
                "to": normalize_whatsapp_number(recipient),
                "type": "text",
                "text": {"preview_url": False, "body": body},
            }
        )

    def send_template(self, recipient: str, order: Order) -> dict[str, Any]:
        if not settings.order_confirmation_template_name:
            raise ConfigurationError("ORDER_CONFIRMATION_TEMPLATE_NAME is not configured.")

        parameters = [
            order.customer_name,
            order.order_id,
            order.product_name,
            str(order.quantity),
            format_rupees(order.total_amount),
            order.delivery_address,
            order.order_status,
        ]
        return self._post_message(
            {
                "messaging_product": "whatsapp",
                "to": normalize_whatsapp_number(order.phone_number),
                "type": "template",
                "template": {
                    "name": settings.order_confirmation_template_name,
                    "language": {"code": settings.order_confirmation_template_language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": value[:1024]} for value in parameters],
                        }
                    ],
                },
            }
        )

    def build_order_confirmation_text(self, order: Order) -> str:
        delivery_slot = city_delivery_slot(order.city)
        city_note = city_message(order.city)
        return (
            f"Hello {order.customer_name} 👋\n\n"
            "Thank you for choosing Pulps & Leaves 🥭\n\n"
            "Your order has been received successfully and is now being prepared with care.\n\n"
            "🧾 Order Details\n\n"
            f"Order ID: {order.order_id}\n"
            f"Product: {order.product_name}\n"
            f"Quantity: {order.quantity} Boxes\n"
            f"Total Amount: {format_rupees(order.total_amount)}\n\n"
            f"City: {order.city or '-'}\n"
            f"Delivery Slot: {delivery_slot or 'Will be shared soon'}\n\n"
            "📍 Delivery Address\n"
            f"{order.delivery_address}\n\n"
            "⏳ Current Status\n"
            f"{order.order_status}\n\n"
            f"{city_note}\n\n"
            "— Team Pulps & Leaves\n"
            "Pure. Fresh. Honest."
        )

    def send_order_confirmation(self, order: Order) -> tuple[str, str]:
        try:
            response_json = (
                self.send_template(order.phone_number, order)
                if settings.order_confirmation_template_name
                else self.send_text(order.phone_number, self.build_order_confirmation_text(order))
            )
        except Exception as exc:
            if not settings.order_confirmation_template_name:
                raise
            if not is_reengagement_error(exc):
                raise
            logger.warning(
                "Free-form order confirmation hit WhatsApp re-engagement rule for %s; retrying with template.",
                order.order_id,
            )
            response_json = self.send_template(order.phone_number, order)
        return self.message_id(response_json), datetime.now().isoformat(timespec="seconds")

    def send_admin_alert(self, order: Order) -> None:
        if not settings.admin_whatsapp_number:
            return

        alert = (
            "🥭 New Pulps & Leaves order received\n\n"
            f"Order ID: {order.order_id}\n"
            f"Customer: {order.customer_name}\n"
            f"Phone: {order.phone_number}\n"
            f"Items: {order.product_name} x {order.quantity}\n"
            f"Total: {format_rupees(order.total_amount)}\n"
            f"Payment: {order.payment_method}"
        )
        self.send_text(settings.admin_whatsapp_number, alert)
