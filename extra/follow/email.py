from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache

from ..utils import get_logger

__all__ = ['DebugEmailBackend', 'EmailBackend', 'SesEmailBackend', 'instances']

logger = get_logger('backends.email')

class EmailBackend(ABC):
    @abstractmethod
    def send(self, sender: str, recipient: str, subject: str, body: str) -> bool: ...

class SesEmailBackend(EmailBackend):

    @property
    @cache
    def client(self):
        import boto3
        return boto3.client('ses')

    def send(self, sender: str, recipient: str, subject: str, body: str) -> bool:
        response = self.client.send_email(
            Source=sender,
            Destination={'ToAddresses': [recipient]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    fmt: {'Data': body,'Charset': 'UTF-8'}
                    for fmt in ('Text', 'Html')}})
        return response['ResponseMetadata']['HTTPStatusCode'] == 200

class DebugEmailBackend(EmailBackend):

    def send(self, sender: str, recipient: str, subject: str, body: str) -> bool:
        logger.info(f'{sender=} {recipient=} {subject=} {body=}')
        return True


instances: dict[str, EmailBackend] = {
    'ses': SesEmailBackend(),
    'debug': DebugEmailBackend()}
