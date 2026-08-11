class OCRDatabaseError(RuntimeError):
    """Base error for the local OCR index."""


class OCRDatabaseSchemaError(OCRDatabaseError):
    pass


class OCRFTSUnavailableError(OCRDatabaseError):
    pass


class OCRDatabaseCorruptionError(OCRDatabaseError):
    pass


class OCRRecordNotFoundError(OCRDatabaseError):
    pass


class OCRDuplicatePathError(OCRDatabaseError):
    pass


class OCRInvalidRecordError(OCRDatabaseError):
    pass


class OCRFolderScanError(OCRDatabaseError):
    """The selected folder could not be scanned safely."""
