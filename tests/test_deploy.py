"""Exercise the updater without touching systemd, hardware or the network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from server import ROOT


class UpdateTests(unittest.TestCase):
    def run_update(self, deployed='', moving=False, tests_fail=False, install_fail=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            marker = root / 'deployed'
            marker.write_text(deployed)
            log = root / 'commands'
            scripts = {
                'git': 'echo "git $*" >> "$COMMAND_LOG"\n'
                       'if [ "$1" = rev-parse ]; then echo new-commit; fi\n',
                'flock': 'exit 0\n',
                'systemctl': 'exit 0\n',
                'python3': 'if [ "$1" = - ]; then\n'
                           '  cat >/dev/null\n'
                           '  exit "$MOVING"\n'
                           'fi\n'
                           'echo tests >> "$COMMAND_LOG"\n'
                           'exit "$TESTS_FAIL"\n',
                'bash': 'echo install >> "$COMMAND_LOG"\nexit "$INSTALL_FAIL"\n',
            }
            for name, body in scripts.items():
                path = root / name
                path.write_text('#!/bin/sh\n' + body)
                path.chmod(0o755)
            script = (ROOT / 'deploy/update.sh').read_text()
            script = script.replace('/opt/antenna-source', str(source))
            script = script.replace('/opt/antenna-deployed-commit', str(marker))
            script = script.replace('/run/antenna-update.lock', str(root / 'lock'))
            result = subprocess.run(['/bin/bash', '-c', script], env={
                **os.environ, 'PATH': f"{root}:{os.environ['PATH']}",
                'COMMAND_LOG': str(log), 'MOVING': str(int(moving)),
                'TESTS_FAIL': str(int(tests_fail)), 'INSTALL_FAIL': str(int(install_fail)),
            }, capture_output=True, text=True)
            return result.returncode, marker.read_text().strip(), log.read_text()

    def test_installs_new_commit_after_tests(self):
        code, marker, log = self.run_update()
        self.assertEqual(code, 0)
        self.assertEqual(marker, 'new-commit')
        self.assertLess(log.index('tests'), log.index('install'))

    def test_unchanged_commit_does_not_restart(self):
        code, marker, log = self.run_update(deployed='new-commit')
        self.assertEqual(code, 0)
        self.assertNotIn('install', log)
        self.assertNotIn('reset', log)

    def test_movement_defers_update(self):
        code, marker, log = self.run_update(deployed='old', moving=True)
        self.assertEqual(code, 0)
        self.assertEqual(marker, 'old')
        self.assertNotIn('reset', log)
        self.assertNotIn('install', log)

    def test_failed_tests_preserve_deployed_marker(self):
        code, marker, log = self.run_update(deployed='old', tests_fail=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(marker, 'old')
        self.assertNotIn('install', log)

    def test_failed_install_is_retried(self):
        code, marker, log = self.run_update(deployed='old', install_fail=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(marker, 'old')
        self.assertIn('install', log)
