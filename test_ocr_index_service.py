from __future__ import annotations

import os,shutil,struct,time
from pathlib import Path

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.index_exceptions import OCRIndexAlreadyRunningError,OCRIndexClosedError
from app.ocr.index_service import OCRIndexService
from app.ocr.models import OCRIndexSettings
from app.ocr.repository import OCRRepository
from app.ocr.worker_client import OCRWorkerClient,OCRWorkerConfig,OCRWorkerTimeouts
from app.ocr.worker_exceptions import OCRWorkerCrashedError
from app.ocr.worker_process import FakeEngine,process_request

NOW="2026-08-03T02:00:00+00:00"

def write_png(path:Path,payload=b"data"):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\x0dIHDR"+struct.pack(">II",10,20)+payload); return path

@pytest.fixture
def repository(tmp_path):
    db=OCRDatabase(tmp_path/"db/index.sqlite3",clock=lambda:NOW).open(); yield OCRRepository(db); db.close()

class StubWorker:
    def __init__(self,mode="success",delay=0): self.engine=FakeEngine("success"); self.mode=mode; self.delay=delay; self.running=False; self.restart_count=0; self.calls=0
    def start(self): self.running=True
    def initialize(self):
        if self.mode=="model_missing": from app.ocr.worker_exceptions import OCRWorkerInitializationError; raise OCRWorkerInitializationError("missing")
        return {"success":True,"model_sha256":"fake-sha"}
    def submit_ocr(self,request):
        self.calls+=1
        if self.delay: request=type(request)(request.request_id,request.path,request.expected_size_bytes,request.expected_mtime_ns,request.expected_quick_fingerprint,{"delay_seconds":self.delay})
        if self.mode=="crash_once" and self.calls==1: raise OCRWorkerCrashedError("crash")
        if self.mode=="fail": request=type(request)(request.request_id,request.path,request.expected_size_bytes,request.expected_mtime_ns,request.expected_quick_fingerprint,{"fail":True})
        if self.mode=="change": request=type(request)(request.request_id,request.path,request.expected_size_bytes,request.expected_mtime_ns,request.expected_quick_fingerprint,{"mutate_after":True})
        return process_request(self.engine,request)
    def restart(self):
        self.restart_count+=1
        if self.mode=="restart_fail": raise RuntimeError("restart failed")
        self.running=True; return self.initialize()
    def shutdown(self): self.running=False
    def terminate(self): self.running=False

def run_service(repository,worker,folder,callback=None,timeout=10):
    service=OCRIndexService(repository,worker,on_progress=callback); service.start_indexing(folder); status=service.wait(timeout); return service,status

def test_all_success_saves_ready_fts_and_preserves_tags(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png")
    service,status=run_service(repository,StubWorker(),folder)
    image=repository.get_image_by_path(path); document=repository.get_ocr_document(image.image_id)
    assert status.state=="completed" and (status.succeeded,status.failed)==(1,0)
    assert document.status=="ready" and document.ocr_text and document.retry_count==0 and document.error_type is None
    assert repository.search("english")[0].image_id==image.image_id

def test_success_preserves_existing_tag_cache(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); from app.ocr.diff_service import OCRDiffService; OCRDiffService(repository).reconcile(folder,dry_run=False)
    image=repository.get_image_by_path(path); repository.update_tags(image.image_id,["keep-tag"])
    _,status=run_service(repository,StubWorker(),folder)
    assert status.succeeded==1 and repository.get_search_document(image.image_id).tags_norm=="keep-tag"

def test_real_subprocess_fake_worker_integration(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png")
    worker=OCRWorkerClient(OCRWorkerConfig(fake_mode="success",timeouts=OCRWorkerTimeouts(initialize=3,ocr=3)))
    _,status=run_service(repository,worker,folder)
    assert status.state=="completed" and status.succeeded==1 and worker.process is None

def test_second_run_has_no_ocr_targets(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); first=StubWorker(); run_service(repository,first,folder)
    second=StubWorker(); _,status=run_service(repository,second,folder)
    assert status.total_requires_ocr==0 and second.calls==0

def test_close_waits_for_active_claim_release_after_worker_terminate(tmp_path):
    db_path=tmp_path/"db"/"index.sqlite3"; db=OCRDatabase(db_path,clock=lambda:NOW).open(); repository=OCRRepository(db)
    folder=tmp_path/"shots"; write_png(folder/"one.png")
    service=OCRIndexService(repository,StubWorker(delay=.2)); service.start_indexing(folder)
    deadline=time.monotonic()+3
    while service.get_status().current_filename is None and time.monotonic()<deadline: time.sleep(.01)
    assert service.get_status().current_filename=="one.png"
    service.close(timeout=.01)
    assert not service.is_running()
    reopened=OCRDatabase(db_path,clock=lambda:NOW).open()
    try:
        states=[row[0] for row in reopened.connection.execute("SELECT status FROM ocr_documents")]
        assert states and "running" not in states
    finally: reopened.close()

def test_modified_image_only_is_reindexed(repository,tmp_path):
    folder=tmp_path/"shots"; first=write_png(folder/"one.png"); write_png(folder/"two.png"); run_service(repository,StubWorker(),folder)
    write_png(first,b"changed-longer"); worker=StubWorker(); _,status=run_service(repository,worker,folder)
    assert status.total_requires_ocr==1 and worker.calls==1 and status.succeeded==1

def test_candidate_priority_stale_pending_failed(repository,tmp_path):
    folder=tmp_path/"shots"; paths=[write_png(folder/f"{name}.png") for name in ("pending","stale","failed")]
    from app.ocr.diff_service import OCRDiffService
    OCRDiffService(repository).reconcile(folder,dry_run=False)
    images=[repository.get_image_by_path(p) for p in paths]
    repository.save_ocr_document(images[1].image_id,status="stale"); repository.save_ocr_document(images[2].image_id,status="failed",retry_count=1)
    assert [doc.status for _,doc in repository.list_ocr_candidates(folder_path=folder,now=NOW)]==["stale","pending","failed"]

def test_next_retry_in_future_is_excluded(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); from app.ocr.diff_service import OCRDiffService; OCRDiffService(repository).reconcile(folder,dry_run=False)
    image=repository.get_image_by_path(path); repository.claim_ocr(image.image_id,worker_id="x",claimed_at=NOW); repository.save_claimed_ocr_failure(image.image_id,worker_id="x",error_type="ocr_failed",error_message_safe="failed",attempted_at=NOW,increment_retry=True,next_retry_at="2026-08-03T02:05:00+00:00")
    assert repository.list_ocr_candidates(folder_path=folder,now=NOW)==[]

def test_failed_ocr_increments_retry_and_sets_next_retry(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); _,status=run_service(repository,StubWorker("fail"),folder)
    doc=repository.get_ocr_document(repository.get_image_by_path(path).image_id)
    assert status.failed==1 and doc.status=="failed" and doc.retry_count==1 and doc.next_retry_at

def test_file_change_does_not_increment_retry(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); _,status=run_service(repository,StubWorker("change"),folder)
    doc=repository.get_ocr_document(repository.get_image_by_path(path).image_id)
    assert doc.retry_count==0 and doc.status=="stale" and status.failed==1

def test_worker_crash_restarts_once_and_preserves_partial_progress(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); write_png(folder/"two.png"); worker=StubWorker("crash_once")
    _,status=run_service(repository,worker,folder)
    assert status.worker_restart_count==1 and worker.restart_count==1 and status.completed==2 and status.succeeded==1 and status.failed==1

def test_worker_restart_failure_stops_run(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); worker=StubWorker("restart_fail")
    def crash(_request): raise OCRWorkerCrashedError("crash")
    worker.submit_ocr=crash
    _,status=run_service(repository,worker,folder)
    assert status.state=="failed" and status.last_error_type=="worker_restart_failed"

def test_pause_and_resume_between_images(repository,tmp_path):
    folder=tmp_path/"shots"; [write_png(folder/f"{i}.png") for i in range(3)]; service=OCRIndexService(repository,StubWorker(delay=.15)); service.start_indexing(folder); time.sleep(.05); service.pause()
    deadline=time.time()+3
    while time.time()<deadline and service.get_status().state!="paused": time.sleep(.02)
    assert service.get_status().state=="paused"; completed=service.get_status().completed; service.resume(); status=service.wait(5)
    assert status.state=="completed" and status.succeeded==3 and status.completed>=completed

def test_cancel_keeps_completed_and_unprocessed_pending(repository,tmp_path):
    folder=tmp_path/"shots"; [write_png(folder/f"{i}.png") for i in range(3)]; service=OCRIndexService(repository,StubWorker(delay=.15)); service.start_indexing(folder)
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        current=service.get_status()
        if current and current.succeeded>=1: break
        time.sleep(.02)
    service.cancel(); status=service.wait(5)
    assert status.state=="cancelled" and status.succeeded>=1
    assert any(doc.status=="pending" for image in repository.list_images() for doc in [repository.get_ocr_document(image.image_id)])

def test_progress_callback_and_exception_are_isolated(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); states=[]
    def callback(progress): states.append(progress.state); raise RuntimeError()
    _,status=run_service(repository,StubWorker(),folder,callback)
    assert status.state=="completed" and "running" in states and status.elapsed_seconds>=0

def test_running_claim_recovery_has_no_retry_penalty(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); from app.ocr.diff_service import OCRDiffService; OCRDiffService(repository).reconcile(folder,dry_run=False)
    image=repository.get_image_by_path(path); repository.claim_ocr(image.image_id,worker_id="dead",claimed_at="2026-08-03T01:00:00+00:00")
    assert repository.recover_expired_claims(before="2026-08-03T01:55:00+00:00")==1
    doc=repository.get_ocr_document(image.image_id); assert doc.status=="pending" and doc.retry_count==0 and doc.worker_id is None

def test_claim_owner_mismatch_cannot_save_result(repository,tmp_path):
    folder=tmp_path/"shots"; path=write_png(folder/"one.png"); from app.ocr.diff_service import OCRDiffService; OCRDiffService(repository).reconcile(folder,dry_run=False)
    image=repository.get_image_by_path(path); repository.claim_ocr(image.image_id,worker_id="owner",claimed_at=NOW)
    from app.ocr.exceptions import OCRInvalidRecordError
    with pytest.raises(OCRInvalidRecordError): repository.save_claimed_ocr_success(image.image_id,worker_id="other",ocr_text="unsafe",average_confidence=.9,indexed_at=NOW,engine_name="x",engine_version="1",model_name="x",model_sha256="x",pipeline_version=1,settings_fingerprint=None)
    assert repository.get_ocr_document(image.image_id).status=="running"

def test_model_missing_fails_before_diff_apply(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); _,status=run_service(repository,StubWorker("model_missing"),folder)
    assert status.state=="failed" and repository.list_images()==[]

def test_double_start_and_closed_service(repository,tmp_path):
    folder=tmp_path/"shots"; write_png(folder/"one.png"); service=OCRIndexService(repository,StubWorker(delay=.2)); service.start_indexing(folder)
    with pytest.raises(OCRIndexAlreadyRunningError): service.start_indexing(folder)
    service.cancel(); service.wait(5); service.close()
    with pytest.raises(OCRIndexClosedError): service.start_indexing(folder)

def test_real_rapidocr_index_service_when_explicitly_configured(repository,tmp_path):
    source=os.environ.get("OCR_WORKER_INTEGRATION_IMAGE"); second=os.environ.get("OCR_WORKER_SECOND_IMAGE"); models=os.environ.get("OCR_WORKER_MODEL_DIR"); worker_python=os.environ.get("OCR_WORKER_PYTHON")
    if not source or not models or not worker_python: pytest.skip("Set real OCR worker environment variables.")
    folder=tmp_path/"real"; folder.mkdir(); first_copy=folder/"first.png"; shutil.copy2(source,first_copy)
    if second: shutil.copy2(second,folder/"second.png")
    def make_worker(): return OCRWorkerClient(OCRWorkerConfig(model_dir=Path(models),command=(worker_python,"-m","app.ocr.worker_entry"),timeouts=OCRWorkerTimeouts(initialize=60,ocr=120)))
    _,first_status=run_service(repository,make_worker(),folder,timeout=180)
    assert first_status.state=="completed" and first_status.succeeded in {1,2}
    assert all(repository.get_ocr_document(image.image_id).status=="ready" for image in repository.list_images(folder_path=folder))
    assert repository.search("images",folder_path=folder) or repository.search("error",folder_path=folder)
    _,second_status=run_service(repository,make_worker(),folder,timeout=180); assert second_status.total_requires_ocr==0
    first_copy.write_bytes(first_copy.read_bytes()+b"changed")
    _,modified_status=run_service(repository,make_worker(),folder,timeout=180); assert modified_status.total_requires_ocr==1 and modified_status.succeeded==1
