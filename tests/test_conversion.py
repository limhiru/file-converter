import io
import json
from pathlib import Path
import stat
import subprocess
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import converters
from app.converters import ConversionError, convert, ffmpeg_binary
from app.main import app

client = TestClient(app)


def image_bytes(fmt="PNG", mode="RGBA", color=(255, 0, 0, 0)):
    output = io.BytesIO()
    image = Image.new(mode, (16, 12), color)
    image.save(output, fmt)
    return output.getvalue()


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def test_image_converts_contents_not_just_extension():
    result = convert(image_bytes(), "사진.wrong", "jpg")
    assert result.filename == "사진.jpg"
    assert result.data.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == "JPEG"
        assert image.size == (16, 12)
        assert all(channel >= 250 for channel in image.getpixel((0, 0)))
    assert any("흰색" in note for note in result.notes)


@pytest.mark.parametrize("target", ["png", "jpg", "webp", "bmp", "tiff", "gif"])
def test_image_targets_decode(target):
    result = convert(image_bytes(), "source.png", target)
    with Image.open(io.BytesIO(result.data)) as image:
        image.load()
        assert image.size == (16, 12)
        assert image.format == converters.IMAGE_FORMATS[target]


def test_animated_image_reports_first_frame():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, "GIF", save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0)
    result = convert(output.getvalue(), "animated.gif", "png")
    assert any("첫 프레임" in note for note in result.notes)


def test_metadata_is_removed():
    image = Image.new("RGB", (10, 10), "red")
    exif = Image.Exif()
    exif[0x010F] = "PRIVATE-CAMERA"
    output = io.BytesIO()
    image.save(output, "JPEG", exif=exif)
    result = convert(output.getvalue(), "private.jpg", "jpg")
    with Image.open(io.BytesIO(result.data)) as converted:
        assert not converted.getexif()
    assert b"PRIVATE-CAMERA" not in result.data


def test_large_pixel_count_is_rejected(monkeypatch):
    content = image_bytes()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ConversionError, match="픽셀"):
        convert(content, "large.png", "jpg")


def test_csv_json_tsv_round_trip_keeps_unicode_and_quoted_fields():
    source = '이름,설명,번호\r\n가나,"쉼표, 줄바꿈\n두 번째",001\r\n'.encode("utf-8-sig")
    as_json = convert(source, "표.csv", "json")
    rows = json.loads(as_json.data)
    assert rows == [{"이름": "가나", "설명": "쉼표, 줄바꿈\n두 번째", "번호": "001"}]
    as_tsv = convert(as_json.data, "표.json", "tsv")
    again = convert(as_tsv.data, "표.tsv", "json")
    assert json.loads(again.data) == rows


@pytest.mark.parametrize("source", [b'a,a\n1,2', b'a,\n1,2', b'a,b\n1,2,3', b''])
def test_bad_csv_is_rejected(source):
    with pytest.raises(ConversionError):
        convert(source, "bad.csv", "json")


@pytest.mark.parametrize("source", [b'{}', b'[1,2]', b'[{"a": [1]}]', b'[{"a": {"b": 1}}]', b'not-json'])
def test_non_tabular_json_is_rejected(source):
    with pytest.raises(ConversionError):
        convert(source, "bad.json", "csv")


def test_zip_preserves_paths_unknown_files_and_collisions():
    original_jpg = image_bytes("JPEG", "RGB", "blue")
    source = zip_bytes([("images/사진.png", image_bytes()), ("images/사진.jpg", original_jpg),
                        ("설명.txt", "보존".encode()), ("conversion-report.json", b"[]")])
    result = convert(source, "묶음.zip", "jpg")
    assert result.filename == "묶음-converted.zip"
    assert result.converted_count == 2
    assert result.skipped_count == 2
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        names = archive.namelist()
        assert len(set(names)) == len(names)
        assert "images/사진 (1).jpg" in names
        assert "images/사진 (2).jpg" in names
        assert archive.read("설명.txt").decode() == "보존"
        assert archive.read("original-conversion-report.json") == b"[]"
        report = json.loads(archive.read("conversion-report.json"))
        assert sum(item["status"] == "converted" for item in report) == 2


@pytest.mark.parametrize("name", ["../outside.png", "/absolute.png", "C:/evil.png", "dir\\evil.png"])
def test_zip_traversal_is_rejected(name):
    source = zip_bytes([(name, image_bytes())])
    with pytest.raises(ConversionError, match="경로"):
        convert(source, "attack.zip", "jpg")


def test_zip_symlink_is_rejected():
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(link, "../../outside")
    with pytest.raises(ConversionError, match="심볼릭"):
        convert(output.getvalue(), "attack.zip", "jpg")


def test_nested_zip_is_preserved():
    nested = zip_bytes([("inner.png", image_bytes())])
    result = convert(zip_bytes([("nested.zip", nested), ("photo.png", image_bytes())]), "outer.zip", "jpg")
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert archive.read("nested.zip") == nested
        assert "photo.jpg" in archive.namelist()


def test_office_container_is_not_rewritten():
    with pytest.raises(ConversionError, match="오피스"):
        convert(zip_bytes([("image.png", image_bytes())]), "document.docx", "jpg")


def test_zip_without_compatible_files_reports_error():
    with pytest.raises(ConversionError, match="변환할 수 있는"):
        convert(zip_bytes([("keep.txt", b"keep")]), "files.zip", "jpg")


def test_zip_limits(monkeypatch):
    monkeypatch.setattr(converters, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(ConversionError, match="항목"):
        convert(zip_bytes([("a.png", image_bytes()), ("b.png", image_bytes())]), "many.zip", "jpg")


def test_zip_bomb_ratio_is_rejected():
    with pytest.raises(ConversionError, match="압축 비율"):
        convert(zip_bytes([("huge.txt", b"0" * (2 * 1024 * 1024))]), "bomb.zip", "jpg")


def test_api_download_headers_and_actual_bytes():
    response = client.post("/api/convert", params={"filename": "한글.png", "target": "jpg"}, content=image_bytes())
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["x-converted-count"] == "1"
    assert response.content.startswith(b"\xff\xd8")


def test_api_rejects_oversize_stream(monkeypatch):
    import app.main
    monkeypatch.setattr(app.main, "MAX_FILE_BYTES", 8)
    response = client.post("/api/convert?filename=test.png&target=jpg", content=b"0" * 9)
    assert response.status_code == 413


@pytest.mark.parametrize("query", ["filename=a.png&target=exe", "filename=a.png&target=jpg&quality=101", "filename=a.png&target=jpg&quality=0"])
def test_api_rejects_invalid_options(query):
    assert client.post("/api/convert?" + query, content=image_bytes()).status_code == 422


def test_api_rejects_malicious_origin_and_host():
    assert client.post("/api/convert?filename=a.png&target=jpg", content=image_bytes(), headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_ui_assets_and_formats_available():
    response = client.get("/")
    assert response.status_code == 200
    assert '<html lang="ko">' in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    for asset in ("app.js", "zip.js", "style.css", "favicon.svg"):
        assert client.get("/static/" + asset).status_code == 200
    assert client.get("/api/formats").json()["groups"][0]["targets"]


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 4000)
    return output.getvalue()


@pytest.mark.skipif(not ffmpeg_binary(), reason="FFmpeg unavailable")
@pytest.mark.parametrize("target", ["mp3", "wav", "flac", "ogg", "m4a"])
def test_audio_targets_decode_with_ffmpeg(tmp_path, target):
    result = convert(wav_bytes(), "audio.wav", target)
    output = tmp_path / result.filename
    output.write_bytes(result.data)
    decoded = subprocess.run([ffmpeg_binary(), "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True)
    assert decoded.returncode == 0, decoded.stderr.decode()


@pytest.mark.skipif(not ffmpeg_binary(), reason="FFmpeg unavailable")
@pytest.mark.parametrize("target", ["mp4", "webm"])
def test_video_targets_decode_with_ffmpeg(tmp_path, target):
    source = tmp_path / "source.mp4"
    subprocess.run([ffmpeg_binary(), "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=32x24:d=0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    result = convert(source.read_bytes(), "source.mp4", target)
    output = tmp_path / ("out." + target)
    output.write_bytes(result.data)
    decoded = subprocess.run([ffmpeg_binary(), "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True)
    assert decoded.returncode == 0, decoded.stderr.decode()


def test_bad_media_fails_without_shell_execution():
    with pytest.raises(ConversionError):
        convert(b"not media", "bad.wav", "mp3")
