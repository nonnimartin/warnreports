from __future__ import annotations

import os.path
from datetime import datetime, timedelta

import boto3
import dateutil.parser
import settings


def send_email(recipient, subject, body):
    sender = settings.EMAIL_ACCOUNT
    ses_client = boto3.client('ses')
    # Create the email message
    message = {
        'Subject': {'Data': subject},
        'Body': {
            'Text': {'Data': body,'Charset': 'UTF-8'},
            'Html': {'Data': body, 'Charset': 'UTF-8'}}}
    # Send the email
    response = ses_client.send_email(
        Source=sender,
        Destination={'ToAddresses': [recipient]},
        Message=message)
    # Check the response
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        print('Email sent successfully!')
    else:
        print('Failed to send email.')

def makedirs(path):
    if not os.path.exists(path):
        os.makedirs(path)

def has_digit(input: str):
    return any(filter(str.isdigit, input))

def get_date(value: str) -> datetime|None:
    # various attempts at handling irregular dates
    if not (value and has_digit(value)):
        return
    try:
        dt = dateutil.parser.parse(value, fuzzy=True)
        dt.timestamp()
        if dt.year > 1:
            return dt
    except ValueError:
        pass

def get_int(value: str) -> int|None:
    if not (value and has_digit(value)):
        return
    try:
        return int(value)
    except ValueError:
        pass

def now(**kw) -> datetime:
    dt = datetime.now()
    if kw:
        dt += timedelta(**kw)
    return dt

def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f'Cannot JSON encode object of type {type(value)}')
