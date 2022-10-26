import os


def get_file_size(path: str) -> float:
    file_stats = os.stat(str(path))
    return file_stats.st_size / (1024 * 1024)
