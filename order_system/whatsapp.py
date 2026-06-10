import hashlib
import hmac
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .config import ConfigurationError, settings
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

    _uploaded_media_ids: dict[str, str] = {}

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

    def _runtime_path(self, file_path: str) -> Path:
        path = Path(file_path).expanduser()
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parent.parent / path

    def upload_media(self, file_path: str) -> str:
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            raise ConfigurationError("Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID.")

        media_path = self._runtime_path(file_path)
        normalized_path = str(media_path)
        if normalized_path in self._uploaded_media_ids:
            return self._uploaded_media_ids[normalized_path]
        if not media_path.exists():
            raise ConfigurationError(f"WhatsApp template header image not found at '{media_path}'.")

        url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
            f"{settings.whatsapp_phone_number_id}/media"
        )
        mime_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        with media_path.open("rb") as file_handle:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                data={"messaging_product": "whatsapp"},
                files={"file": (media_path.name, file_handle, mime_type)},
                params=self._params(),
                timeout=60,
            )

        if not response.ok:
            logger.error("WhatsApp media upload failed: %s", response.text)
            response.raise_for_status()

        media_id = str(response.json().get("id") or "")
        if not media_id:
            raise ConfigurationError("WhatsApp media upload succeeded but no media id was returned.")
        self._uploaded_media_ids[normalized_path] = media_id
        return media_id

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

    def send_template_by_name(
        self,
        recipient: str,
        template_name: str,
        *,
        language_code: str = "en_US",
        body_parameters: list[str] | None = None,
    ) -> dict[str, Any]:
        parameters = [str(value).strip() for value in body_parameters or [] if str(value).strip()]
        clean_template_name = template_name.strip()
        language_code = self._template_language(clean_template_name, language_code)
        header_image_id, header_image_url = self._template_header_image(clean_template_name)
        template: dict[str, Any] = {
            "name": clean_template_name,
            "language": {"code": language_code},
        }
        components: list[dict[str, Any]] = []
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
                    "parameters": [{"type": "text", "text": value[:1024]} for value in parameters],
                }
            )
        if components:
            template["components"] = components

        return self._post_message(
            {
                "messaging_product": "whatsapp",
                "to": normalize_whatsapp_number(recipient),
                "type": "template",
                "template": template,
            }
        )

    def _template_language(self, template_name: str, language_code: str) -> str:
        if template_name == settings.order_confirmation_template_name:
            return settings.order_confirmation_template_language
        if template_name == settings.offline_order_template_name:
            return settings.offline_order_template_language
        if template_name == settings.order_delivered_template_name:
            return settings.order_delivered_template_language
        return language_code or "en_US"

    def _template_header_image(self, template_name: str) -> tuple[str, str]:
        if template_name == settings.offline_order_template_name:
            return self._configured_template_header(
                image_id=settings.offline_order_header_image_id,
                image_url=settings.offline_order_header_image_url,
                image_path=settings.offline_order_header_image_path,
            )
        if template_name == settings.order_delivered_template_name:
            return self._configured_template_header(
                image_id=settings.order_delivered_header_image_id,
                image_url=settings.order_delivered_header_image_url,
                image_path=settings.order_delivered_header_image_path,
            )
        return "", ""

    def _configured_template_header(self, *, image_id: str, image_url: str, image_path: str) -> tuple[str, str]:
        if image_id or image_url:
            return image_id, image_url
        if image_path:
            return self.upload_media(image_path), ""
        return "", ""

    def send_template(self, recipient: str, order: Order) -> dict[str, Any]:
        if not settings.order_confirmation_template_name:
            raise ConfigurationError("ORDER_CONFIRMATION_TEMPLATE_NAME is not configured.")

        amount_text = (
            str(int(order.total_amount))
            if float(order.total_amount).is_integer()
            else str(order.total_amount)
        )
        parameters = [
            order.customer_name or "Customer",
            order.product_name or "Malda Mangoes",
            str(order.quantity or 1),
            amount_text,
            order.payment_method or "COD",
            order.delivery_address or "-",
            order.order_id or "-",
        ]
        return self.send_template_by_name(
            recipient,
            settings.order_confirmation_template_name,
            language_code=settings.order_confirmation_template_language,
            body_parameters=parameters,
        )

    def send_offline_order_template(self, recipient: str, order: Order) -> dict[str, Any]:
        parameters = [
            order.customer_name or "Customer",
            settings.google_review_url or "-",
            settings.instagram_url or "-",
        ]
        return self.send_template_by_name(
            recipient,
            settings.offline_order_template_name,
            language_code=settings.offline_order_template_language,
            body_parameters=parameters,
        )

    def build_order_confirmation_text(self, order: Order) -> str:
        total_amount_text = f"Rs {int(order.total_amount) if float(order.total_amount).is_integer() else order.total_amount}"
        return (
            f"Namaskar {order.customer_name} !! 🙏\n\n"
            "🥭 Your mango order is confirmed! Our mangoes are currently getting VIP treatment before reaching your home.\n\n"
            "🧾 Order Details\n\n"
            f"Order ID: {order.order_id}\n"
            f"Product: {order.product_name}\n"
            f"Quantity: {order.quantity} Boxes\n"
            f"Total Amount: {total_amount_text}\n\n"
            "📍 Delivery Address\n"
            f"{order.delivery_address}\n\n"
            "⏳ Current Status\n"
            f"{order.order_status}\n\n"
            f"📳 Payment Mode {order.payment_method}\n\n"
            "Thank you for choosing Pulps & Leaves !! 🥰 🥭"
        )

    def send_order_confirmation(self, order: Order) -> tuple[str, str]:
        try:
            response_json = self.send_template(order.phone_number, order)
        except Exception as exc:
            if not is_reengagement_error(exc):
                raise
            logger.warning(
                "Order confirmation hit WhatsApp re-engagement rule for %s; retrying with template.",
                order.order_id,
            )
            response_json = self.send_template(order.phone_number, order)
        return self.message_id(response_json), datetime.now().isoformat(timespec="seconds")

    def send_offline_order_confirmation(self, order: Order) -> tuple[str, str]:
        response_json = self.send_offline_order_template(order.phone_number, order)
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
