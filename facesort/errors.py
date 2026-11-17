"""Lỗi có thông báo thân thiện cho người dùng."""


class FacesortError(Exception):
    """Lỗi mà người dùng cần đọc; CLI in thông báo, không in traceback."""


class ConfigError(FacesortError):
    pass


class ProjectError(FacesortError):
    pass


class LabelError(FacesortError):
    pass
