import json
import threading
import time
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from server import Controller, ROOT, handler_for


class ServerTests(unittest.TestCase):
    def setUp(self):
        config = json.loads((ROOT / 'config.json').read_text())
        config['motor'] = 'simulation'
        self.controller = Controller(config)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.controller))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.controller.close()

    def post(self, path, data, content_type='application/json'):
        req = Request(self.url + path, data=json.dumps(data).encode(),
                      headers={'Content-Type': content_type})
        with urlopen(req, timeout=2) as response:
            return json.load(response)

    def test_page_and_state(self):
        with urlopen(self.url, timeout=2) as response:
            page = response.read().decode()
            self.assertIn('Керування антеною', page)
            self.assertIn('id="rotate"', page)
            self.assertIn('Один оберт 360°', page)
        with urlopen(self.url + '/api/state', timeout=2) as response:
            self.assertEqual(json.load(response)['mode'], 'simulation')

    def test_move_stop_and_limits(self):
        self.post('/api/move', {'angle': 150})
        deadline = time.monotonic() + 2
        while self.controller.state()['angle'] == 90 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreater(self.controller.state()['angle'], 90)
        stopped = self.post('/api/stop', {})
        time.sleep(0.08)
        self.assertFalse(stopped['moving'])
        self.assertEqual(stopped['angle'], self.controller.state()['angle'])
        for value in (-1, 181, True, None, '90', float('nan')):
            with self.assertRaises(HTTPError) as error:
                self.post('/api/move', {'angle': value})
            self.assertEqual(error.exception.code, 400)

    def test_reject_form_and_cross_site(self):
        with self.assertRaises(HTTPError) as error:
            self.post('/api/stop', {}, 'application/x-www-form-urlencoded')
        self.assertEqual(error.exception.code, 415)
        req = Request(self.url + '/api/stop', data=b'{}', headers={
            'Content-Type': 'application/json', 'Sec-Fetch-Site': 'cross-site'})
        with self.assertRaises(HTTPError) as error:
            urlopen(req, timeout=2)
        self.assertEqual(error.exception.code, 403)

    def test_rotation_timing_full_circle_and_stop(self):
        initial = self.controller.state()['angle']
        state = self.post('/api/rotate', {})
        self.assertTrue(state['moving'])
        with self.assertRaises(HTTPError) as error:
            self.post('/api/rotate', {})
        self.assertEqual(error.exception.code, 400)
        with self.controller.lock:
            due = self.controller.rotation['next_step']
            self.controller.advance_rotation(due - 0.001)
            self.assertEqual(self.controller.angle, initial)
            for step in range(1, 361):
                self.controller.advance_rotation(due)
                self.assertEqual(self.controller.angle, (initial + step) % 360)
                if step < 360:
                    due = self.controller.rotation['next_step']
            self.assertIsNone(self.controller.rotation)
            self.assertTrue(self.controller.stopped)
        self.post('/api/rotate', {})
        self.post('/api/stop', {})
        self.assertIsNone(self.controller.state()['rotation_degrees'])
        self.assertFalse(self.controller.state()['moving'])

    def test_rotation_replacement_and_servo_rejection(self):
        self.post('/api/rotate', {})
        self.post('/api/move', {'angle': 100})
        self.assertIsNone(self.controller.state()['rotation_degrees'])
        self.controller.config['motor'] = 'servo'
        with self.assertRaises(HTTPError) as error:
            self.post('/api/rotate', {})
        self.assertEqual(error.exception.code, 400)

    def test_servo_full_turn_in_both_directions(self):
        self.controller.config.update(motor='servo', min_angle=0, max_angle=360)
        self.controller.servo = Mock()
        for start, finish in ((0, 360), (360, 0)):
            with self.controller.lock:
                self.controller.angle = start
            self.post('/api/rotate', {})
            with self.controller.lock:
                for _ in range(360):
                    self.controller.advance_rotation(self.controller.rotation['next_step'])
                self.assertEqual(self.controller.angle, finish)
                self.assertEqual(self.controller.servo.angle, finish)
                self.assertTrue(self.controller.stopped)


if __name__ == '__main__':
    unittest.main()
