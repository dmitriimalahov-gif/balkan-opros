#!/usr/bin/env python3
"""Запуск server.py в контейнере.

server.py жёстко слушает 127.0.0.1 — в контейнере это недоступно снаружи. Подменяем класс
HTTP-сервера на тот же ThreadingHTTPServer, но с адресом 0.0.0.0 (порт берётся из SURVEY_PORT).
Наружу контейнер публикуется только на 127.0.0.1 хоста (см. compose), код опроса не меняется.
"""
import sys

sys.path.insert(0, '/app')
import server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


class AnyAddrServer(ThreadingHTTPServer):
    def __init__(self, address, handler):
        super().__init__(('0.0.0.0', address[1]), handler)


server.ThreadingHTTPServer = AnyAddrServer
server.main()
