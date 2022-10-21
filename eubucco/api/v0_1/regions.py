from typing import Optional

from fastapi import APIRouter
from fastapi.openapi.models import Schema
from pydantic import validator

from eubucco.api.v0_1.buildings import BuildingResponse
from eubucco.api.v0_1.cities import CityResponse
from eubucco.data.models import Building, City, Region

router = APIRouter()


class RegionCountryResponse(Schema):
    id: int
    name: str


class RegionResponse(Schema):
    id: int
    name: str
    in_country: RegionCountryResponse
    geometry: Optional[str]

    @validator("geometry", pre=True)
    def stringify_geometry(cls, v):
        return v.wkt if v is not None else None


@router.get("", response_model=list[RegionResponse])
def get_all_countries(request):
    return Region.objects.select_related("in_country").all()


@router.get("/search", response_model=list[RegionResponse])
def search_for_regions(request, query: str):
    return Region.objects.filter(name__icontains=query).select_related()


@router.get("/{id}", response_model=list[RegionResponse])
def get_region_by_id(request, id: int):
    return Region.objects.filter(pk=id).select_related()


@router.get("/{id}/cities", response_model=list[CityResponse])
def get_city_by_region_id(request, id: int):
    return City.objects.filter(in_region=id).select_related()


@router.get("/{id}/buildings", response_model=list[BuildingResponse])
def get_buildings_of_region(request, id: int):
    return Building.objects.filter(city_id=id).select_related()
