import os
from typing import Optional

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, root_validator

from eubucco.examples.models import Example

router = APIRouter()


class ExampleResponse(BaseModel):
    name: str
    csv_link: Optional[str]
    csv_size_in_mb: str
    gpkg_link: Optional[str]
    gpkg_size_in_mb: str

    @root_validator()
    def create_download_links(cls, values):
        values["csv_link"] = f"{os.environ['API_URL']}examples/{values['name']}/csv"
        values["gpkg_link"] = f"{os.environ['API_URL']}examples/{values['name']}/gpkg"
        return values

    class Config:
        orm_mode = True


@router.get("", response_model=list[ExampleResponse])
def get_all_examples():
    return [ExampleResponse.from_orm(e) for e in Example.objects.all()]


@router.get("/{name}/{type}", response_class=FileResponse)
async def download_example(name, type):
    try:
        example = await sync_to_async(Example.objects.get)(pk=name)
        if type == "csv":
            return FileResponse(
                f"{example.csv_path}",
                headers={
                    "Content-Disposition": f'attachment; filename="{example.csv_path.split("/")[-1]}"'
                },
            )

        if type == "gpkg":
            return FileResponse(
                f"{example.gpkg_path}",
                headers={
                    "Content-Disposition": f'attachment; filename="{example.gpkg_path.split("/")[-1]}"'
                },
            )

        raise HTTPException(status_code=404, detail="Item not found")

    except ObjectDoesNotExist:
        raise HTTPException(status_code=404, detail="Item not found")
