import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from .ldap_service import get_ldap_user_details

def send_notification_email(to_email, subject, body):
    """
    Sends an email notification to the specified email address.
    
    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        body (str): Email body content
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    if not to_email:
        logging.warning("Attempted to send email to empty address")
        return False
        
    try:
        # Get email configuration from Flask app config
        smtp_server = current_app.config.get('SMTP_SERVER')
        smtp_port = current_app.config.get('SMTP_PORT', 587)
        smtp_username = current_app.config.get('SMTP_USERNAME')
        smtp_password = current_app.config.get('SMTP_PASSWORD')
        sender_email = current_app.config.get('SENDER_EMAIL')
        
        if not all([smtp_server, smtp_username, smtp_password, sender_email]):
            logging.error("SMTP configuration is incomplete")
            return False
            
        # Create message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add body to email
        msg.attach(MIMEText(body, 'html'))
        
        # Create SMTP session
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable security
        server.login(smtp_username, smtp_password)
        
        # Send email
        text = msg.as_string()
        server.sendmail(sender_email, to_email, text)
        server.quit()
        
        logging.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

def get_user_email(user_id_str):
    """
    Gets the email address for a user.
    
    Args:
        user_id_str (str): User ID in format "local:1" or "ldap:jdoe"
        
    Returns:
        str: User's email address or None if not found
    """
    if not user_id_str:
        return None
        
    try:
        prefix, actual_id = user_id_str.split(":", 1)
    except (ValueError, AttributeError):
        logging.error(f"Invalid user ID format: {user_id_str}")
        return None

    if prefix == 'local':
        # For local users, we would need to get their email from the database
        # This is a placeholder - you would need to implement this based on your schema
        return None
        
    elif prefix == 'ldap':
        # For LDAP users, get details from LDAP and extract email
        ldap_details = get_ldap_user_details(actual_id)
        if ldap_details:
            return ldap_details.get('mail')
        return None
        
    logging.error(f"Unknown user prefix in identifier: {prefix}")
    return None

def send_user_notification(user_id_str, subject, body):
    """
    Sends a notification email to a user based on their user ID.
    
    Args:
        user_id_str (str): User ID in format "local:1" or "ldap:jdoe"
        subject (str): Email subject
        body (str): Email body content
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    email = get_user_email(user_id_str)
    if email:
        return send_notification_email(email, subject, body)
    else:
        logging.warning(f"No email found for user {user_id_str}")
        return False