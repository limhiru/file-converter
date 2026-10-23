"""Actual format conversion with bounded inputs and no archive extraction."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import warnings
import zipfile
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_OUTPUT_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 500
Image.MAX_IMAGE_PIXELS = 25_000_000

IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF"}
DATA_FORMATS = ("csv", "tsv", "json")
AUDIO_FORMATS = ("mp3", "wav", "flac", "ogg", "m4a")
VIDEO_FORMATS = ("mp4", "webm")
MEDIA_INPUTS = set(AUDIO_FORMATS + VIDEO_FORMATS + ("mov", "mkv", "avi", "aac", "aiff", "opus", "wma", "m4v"))
MIME_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "bmp": "image/bmp",
    "tiff": "image/tiff", "gif": "image/gif", "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8", "json": "application/json",
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg",
    "m4a": "audio/mp4", "mp4": "video/mp4", "webm": "video/webm", "zip": "application/zip",
}


class ConversionError(ValueError):
    """A user-readable conversion failure."""


class UnsupportedFormat(ConversionError):
    """Input and target do not have a supported conversion path."""


@dataclass
class Result:
    data: bytes
    filename: str
    mime: str
    notes: list[str] = field(default_factory=list)
    converted_count: int = 1
    skipped_count: int = 0


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    return name[:180] or "file"


def ffmpeg_binary() -> str | None:
    configured = os.environ.get("FFMPEG_BINARY")
    if configured:
        return shutil.which(configured)
    installed = shutil.which("ffmpeg")
    if installed:
        return installed
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


def capabilities() -> dict:
    media = ffmpeg_binary() is not None
    return {
        "groups": [
            {"id": "image", "label": "이미지", "targets": list(IMAGE_FORMATS), "enabled": True},
            {"id": "data", "label": "데이터", "targets": list(DATA_FORMATS), "enabled": True},
            {"id": "audio", "label": "오디오", "targets": list(AUDIO_FORMATS), "enabled": media},
            {"id": "video", "label": "동영상", "targets": list(VIDEO_FORMATS), "enabled": media},
        ],
        "max_file_bytes": MAX_FILE_BYTES,
        "max_archive_entries": MAX_ARCHIVE_ENTRIES,
        "max_archive_bytes": MAX_ARCHIVE_BYTES,
        "media_available": media,
    }


def convert_image(data: bytes, filename: str, target: str, quality: int) -> Result:
    notes = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if getattr(source, "n_frames", 1) > 1:
                    notes.append("애니메이션·다중 페이지 이미지의 첫 프레임만 변환했습니다.")
                image = ImageOps.exif_transpose(source)
                image.load()
                if target in ("jpg", "bmp"):
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", image.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                    if source.mode in ("RGBA", "LA") or "transparency" in source.info:
                        notes.append("투명 영역을 흰색 배경으로 바꿨습니다.")
                elif target == "gif":
                    image = image.convert("RGBA")
                else:
                    image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
                # Export pixel data only; do not carry EXIF/GPS or other source metadata.
                image.info.clear()
                output = io.BytesIO()
                options = {"quality": quality} if target in ("jpg", "webp") else {}
                image.save(output, format=IMAGE_FORMATS[target], **options)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ConversionError("이미지는 최대 2,500만 픽셀까지 지원합니다.") from exc
    except UnidentifiedImageError as exc:
        raise UnsupportedFormat("이미지 내용을 인식하지 못했습니다. 지원 형식과 파일 손상 여부를 확인하세요.") from exc
    except (OSError, ValueError) as exc:
        raise ConversionError("이미지를 읽거나 변환할 수 없습니다. 파일이 손상되었을 수 있습니다.") from exc
    notes.append("이미지 메타데이터(EXIF/GPS 등)는 결과에 포함하지 않습니다.")
    return Result(output.getvalue(), str(PurePosixPath(filename).with_suffix(f".{target}")), MIME_TYPES[target], notes)


def convert_data(data: bytes, filename: str, target: str) -> Result:
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    if suffix not in DATA_FORMATS:
        raise UnsupportedFormat("데이터 변환은 CSV, TSV, JSON 파일을 지원합니다.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionError("UTF-8 인코딩 파일을 사용하세요. CP949/EUC-KR 파일은 UTF-8로 저장해 주세요.") from exc
    try:
        if suffix == "json":
            def invalid_constant(value):
                raise ValueError(f"Invalid JSON constant: {value}")
            rows = json.loads(text, parse_constant=invalid_constant)
            if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
                raise ConversionError("JSON은 객체가 들어 있는 배열이어야 합니다. 예: [{\"이름\": \"가나\"}]")
            headers = list(dict.fromkeys(key for row in rows for key in row))
            if not headers:
                raise ConversionError("JSON 객체에 하나 이상의 열이 필요합니다.")
            if any(isinstance(value, (list, dict)) for row in rows for value in row.values()):
                raise ConversionError("중첩 JSON은 표로 바꿀 수 없습니다. 각 값에 문자열·숫자·참/거짓·null을 사용하세요.")
        else:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t" if suffix == "tsv" else ",", strict=True)
            headers = next(reader, [])
            if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ConversionError("첫 행에는 비어 있지 않은 고유한 열 이름이 필요합니다.")
            rows = []
            for index, values in enumerate(reader, start=2):
                if not values:
                    continue
                if len(values) != len(headers):
                    raise ConversionError(f"{index}행의 열 개수가 첫 행과 다릅니다.")
                rows.append(dict(zip(headers, values)))
        notes = ["CSV/TSV의 값은 문자열로 읽습니다. 표로 내보낼 때 JSON 값의 자료형은 보존되지 않습니다."]
        if target == "json":
            output = json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        else:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=headers, delimiter="\t" if target == "tsv" else ",")
            writer.writeheader()
            writer.writerows(rows)
            output = stream.getvalue().encode("utf-8-sig")
    except (json.JSONDecodeError, csv.Error, ValueError, RecursionError) as exc:
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError("데이터 구문을 읽을 수 없습니다. CSV/TSV 또는 JSON 구조를 확인하세요.") from exc
    return Result(output, str(PurePosixPath(filename).with_suffix(f".{target}")), MIME_TYPES[target], notes)


def convert_media(data: bytes, filename: str, target: str, quality: int) -> Result:
    if PurePosixPath(filename).suffix.lower().lstrip(".") not in MEDIA_INPUTS:
        raise UnsupportedFormat("지원하는 오디오·동영상 파일을 선택하세요.")
    binary = ffmpeg_binary()
    if not binary:
        raise ConversionError("FFmpeg 엔진이 없습니다. requirements.txt의 의존성을 설치하세요.")
    # Never interpolate user input in a shell command or let FFmpeg follow remote URLs/playlists.
    with tempfile.TemporaryDirectory(prefix="file-converter-") as folder:
        source = Path(folder, "input" + PurePosixPath(filename).suffix.lower())
        output = Path(folder, "output." + target)
        source.write_bytes(data)
        command = [binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-max_alloc", "268435456",
                   "-protocol_whitelist", "file", "-format_whitelist", "mov,mp3,wav,flac,ogg,matroska,webm,avi,aac,aiff,asf",
                   "-i", str(source), "-map_metadata", "-1", "-threads", "2"]
        if target in AUDIO_FORMATS:
            command += ["-map", "0:a:0", "-vn"]
            command += {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
                        "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"],
                        "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
                        "m4a": ["-c:a", "aac", "-b:a", "192k"]}[target]
        else:
            command += ["-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
            if target == "mp4":
                command += ["-c:v", "libx264", "-preset", "fast", "-crf", str(round(35 - quality * .2)),
                            "-c:a", "aac", "-movflags", "+faststart"]
            else:
                command += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(round(45 - quality * .2)),
                            "-c:a", "libopus"]
        command += ["-fs", str(MAX_OUTPUT_BYTES + 1), str(output)]
        try:
            process = subprocess.run(command, capture_output=True, timeout=180, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("변환 시간이 3분을 초과했습니다. 더 짧은 파일을 사용하세요.") from exc
        except OSError as exc:
            raise ConversionError("FFmpeg 엔진을 실행할 수 없습니다.") from exc
        if process.returncode or not output.exists() or not output.stat().st_size:
            raise ConversionError("미디어를 변환할 수 없습니다. 파일 손상·지원 코덱·오디오/영상 트랙을 확인하세요.")
        if output.stat().st_size >= MAX_OUTPUT_BYTES:
            raise ConversionError("변환 결과가 100 MB를 초과했습니다. 더 작은 파일을 사용하세요.")
        result = output.read_bytes()
    return Result(result, str(PurePosixPath(filename).with_suffix(f".{target}")), MIME_TYPES[target],
                  ["미디어를 다시 인코딩하며, 원본 메타데이터는 결과에 포함하지 않습니다."])


def _archive_name(name: str) -> str:
    if "\\" in name or "\x00" in name or any(ord(c) < 32 for c in name):
        raise ConversionError("ZIP 내부에 안전하지 않은 경로가 있습니다.")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or ":" in path.parts[0]:
        raise ConversionError("ZIP 내부에 안전하지 않은 경로가 있습니다.")
    return path.as_posix()


def convert_archive(data: bytes, filename: str, target: str, quality: int) -> Result:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ConversionError("올바른 ZIP 파일이 아닙니다.") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise ConversionError("ZIP 내부 항목은 최대 500개까지 지원합니다.")
        total = 0
        seen = set()
        for entry in entries:
            # ZipInfo.filename normalizes backslashes on Windows. Inspect the raw name too.
            _archive_name(entry.orig_filename)
            name = _archive_name(entry.filename)
            if name.casefold() in seen:
                raise ConversionError("ZIP 안에 중복 경로가 있습니다.")
            seen.add(name.casefold())
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ConversionError("심볼릭 링크 또는 암호화된 ZIP 파일은 지원하지 않습니다.")
            total += entry.file_size
            if entry.file_size > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                raise ConversionError("ZIP 내부 파일은 각각 100 MB, 전체 256 MB까지 지원합니다.")
            if entry.file_size > 1024 * 1024 and entry.file_size / max(entry.compress_size, 1) > 200:
                raise ConversionError("압축 비율이 너무 큰 ZIP 파일은 처리할 수 없습니다.")
        # Reserve all original paths before writing so a.png → a.jpg never overwrites a.jpg.
        used = set(seen)
        for entry in entries:
            used.update(str(parent).casefold() for parent in PurePosixPath(entry.filename).parents)
        used.add("conversion-report.json")
        def unique_path(name: str) -> str:
            candidate = name
            number = 1
            while candidate.casefold() in used:
                path = PurePosixPath(name)
                candidate = str(path.with_name(f"{path.stem} ({number}){path.suffix}"))
                number += 1
            used.add(candidate.casefold())
            return candidate

        report = []
        output = io.BytesIO()
        converted = skipped = written = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            for entry in entries:
                if entry.is_dir():
                    destination.writestr(entry.filename, b"")
                    continue
                try:
                    content = archive.read(entry)
                except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
                    raise ConversionError("ZIP 내부 파일을 읽을 수 없습니다. CRC·압축 방식·손상 여부를 확인하세요.") from exc
                try:
                    # Nested archives remain intact, preventing recursive decompression.
                    if zipfile.is_zipfile(io.BytesIO(content)):
                        raise UnsupportedFormat("중첩 압축 파일은 원본을 보존했습니다.")
                    result = convert_single(content, entry.filename, target, quality)
                    saved_name = unique_path(result.filename)
                    content = result.data
                    report.append({"source": entry.filename, "output": saved_name, "status": "converted", "notes": result.notes})
                    converted += 1
                except ConversionError as exc:
                    saved_name = entry.filename
                    if saved_name.casefold() == "conversion-report.json":
                        saved_name = unique_path("original-conversion-report.json")
                    report.append({"source": entry.filename, "output": saved_name, "status": "preserved", "reason": str(exc)})
                    skipped += 1
                written += len(content)
                if written > MAX_ARCHIVE_BYTES:
                    raise ConversionError("ZIP 결과의 전체 파일 크기가 256 MB를 초과합니다.")
                destination.writestr(saved_name, content)
                if output.tell() > MAX_OUTPUT_BYTES:
                    raise ConversionError("ZIP 변환 결과가 100 MB를 초과합니다.")
            destination.writestr("conversion-report.json", json.dumps(report, ensure_ascii=False, indent=2))
        if not converted:
            raise ConversionError("ZIP 안에 선택한 형식으로 변환할 수 있는 파일이 없습니다.")
        if len(output.getvalue()) > MAX_OUTPUT_BYTES:
            raise ConversionError("ZIP 변환 결과가 100 MB를 초과합니다.")
    return Result(output.getvalue(), PurePosixPath(filename).stem + "-converted.zip", MIME_TYPES["zip"],
                  [f"{converted}개 변환, {skipped}개 원본 보존. ZIP 안의 conversion-report.json을 확인하세요."], converted, skipped)


def convert_single(data: bytes, filename: str, target: str, quality: int) -> Result:
    if not data:
        raise ConversionError("빈 파일은 변환할 수 없습니다.")
    if len(data) > MAX_FILE_BYTES:
        raise ConversionError("파일 크기는 최대 100 MB까지 지원합니다.")
    if target in IMAGE_FORMATS:
        result = convert_image(data, filename, target, quality)
    elif target in DATA_FORMATS:
        result = convert_data(data, filename, target)
    elif target in AUDIO_FORMATS + VIDEO_FORMATS:
        result = convert_media(data, filename, target, quality)
    else:
        raise UnsupportedFormat("지원하지 않는 출력 형식입니다.")
    if len(result.data) > MAX_OUTPUT_BYTES:
        raise ConversionError("변환 결과가 100 MB를 초과했습니다.")
    return result


def convert(data: bytes, filename: str, target: str, quality: int = 90) -> Result:
    filename = safe_filename(filename)
    target = target.lower().lstrip(".")
    if target not in MIME_TYPES or target == "zip":
        raise UnsupportedFormat("지원하지 않는 출력 형식입니다.")
    if not 1 <= quality <= 100:
        raise ConversionError("품질은 1~100 사이여야 합니다.")
    if not data:
        raise ConversionError("빈 파일은 변환할 수 없습니다.")
    if len(data) > MAX_FILE_BYTES:
        raise ConversionError("파일 크기는 최대 100 MB까지 지원합니다.")
    if zipfile.is_zipfile(io.BytesIO(data)):
        # OOXML/EPUB are ZIP packages, not user archives that we should rewrite.
        if PurePosixPath(filename).suffix.lower() in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".epub"):
            raise UnsupportedFormat("오피스 문서·전자책은 현재 지원하지 않습니다.")
        return convert_archive(data, filename, target, quality)
    if filename.lower().endswith(".zip"):
        raise ConversionError("올바른 ZIP 파일이 아닙니다.")
    return convert_single(data, filename, target, quality)
