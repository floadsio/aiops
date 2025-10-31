from flask import Flask

from app import create_app


def get_app() -> Flask:
    return create_app()


app = get_app()


if __name__ == "__main__":
    app.run(debug=True)
