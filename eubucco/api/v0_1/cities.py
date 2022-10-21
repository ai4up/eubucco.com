from typing import Optional

from fastapi import APIRouter
from fastapi.openapi.models import Schema
from pydantic import validator

from eubucco.api.v0_1.buildings import BuildingResponse
from eubucco.data.models import Building, City

router = APIRouter()


class CityCountryResponse(Schema):
    id: int
    name: str


class CityRegionResponse(Schema):
    id: int
    name: str


class CityResponse(Schema):
    id: int
    name: str
    in_country: CityCountryResponse
    in_region: CityRegionResponse
    geometry: Optional[str]

    @validator("geometry", pre=True)
    def stringify_geometry(cls, v):
        return v.wkt if v is not None else None


@router.get("", response_model=list[CityResponse])
def get_all_cities(request):
    """
    This endpoint returns a paginated response of all cities in the Database.
    """
    return City.objects.select_related().all()


@router.get("/search", response_model=list[CityResponse])
def search_for_cities(request, query: str):
    return City.objects.filter(name__icontains=query).select_related()


@router.get("/{id}", response_model=list[CityResponse])
def get_city_by_id(request, id: int):
    return City.objects.filter(pk=id).select_related()


@router.get("/{id}/buildings", response_model=list[BuildingResponse])
def get_buildings_of_city(request, id: int):
    return Building.objects.filter(city_id=id).select_related()
