class LibraryError(Exception):
    """A business rule was violated. The message is safe to show to users."""

    status_code = 400


class NotFoundError(LibraryError):
    status_code = 404


class PermissionDeniedError(LibraryError):
    status_code = 403


class ConflictError(LibraryError):
    status_code = 409
