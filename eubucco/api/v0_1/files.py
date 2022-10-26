import os
from typing import Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, root_validator

from eubucco.files.models import File

router = APIRouter()


class FileInfoResponse(BaseModel):
    id: UUID
    name: str
    size_in_mb: float
    type: str
    download_link: Optional[str]

    @root_validator()
    def create_download_link(cls, values):
        values[
            "download_link"
        ] = f"{os.environ['API_URL']}files/{values['id']}/download"
        return values

    class Config:
        orm_mode = True


@router.get("/{file_id}", response_model=FileInfoResponse)
async def get_file_info(file_id):
    file = await sync_to_async(File.objects.get)(pk=file_id)
    if file:
        return FileInfoResponse.from_orm(file)
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/{file_id}/download", response_class=FileResponse)
async def download_file(file_id):
    try:
        file = await sync_to_async(File.objects.get)(pk=file_id)
        return FileResponse(
            f"{file.path}",
            headers={
                "Content-Disposition": f'attachment; filename="{file.path.split("/")[-1]}"'
            },
        )

    except ObjectDoesNotExist:
        raise HTTPException(status_code=404, detail="Item not found")
