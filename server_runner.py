import pathlib
import traceback

from app import app


LOG_PATH = pathlib.Path(__file__).with_name("server-launch.log")


def main() -> None:
    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    except Exception:
        LOG_PATH.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
