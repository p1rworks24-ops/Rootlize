from __future__ import annotations

import hashlib
import math
import sqlite3
import struct

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.ocr.schema import SCHEMA_SQL, SCHEMA_VERSION
from app.semantic.embedding import (EMBEDDING_BYTE_LENGTH, SemanticValidationError,
                                    decode_embedding, encode_embedding)
from app.semantic.models import (ModelIdentity, SemanticDiffState, SemanticWorkerEvent,
                                 SourceSnapshot)
from app.semantic.repository import SemanticRepository
from app.semantic.service import (SemanticAnalysisService, SemanticWorkerCrashedError)

NOW = "2026-08-12T00:00:00+00:00"
IDENTITY = ModelIdentity("fake-semantic", "test-v1")


def deterministic_embedding(image_id: int) -> bytes:
    digest = hashlib.sha256(str(image_id).encode("ascii")).digest()
    values = [float(digest[index % len(digest)] + 1) for index in range(768)]
    norm = math.sqrt(sum(value * value for value in values))
    return encode_embedding(value / norm for value in values)


@pytest.fixture
def repositories(tmp_path):
    database = OCRDatabase(tmp_path / "index.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database); semantic = SemanticRepository(database)
    yield database, images, semantic
    database.close()


def add_image(images: OCRRepository, index: int, *, size: int = 100, mtime: int = 200, fingerprint: str | None = "same"):
    return images.upsert_image(f"D:\\Shots\\{index}.png", size_bytes=size, mtime_ns=mtime, quick_fingerprint=fingerprint)


class FakeSemanticWorker:
    def __init__(self, *, cancel_after: int | None = None, fail_id: int | None = None, crash_after: int | None = None, identity: ModelIdentity = IDENTITY):
        self.cancel_after=cancel_after; self.fail_id=fail_id; self.crash_after=crash_after; self.identity=identity

    def analyze(self, items, *, request_id, cancel_event):
        total=len(items)
        for processed,item in enumerate(items,1):
            if cancel_event.is_set(): break
            if self.crash_after is not None and processed > self.crash_after:
                raise SemanticWorkerCrashedError("simulated worker crash")
            if item.image_id == self.fail_id:
                yield SemanticWorkerEvent("item_error",request_id,processed,total,image_id=item.image_id,error_code="INFERENCE_FAILED")
            else:
                yield SemanticWorkerEvent("item_result",request_id,processed,total,image_id=item.image_id,embedding=deterministic_embedding(item.image_id),model_identity=self.identity,source_snapshot=item.source_snapshot)
            yield SemanticWorkerEvent("progress",request_id,processed,total,image_id=item.image_id)
            if self.cancel_after == processed: cancel_event.set()


def test_embedding_round_trip_is_little_endian_fp32_and_validated():
    values=[0.0]*768; values[0]=1.0
    blob=encode_embedding(values)
    assert len(blob)==EMBEDDING_BYTE_LENGTH and blob[:4]==struct.pack("<f",1.0)
    assert decode_embedding(blob)==tuple(values)
    for invalid in ([0.0]*768, [float("nan")]+[0.0]*767, [float("inf")]+[0.0]*767, [1.0]*767):
        with pytest.raises(SemanticValidationError): encode_embedding(invalid)
    with pytest.raises(SemanticValidationError): decode_embedding(blob[:-4])


def test_schema_v3_migration_preserves_existing_rows_and_adds_semantic(tmp_path):
    path=tmp_path/"v3.sqlite3"; old_sql=SCHEMA_SQL.split("CREATE TABLE IF NOT EXISTS semantic_embeddings",1)[0]
    connection=sqlite3.connect(path); connection.executescript(old_sql)
    connection.executemany("INSERT INTO schema_meta(key,value) VALUES(?,?)",[("schema_version","3"),("normalization_version","1"),("search_schema_version","1"),("created_at",NOW),("updated_at",NOW)])
    connection.execute("INSERT INTO images(path,path_norm,folder_path,folder_path_norm,filename,filename_norm,size_bytes,mtime_ns,file_state,discovered_at,last_seen_at) VALUES('D:\\a.png','d:\\a.png','D:\\','d:\\','a.png','a.png',1,1,'present',?,?)",(NOW,NOW))
    connection.execute("INSERT INTO search_documents(image_id,filename_norm,tags_norm,ocr_norm,ocr_compact_norm) VALUES(1,'a.png','keep-tag','keep text','keeptext')")
    connection.commit(); connection.close()
    with OCRDatabase(path,clock=lambda:NOW) as database:
        names={row[0] for row in database.connection.execute("SELECT name FROM sqlite_master")}
        assert database.schema_version()==SCHEMA_VERSION
        assert {"semantic_embeddings","semantic_analysis_failures","semantic_embeddings_model_idx","semantic_indexes","semantic_index_failures"} <= names
        assert tuple(database.connection.execute("SELECT tags_norm,ocr_norm FROM search_documents WHERE image_id=1").fetchone())==("keep-tag","keep text")
        assert database.connection.execute("SELECT count(*) FROM semantic_embeddings").fetchone()[0]==0


def test_repository_crud_failure_upsert_and_cascade(repositories):
    database,images,semantic=repositories; image=add_image(images,1); source=SourceSnapshot(100,200,"same")
    first=semantic.upsert_embedding(image.image_id,deterministic_embedding(image.image_id),IDENTITY,source)
    assert first.created_at==NOW and semantic.get_embedding(image.image_id)==first
    failure=semantic.record_failure(image.image_id,"INFERENCE_FAILED",False); assert failure.attempt_count==1
    failure=semantic.record_failure(image.image_id,"INFERENCE_FAILED",True); assert failure.attempt_count==2
    semantic.clear_failure(image.image_id); assert semantic.get_failure(image.image_id) is None
    semantic.delete_embedding(image.image_id); assert semantic.get_embedding(image.image_id) is None
    assert semantic.delete_orphans()==0
    semantic.record_failure(image.image_id,"INFERENCE_FAILED",True)
    second=semantic.upsert_embedding(image.image_id,deterministic_embedding(2),IDENTITY,source)
    assert second.created_at==first.created_at and semantic.get_failure(image.image_id) is None
    assert len(semantic.list_embeddings())==1
    images.delete_image(image.image_id)
    assert semantic.get_embedding(image.image_id) is None and semantic.get_failure(image.image_id) is None
    assert database.quick_check()=="ok"


def test_diff_missing_failed_modified_stale_corrupt_deleted_and_rename_reuse(repositories):
    database,images,semantic=repositories
    missing=add_image(images,1); failed=add_image(images,2); modified=add_image(images,3); stale=add_image(images,4); corrupt=add_image(images,5); unchanged=add_image(images,6); deleted=add_image(images,7)
    semantic.record_failure(failed.image_id,"INFERENCE_FAILED",False)
    for image in (modified,stale,corrupt,unchanged,deleted): semantic.upsert_embedding(image.image_id,deterministic_embedding(image.image_id),IDENTITY,SourceSnapshot(100,200,"same"))
    images.upsert_image(modified.path,size_bytes=101,mtime_ns=201,quick_fingerprint="changed")
    database.connection.execute("UPDATE semantic_embeddings SET bundle_version='test-v0' WHERE image_id=?",(stale.image_id,))
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    database.connection.execute("UPDATE semantic_embeddings SET embedding=? WHERE image_id=?",(b"short",corrupt.image_id))
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")
    images.mark_file_state(deleted.image_id,"missing")
    renamed=images.update_path(unchanged.image_id,r"D:\\Archive\\renamed.png",mtime_ns=200)
    states=semantic.classify_embeddings([missing.image_id,failed.image_id,modified.image_id,stale.image_id,corrupt.image_id,renamed.image_id,deleted.image_id],IDENTITY)
    assert states=={missing.image_id:SemanticDiffState.MISSING,failed.image_id:SemanticDiffState.FAILED,modified.image_id:SemanticDiffState.MODIFIED,stale.image_id:SemanticDiffState.STALE_MODEL,corrupt.image_id:SemanticDiffState.CORRUPT,renamed.image_id:SemanticDiffState.UNCHANGED,deleted.image_id:SemanticDiffState.DELETED}


def test_mtime_only_change_with_matching_quick_fingerprint_reuses_embedding(repositories):
    _,images,semantic=repositories; image=add_image(images,1); semantic.upsert_embedding(image.image_id,deterministic_embedding(1),IDENTITY,SourceSnapshot(100,200,"same"))
    images.upsert_image(image.path,size_bytes=100,mtime_ns=999,quick_fingerprint="same")
    assert semantic.classify_embeddings([image.image_id],IDENTITY)[image.image_id]==SemanticDiffState.UNCHANGED


@pytest.mark.parametrize("corruption,expected", [
    ("short", SemanticDiffState.CORRUPT),
    ("dimension", SemanticDiffState.CORRUPT),
    ("nan", SemanticDiffState.CORRUPT),
    ("format", SemanticDiffState.STALE_MODEL),
])
def test_corrupt_and_stale_rows_are_isolated(repositories, corruption, expected):
    database,images,semantic=repositories; image=add_image(images,1)
    blob=deterministic_embedding(1); semantic.upsert_embedding(image.image_id,blob,IDENTITY,SourceSnapshot(100,200,"same"))
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    if corruption=="short": database.connection.execute("UPDATE semantic_embeddings SET embedding=? WHERE image_id=?",(b"short",image.image_id))
    elif corruption=="dimension": database.connection.execute("UPDATE semantic_embeddings SET dimension=767 WHERE image_id=?",(image.image_id,))
    elif corruption=="nan": database.connection.execute("UPDATE semantic_embeddings SET embedding=? WHERE image_id=?",(struct.pack("<f",float("nan"))+blob[4:],image.image_id))
    else: database.connection.execute("UPDATE semantic_embeddings SET embedding_format_version=99 WHERE image_id=?",(image.image_id,))
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")
    assert semantic.classify_embeddings([image.image_id],IDENTITY)[image.image_id]==expected


def test_service_partial_commit_cancel_failure_progress_and_crash(repositories):
    database,images,semantic=repositories; image_ids=[add_image(images,index).image_id for index in range(100)]; progress=[]
    service=SemanticAnalysisService(semantic,images,FakeSemanticWorker(cancel_after=50),on_progress=progress.append)
    result=service.analyze(image_ids,IDENTITY,request_id="cancel-test")
    assert result.state=="cancelled" and result.succeeded==50 and len(semantic.list_embeddings())==50
    assert progress[-1].request_id=="cancel-test" and progress[-1].processed==50 and progress[-1].total==100
    remaining=[image_id for image_id,state in semantic.classify_embeddings(image_ids,IDENTITY).items() if state!=SemanticDiffState.UNCHANGED]
    failure_id=remaining[0]; result=SemanticAnalysisService(semantic,images,FakeSemanticWorker(fail_id=failure_id)).analyze(remaining,IDENTITY)
    assert result.failed==1 and result.succeeded==49 and semantic.get_failure(failure_id).error_code=="INFERENCE_FAILED"
    extra=[add_image(images,index).image_id for index in range(100,103)]
    with pytest.raises(SemanticWorkerCrashedError): SemanticAnalysisService(semantic,images,FakeSemanticWorker(crash_after=1)).analyze(extra,IDENTITY)
    assert semantic.get_embedding(extra[0]) is not None and semantic.get_embedding(extra[1]) is None and database.quick_check()=="ok"


def test_wrong_worker_model_is_rejected_without_overwriting(repositories):
    _,images,semantic=repositories; image=add_image(images,1)
    result=SemanticAnalysisService(semantic,images,FakeSemanticWorker(identity=ModelIdentity("fake-semantic","test-v2"))).analyze([image.image_id],IDENTITY)
    assert result.failed==1 and semantic.get_embedding(image.image_id) is None
    assert semantic.get_failure(image.image_id).error_code=="INVALID_EMBEDDING"
