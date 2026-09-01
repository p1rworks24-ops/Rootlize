"""Qt wrapper around AuthService. Widgets never call Supabase."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.auth import (
    AccountSession,
    AuthError,
    AuthService,
    AuthStatus,
    OAuthProvider,
    build_auth_service,
    local_features_available,
)
from app.auth.config import allow_anonymous_prototype_session, is_auth_required
from app.budget.models import AIUsageStatus
from app.budget.service import BudgetService
from app.i18n import t


def _qobject_alive(obj) -> bool:
    if obj is None:
        return False
    try:
        from shiboken6 import isValid
    except Exception:
        return True
    try:
        return bool(isValid(obj))
    except Exception:
        return False


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


class _AuthWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except AuthError as exc:
            self.failed.emit(exc.message_key)
        except Exception:
            self.failed.emit("account.error.unknown")


class AccountController(QObject):
    session_changed = Signal(object)
    usage_changed = Signal(object)
    busy_changed = Signal(bool)
    message = Signal(str)

    def __init__(
        self,
        service: AuthService | None = None,
        budget: BudgetService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service or build_auth_service()
        self._budget = budget or BudgetService(
            rest_url=self._service.rest_url,
            publishable_key=self._service.publishable_key,
            http=self._service.http,
        )
        self._thread: QThread | None = None
        self._worker: _AuthWorker | None = None
        self._usage_thread: QThread | None = None
        self._usage_worker: _AuthWorker | None = None
        self._generation = 0
        self._shutting_down = False

    @property
    def service(self) -> AuthService:
        return self._service

    @property
    def budget(self) -> BudgetService:
        return self._budget

    @property
    def session(self) -> AccountSession:
        return self._service.session

    def local_library_available(self) -> bool:
        return local_features_available(self.session)

    def restore_in_background(self) -> None:
        if not self._accepting_callbacks():
            return
        signed_out = self._service.session.status == AuthStatus.SIGNED_OUT
        if (
            signed_out
            and not self._service.has_stored_session()
            and (is_auth_required() or not self._service.configured or not allow_anonymous_prototype_session())
        ):
            self.session_changed.emit(self._service.restore_session())
            return
        self._run(self._service.restore_or_ensure_session)

    def sign_in_email(self, email: str, password: str) -> None:
        self._run(lambda: self._service.sign_in_email(email, password))

    def sign_up_email(self, email: str, password: str) -> None:
        self._run(lambda: self._service.sign_up_email(email, password))

    def start_google(self) -> None:
        self._run(lambda: self._service.start_oauth(OAuthProvider.GOOGLE))

    def start_github(self) -> None:
        self._run(lambda: self._service.start_oauth(OAuthProvider.GITHUB))

    def sign_out(self) -> None:
        self._run(self._service.sign_out)

    def apply_proxy_usage(self, payload: dict) -> None:
        if not self._accepting_callbacks():
            return
        status = self._budget.apply_status(AIUsageStatus.from_payload(payload))
        self.usage_changed.emit(status)

    def refresh_usage(self) -> None:
        if not self._accepting_callbacks():
            return
        session = self.session
        if not session.is_authenticated:
            self.usage_changed.emit(None)
            return
        if session.status == AuthStatus.OFFLINE_SESSION:
            self.usage_changed.emit(self._budget.unavailable_status())
            return
        token = self._service.bearer_token()
        if not token:
            self.usage_changed.emit(self._budget.unavailable_status())
            return
        if self._usage_thread is not None:
            return
        thread = QThread()
        worker = _AuthWorker(lambda: self._budget.get_status(token))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_usage_finished)
        worker.failed.connect(self._on_usage_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_usage_thread)
        self._usage_thread = thread
        self._usage_worker = worker
        thread.start()

    def shutdown(self) -> None:
        from app.ai_budget import reset_ai_budget_gate_for_tests
        from app.ai_proxy import reset_ai_proxy_client_for_tests

        self._shutting_down = True
        self._generation += 1
        self.blockSignals(True)
        self._service.cancel_oauth()
        self._detach_worker(self._worker, self._on_finished, self._on_failed)
        self._detach_worker(
            self._usage_worker, self._on_usage_finished, self._on_usage_failed
        )
        thread = self._thread
        if thread is not None:
            thread.quit()
            thread.wait(3000)
        usage_thread = self._usage_thread
        if usage_thread is not None:
            usage_thread.quit()
            usage_thread.wait(3000)
        still_running = (
            thread is not None and thread.isRunning()
        ) or (
            usage_thread is not None and usage_thread.isRunning()
        )
        if still_running:
            # Keep QObjects alive so a late restore cannot emit into teardown.
            self.setParent(None)
        else:
            self._thread = None
            self._worker = None
            self._usage_thread = None
            self._usage_worker = None
        reset_ai_budget_gate_for_tests()
        reset_ai_proxy_client_for_tests()

    def _accepting_callbacks(self) -> bool:
        return not self._shutting_down and _qobject_alive(self)

    def _detach_worker(self, worker, finished_slot, failed_slot) -> None:
        if worker is None:
            return
        _disconnect(worker.finished, finished_slot)
        _disconnect(worker.failed, failed_slot)

    def _run(self, fn) -> None:
        if not self._accepting_callbacks() or self._thread is not None:
            return
        self.busy_changed.emit(True)
        quiet = fn in {
            self._service.restore_session,
            self._service.restore_or_ensure_session,
            self._service.ensure_prototype_session,
            self._service.sign_out,
        }
        if not quiet:
            current = self._service.session
            self.session_changed.emit(
                AccountSession(
                    status=AuthStatus.SIGNING_IN,
                    user=current.user,
                    entitlement=current.entitlement,
                )
            )
        thread = QThread()
        worker = _AuthWorker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_finished(self, session: AccountSession) -> None:
        if not self._accepting_callbacks():
            return
        self.busy_changed.emit(False)
        self.session_changed.emit(session)
        if session.message_key:
            self.message.emit(t(session.message_key))
        self.refresh_usage()

    def _on_usage_finished(self, status: AIUsageStatus) -> None:
        if not self._accepting_callbacks():
            return
        self.usage_changed.emit(status)

    def _on_usage_failed(self, _message_key: str) -> None:
        if not self._accepting_callbacks():
            return
        self.usage_changed.emit(self._budget.unavailable_status())

    def _cleanup_usage_thread(self) -> None:
        self._usage_thread = None
        self._usage_worker = None

    def _on_failed(self, message_key: str) -> None:
        if not self._accepting_callbacks():
            return
        self.busy_changed.emit(False)
        self.message.emit(t(message_key))
        self.session_changed.emit(self._service.session)

    def _cleanup_thread(self) -> None:
        self._thread = None
        self._worker = None
