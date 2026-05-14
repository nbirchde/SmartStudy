from cloud_function.main import _parse_folder_object


def test_parse_folder_object_with_nested_path():
    info = _parse_folder_object(
        "folders/abc123/Cloud-Computing/week-2/deadbeef1234-notes.pdf"
    )

    assert info == {
        "folder_id": "abc123",
        "folder_path": "Cloud-Computing/week-2",
        "upload_id": "deadbeef1234",
        "source_file": "notes.pdf",
    }


def test_parse_folder_object_rejects_legacy_root_pdf():
    assert _parse_folder_object("test.pdf") is None
