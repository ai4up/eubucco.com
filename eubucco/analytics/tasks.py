from eubucco.analytics.models import FileDownload


def insert_download_analytics(file_id, is_api):
    file_download = FileDownload(file_id=file_id, is_api=is_api)
    file_download.save()
