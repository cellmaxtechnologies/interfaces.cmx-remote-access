class PDMError(Exception):
    pass

class PDMConnectionError(PDMError):
    pass

class PDMFileNotFoundError(PDMError):
    pass

class PDMFileInfoError(PDMError):
    pass

class PDMOperationFailedError(PDMError):
    pass

class PDMCastError(PDMError):
    pass

class PDMFileExistsError(PDMError):
    pass

