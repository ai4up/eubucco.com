# from datetime import datetime
# from uuid import UUID
#
# from django.http import HttpResponse
# from ninja import Router, Schema
# from slugify import slugify
#
# from eubucco.api.v1.auth import ApiKey
# from eubucco.api.v1.cities import CityResponse
# from eubucco.api.v1.countries import CountryResponse
# from eubucco.api.v1.regions import RegionResponse
# from eubucco.dumps.models import Dump
# from eubucco.dumps.tasks import create_custom_dump
# from eubucco.users.models import User
#
# api_key = ApiKey()
# router = Router()
#
#
# class DumpRequest(Schema):
#     name: str
#     country_ids: list[int]
#     region_ids: list[int]
#     city_ids: list[int]
#
#
# class DumpResponse(Schema):
#     id: UUID
#     requested_on: datetime
#     name: str
#     countries: list[CountryResponse]
#     regions: list[RegionResponse]
#     cities: list[CityResponse]
#     is_done: bool
#     status: str
#     is_deleted: bool
#
#
# @router.get("", auth=api_key, response=list[DumpResponse])
# def get_my_dumps(request):
#     assert isinstance(request.auth, User)
#     user = request.auth
#     return (
#         Dump.objects.filter(user=user)
#         .filter(is_deleted=False)
#         .order_by("-requested_on")
#         .select_related()[:1]
#     )
#
#
# @router.post("", auth=api_key, response=DumpResponse)
# def post_dump(request, data: DumpRequest):
#     assert isinstance(request.auth, User)
#     user = request.auth
#
#     dump = create_custom_dump(
#         user=user,
#         name=data.name,
#         country_ids=data.country_ids,
#         region_ids=data.region_ids,
#         city_ids=data.city_ids,
#     )
#
#     return dump
#
#
# @router.get("/{id}", auth=api_key, response=DumpResponse)
# def get_dump(request, id: UUID):
#     assert isinstance(request.auth, User)
#     user = request.auth
#     dump = Dump.objects.get(id=id)
#     assert dump.user == user
#     return dump
#
#
# @router.get("/{id}/download", auth=api_key, response=DumpResponse)
# def get_dump_download(request, id: UUID):
#     assert isinstance(request.auth, User)
#     user = request.auth
#     dump = Dump.objects.get(id=id)
#     assert dump.user == user
#     if not dump.is_done:
#         return
#     if dump.is_deleted:
#         return
#
#     response = HttpResponse(
#         f"/dumps/data/{dump.id}.zip",  # output is the file
#         content_type="application/zip",
#     )
#     response[
#         "Content-Disposition"
#     ] = f"attachment; filename={slugify(dump.name)}.zip"  # fname is the name of the file
#     return response
