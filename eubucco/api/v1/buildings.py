from math import isnan
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, validator

from eubucco.data.models import Building

router = APIRouter()


class BuildingResponse(BaseModel):
    id: str
    id_source: str
    height: Optional[float]
    country_id: int
    region_id: int
    city_id: int
    age: Optional[int]
    type: str
    type_source: str

    geometry: str

    @validator("geometry", pre=True)
    def stringify_geometry(cls, v):
        return v.wkt if v is not None else None

    @validator("height", pre=True)
    def clean_nan(cls, v):
        return None if isnan(v) else v

    class Config:
        orm_mode = True


@router.get("", response_model=list[BuildingResponse])
def get_buildings():
    """
    This endpoint returns a paginated response of all buildings in the Database.
    """
    return list(Building.objects.all()[:500])
