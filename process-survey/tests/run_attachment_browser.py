#!/usr/bin/env python3
"""Запуск мобильного WebKit-сценария на изолированной временной базе."""
import json
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


def fake_summary(prompt):
    return {
        'summary': 'Тестовое резюме документа о проверке серии',
        'key_points': ['Поля и связи подтверждены'],
        'fields': [{'name': 'Артикул', 'description': 'Код продукта', 'example': 'BAL-001'}],
        'systems': ['Excel'], 'processes': ['Проверка серии'], 'handoffs': ['Склад → QA: серия'],
        'data_quality': [],
    }


def main():
    script = sys.argv[1] if len(sys.argv) > 1 else 'browser_attachments.js'
    result_name = {'browser_attachments.js': 'attachment-browser-result.json',
                   'browser_multirole_smoke.js': 'multirole-smoke-result.json'}.get(script, script.replace('.js', '-result.json'))
    with tempfile.TemporaryDirectory(prefix='attachment-browser-', dir=ROOT / 'run') as folder:
        temporary = Path(folder)
        server.DB_PATH = str(temporary / 'survey.db')
        server.ADMIN_FILE = str(temporary / 'admin.txt')
        server.TUNNEL_LOG = str(temporary / 'tunnel.log')
        server.PUSHED_FILE = str(temporary / 'pushed-url')
        Path(server.ADMIN_FILE).write_text('test-admin-key\n', encoding='utf-8')
        server.ai_available = lambda: False
        server.warm_async = lambda: None
        server._hits = {}
        server.init_db()
        server.start_knowledge_worker(fake_summary)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        config = temporary / 'config.json'
        config.write_text(json.dumps({
            'base': 'http://127.0.0.1:%d' % httpd.server_port,
            'admin': 'test-admin-key',
        }), encoding='utf-8')
        try:
            subprocess.run(['node', str(ROOT / 'tests' / script), str(config)], cwd=ROOT, check=True, timeout=180)
            result = json.loads((ROOT / 'run' / result_name).read_text(encoding='utf-8'))
            interview_id = result.get('interviewId')
            if interview_id and (temporary / 'attachments' / interview_id).exists():
                raise AssertionError('Файлы временного интервью не удалены')
        finally:
            server.stop_knowledge_worker()
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
