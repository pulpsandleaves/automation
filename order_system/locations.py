CITY_DETAILS = {
    "Bangalore": {
        "slot": "Delivery update soon",
        "image": "city-icons/bangalore.png",
        "message": (
            "Bangalore selected. "
            "You can place your Pulps & Leaves premium makhana order now. "
            "Our team will update you with delivery details after the order is saved."
        ),
    },
    "Hyderabad": {
        "slot": "Delivery update soon",
        "image": "city-icons/hyderabad.png",
        "message": (
            "Hyderabad selected. "
            "You can place your Pulps & Leaves premium makhana order now. "
            "Our team will update you with delivery details after the order is saved."
        ),
    },
    "Pune": {
        "slot": "Delivery update soon",
        "image": "city-icons/pune.png",
        "message": (
            "Pune selected. "
            "You can place your Pulps & Leaves premium makhana order now. "
            "Our team will update you with delivery details after the order is saved."
        ),
    },
    "Mumbai": {
        "slot": "Delivery update soon",
        "image": "city-icons/mumbai.png",
        "message": (
            "Mumbai selected. "
            "You can place your Pulps & Leaves premium makhana order now. "
            "Our team will update you with delivery details after the order is saved."
        ),
    },
}


def city_choices() -> list[str]:
    return list(CITY_DETAILS.keys())


def city_picker_options() -> list[dict[str, str]]:
    return [
        {
            "name": city,
            "slot": details.get("slot", ""),
            "message": details.get("message", ""),
            "image": details.get("image", ""),
        }
        for city, details in CITY_DETAILS.items()
    ]


def city_message(city: str) -> str:
    return CITY_DETAILS.get(city, {}).get("message", "")


def city_delivery_slot(city: str) -> str:
    return CITY_DETAILS.get(city, {}).get("slot", "")
