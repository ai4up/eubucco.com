# from ninja.security import APIKeyQuery
#
# from eubucco.users.models import User
#
#
# class ApiKey(APIKeyQuery):
#     param_name = "api_key"
#
#     def authenticate(self, request, key):
#         return User.objects.filter(api_key=key).first()
