class OCRIndexError(RuntimeError): pass
class OCRIndexAlreadyRunningError(OCRIndexError): pass
class OCRIndexPreparationError(OCRIndexError): pass
class OCRIndexWorkerError(OCRIndexError): pass
class OCRIndexCancelledError(OCRIndexError): pass
class OCRIndexClosedError(OCRIndexError): pass
