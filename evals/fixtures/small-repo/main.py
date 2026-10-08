"""Entry point: read settings, build the WSGI app, serve it."""

import json
import os
import tomllib
from pathlib import Path
from wsgiref.simple_server import make_server

from api.auth import login
from api.orders import list_orders
from db.connection import connect

DEFAULTS = {"host": "127.0.0.1", "port": 8080, "database": "app.db", "page_size": 50}
ENV_NAMES = {
    "host": "SHOP_HOST",
    "port": "SHOP_PORT",
    "database": "SHOP_DATABASE",
    "page_size": "SHOP_PAGE_SIZE",
}

config = dict(DEFAULTS)
config_file = Path(os.environ.get("SHOP_CONFIG", "config.toml"))
if config_file.is_file():
    with config_file.open("rb") as handle:
        config.update(tomllib.load(handle))
for key, env_name in ENV_NAMES.items():
    if env_name in os.environ:
        value = os.environ[env_name]
        config[key] = int(value) if isinstance(DEFAULTS[key], int) else value
if not 0 < int(config["port"]) < 65536:
    raise SystemExit(f"port out of range: {config['port']}")


def respond(start_response, status: str, payload: object) -> list[bytes]:
    body = json.dumps(payload).encode()
    start_response(status, [("Content-Type", "application/json")])
    return [body]


def app(environ, start_response):
    conn = connect(config["database"])
    method, path = environ["REQUEST_METHOD"], environ["PATH_INFO"]
    if method == "GET" and path == "/orders":
        return respond(start_response, "200 OK", list_orders(conn))
    if method == "POST" and path == "/login":
        size = int(environ.get("CONTENT_LENGTH") or 0)
        code, payload = login(conn, environ["wsgi.input"].read(size).decode())
        return respond(start_response, f"{code} OK", payload)
    return respond(start_response, "404 Not Found", {"error": "not found"})


if __name__ == "__main__":
    with make_server(config["host"], int(config["port"]), app) as server:
        print(f"listening on {config['host']}:{config['port']}")
        server.serve_forever()
