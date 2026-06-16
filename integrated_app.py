from __future__ import annotations

from http.server import ThreadingHTTPServer

from app.config import HOST, PORT
from app.web import BlackIceRequestHandler


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), BlackIceRequestHandler)
    print(f'Integrated server running at http://{HOST}:{PORT}')
    server.serve_forever()
