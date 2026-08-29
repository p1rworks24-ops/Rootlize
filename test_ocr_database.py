from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.ocr.database import DB_FILE_NAME, OCRDatabase
from app.ocr.exceptions import (
    OCRDatabaseError,
    OCRDatabaseSchemaError,
    OCRDuplicatePathError,
    OCRFTSUnavailableError,
    OCRInvalidRecordError,
    OCRRecordNotFoundError,
)
from app.ocr.path_normalization import display_path, normalize_windows_path
from app.ocr.repository import OCRRepository
from app.ocr.schema import SCHEMA_SQL, SCHEMA_VERSION, SEARCH_SCHEMA_VERSION
from app.ocr.text_normalization import NORMALIZATION_VERSION, normalize_search_text


NOW = "2026-08-03T00:00:00+00:00"


@pytest.fixture
def database(tmp_path):
    database = OCRDatabase(tmp_path / "ocr-index.sqlite3", clock=lambda: NOW).open()
    yield database
    database.close()


@pytest.fixture
def repository(database):
    return OCRRepository(database)


def add_image(repository, name="ScreenShot_01.png", folder=r"D:\Shots", **overrides):
    values = dict(size_bytes=1200, mtime_ns=100, width=1280, height=720)
    values.update(overrides)
    return repository.upsert_image(folder + "\\" + name, **values)


def test_database_initializes_schema_fts_wal_and_versions(database):
    objects = {row[0] for row in database.connection.execute("SELECT name FROM sqlite_master")}
    assert {"schema_meta", "images", "ocr_documents", "search_documents", "search_fts", "semantic_indexes", "semantic_index_failures", "image_facts", "image_facts_failures"} <= objects
    assert {"search_documents_ai", "search_documents_au", "search_documents_ad"} <= objects
    assert database.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    info = OCRRepository(database).schema_info()
    assert (info.schema_version, info.normalization_version, info.search_schema_version) == (
        SCHEMA_VERSION, NORMALIZATION_VERSION, SEARCH_SCHEMA_VERSION
    )
    assert database.quick_check() == "ok"


def test_database_reopen_is_idempotent(tmp_path):
    path = tmp_path / "ocr.sqlite3"
    OCRDatabase(path, clock=lambda: NOW).open().close()
    with OCRDatabase(path, clock=lambda: NOW) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION


def test_future_schema_is_rejected(tmp_path):
    path = tmp_path / "ocr.sqlite3"
    db = OCRDatabase(path, clock=lambda: NOW).open()
    db.connection.execute("UPDATE schema_meta SET value='999' WHERE key='schema_version'")
    db.close()
    with pytest.raises(OCRDatabaseSchemaError):
        OCRDatabase(path).open()


def test_schema_v1_migrates_without_recreating_data(tmp_path):
    path = tmp_path / "v1.sqlite3"
    v1_sql = SCHEMA_SQL.replace(", missing_since TEXT", "").replace(
        " previous_status TEXT CHECK(previous_status IS NULL OR previous_status IN ('pending','running','ready','failed','stale')),\n", ""
    ).replace(" ,claimed_at TEXT, worker_id TEXT, last_attempt_at TEXT, next_retry_at TEXT\n", "")
    connection = sqlite3.connect(path)
    connection.executescript(v1_sql)
    connection.executemany("INSERT INTO schema_meta(key,value) VALUES(?,?)", [
        ("schema_version","1"),("normalization_version","1"),("search_schema_version","1"),
        ("created_at",NOW),("updated_at",NOW),
    ])
    connection.execute("INSERT INTO images(path,path_norm,folder_path,folder_path_norm,filename,filename_norm,size_bytes,mtime_ns,file_state,discovered_at,last_seen_at) VALUES('D:\\a.png','d:\\a.png','D:\\','d:\\','a.png','a.png',1,1,'present',?,?)", (NOW,NOW))
    connection.commit(); connection.close()
    with OCRDatabase(path, clock=lambda: NOW) as migrated:
        assert migrated.schema_version() == SCHEMA_VERSION
        assert migrated.connection.execute("SELECT missing_since FROM images").fetchone()[0] is None


def test_schema_v2_adds_claim_and_retry_columns(tmp_path):
    path=tmp_path/"v2.sqlite3"
    v2_sql=SCHEMA_SQL.replace(" ,claimed_at TEXT, worker_id TEXT, last_attempt_at TEXT, next_retry_at TEXT\n","")
    connection=sqlite3.connect(path); connection.executescript(v2_sql)
    connection.executemany("INSERT INTO schema_meta(key,value) VALUES(?,?)",[("schema_version","2"),("normalization_version","1"),("search_schema_version","1"),("created_at",NOW),("updated_at",NOW)])
    connection.commit(); connection.close()
    with OCRDatabase(path,clock=lambda:NOW) as migrated:
        assert migrated.schema_version()==SCHEMA_VERSION
        columns={row[1] for row in migrated.connection.execute("PRAGMA table_info(ocr_documents)")}
        assert {"claimed_at","worker_id","last_attempt_at","next_retry_at"}<=columns


def test_schema_v6_adds_image_facts_without_dropping_indexes(tmp_path):
    path = tmp_path / "v6.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_SQL)
    connection.execute("DROP TABLE IF EXISTS image_facts_failures")
    connection.execute("DROP INDEX IF EXISTS image_facts_identity_idx")
    connection.execute("DROP TABLE IF EXISTS image_facts")
    connection.executemany(
        "INSERT INTO schema_meta(key,value) VALUES(?,?)",
        [
            ("schema_version", "6"),
            ("normalization_version", "1"),
            ("search_schema_version", "1"),
            ("created_at", NOW),
            ("updated_at", NOW),
        ],
    )
    connection.execute(
        "INSERT INTO images(path,path_norm,folder_path,folder_path_norm,filename,filename_norm,"
        "size_bytes,mtime_ns,file_state,discovered_at,last_seen_at) "
        "VALUES('D:\\a.png','d:\\a.png','D:\\','d:\\','a.png','a.png',1,1,'present',?,?)",
        (NOW, NOW),
    )
    blob = b"\x00" * (512 * 4)
    connection.execute(
        """INSERT INTO semantic_indexes(
 image_id,metadata_json,text_embedding,embedding_dimension,embedding_format_version,
 vision_model,prompt_version,index_schema_version,embedding_model_id,
 source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at
) VALUES(1,'{}',?,512,1,'vision','prompt','schema','embed',1,1,'fp',?,?)""",
        (blob, NOW, NOW),
    )
    connection.commit()
    connection.close()
    with OCRDatabase(path, clock=lambda: NOW) as migrated:
        names = {row[0] for row in migrated.connection.execute("SELECT name FROM sqlite_master")}
        assert migrated.schema_version() == SCHEMA_VERSION == 7
        assert {"image_facts", "image_facts_failures", "semantic_indexes"} <= names
        assert migrated.connection.execute("SELECT COUNT(*) FROM semantic_indexes").fetchone()[0] == 1
        assert migrated.connection.execute("SELECT COUNT(*) FROM image_facts").fetchone()[0] == 0


def test_missing_fts_is_reported_as_dedicated_error(tmp_path):
    class NoFTSDatabase(OCRDatabase):
        def _check_fts5(self):
            raise OCRFTSUnavailableError("not available")

    with pytest.raises(OCRFTSUnavailableError):
        NoFTSDatabase(tmp_path / "ocr.sqlite3").open()


def test_default_database_path_uses_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr("app.ocr.database.get_local_app_data_dir", lambda: tmp_path)
    assert OCRDatabase().path == (tmp_path / DB_FILE_NAME).resolve()


@pytest.mark.parametrize("source", [r"D:/Shots/../Shots/Test.PNG", r"d:\shots\test.png"])
def test_windows_path_normalization_is_absolute_and_case_insensitive(source):
    assert normalize_windows_path(source) == normalize_windows_path(r"D:\Shots\Test.PNG")
    assert display_path(source).endswith(r"Shots\Test.PNG") or display_path(source).endswith(r"shots\test.png")


def test_unc_path_normalization():
    assert normalize_windows_path(r"\\SERVER\Share\Shots\A.png") == normalize_windows_path(r"\\server\share\shots\a.PNG")


def test_search_text_normalization_handles_width_case_and_whitespace():
    assert normalize_search_text("  ＬＯＧＳ\n Error  ") == "logs error"


def test_image_crud_and_upsert_preserve_identity(repository):
    image = add_image(repository)
    updated = add_image(repository, size_bytes=2200, mtime_ns=200)
    assert updated.image_id == image.image_id
    assert updated.size_bytes == 2200
    assert repository.get_image_by_path(r"d:\shots\SCREENSHOT_01.PNG") == updated
    repository.delete_path(updated.path)
    with pytest.raises(OCRRecordNotFoundError):
        repository.get_image(updated.image_id)


def test_image_list_filters_folder_and_state(repository):
    present = add_image(repository, "one.png", r"D:\One")
    missing = add_image(repository, "two.png", r"D:\One")
    add_image(repository, "three.png", r"D:\Two")
    repository.mark_file_state(missing.image_id, "missing")
    assert [item.image_id for item in repository.list_images(folder_path=r"d:\one", file_state="present")] == [present.image_id]


def test_invalid_image_metadata_is_rejected(repository):
    with pytest.raises(OCRInvalidRecordError):
        add_image(repository, size_bytes=-1)


def test_rename_move_preserves_id_and_ocr(repository):
    image = add_image(repository)
    repository.save_ocr_document(image.image_id, status="ready", ocr_text="Fatal error localhost")
    moved = repository.update_path(image.image_id, r"D:\Archive\Renamed.png", mtime_ns=300)
    assert moved.image_id == image.image_id
    assert repository.get_ocr_document(image.image_id).ocr_text == "Fatal error localhost"
    assert repository.search("renamed")[0].image_id == image.image_id
    assert repository.search("fatal error")[0].image_id == image.image_id


def test_rename_to_existing_path_is_rejected(repository):
    first = add_image(repository, "one.png")
    second = add_image(repository, "two.png")
    with pytest.raises(OCRDuplicatePathError):
        repository.update_path(second.image_id, first.path, mtime_ns=200)


def test_delete_folder_cascades_all_related_rows(repository):
    first = add_image(repository, "one.png", r"D:\One")
    second = add_image(repository, "two.png", r"D:\One")
    repository.save_ocr_document(first.image_id, status="ready", ocr_text="alpha content")
    assert repository.delete_folder(r"d:\one") == 2
    assert repository.list_images() == []
    assert repository.fts_counts() == (0, 0)
    with pytest.raises(OCRRecordNotFoundError):
        repository.get_ocr_document(first.image_id)
    with pytest.raises(OCRRecordNotFoundError):
        repository.get_image(second.image_id)


def test_ocr_document_crud_normalizes_and_updates_search(repository):
    image = add_image(repository)
    document = repository.save_ocr_document(
        image.image_id, status="ready", ocr_text="  日本語  Error CODE 500 ",
        average_confidence=0.92, indexed_at=NOW, engine_name="RapidOCR",
        engine_version="1", model_name="test", pipeline_version=2,
    )
    assert document.ocr_text_norm == "日本語 error code 500"
    assert repository.get_search_document(image.image_id).ocr_norm == document.ocr_text_norm
    assert repository.search("error code")[0].matched_ocr


@pytest.mark.parametrize("kwargs", [
    {"status": "unknown"}, {"status": "ready", "average_confidence": 1.1},
    {"status": "failed", "retry_count": -1},
])
def test_invalid_ocr_document_is_rejected(repository, kwargs):
    image = add_image(repository)
    with pytest.raises(OCRInvalidRecordError):
        repository.save_ocr_document(image.image_id, **kwargs)


def test_failed_ocr_document_and_empty_text_are_storable(repository):
    image = add_image(repository)
    result = repository.save_ocr_document(
        image.image_id, status="failed", ocr_text=None,
        error_type="decode", error_message_safe="Could not read image", retry_count=1,
    )
    assert result.ocr_text_norm == ""
    assert result.error_type == "decode"


def test_missing_image_marks_existing_ocr_state(repository):
    image = add_image(repository)
    repository.save_ocr_document(image.image_id, status="ready", ocr_text="searchable")
    repository.mark_file_state(image.image_id, "missing")
    assert repository.get_ocr_document(image.image_id).status == "missing"
    assert repository.search("searchable") == []


def test_missing_image_can_return_to_present(repository):
    image = add_image(repository)
    repository.mark_file_state(image.image_id, "missing")
    restored = repository.mark_file_state(image.image_id, "present")
    assert restored.file_state == "present"


@pytest.mark.parametrize("status", ["pending", "running", "ready", "failed", "stale", "missing"])
def test_all_ocr_states_are_storable(repository, status):
    image = add_image(repository, f"{status}.png")
    assert repository.save_ocr_document(image.image_id, status=status).status == status


def test_tags_are_searchable_and_replaceable(repository):
    image = add_image(repository)
    repository.update_tags(image.image_id, ["Logs", "エラー"])
    assert repository.search("logs")[0].matched_tags
    assert repository.search("エラー")[0].matched_tags
    repository.update_tags(image.image_id, ["pricing"])
    assert repository.search("logs") == []
    assert repository.search("pricing")[0].image_id == image.image_id


@pytest.mark.parametrize("term", ["error", "localhost", "https://example.com", "D:\\Shots", "foo_bar()", "日本語"])
def test_trigram_search_handles_screenshot_text_patterns(repository, term):
    image = add_image(repository)
    repository.save_ocr_document(
        image.image_id, status="ready",
        ocr_text="日本語 error localhost https://example.com D:\\Shots foo_bar()",
    )
    assert repository.search(term)[0].image_id == image.image_id


def test_search_supports_filename_while_ocr_is_unprocessed(repository):
    image = add_image(repository, "Pricing_Screenshot.png")
    result = repository.search("pricing")[0]
    assert result.image_id == image.image_id and result.matched_filename and not result.matched_ocr


def test_search_filters_folder_and_omits_missing(repository):
    first = add_image(repository, "one.png", r"D:\One")
    second = add_image(repository, "two.png", r"D:\Two")
    for item in (first, second):
        repository.save_ocr_document(item.image_id, status="ready", ocr_text="shared keyword")
    assert [x.image_id for x in repository.search("keyword", folder_path=r"d:\one")] == [first.image_id]
    repository.mark_file_state(first.image_id, "missing")
    assert repository.search("keyword", folder_path=r"D:\One") == []


@pytest.mark.parametrize("query", ["", "a", "ab", "  "])
def test_short_queries_are_explicitly_not_supported(repository, query):
    add_image(repository, "ab.png")
    assert repository.search(query) == []


def test_fts_triggers_stay_in_sync_for_insert_update_delete_and_rebuild(database, repository):
    image = add_image(repository)
    assert repository.fts_counts() == (1, 1)
    repository.update_tags(image.image_id, ["updated-tag"])
    assert repository.search("updated-tag")
    repository.delete_image(image.image_id)
    assert repository.fts_counts() == (0, 0)
    add_image(repository, "again.png")
    database.rebuild_fts()
    assert repository.fts_counts() == (1, 1)


def test_transaction_rolls_back_on_failure(database):
    with pytest.raises(RuntimeError):
        with database.transaction():
            database.connection.execute("INSERT INTO schema_meta(key,value) VALUES('temporary','1')")
            raise RuntimeError("stop")
    assert database.connection.execute("SELECT 1 FROM schema_meta WHERE key='temporary'").fetchone() is None


def test_closed_database_raises_domain_error(tmp_path):
    db = OCRDatabase(tmp_path / "closed.sqlite3")
    with pytest.raises(OCRDatabaseError):
        OCRRepository(db).list_images()


def test_write_lock_timeout_is_wrapped_in_domain_error(tmp_path):
    path = tmp_path / "locked.sqlite3"
    database = OCRDatabase(path, busy_timeout_ms=20, clock=lambda: NOW).open()
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(OCRDatabaseError) as captured:
            OCRRepository(database).upsert_image(r"D:\Shots\locked.png", size_bytes=1, mtime_ns=1)
        assert isinstance(captured.value.__cause__, sqlite3.OperationalError)
    finally:
        other.rollback()
        other.close()
        database.close()
