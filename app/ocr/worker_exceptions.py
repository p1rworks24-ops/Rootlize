class OCRWorkerError(RuntimeError): pass
class OCRWorkerStartupError(OCRWorkerError): pass
class OCRWorkerInitializationError(OCRWorkerError): pass
class OCRWorkerTimeoutError(OCRWorkerError): pass
class OCRWorkerProtocolError(OCRWorkerError): pass
class OCRWorkerCrashedError(OCRWorkerError): pass
class OCRWorkerNotRunningError(OCRWorkerError): pass
class OCRWorkerBusyError(OCRWorkerError): pass
