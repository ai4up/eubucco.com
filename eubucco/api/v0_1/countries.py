import os
from typing import Optional

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, root_validator, validator

from eubucco.data.models import Country

router = APIRouter()


class CountryResponse(BaseModel):
    id: int
    name: str
    convex_hull: Optional[str]
    csv_link: Optional[str]
    csv_size_in_mb: Optional[str]
    gpkg_link: Optional[str]
    gpkg_size_in_mb: Optional[str]

    @validator("convex_hull", pre=True)
    def stringify_geometry(cls, v):
        return v.wkt if v is not None else None

    @root_validator()
    def create_download_links(cls, values):
        values["csv_link"] = f"{os.environ['API_URL']}countries/{values['id']}/csv"
        values["gpkg_link"] = f"{os.environ['API_URL']}countries/{values['id']}/gpkg"
        return values

    class Config:
        orm_mode = True


@router.get("", response_model=list[CountryResponse])
def get_all_countries():
    return list(Country.objects.all().defer("geometry"))


@router.get("/{country_id}/{type}", response_class=FileResponse)
async def download_example(country_id, type):
    try:
        country = await sync_to_async(Country.objects.get)(pk=country_id)
        if type == "csv":
            return FileResponse(
                f"{country.csv_path}",
                headers={
                    "Content-Disposition": f'attachment; filename="{country.csv_path.split("/")[-1]}"'
                },
            )

        if type == "gpkg":
            return FileResponse(
                f"{country.gpkg_path}",
                headers={
                    "Content-Disposition": f'attachment; filename="{country.gpkg_path.split("/")[-1]}"'
                },
            )

        raise HTTPException(status_code=404, detail="Item not found")

    except ObjectDoesNotExist:
        raise HTTPException(status_code=404, detail="Item not found")


# @router.get("/search", response_model=List[CountryResponse])
# async def search_for_countries(query: str):
#     return list(Country.objects.filter(name__icontains=query).select_related())
#
#
# @router.get("/{id}", response_model=List[CountryResponse])
# async def get_country_by_id(id: int):
#     return list(Country.objects.filter(pk=id).select_related())
#
#
# @router.get("/{id}/regions", response_model=List[RegionResponse])
# async def get_regions_by_country_id(id: int):
#     return list(Region.objects.filter(in_country=id).select_related())
