"""Local antenna controller. Python 3.9+, no dependencies in simulation mode."""
import argparse
import json
import math
from pathlib import Path
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, config):
        self.config = config
        for key in ('min_angle', 'max_angle', 'initial_angle', 'speed_deg_per_second'):
            value = config[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'Invalid {key}')
        if not config['min_angle'] < config['max_angle']:
            raise ValueError('min_angle must be less than max_angle')
        if not config['min_angle'] <= config['initial_angle'] <= config['max_angle']:
            raise ValueError('initial_angle is outside limits')
        if not 0 < config['speed_deg_per_second'] <= 180:
            raise ValueError('speed_deg_per_second must be between 0 and 180')
        if config['motor'] not in ('simulation', 'servo'):
            raise ValueError('Supported motors: simulation, servo. Stepper driver is not configured.')
        self.angle = float(config['initial_angle'])
        self.target = self.angle
        self.stopped = True
        self.error = None
        self.rotation = None
        self.lock = threading.Lock()
        self.quit = threading.Event()
        self.servo = None
        if config['motor'] == 'servo':
            from gpiozero import AngularServo
            self.servo = AngularServo(
                config['servo_gpio'], initial_angle=None,
                min_angle=config['min_angle'], max_angle=config['max_angle'],
                min_pulse_width=config['servo_min_pulse_ms'] / 1000,
                max_pulse_width=config['servo_max_pulse_ms'] / 1000,
            )
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def state(self):
        with self.lock:
            return dict(mode=self.config['motor'], angle=round(self.angle, 1),
                        target=self.target, moving=not self.stopped,
                        min_angle=self.config['min_angle'], max_angle=self.config['max_angle'],
                        error=self.error, position_source='estimated',
                        rotation_degrees=self.rotation['steps'] if self.rotation else None)

    def rotate(self):
        with self.lock:
            if self.error:
                raise ValueError('Помилка мотора; перевірте обладнання і перезапустіть сервер')
            direction = 1
            if self.config['motor'] == 'servo':
                if self.angle + 360 <= self.config['max_angle']:
                    direction = 1
                elif self.angle - 360 >= self.config['min_angle']:
                    direction = -1
                else:
                    raise ValueError('Недостатньо діапазону для оберту 360°. Потрібна позиційна серва з відповідним ходом та калібруванням; перемістіть її до краю діапазону.')
            if self.rotation:
                raise ValueError('Оберт уже виконується')
            self.rotation = dict(start=self.angle, direction=direction, steps=0, next_step=time.monotonic() + 0.5)
            self.target = self.angle if self.config['motor'] == 'simulation' else self.angle + direction * 360
            self.stopped = False

    def advance_rotation(self, now):
        """Called with the controller lock held; one degree per 0.5-second pause."""
        rotation = self.rotation
        if now < rotation['next_step']:
            return
        steps = rotation['steps'] + 1
        angle = rotation['start'] + rotation['direction'] * steps
        if self.servo:
            self.servo.angle = angle
        self.angle = angle % 360 if self.config['motor'] == 'simulation' else angle
        rotation['steps'] = steps
        rotation['next_step'] = now + 0.5
        if rotation['steps'] == 360:
            if self.config['motor'] == 'simulation':
                self.angle = rotation['start']
            self.rotation = None
            self.stopped = True

    def move(self, angle):
        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle):
            raise ValueError('Кут має бути скінченним числом')
        if not self.config['min_angle'] <= angle <= self.config['max_angle']:
            raise ValueError('Кут за межами дозволеного діапазону')
        with self.lock:
            if self.error:
                raise ValueError('Помилка мотора; перевірте обладнання і перезапустіть сервер')
            self.rotation = None
            self.target = angle
            self.stopped = False

    def stop(self):
        with self.lock:
            self.rotation = None
            self.target = self.angle
            self.stopped = True
            if self.servo:
                self.servo.detach()

    def run(self):
        last = time.monotonic()
        while not self.quit.wait(0.02):
            now = time.monotonic()
            dt, last = min(now - last, 0.1), now
            with self.lock:
                if self.stopped:
                    continue
                if self.rotation:
                    try:
                        self.advance_rotation(now)
                    except Exception:
                        self.error = 'Помилка GPIO / мотора'
                        self.rotation = None
                        self.stopped = True
                        if self.servo:
                            self.servo.detach()
                    continue
                delta = self.target - self.angle
                step = self.config['speed_deg_per_second'] * dt
                angle = self.target if abs(delta) <= step else self.angle + math.copysign(step, delta)
                try:
                    if self.servo:
                        self.servo.angle = angle
                    self.angle = angle
                    if angle == self.target:
                        self.stopped = True
                except Exception:
                    self.error = 'Помилка GPIO / мотора'
                    self.stopped = True
                    if self.servo:
                        self.servo.detach()

    def close(self):
        self.quit.set()
        self.worker.join()
        if self.servo:
            self.servo.close()


def handler_for(controller):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/api/state':
                self.reply(200, controller.state())
            elif self.path == '/':
                self.reply(200, (ROOT / 'static/index.html').read_bytes(), 'text/html; charset=utf-8')
            else:
                self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            # Browser cross-origin forms cannot issue motor commands as JSON.
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply(403, {'error': 'Cross-site request rejected'})
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                return self.reply(415, {'error': 'Expected application/json'})
            if self.path not in ('/api/move', '/api/stop', '/api/rotate'):
                return self.reply(404, {'error': 'Not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected JSON object')
                if self.path == '/api/move':
                    controller.move(data.get('angle'))
                elif self.path == '/api/rotate':
                    controller.rotate()
                else:
                    controller.stop()
                self.reply(200, controller.state())
            except (ValueError, UnicodeDecodeError) as exc:
                self.reply(400, {'error': str(exc)})

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    controller = Controller(config)
    try:
        server = ThreadingHTTPServer((config['host'], config['port']), handler_for(controller))
        def terminate(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, terminate)
        print(f"Antenna controller: http://{config['host']}:{config['port']} ({config['motor']})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        controller.close()


if __name__ == '__main__':
    main()
