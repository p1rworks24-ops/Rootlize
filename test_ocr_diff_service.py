from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.diff_service import OCRDiffService, decide_reindex
from app.ocr.exceptions import OCRFolderScanError, OCRRecordNotFoundError
from app.ocr.fingerprint import calculate_quick_fingerprint, calculate_sha256
from app.ocr.models import OCRIndexSettings
from app.ocr.repository import OCRRepository
from app.ocr.scanner import scan_folder

NOW = "2026-08-03T01:00:00+00:00"


@pytest.fixture
def repository(tmp_path):
    database = OCRDatabase(tmp_path / "index" / "ocr.sqlite3", clock=lambda: NOW).open()
    yield OCRRepository(database)
    database.close()


def write_png(path: Path, payload: bytes = b"content", *, width: int = 10, height: int = 20):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + payload)
    return path


def apply_folder(repository, folder, **kwargs):
    return OCRDiffService(repository, **kwargs).reconcile(folder, dry_run=False)


def test_scan_empty_folder(tmp_path):
    scan = scan_folder(tmp_path)
    assert scan.items == ()


def test_scan_png_case_insensitive_and_excludes_other_formats_and_subfolders(tmp_path):
    write_png(tmp_path / "one.png")
    write_png(tmp_path / "TWO.PNG")
    write_png(tmp_path / "ignored.jpg")
    write_png(tmp_path / ".hidden.png")
    write_png(tmp_path / "child" / "nested.png")
    assert [item.filename for item in scan_folder(tmp_path).items] == ["one.png", "TWO.PNG"]


def test_scan_reads_dimensions_and_non_ascii_paths(tmp_path):
    folder = tmp_path / "日本語 folder"
    write_png(folder / "画像 １.png", width=321, height=123)
    item = scan_folder(folder).items[0]
    assert item.read_success and (item.width, item.height) == (321, 123)
    assert item.size_bytes == (folder / "画像 １.png").stat().st_size


def test_scan_corrupt_png_continues(tmp_path):
    (tmp_path / "broken.png").write_bytes(b"not png")
    write_png(tmp_path / "valid.png")
    scan = scan_folder(tmp_path)
    assert len(scan.items) == 2
    assert [item.read_success for item in scan.items] == [False, True]


@pytest.mark.parametrize("folder", ["", "does-not-exist"])
def test_scan_invalid_or_missing_folder_raises(folder):
    with pytest.raises(OCRFolderScanError):
        scan_folder(folder)


def test_folder_access_failure_is_dedicated_error(monkeypatch, tmp_path):
    monkeypatch.setattr("app.ocr.scanner.os.scandir", lambda _path: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(OCRFolderScanError):
        scan_folder(tmp_path)


def test_file_disappearing_during_scan_is_one_failed_item(monkeypatch, tmp_path):
    image = write_png(tmp_path / "gone.png")
    original = os.scandir
    def disappearing(path):
        entries = list(original(path)); image.unlink(); return entries
    monkeypatch.setattr("app.ocr.scanner.os.scandir", disappearing)
    item = scan_folder(tmp_path).items[0]
    assert not item.read_success and item.error_type


def test_quick_fingerprint_same_content_and_changes(tmp_path):
    first = write_png(tmp_path / "first.png", b"a" * 200)
    second = write_png(tmp_path / "second.png", b"a" * 200)
    assert calculate_quick_fingerprint(first) == calculate_quick_fingerprint(second)
    write_png(second, b"b" * 200)
    assert calculate_quick_fingerprint(first) != calculate_quick_fingerprint(second)


def test_quick_fingerprint_handles_small_and_large_files(tmp_path):
    small = write_png(tmp_path / "small.png", b"x")
    large = write_png(tmp_path / "large.png", b"x" * (1024 * 1024))
    assert calculate_quick_fingerprint(small).startswith("qf1:")
    assert calculate_quick_fingerprint(large).startswith("qf1:")
    assert len(calculate_sha256(large)) == 64


def test_fingerprint_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        calculate_quick_fingerprint(tmp_path / "gone.png")


def test_dry_run_reports_new_without_database_change(repository, tmp_path):
    write_png(tmp_path / "new.png")
    result = OCRDiffService(repository).reconcile(tmp_path, dry_run=True)
    assert len(result.new_items) == 1 and result.reindex_required_count == 1
    assert repository.list_images() == []


def test_apply_registers_new_pending_and_search_cache(repository, tmp_path):
    image_path = write_png(tmp_path / "Pricing_Screenshot.png")
    result = apply_folder(repository, tmp_path)
    image = repository.get_image_by_path(image_path)
    assert result.database_updated_count == 1
    assert image.file_state == "present" and image.quick_fingerprint
    assert repository.get_ocr_document(image.image_id).status == "pending"
    search = repository.get_search_document(image.image_id)
    assert search.filename_norm == "pricing_screenshot.png" and search.ocr_norm == "" and search.tags_norm == ""


def test_second_scan_is_unchanged_without_duplicate(repository, tmp_path):
    write_png(tmp_path / "one.png")
    apply_folder(repository, tmp_path)
    result = apply_folder(repository, tmp_path)
    assert len(result.unchanged_items) == 1 and len(repository.list_images()) == 1
    image = repository.list_images()[0]
    assert repository.get_ocr_document(image.image_id).status == "pending"


def test_size_change_becomes_stale_and_only_ocr_search_is_cleared(repository, tmp_path):
    image_path = write_png(tmp_path / "one.png", b"old")
    apply_folder(repository, tmp_path)
    image = repository.get_image_by_path(image_path)
    repository.update_tags(image.image_id, ["keep-tag"])
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="obsolete searchable text",model_sha256=None,settings_fingerprint=None)
    write_png(image_path, b"new-longer")
    result = apply_folder(repository, tmp_path)
    assert len(result.modified_items) == 1
    assert repository.get_ocr_document(image.image_id).status == "stale"
    assert repository.get_ocr_document(image.image_id).ocr_text == "obsolete searchable text"
    search = repository.get_search_document(image.image_id)
    assert search.ocr_norm == "" and search.tags_norm == "keep-tag" and search.filename_norm == "one.png"


def test_mtime_only_with_matching_fingerprint_preserves_ready(repository, tmp_path):
    image_path = write_png(tmp_path / "one.png")
    apply_folder(repository, tmp_path)
    image = repository.get_image_by_path(image_path)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="still valid")
    os.utime(image_path, ns=(image_path.stat().st_atime_ns, image_path.stat().st_mtime_ns + 10_000_000))
    result = apply_folder(repository, tmp_path)
    assert len(result.unchanged_items) == 1
    assert "fingerprint matches" in result.unchanged_items[0].reason
    assert repository.get_ocr_document(image.image_id).status == "ready"


def test_mtime_only_without_existing_fingerprint_is_safely_modified(repository, tmp_path):
    image_path = write_png(tmp_path / "one.png")
    stat = image_path.stat()
    image = repository.upsert_image(image_path,size_bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,width=10,height=20)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="old")
    os.utime(image_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert len(OCRDiffService(repository).reconcile(tmp_path).modified_items) == 1


def test_missing_keeps_row_and_ocr_but_excludes_search(repository, tmp_path):
    image_path = write_png(tmp_path / "one.png")
    apply_folder(repository, tmp_path)
    image = repository.get_image_by_path(image_path)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="retained text")
    image_path.unlink()
    result = apply_folder(repository, tmp_path)
    assert len(result.missing_items) == 1
    assert repository.get_image(image.image_id).file_state == "missing"
    assert repository.get_image(image.image_id).missing_since == NOW
    assert repository.get_ocr_document(image.image_id).ocr_text == "retained text"
    assert repository.search("retained") == []


def test_folder_failure_never_marks_database_missing(repository, tmp_path):
    folder = tmp_path / "folder"; image_path = write_png(folder / "one.png")
    apply_folder(repository, folder); image = repository.get_image_by_path(image_path)
    folder.rename(tmp_path / "disconnected")
    with pytest.raises(OCRFolderScanError): OCRDiffService(repository).reconcile(folder,dry_run=False)
    assert repository.get_image(image.image_id).file_state == "present"


def test_restored_same_content_reuses_ready_ocr_and_identity(repository, tmp_path):
    image_path = write_png(tmp_path / "one.png")
    apply_folder(repository, tmp_path); image = repository.get_image_by_path(image_path)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="reuse me")
    data=image_path.read_bytes(); image_path.unlink(); apply_folder(repository,tmp_path); image_path.write_bytes(data)
    result=apply_folder(repository,tmp_path)
    assert len(result.restored_items)==1 and not result.restored_items[0].requires_ocr
    assert repository.get_image_by_path(image_path).image_id==image.image_id
    assert repository.get_ocr_document(image.image_id).status=="ready"


def test_restored_changed_content_is_stale(repository, tmp_path):
    image_path=write_png(tmp_path/"one.png",b"first")
    apply_folder(repository,tmp_path); image=repository.get_image_by_path(image_path)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="old")
    image_path.unlink(); apply_folder(repository,tmp_path); write_png(image_path,b"different size")
    result=apply_folder(repository,tmp_path)
    assert result.restored_items[0].requires_ocr
    assert repository.get_ocr_document(image.image_id).status=="stale"


def test_unique_external_rename_preserves_id_and_ocr(repository, tmp_path):
    old=write_png(tmp_path/"old.png")
    apply_folder(repository,tmp_path); image=repository.get_image_by_path(old)
    repository.save_ocr_document(image.image_id,status="ready",ocr_text="keep OCR")
    new=old.rename(tmp_path/"new.png")
    result=apply_folder(repository,tmp_path)
    assert len(result.moved_items)==1 and not result.new_items and not result.missing_items
    assert repository.get_image_by_path(new).image_id==image.image_id
    assert repository.get_ocr_document(image.image_id).ocr_text=="keep OCR"
    assert repository.search("new.png")[0].image_id==image.image_id


def test_ambiguous_external_rename_is_not_joined(repository, tmp_path):
    old1=write_png(tmp_path/"old1.png",b"same"); old2=write_png(tmp_path/"old2.png",b"same")
    apply_folder(repository,tmp_path)
    old1.rename(tmp_path/"new1.png"); old2.rename(tmp_path/"new2.png")
    result=OCRDiffService(repository).reconcile(tmp_path,dry_run=True)
    assert not result.moved_items and len(result.new_items)==2 and len(result.missing_items)==2


def test_internal_rename_and_move_preserve_ocr(repository, tmp_path):
    old=write_png(tmp_path/"old.png"); apply_folder(repository,tmp_path)
    image=repository.get_image_by_path(old); repository.save_ocr_document(image.image_id,status="ready",ocr_text="preserved")
    new=tmp_path/"renamed.png"; old.rename(new)
    service=OCRDiffService(repository); renamed=service.record_internal_rename(old,new,mtime_ns=new.stat().st_mtime_ns)
    moved_path=tmp_path/"other"/"moved.png"; moved_path.parent.mkdir(); new.rename(moved_path)
    moved=service.record_internal_move(new,moved_path,mtime_ns=moved_path.stat().st_mtime_ns)
    assert renamed.image_id==moved.image_id==image.image_id
    assert repository.get_ocr_document(image.image_id).ocr_text=="preserved"


@pytest.mark.parametrize("retry,required", [(0,True),(1,True),(2,True),(3,False)])
def test_failed_retry_limit(repository, tmp_path, retry, required):
    path=write_png(tmp_path/f"{retry}.png"); apply_folder(repository,tmp_path)
    image=repository.get_image_by_path(path)
    document=repository.save_ocr_document(image.image_id,status="failed",retry_count=retry)
    assert decide_reindex(document,OCRIndexSettings()).required is required


@pytest.mark.parametrize("change", ["pipeline", "model", "settings"])
def test_failed_retry_reenabled_by_version_change(repository, tmp_path, change):
    path=write_png(tmp_path/"one.png"); apply_folder(repository,tmp_path); image=repository.get_image_by_path(path)
    document=repository.save_ocr_document(image.image_id,status="failed",retry_count=3,pipeline_version=1,model_sha256="old",settings_fingerprint="old")
    settings=OCRIndexSettings(pipeline_version=2 if change=="pipeline" else 1,model_sha256="new" if change=="model" else "old",settings_fingerprint="new" if change=="settings" else "old")
    assert decide_reindex(document,settings).required


def test_normal_scan_never_calls_full_sha256(monkeypatch, repository, tmp_path):
    write_png(tmp_path/"one.png")
    monkeypatch.setattr("app.ocr.diff_service.calculate_sha256", lambda *_a,**_k: (_ for _ in ()).throw(AssertionError("must not run")))
    apply_folder(repository,tmp_path)


def test_batches_commit_completed_chunks_and_rollback_failed_chunk(monkeypatch, repository, tmp_path):
    write_png(tmp_path/"one.png"); write_png(tmp_path/"two.png")
    service=OCRDiffService(repository,batch_size=1); original=service._apply_item; calls=0
    def fail_second(item):
        nonlocal calls; calls+=1
        if calls==2: raise RuntimeError("batch failed")
        return original(item)
    monkeypatch.setattr(service,"_apply_item",fail_second)
    with pytest.raises(RuntimeError): service.reconcile(tmp_path,dry_run=False)
    assert len(repository.list_images())==1
