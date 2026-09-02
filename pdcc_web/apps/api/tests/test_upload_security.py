from __future__ import annotations

import zipfile

import pytest

from app.config import settings
from app.inventory.importers import validate_upload_filename
from app.inventory.xmlbuild import InventoryError
from app.nrl.client import NrlError
from app.nrl.offline import _build_index, download_library
from tests.test_import import _valid_xml
from tests.test_nrl_offline import _make_library


def test_upload_filename_allowlist_and_path_rejection():
    assert validate_upload_filename("network.XML") == "network.XML"
    assert validate_upload_filename("volume.DATALess") == "volume.DATALess"
    assert validate_upload_filename("RESP.YZ.TEST1.00.BHZ") == "RESP.YZ.TEST1.00.BHZ"

    for filename in ("network.txt", "../network.xml", r"..\network.xml", "C:network.xml"):
        with pytest.raises(InventoryError) as exc:
            validate_upload_filename(filename)
        assert exc.value.code == "E_UPLOAD_EXTENSION"


def test_import_file_rejects_bad_extension_and_oversize_before_create(
    client, monkeypatch
):
    assert client.post(
        "/api/login", json={"username": "stub", "password": "stub"}
    ).status_code == 200
    xml = _valid_xml().encode()
    project_ids = {
        row["id"] for row in client.get("/api/projects").json()["projects"]
    }

    bad_extension = client.post(
        "/api/projects/import-file",
        files={"file": ("network.txt", xml, "application/xml")},
    )
    assert bad_extension.status_code == 400
    assert ".xml" in bad_extension.json()["detail"]

    traversal = client.post(
        "/api/projects/import-file",
        files={"file": ("../network.xml", xml, "application/xml")},
    )
    assert traversal.status_code == 400

    monkeypatch.setattr(settings, "max_upload_bytes", len(xml) - 1)
    oversized = client.post(
        "/api/projects/import-file",
        files={"file": ("network.xml", xml, "application/xml")},
    )
    assert oversized.status_code == 413
    assert "너무 큽니다" in oversized.json()["detail"]
    assert {
        row["id"] for row in client.get("/api/projects").json()["projects"]
    } == project_ids


def test_nrl_zip_rejects_traversal_and_size_limits(tmp_path, monkeypatch):
    archive_path = tmp_path / "nrl.zip"
    _make_library(archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("../escape.xml", b"<unsafe/>")

    with pytest.raises(NrlError, match="안전하지 않은 경로"):
        _build_index(archive_path)

    _make_library(archive_path)
    monkeypatch.setattr(settings, "max_zip_bytes", archive_path.stat().st_size - 1)
    with pytest.raises(NrlError, match="파일이 너무 큽니다"):
        _build_index(archive_path)

    monkeypatch.setattr(settings, "max_zip_bytes", archive_path.stat().st_size)
    monkeypatch.setattr(settings, "max_zip_uncompressed_bytes", 1)
    with pytest.raises(NrlError, match="압축 해제 크기가 너무 큽니다"):
        _build_index(archive_path)


def test_nrl_download_counts_bytes_when_content_length_is_missing(
    tmp_path, monkeypatch
):
    target = tmp_path / "nrl.zip"
    monkeypatch.setattr(settings, "nrl_offline_zip", str(target))
    monkeypatch.setattr(settings, "max_zip_bytes", 5)

    class FakeResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, _chunk_size):
            yield b"123"
            yield b"456"

    monkeypatch.setattr(
        "app.nrl.offline.httpx.stream", lambda *_args, **_kwargs: FakeResponse()
    )
    with pytest.raises(NrlError, match="파일이 너무 큽니다"):
        download_library()
    assert not target.exists()
    assert not target.with_name(f".{target.name}.part").exists()
