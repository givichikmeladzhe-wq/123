import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from runtime.control_api import ControlAPIHandler
from runtime.control_service import ControlService
from runtime.execution_store import ExecutionStore


class ControlAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.tmp.name) / 'api.sqlite3')
        self.service = ControlService(self.store)
        handler = type('BoundControlAPIHandler', (ControlAPIHandler,), {'service': self.service})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.store.close(); self.tmp.cleanup()

    def req(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)

    def test_health(self):
        status, body = self.req('GET', '/healthz')
        self.assertEqual(status, 200); self.assertEqual(body['status'], 'ok')

    def test_full_http_flow_reaches_pass(self):
        self.req('POST','/tasks',{'task_id':'t1','project_id':'p1'})
        self.req('POST','/tasks/t1/start',{})
        self.req('POST','/tasks/t1/executor-running',{'job_id':'j1','executor_id':'impl','live_job':True})
        self.req('POST','/tasks/t1/result',{'evidence':[{'kind':'artifact','ref':'git://sha'}]})
        self.req('POST','/tasks/t1/qa/start',{'qa_executor_id':'qa'})
        status, body = self.req('POST','/tasks/t1/qa/result',{'passed':True,'evidence':[{'kind':'qa','ref':'qa://pass'}]})
        self.assertEqual(status, 200); self.assertEqual(body['state'], 'PASS')
        _, snapshot = self.req('GET','/tasks/t1')
        self.assertEqual(snapshot['task']['state'], 'PASS')
        self.assertEqual(snapshot['events'][-1]['event_type'], 'QA_PASS')


if __name__ == '__main__': unittest.main()
