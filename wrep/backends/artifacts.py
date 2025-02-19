from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from .. import settings
from ..models import *

type Disp = Literal['inline', 'download']
async def get_artifact_response(artifact: ArtifactDetail, disposition: Disp):
    if settings.ARTIFACTS_SRV_BACKEND == 's3':
        return await get_s3_reponse(artifact, disposition)
    return FileResponse(
        Path(settings.ARTIFACTS_SRV_URI)/artifact.path,
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type=disposition)

async def get_s3_reponse(artifact: ArtifactDetail, disposition: Disp):
    s3 = gets3()
    try:
        result = s3.get_object(
            Bucket=settings.ARTIFACTS_SRV_URI,
            Key=artifact.path)
        return StreamingResponse(content=result['Body'].iter_chunks())
    except Exception as e:
        if hasattr(e, 'message'):
            raise HTTPException(
                status_code=e.message['response']['Error']['Code'],
                detail=e.message['response']['Error']['Message'],)
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e))

@functools.cache
def gets3():
    import boto3
    return boto3.client('s3')