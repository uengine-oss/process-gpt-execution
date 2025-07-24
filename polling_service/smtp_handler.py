import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from dotenv import load_dotenv

if os.getenv("ENV") != "production":
    load_dotenv(override=True)

# SMTP Configuration
smtp_server = os.getenv("SMTP_SERVER")
smtp_port = os.getenv("SMTP_PORT")
smtp_username = os.getenv("SMTP_USERNAME")
smtp_password = os.getenv("SMTP_PASSWORD")


class EmailSendError(Exception):
    """Custom exception for email sending errors"""
    pass

def generate_email_template(activity: any, url: str, additional_info: Optional[any] = None) -> str:
    """
    Generates an HTML email template using process instance information.
    """
    
    html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{activity.name}</title>
</head>
<body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px;">
    <div style="max-width: 600px; background-color: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 0 10px rgba(0, 0, 0, 0.1); text-align: center; margin: 0 auto;">
        <h2 style="color: #333; margin-bottom: 20px;">다음 절차를 도와주세요.</h2>
        <p style="color: #555; font-size: 16px; line-height: 1.5;">
        '{activity.name}' 을(를) 진행해 주실 차례입니다. 아래 버튼을 눌러 내용을 확인하고 완료해 주세요.
        </p>
        
        <div style="margin: 30px 0;">
            <a href="{url}" style="display: inline-block; padding: 12px 24px; background-color: #0366d6; color: #fff; text-decoration: none; border-radius: 5px; font-weight: bold;">
                {activity.name}
            </a>
        </div>

        <p style="margin-top: 30px; font-size: 13px; color: #888; line-height: 1.5;">
            If you run into problems, please contact our support team. {additional_info.get("support_email", "help@uengine.org")}
        </p>
    </div>
</body>
</html>
    """
    return html_template

def send_email(subject: str, body: str, to_email: str) -> bool:
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = 'noreply@process-gpt.io'
        msg["Reply-To"] = "help@uengine.org"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))

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

