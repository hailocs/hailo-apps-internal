import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import numpy as np

# Add the project root to sys.path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Add the vlm_chat directory to sys.path to allow importing backend module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../hailo_apps/python/standalone_apps/vlm_chat')))

from hailo_apps.python.standalone_apps.vlm_chat.backend import Backend
from hailo_apps.python.standalone_apps.vlm_chat.vlm_chat import VLMChatApp

class TestBackend(unittest.TestCase):
    @patch('hailo_apps.python.standalone_apps.vlm_chat.backend.mp.Process')
    @patch('hailo_apps.python.standalone_apps.vlm_chat.backend.mp.Queue')
    @patch('hailo_apps.python.standalone_apps.vlm_chat.backend.VDevice')
    @patch('hailo_apps.python.standalone_apps.vlm_chat.backend.VLM')
    def setUp(self, mock_vlm, mock_vdevice, mock_queue, mock_process):
        self.mock_queue = mock_queue
        self.mock_process = mock_process
        self.mock_vdevice = mock_vdevice
        self.mock_vlm = mock_vlm

        self.backend = Backend(hef_path="dummy.hef")

    def test_initialization(self):
        """Test if Backend initializes queues and process correctly."""
        self.assertEqual(self.backend.hef_path, "dummy.hef")
        self.assertTrue(self.mock_queue.called)
        self.assertTrue(self.mock_process.called)

    @patch('hailo_apps.python.standalone_apps.vlm_chat.backend.Backend.convert_resize_image')
    def test_vlm_inference(self, mock_convert):
        """Test vlm_inference method sends data to queue and retrieves result."""
        mock_convert.return_value = np.zeros((336, 336, 3), dtype=np.uint8)

        # Mock request and response queues
        request_queue = MagicMock()
        response_queue = MagicMock()
        self.backend._request_queue = request_queue
        self.backend._response_queue = response_queue

        # Mock successful response
        expected_result = {'answer': 'Test answer', 'time': '0.5s'}
        response_queue.get.return_value = {'result': expected_result, 'error': None}

        result = self.backend.vlm_inference(np.zeros((100, 100, 3)), "Test prompt")

        self.assertEqual(result, expected_result)
        request_queue.put.assert_called()

    def test_convert_resize_image(self):
        """Test image conversion and resizing."""
        input_image = np.zeros((480, 640, 3), dtype=np.uint8)
        resized = Backend.convert_resize_image(input_image)
        self.assertEqual(resized.shape, (336, 336, 3))
        self.assertEqual(resized.dtype, np.uint8)

    def test_close(self):
        """Test cleanup resources."""
        self.backend.close()
        self.backend._request_queue.put.assert_called_with(None)
        self.backend._process.join.assert_called()


class TestVLMChatApp(unittest.TestCase):
    @patch('hailo_apps.python.standalone_apps.vlm_chat.vlm_chat.get_resource_path')
    @patch('hailo_apps.python.standalone_apps.vlm_chat.vlm_chat.Backend')
    @patch('hailo_apps.python.standalone_apps.vlm_chat.vlm_chat.cv2.VideoCapture')
    def setUp(self, mock_cap, mock_backend, mock_get_path):
        self.mock_cap = mock_cap
        self.mock_backend = mock_backend
        self.mock_get_path = mock_get_path
        self.app = VLMChatApp(camera=0, camera_type='usb')

    def test_initialization(self):
        """Test App initialization."""
        self.assertEqual(self.app.camera_type, 'usb')
        self.assertTrue(self.app.running)
        self.assertIsNotNone(self.app.executor)

    def test_get_user_input_none(self):
        """Test non-blocking input when no input is available."""
        with patch('hailo_apps.python.standalone_apps.vlm_chat.vlm_chat.select.select') as mock_select:
            mock_select.return_value = ([], [], [])
            result = self.app._get_user_input()
            self.assertIsNone(result)

    def test_get_user_input_data(self):
        """Test non-blocking input when input is available."""
        with patch('hailo_apps.python.standalone_apps.vlm_chat.vlm_chat.select.select') as mock_select:
            with patch('sys.stdin.readline', return_value='test input\n'):
                mock_select.return_value = ([sys.stdin], [], [])
                result = self.app._get_user_input()
                self.assertEqual(result, 'test input')

    def test_stop(self):
        """Test stop method cleans up backend and executor."""
        self.app.backend = MagicMock()
        self.app.stop()
        self.assertFalse(self.app.running)
        self.app.backend.close.assert_called()

if __name__ == '__main__':
    unittest.main()

