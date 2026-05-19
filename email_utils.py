import os
import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(to_email, subject, body):

    # GET FROM ENVIRONMENT VARIABLES
    EMAIL_ADDRESS = os.getenv("MAIL_USERNAME")
    EMAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

    # LOCAL FALLBACK (FOR TESTING ON YOUR LAPTOP)
    if not EMAIL_ADDRESS:
        EMAIL_ADDRESS = "nafbasekano@gmail.com"

    if not EMAIL_PASSWORD:
        EMAIL_PASSWORD = "zije cqyy wgby yhip"

    try:

        msg = MIMEMultipart()

        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)

        server.starttls()

        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

        server.send_message(msg)

        server.quit()

        print(f"Email sent to {to_email}")

    except Exception as e:

        print("EMAIL ERROR:", e)