class ApiError(Exception):
    def __init__(self, msg, status=400, fields=None):
        self.msg, self.status, self.fields = msg, status, fields or {}
