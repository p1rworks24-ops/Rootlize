"""Manual, UI-independent orchestration of diff, worker, and OCR repository."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Callable

from app.ocr.diff_service import OCRDiffService
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.index_exceptions import OCRIndexAlreadyRunningError,OCRIndexClosedError,OCRIndexPreparationError
from app.ocr.job_models import OCRIndexProgress
from app.ocr.models import OCRIndexSettings
from app.ocr.path_normalization import normalize_windows_path
from app.ocr.repository import OCRRepository
from app.ocr.retry_policy import INCREMENT_RETRY_ERRORS,MAX_RETRIES,TERMINAL_ERRORS,next_retry_time
from app.ocr.worker_exceptions import OCRWorkerCrashedError,OCRWorkerInitializationError,OCRWorkerTimeoutError
from app.ocr.worker_process import snapshot
from app.ocr.worker_protocol import OCRWorkerRequest
from app.utils.logger import setup_logger

logger=setup_logger()
LEASE_SECONDS=300


class OCRIndexService:
    def __init__(self,repository:OCRRepository,worker_client,*,settings:OCRIndexSettings|None=None,on_progress:Callable[[OCRIndexProgress],None]|None=None):
        self.repository=repository; self.worker=worker_client; self.settings=settings or OCRIndexSettings(); self.on_progress=on_progress
        self._lock=threading.RLock(); self._condition=threading.Condition(self._lock); self._progress=OCRIndexProgress(); self._thread=None
        self._pause=False; self._cancel=False; self._closed=False; self._started_at=0.0; self._ocr_durations=[]

    def preview_indexing(self,folder_path): return OCRDiffService(self.repository,settings=self.settings).reconcile(folder_path,dry_run=True)

    def start_indexing(self,folder_path)->str:
        with self._lock:
            if self._closed: raise OCRIndexClosedError("OCR index service is closed.")
            if self.is_running(): raise OCRIndexAlreadyRunningError("OCR indexing is already running.")
            run_id=uuid.uuid4().hex; self._pause=False; self._cancel=False; self._started_at=time.perf_counter(); self._ocr_durations=[]
            self._progress=OCRIndexProgress(run_id=run_id,folder_path=str(Path(folder_path).resolve()),state="preparing")
            self._thread=threading.Thread(target=self._run,args=(folder_path,run_id),name="CapixeOCRIndex",daemon=True); self._thread.start()
            return run_id

    def pause(self):
        with self._condition:
            if self.is_running(): self._pause=True; self._set(state="pausing")

    def resume(self):
        with self._condition:
            if self._progress.state in {"paused","pausing"}: self._pause=False; self._set(state="running"); self._condition.notify_all()

    def cancel(self,*,immediate:bool=False):
        with self._condition:
            if self.is_running(): self._cancel=True; self._pause=False; self._set(state="cancelling"); self._condition.notify_all()
        if immediate: self.worker.terminate()

    def get_status(self):
        with self._lock: return self._with_timing(self._progress)

    def is_running(self): return self._thread is not None and self._thread.is_alive()

    def wait(self,timeout=None):
        thread=self._thread
        if thread: thread.join(timeout)
        return self.get_status()

    def close(self,timeout:float=5):
        with self._lock:
            if self._closed: return
        self.cancel(); self.wait(timeout)
        if self.is_running():
            # Termination wakes a blocked worker request.  Keep the database
            # open until the index thread has released its active claim.
            self.worker.terminate()
            self.wait(2.0)
        else:
            self.worker.shutdown()
        with self._lock: self._closed=True; self._set(state="closing")
        self.repository.database.close()

    def _run(self,folder_path,run_id):
        try:
            self._set(state="scanning")
            preview=OCRDiffService(self.repository,settings=self.settings).reconcile(folder_path,dry_run=True)
            shutil.disk_usage(Path(folder_path))
            self._set(total_discovered=preview.total_files,total_requires_ocr=preview.reindex_required_count)
            self._set(state="initializing_worker"); self.worker.start(); initialized=self.worker.initialize()
            if initialized.get("model_sha256"):
                self.settings=replace(self.settings,model_sha256=initialized["model_sha256"])
            OCRDiffService(self.repository,settings=self.settings).reconcile(folder_path,dry_run=False)
            now=self.repository.database.clock(); cutoff=(datetime.fromisoformat(now)-timedelta(seconds=LEASE_SECONDS)).astimezone(timezone.utc).isoformat()
            self.repository.recover_expired_claims(before=cutoff)
            candidates=self.repository.list_ocr_candidates(folder_path=folder_path,now=now,retry_limit=MAX_RETRIES)
            self._set(state="running",total_requires_ocr=len(candidates),pending=len(candidates))
            for image,document in candidates:
                if not self._before_next(): break
                self._process_one(image,document,run_id)
            with self._lock:
                if self._progress.state=="failed": pass
                elif self._cancel: self._set(state="cancelled",current_image_id=None,current_filename=None,current_started_at=None)
                else: self._set(state="completed",current_image_id=None,current_filename=None,current_started_at=None,pending=max(0,self._progress.total_requires_ocr-self._progress.completed))
        except OCRWorkerInitializationError as exc:
            self._set(state="failed",last_error_type="worker_initialization")
            logger.error("OCR index worker initialization failed: %s",type(exc).__name__)
        except Exception as exc:
            self._set(state="failed",last_error_type=type(exc).__name__)
            logger.error("OCR index run failed: %s",type(exc).__name__)
        finally:
            try: self.worker.shutdown()
            except Exception: self.worker.terminate()

    def _before_next(self):
        with self._condition:
            if self._cancel: return False
            while self._pause and not self._cancel:
                self._set(state="paused",current_image_id=None,current_filename=None,current_started_at=None); self._condition.wait(.2)
            return not self._cancel

    def _process_one(self,image,document,run_id):
        now=self.repository.database.clock(); worker_id=run_id
        try: self.repository.claim_ocr(image.image_id,worker_id=worker_id,claimed_at=now)
        except Exception:
            self._finish_item(success=False,skipped=True,error_type="claim_mismatch"); return
        self._set(current_image_id=image.image_id,current_filename=image.filename,current_started_at=now)
        try:
            current=self.repository.get_image(image.image_id); path=Path(current.path)
            before=snapshot(path)
            if (before.size_bytes,before.mtime_ns,before.quick_fingerprint)!=(current.size_bytes,current.mtime_ns,current.quick_fingerprint):
                self.repository.release_claim(image.image_id,worker_id=worker_id,status="stale"); self._finish_item(success=False,skipped=True,error_type="file_changed_before_processing"); return
            request=OCRWorkerRequest(uuid.uuid4().hex,current.path,current.size_bytes,current.mtime_ns,current.quick_fingerprint,{})
            started=time.perf_counter(); result=self.worker.submit_ocr(request); duration=time.perf_counter()-started
            if self._cancel:
                self.repository.release_claim(image.image_id,worker_id=worker_id,status="stale"); self._finish_item(success=False,skipped=True,error_type="cancelled"); return
            if result.success and not result.file_changed_before_processing and not result.file_changed_during_processing and self._final_snapshot_matches(image.image_id,worker_id,result):
                self.repository.save_claimed_ocr_success(image.image_id,worker_id=worker_id,ocr_text=result.full_text,average_confidence=result.average_confidence,indexed_at=self.repository.database.clock(),engine_name=result.engine_name,engine_version=result.engine_version,model_name=result.model_name,model_sha256=result.model_sha256,pipeline_version=result.pipeline_version,settings_fingerprint=self.settings.settings_fingerprint)
                self._ocr_durations.append(duration); self._finish_item(success=True); return
            self._save_failure(image.image_id,worker_id,document,result.error_type or "file_changed_during_processing",result.error_message_safe or "OCR result could not be saved.",retryable=result.retryable)
        except (FileNotFoundError,OSError):
            self.repository.release_claim(image.image_id,worker_id=worker_id,status="stale"); self._finish_item(success=False,skipped=True,error_type="file_missing")
        except (OCRWorkerTimeoutError,OCRWorkerCrashedError) as exc:
            if self._cancel:
                self.repository.release_claim(image.image_id,worker_id=worker_id,status="stale"); self._finish_item(success=False,skipped=True,error_type="cancelled"); return
            error_type="timeout" if isinstance(exc,OCRWorkerTimeoutError) else "worker_crashed"
            self._save_failure(image.image_id,worker_id,document,error_type,"OCR worker did not complete the request.")
            if self._progress.worker_restart_count<1:
                try: self.worker.restart(); self._set(worker_restart_count=1)
                except Exception: self._set(state="failed",last_error_type="worker_restart_failed"); self._cancel=True
            else: self._set(state="failed",last_error_type=error_type); self._cancel=True

    def _final_snapshot_matches(self,image_id,worker_id,result):
        try:
            image=self.repository.get_image(image_id); document=self.repository.get_ocr_document(image_id); current=snapshot(Path(image.path))
            return document.worker_id==worker_id and normalize_windows_path(result.path)==image.path_norm and result.file_after==current
        except Exception: return False

    def _save_failure(self,image_id,worker_id,document,error_type,message,*,retryable=True):
        increment=retryable and error_type in INCREMENT_RETRY_ERRORS; count=document.retry_count+(1 if increment else 0); terminal=error_type in TERMINAL_ERRORS or not retryable or count>=MAX_RETRIES
        now=self.repository.database.clock(); retry_at=next_retry_time(count,now) if increment and not terminal else None
        self.repository.save_claimed_ocr_failure(image_id,worker_id=worker_id,error_type=error_type,error_message_safe=message,attempted_at=now,increment_retry=increment,next_retry_at=retry_at,terminal=terminal)
        self._finish_item(success=False,error_type=error_type)

    def _finish_item(self,*,success,skipped=False,error_type=None):
        p=self._progress; self._set(completed=p.completed+1,succeeded=p.succeeded+(1 if success else 0),failed=p.failed+(1 if not success and not skipped else 0),skipped=p.skipped+(1 if skipped else 0),pending=max(0,p.total_requires_ocr-p.completed-1),current_image_id=None,current_filename=None,current_started_at=None,last_error_type=error_type)

    def _with_timing(self,progress):
        elapsed=max(0,time.perf_counter()-self._started_at) if self._started_at else 0; estimate=None
        if self._ocr_durations and progress.pending: estimate=sum(self._ocr_durations)/len(self._ocr_durations)*progress.pending
        return replace(progress,elapsed_seconds=elapsed,estimated_remaining_seconds=estimate)

    def _set(self,**changes):
        with self._lock: self._progress=replace(self._progress,**changes); snapshot_progress=self._with_timing(self._progress)
        if self.on_progress:
            try: self.on_progress(snapshot_progress)
            except Exception: logger.warning("OCR progress callback failed: callback_error")
