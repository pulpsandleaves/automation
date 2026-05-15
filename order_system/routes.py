import logging
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from .config import ConfigurationError, settings
from .locations import CITY_DETAILS, city_choices, city_message
from .services import OrderService

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
    token = request.headers.get("X-Admin-Token", "") or request.args.get("token", "")
    return (token == settings.admin_dashboard_token, "Invalid or missing admin token.")


@order_blueprint.get("/")
@order_blueprint.get("/checkout")
def checkout_page():
    default_city = city_choices()[0] if city_choices() else ""
    return render_template(
        "checkout.html",
        brand_name=settings.brand_name,
        city_choices=city_choices(),
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

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    orders = service().list_orders(search=search, status=status)
    return render_template(
        "admin.html",
        brand_name=settings.brand_name,
        orders=orders,
        search=search,
        status=status,
    )


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
