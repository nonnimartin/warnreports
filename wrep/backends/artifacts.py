from __future__ import annotations

import functools
import hashlib
import logging
from email.utils import formatdate
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, status
from fastapi.responses import Response, StreamingResponse

from .. import settings
from ..models import *

type Disp = Literal['inline', 'download']

logger = logging.getLogger(__name__)

def get_artifact_response(method: str, artifact: ArtifactDetail, disposition: Disp):
    headers = get_resp_headers(artifact, disposition)
    if method == 'HEAD':
        RepCls = Response
        status_code = status.HTTP_204_NO_CONTENT
        content = None
    else:
        RepCls = StreamingResponse
        status_code = status.HTTP_200_OK
        try:
            if settings.ARTIFACTS_SRV_BACKEND == 's3':
                content = get_s3_content(artifact)
            else:
                content = get_file_content(artifact)
        except Exception as e:
            logger.exception(f'{artifact=}')
            status_code, detail = get_errargs(e)
            raise HTTPException(status_code=status_code, detail=detail)
    return RepCls(
        content=content,
        status_code=status_code,
        headers=headers,
        media_type=artifact.media_type)

def get_s3_content(artifact: ArtifactDetail):
    return gets3().get_object(
        Bucket=settings.ARTIFACTS_SRV_URI,
        Key=artifact.path)['Body'].iter_chunks()

def get_file_content(artifact: ArtifactDetail):
    root = Path(settings.ARTIFACTS_SRV_URI)
    return (root/artifact.path).open('rb')

def get_resp_headers(artifact: ArtifactDetail, disposition: Disp) -> dict[str, str]:
    mtime = artifact.modified.timestamp()
    etag_base = f'{mtime}-{artifact.size}'
    digest = hashlib.md5(etag_base.encode(), usedforsecurity=False).hexdigest()
    return {
        'content-disposition': f'{disposition}; filename="{artifact.name}"',
        'content-length': str(artifact.size),
        'last-modified': formatdate(mtime, usegmt=True),
        'etag': f'"{digest}"'}

def get_errargs(e: Exception) -> tuple[int, str]:
    if isinstance(e, FileNotFoundError):
        return status.HTTP_404_NOT_FOUND, 'Not Found'
    if hasattr(e, 'message'):
        err = e.message['response']['Error']
        return err['Code'], err['Message']
    return status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)

@functools.cache
def gets3():
    import boto3
    return boto3.client('s3')
