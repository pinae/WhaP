import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from app.services.notification_service import send_notification_email, get_user_email, send_user_notification


class TestNotificationSystem(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a minimal Flask app for testing
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SMTP_SERVER'] = 'smtp.example.com'
        self.app.config['SMTP_PORT'] = 587
        self.app.config['SMTP_USERNAME'] = 'test@example.com'
        self.app.config['SMTP_PASSWORD'] = 'password'
        self.app.config['SENDER_EMAIL'] = 'sender@example.com'

        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        """Clean up after each test method."""
        self.ctx.pop()

    @patch('smtplib.SMTP')
    def test_send_notification_email_success(self, mock_smtp):
        """Test sending an email notification successfully."""
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server

        result = send_notification_email('test@example.com', 'Test Subject', 'Test Body')

        self.assertTrue(result)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch('smtplib.SMTP')
    def test_send_notification_email_failure(self, mock_smtp):
        """Test sending an email notification fails when SMTP server is unreachable."""
        mock_smtp.side_effect = Exception("Connection failed")

        result = send_notification_email('test@example.com', 'Test Subject', 'Test Body')

        self.assertFalse(result)

    @patch('app.services.notification_service.get_ldap_user_details')
    def test_get_user_email_ldap_user(self, mock_get_details):
        """Test getting email for LDAP user."""
        mock_get_details.return_value = {
            'uid': 'jdoe',
            'full_name': 'John Doe',
            'mail': 'john.doe@example.com'
        }

        result = get_user_email('ldap:jdoe')

        self.assertEqual(result, 'john.doe@example.com')
        mock_get_details.assert_called_once_with('jdoe')

    @patch('app.services.notification_service.get_ldap_user_details')
    def test_get_user_email_ldap_user_no_email(self, mock_get_details):
        """Test getting email for LDAP user when no email is available."""
        mock_get_details.return_value = {
            'uid': 'jdoe',
            'full_name': 'John Doe'
        }

        result = get_user_email('ldap:jdoe')

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with('jdoe')

    def test_get_user_email_local_user(self):
        """Test getting email for local user (placeholder)."""
        # For local users, this would need to be implemented based on your schema
        result = get_user_email('local:1')

        # This should return None for now since we don't have local user email implementation
        self.assertIsNone(result)

    def test_get_user_email_invalid_format(self):
        """Test getting email for invalid user ID format."""
        result = get_user_email('invalid-format')

        self.assertIsNone(result)

    @patch('app.services.notification_service.send_notification_email')
    @patch('app.services.notification_service.get_user_email')
    def test_send_user_notification_success(self, mock_get_email, mock_send_email):
        """Test sending notification to user successfully."""
        mock_get_email.return_value = 'john.doe@example.com'
        mock_send_email.return_value = True

        result = send_user_notification('ldap:jdoe', 'Test Subject', 'Test Body')

        self.assertTrue(result)
        mock_get_email.assert_called_once_with('ldap:jdoe')
        mock_send_email.assert_called_once_with('john.doe@example.com', 'Test Subject', 'Test Body')

    @patch('app.services.notification_service.send_notification_email')
    @patch('app.services.notification_service.get_user_email')
    def test_send_user_notification_no_email(self, mock_get_email, mock_send_email):
        """Test sending notification to user when no email is available."""
        mock_get_email.return_value = None

        result = send_user_notification('ldap:jdoe', 'Test Subject', 'Test Body')

        self.assertFalse(result)
        mock_get_email.assert_called_once_with('ldap:jdoe')
        mock_send_email.assert_not_called()


if __name__ == '__main__':
    unittest.main()
