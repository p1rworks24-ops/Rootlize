from __future__ import annotations


class SemanticWorkerError(RuntimeError):
    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None):
        super().__init__(message)
        self.code = code or self.code
        self.retryable = self.retryable if retryable is None else retryable


class SemanticWorkerCrashedError(SemanticWorkerError):
    code = "WORKER_CRASHED"


class SemanticWorkerTimeoutError(SemanticWorkerError):
    code = "TIMEOUT"


class SemanticWorkerBusyError(SemanticWorkerError):
    code = "WORKER_BUSY"


class ModelNotInstalledError(SemanticWorkerError):
    code = "MODEL_NOT_INSTALLED"


class ModelCorruptError(SemanticWorkerError):
    code = "MODEL_CORRUPT"

