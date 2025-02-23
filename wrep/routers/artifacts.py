from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from .. import utils
from ..backends.artifacts import Disp, get_artifact_response
from ..models import ArtifactDetail
from .api import retrieve404

logger = utils.get_logger('artifacts')

router = APIRouter()

@router.head('/artifacts/{id}/data')
@router.get('/artifacts/{id}/data')
async def artifact_data(req: Request, id: UUID, disposition: Disp = 'download'):
    artifact = await retrieve404(ArtifactDetail, id=[id])
    return get_artifact_response(req.method, artifact, disposition)
