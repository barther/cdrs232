import unittest
from unittest.mock import MagicMock, patch

import app as app_module


class ConnectRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        app_module.controller = None

    def test_connect_rejects_non_integer_baudrate(self):
        response = self.client.post("/api/connect", json={"port": "/dev/ttyUSB0", "baudrate": "fast"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("integer", response.get_json()["message"])

    def test_connect_rejects_unsupported_baudrate(self):
        response = self.client.post("/api/connect", json={"port": "/dev/ttyUSB0", "baudrate": 115200})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Must be one of", response.get_json()["message"])

    @patch("app.TascamController")
    def test_connect_success_returns_200(self, controller_cls):
        controller_cls.VALID_BAUDRATES = [9600, 19200]
        controller = MagicMock()
        controller.connect.return_value = True
        controller_cls.return_value = controller

        response = self.client.post("/api/connect", json={"port": "/dev/ttyUSB0", "baudrate": 9600})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        controller_cls.assert_called_once_with(port="/dev/ttyUSB0", baudrate=9600)
        controller.register_callback.assert_called_once()
        controller.connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
