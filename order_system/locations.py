CITY_DETAILS = {
    "Bangalore": {
        "slot": "2nd - 4th June '26",
        "image": "city-icons/bangalore.png",
        "message": (
            "📦🥭 Good news, Namma Bengaluru !! "
            "Your next mango delivery slot is scheduled between 2nd - 4th June '26. "
            "Our mangoes are already warming up for their Bengaluru trip."
        ),
    },
    "Hyderabad": {
        "slot": "2nd - 4th June '26",
        "image": "city-icons/hyderabad.png",
        "message": (
            "📦🥭 Hello Hyderabad! "
            "Your next mango delivery slot is scheduled between 2nd - 4th June '26. "
            "Our mangoes are crossing the lanes of Charminar with full Hyderabadi swag."
        ),
    },
    "Pune": {
        "slot": "10th - 12th June '26",
        "image": "city-icons/pune.png",
        "message": (
            "📦🥭 Hey Pune! "
            "Your next mango delivery slot is scheduled between 10th - 12th June '26. "
            "Our mangoes are cruising through Maharashtra with full Puneri swag."
        ),
    },
    "Mumbai": {
        "slot": "10th - 12th June '26",
        "image": "city-icons/mumbai.png",
        "message": (
            "📦🥭 Hello Mumbai! "
            "Your next mango delivery slot is scheduled between 10th - 12th June '26. "
            "Our mangoes are already practicing their Mumbai local survival skills."
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
