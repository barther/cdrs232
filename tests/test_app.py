import unittest
from unittest.mock import MagicMock

import app as app_module


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.ctrl = MagicMock()
        self.ctrl.online = True
        self.ctrl.get_status.return_value = {'online': True, 'port_open': True, 'mecha_status': 'stop'}
        app_module.controller = self.ctrl
        self.addCleanup(setattr, app_module, 'controller', None)

    def test_page_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/api/status', response.data)

    def test_status(self):
        data = self.client.get('/api/status').get_json()
        self.assertTrue(data['online'])
        self.assertEqual(data['mecha_status'], 'stop')

    def test_status_before_startup(self):
        app_module.controller = None
        data = self.client.get('/api/status').get_json()
        self.assertEqual(data, {'online': False, 'port_open': False})

    def test_command_runs_when_online(self):
        response = self.client.post('/api/play')
        self.assertEqual(response.status_code, 200)
        self.ctrl.play.assert_called_once()

    def test_command_refused_while_deck_offline(self):
        self.ctrl.online = False
        response = self.client.post('/api/play')
        self.assertEqual(response.status_code, 503)
        self.ctrl.play.assert_not_called()

    def test_track_range(self):
        self.assertEqual(self.client.post('/api/track/0').status_code, 400)
        self.assertEqual(self.client.post('/api/track/12').status_code, 200)
        self.ctrl.goto_track.assert_called_once_with(12)

    def test_mode_and_device_validation(self):
        self.assertEqual(self.client.post('/api/mode/shuffle').status_code, 400)
        self.assertEqual(self.client.post('/api/mode/random').status_code, 200)
        self.assertEqual(self.client.post('/api/device/tape').status_code, 400)
        self.assertEqual(self.client.post('/api/device/usb').status_code, 200)

    def test_repeat_parses_string_false(self):
        self.client.post('/api/repeat', json={'enabled': 'false'})
        self.ctrl.set_repeat.assert_called_once_with(False)

    def test_search_hold(self):
        self.client.post('/api/search/start', json={'forward': False})
        self.ctrl.search_start.assert_called_once_with(forward=False, high_speed=False)
        self.client.post('/api/search/stop')
        self.ctrl.search_stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
