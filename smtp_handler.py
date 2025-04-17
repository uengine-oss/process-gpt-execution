import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# SMTP Configuration
smtp_server = os.getenv("SMTP_SERVER")
smtp_port = os.getenv("SMTP_PORT")
smtp_username = os.getenv("SMTP_USERNAME")
smtp_password = os.getenv("SMTP_PASSWORD")


class EmailSendError(Exception):
    """Custom exception for email sending errors"""
    pass

def send_email(subject: str, body: str, to_email: str) -> bool:
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            
        return True
        
    except smtplib.SMTPAuthenticationError:
        raise EmailSendError("SMTP authentication failed. Check credentials.")
    except smtplib.SMTPException as e:
        raise EmailSendError(f"SMTP error occurred: {str(e)}")
    except Exception as e:
        raise EmailSendError(f"Unexpected error sending email: {str(e)}")

