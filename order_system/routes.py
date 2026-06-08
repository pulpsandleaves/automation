import logging
import re
from typing import Any

import requests
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from .config import ConfigurationError, settings
from .locations import CITY_DETAILS, city_choices, city_message, city_picker_options
from .services import OrderService
from .utils import normalize_whatsapp_number
from .whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)

order_blueprint = Blueprint("order_system", __name__)


def service() -> OrderService:
    return OrderService()


def request_payload() -> dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def require_api_secret() -> tuple[bool, str]:
    if not settings.order_api_secret:
        return True, ""
    token = request.headers.get("X-Order-Api-Key", "") or request.args.get("token", "")
    return (token == settings.order_api_secret, "Invalid or missing X-Order-Api-Key.")


def require_admin_token() -> tuple[bool, str]:
    if not settings.admin_dashboard_token:
        return True, ""
    token = request.headers.get("X-Admin-Token", "") or request.args.get("token", "") or request.form.get("token", "")
    if not token and request.is_json:
        payload = request.get_json(silent=True) or {}
        token = str(payload.get("token", ""))
    return (token == settings.admin_dashboard_token, "Invalid or missing admin token.")


def current_admin_token() -> str:
    return (request.args.get("token", "") or request.form.get("token", "")).strip()


def is_valid_bulk_recipient(value: str) -> bool:
    return bool(re.fullmatch(r"91[6-9]\d{9}", normalize_whatsapp_number(value)))


def parse_bulk_whatsapp_numbers(raw_numbers: str) -> tuple[list[str], list[str]]:
    recipients: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for part in re.split(r"[,;\n]+", raw_numbers or ""):
        cleaned_part = part.strip()
        if not cleaned_part:
            continue

        squashed_part = re.sub(r"[\s().-]+", "", cleaned_part)
        candidates = re.findall(r"(?:\+?91)?[6-9]\d{9}", squashed_part) or [cleaned_part]
        for candidate in candidates:
            recipient = normalize_whatsapp_number(candidate)
            if not is_valid_bulk_recipient(recipient):
                invalid.append(cleaned_part)
                continue
            if recipient in seen:
                continue
            seen.add(recipient)
            recipients.append(recipient)

    return recipients, invalid


def template_parameters_from_text(raw_parameters: str) -> list[str]:
    return [line.strip() for line in (raw_parameters or "").splitlines() if line.strip()]


def describe_whatsapp_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            payload = exc.response.json()
        except ValueError:
            return exc.response.text[:500]
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message", "")).strip()
        code = str(error.get("code", "")).strip()
        error_data = error.get("error_data", {}) if isinstance(error, dict) else {}
        details = str(error_data.get("details", "")).strip() if isinstance(error_data, dict) else str(error_data).strip()
        return " | ".join(part for part in (message, details, f"code {code}" if code else "") if part)[:500]
    return str(exc)[:500]


def build_admin_context(**extra: Any) -> dict[str, Any]:
    search = request.values.get("search", "").strip()
    status = request.values.get("status", "").strip()
    context = {
        "brand_name": settings.brand_name,
        "orders": service().list_orders(search=search, status=status),
        "search": search,
        "status": status,
        "admin_token": current_admin_token(),
        "bulk_form": {
            "template_name": settings.bulk_message_template_name,
            "language_code": settings.bulk_message_template_language,
            "phone_numbers": "",
            "template_parameters": "",
            "dry_run": False,
        },
        "bulk_result": None,
    }
    context.update(extra)
    return context


def send_bulk_template_messages(
    phone_numbers: str,
    template_name: str,
    language_code: str,
    body_parameters: list[str],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_template_name = (template_name or "").strip()
    clean_language_code = (language_code or settings.bulk_message_template_language).strip() or "en_US"
    if not clean_template_name:
        raise ValueError("Template name is required.")

    recipients, invalid_numbers = parse_bulk_whatsapp_numbers(phone_numbers)
    if len(recipients) > 200:
        raise ValueError("Bulk sends are limited to 200 recipients at a time.")

    client = WhatsAppClient()
    result: dict[str, Any] = {
        "template_name": clean_template_name,
        "language_code": clean_language_code,
        "dry_run": dry_run,
        "sent": [],
        "failed": [],
        "skipped": [{"recipient": value, "reason": "Invalid Indian WhatsApp number"} for value in invalid_numbers],
    }

    for recipient in recipients:
        if dry_run:
            result["sent"].append({"recipient": recipient, "status": "Ready"})
            continue

        try:
            response_json = client.send_template_by_name(
                recipient,
                clean_template_name,
                language_code=clean_language_code,
                body_parameters=body_parameters,
            )
            result["sent"].append(
                {
                    "recipient": recipient,
                    "status": "Sent",
                    "message_id": client.message_id(response_json),
                }
            )
        except Exception as exc:  # noqa: BLE001 - each recipient needs its own result row
            logger.exception("Failed to send template %s to %s: %s", clean_template_name, recipient, exc)
            result["failed"].append(
                {
                    "recipient": recipient,
                    "status": "Failed",
                    "error": describe_whatsapp_error(exc),
                }
            )

    result["sent_count"] = len(result["sent"])
    result["failed_count"] = len(result["failed"])
    result["skipped_count"] = len(result["skipped"])
    result["recipient_count"] = len(recipients)
    return result


@order_blueprint.get("/")
@order_blueprint.get("/checkout")
def checkout_page():
    default_city = city_choices()[0] if city_choices() else ""
    return render_template(
        "checkout.html",
        brand_name=settings.brand_name,
        city_choices=city_choices(),
        city_options=city_picker_options(),
        city_messages={city: details["message"] for city, details in CITY_DETAILS.items()},
        selected_city=default_city,
        selected_city_message=city_message(default_city),
    )


@order_blueprint.post("/checkout")
def checkout_submit():
    try:
        result = service().create_order(request_payload())
    except ValueError as exc:
        payload = request_payload()
        selected_city = str(payload.get("city", "")).strip()
        return render_template(
            "checkout.html",
            brand_name=settings.brand_name,
            city_choices=city_choices(),
            city_options=city_picker_options(),
            city_messages={city: details["message"] for city, details in CITY_DETAILS.items()},
            selected_city=selected_city,
            selected_city_message=city_message(selected_city or (city_choices()[0] if city_choices() else "")),
            error=str(exc),
        ), 400
    except ConfigurationError as exc:
        logger.exception("Checkout configuration error: %s", exc)
        payload = request_payload()
        selected_city = str(payload.get("city", "")).strip()
        return render_template(
            "checkout.html",
            brand_name=settings.brand_name,
            city_choices=city_choices(),
            city_options=city_picker_options(),
            city_messages={city: details["message"] for city, details in CITY_DETAILS.items()},
            selected_city=selected_city,
            selected_city_message=city_message(selected_city or (city_choices()[0] if city_choices() else "")),
            error=str(exc),
        ), 500
    except Exception as exc:
        logger.exception("Checkout failed: %s", exc)
        payload = request_payload()
        selected_city = str(payload.get("city", "")).strip()
        return render_template(
            "checkout.html",
            brand_name=settings.brand_name,
            city_choices=city_choices(),
            city_options=city_picker_options(),
            city_messages={city: details["message"] for city, details in CITY_DETAILS.items()},
            selected_city=selected_city,
            selected_city_message=city_message(selected_city or (city_choices()[0] if city_choices() else "")),
            error="Order saved failed. Please try again or contact support.",
        ), 500

    return render_template("order_success.html", result=result, brand_name=settings.brand_name)


@order_blueprint.post("/api/orders")
def create_order_api():
    allowed, error = require_api_secret()
    if not allowed:
        return jsonify({"error": error}), 401

    try:
        result = service().create_order(request_payload())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ConfigurationError as exc:
        logger.exception("Order API configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.exception("Order API failed: %s", exc)
        return jsonify({"error": "Failed to create order."}), 500

    return jsonify(result), 201


@order_blueprint.post("/api/orders/confirm-latest")
def confirm_latest_order_api():
    allowed, error = require_api_secret()
    if not allowed:
        return jsonify({"error": error}), 401

    try:
        result = service().confirm_latest_sheet_order()
    except Exception as exc:
        logger.exception("Latest order confirmation failed: %s", exc)
        return jsonify({"error": "Failed to confirm latest order."}), 500

    return jsonify(result), 200


@order_blueprint.get("/admin")
def admin_dashboard():
    allowed, error = require_admin_token()
    if not allowed:
        return jsonify({"error": error}), 401

    return render_template("admin.html", **build_admin_context())


@order_blueprint.post("/admin/send-template")
def admin_send_template():
    allowed, error = require_admin_token()
    if not allowed:
        return jsonify({"error": error}), 401

    payload = request_payload()
    raw_parameters = payload.get("template_parameters", "")
    body_parameters = (
        [str(value).strip() for value in raw_parameters if str(value).strip()]
        if isinstance(raw_parameters, list)
        else template_parameters_from_text(str(raw_parameters))
    )
    dry_run = str(payload.get("dry_run", "")).strip().lower() in {"1", "true", "yes", "on"}
    bulk_form = {
        "template_name": str(payload.get("template_name", settings.bulk_message_template_name)).strip(),
        "language_code": str(payload.get("language_code", settings.bulk_message_template_language)).strip(),
        "phone_numbers": str(payload.get("phone_numbers", "")),
        "template_parameters": "\n".join(body_parameters),
        "dry_run": dry_run,
    }

    try:
        bulk_result = send_bulk_template_messages(
            bulk_form["phone_numbers"],
            bulk_form["template_name"],
            bulk_form["language_code"],
            body_parameters,
            dry_run=dry_run,
        )
    except ValueError as exc:
        bulk_result = {"error": str(exc), "sent": [], "failed": [], "skipped": [], "sent_count": 0, "failed_count": 0, "skipped_count": 0}
        status_code = 400
    except ConfigurationError as exc:
        logger.exception("Bulk template sender configuration error: %s", exc)
        bulk_result = {"error": str(exc), "sent": [], "failed": [], "skipped": [], "sent_count": 0, "failed_count": 0, "skipped_count": 0}
        status_code = 500
    else:
        status_code = 200

    return render_template(
        "admin.html",
        **build_admin_context(bulk_form=bulk_form, bulk_result=bulk_result),
    ), status_code


@order_blueprint.post("/api/admin/template-messages")
def admin_template_messages_api():
    allowed, error = require_admin_token()
    if not allowed:
        return jsonify({"error": error}), 401

    payload = request_payload()
    raw_numbers = payload.get("phone_numbers", payload.get("numbers", ""))
    phone_numbers = "\n".join(str(value) for value in raw_numbers) if isinstance(raw_numbers, list) else str(raw_numbers)
    raw_parameters = payload.get("template_parameters", payload.get("body_parameters", ""))
    body_parameters = (
        [str(value).strip() for value in raw_parameters if str(value).strip()]
        if isinstance(raw_parameters, list)
        else template_parameters_from_text(str(raw_parameters))
    )
    dry_run = str(payload.get("dry_run", "")).strip().lower() in {"1", "true", "yes", "on"}

    try:
        result = send_bulk_template_messages(
            phone_numbers,
            str(payload.get("template_name", settings.bulk_message_template_name)),
            str(payload.get("language_code", settings.bulk_message_template_language)),
            body_parameters,
            dry_run=dry_run,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ConfigurationError as exc:
        logger.exception("Bulk template API configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify(result), 200


@order_blueprint.get("/api/admin/orders")
def admin_orders_api():
    allowed, error = require_admin_token()
    if not allowed:
        return jsonify({"error": error}), 401

    orders = service().list_orders(
        search=request.args.get("search", "").strip(),
        status=request.args.get("status", "").strip(),
    )
    return jsonify({"orders": orders}), 200


@order_blueprint.get("/orders")
def orders_redirect():
    return redirect(url_for("order_system.admin_dashboard"))
