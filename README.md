# 파일 변환

[![Test file conversion](https://github.com/limhiru/file-converter/actions/workflows/test.yml/badge.svg)](https://github.com/limhiru/file-converter/actions/workflows/test.yml)

파일을 끌어 놓고 형식을 선택하면 **파일 내용을 실제로 변환**하는 한국어 로컬 웹 앱입니다. 이미지, 표 데이터, 오디오·동영상, ZIP 내부 파일을 처리합니다. Python 서버와 브라우저 모두 내 컴퓨터에서 실행합니다.

## 빠르게 실행하기

Python **3.11 이상**이 필요합니다. 첫 설치 때 패키지를 내려받으려면 인터넷 연결이 필요하며, 이후 변환은 오프라인으로 가능합니다. 별도의 Node.js·FFmpeg 설치는 필요하지 않습니다. `imageio-ffmpeg`가 지원하는 플랫폼에서 FFmpeg 실행 파일을 함께 설치합니다.

```bash
git clone https://github.com/limhiru/file-converter.git
cd file-converter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

브라우저에서 `http://127.0.0.1:8765`가 열립니다. 서버 종료는 터미널에서 `Ctrl+C`를 누르세요.

macOS는 `start.command`, Windows는 `start.bat`를 실행할 수도 있습니다. Windows 수동 설치 시 `py -3 -m venv .venv`, `.venv\Scripts\activate`, `python -m pip install -r requirements.txt`, `python run.py`를 순서대로 실행하세요. 실행 스크립트는 의존성 설치 후 브라우저를 엽니다.

포트 변경·브라우저 자동 열기 비활성화:

```bash
python run.py --port 9000 --no-browser
```

## 사용 방법

1. 파일을 끌어 놓거나 **파일 선택**을 누릅니다.
2. 각 파일 오른쪽에서 출력 형식을 선택합니다. ZIP은 내부 파일에 적용할 출력 형식을 고릅니다.
3. 필요하면 기본 형식·품질을 정합니다. **대기 중인 파일에 적용**은 호환되는 대기 파일의 출력 형식만 바꾸며, 품질은 변환 시작 시 전체에 적용합니다.
4. **모두 변환**을 누릅니다. 실패한 파일은 오류를 확인한 뒤 다시 시도할 수 있습니다.
5. 파일별 다운로드 버튼이나 **결과 ZIP 받기**로 저장합니다. `?` 안내 버튼에서 손실·메타데이터 변경 안내를 확인하세요.

결과는 탭 메모리에 보관합니다. **새로고침하거나 탭을 닫기 전에 다운로드하세요.** 원본 경로에는 쓰지 않습니다.

## 지원 범위

| 종류 | 입력 | 출력 | 동작·제약 |
| --- | --- | --- | --- |
| 이미지 | Pillow가 읽을 수 있는 이미지: PNG, JPEG, WebP, BMP, TIFF, GIF, ICO 등 | PNG, JPG, WebP, BMP, TIFF, GIF | 바이너리 내용으로 식별, EXIF 방향 보정. 투명→JPG/BMP는 흰색 배경. 다중 프레임·페이지는 첫 프레임만 처리 |
| 표 데이터 | UTF-8 CSV, TSV, JSON | CSV, TSV, JSON | CSV/TSV 첫 행에 고유한 열 이름 필요. JSON은 평평한 객체 배열만 지원. CSV/TSV 값은 문자열로 읽음 |
| 오디오 | MP3, WAV, FLAC, OGG, M4A, AAC, AIFF, OPUS, WMA 및 지원 동영상의 오디오 트랙 | MP3, WAV, FLAC, OGG, M4A | FFmpeg로 재인코딩. 실제 지원 코덱은 설치된 엔진에 따라 다름 |
| 동영상 | MP4, WebM, MOV, MKV, AVI, M4V | MP4(H.264/AAC), WebM(VP9/Opus) | 짝수 해상도·yuv420p로 변환. 미디어 파일당 최대 3분 처리 |
| ZIP | 일반 ZIP | 내부 파일을 변환한 새 ZIP | 폴더 구조 유지, 파일명 충돌 시 번호 추가, 미지원·실패 파일과 중첩 ZIP은 원본 보존, 결과 보고서 포함 |

이미지·미디어의 원본 메타데이터는 결과에 복사하지 않습니다. JPG·WebP·동영상 품질 슬라이더는 재인코딩 품질을 조절하며 용량을 보장하지 않습니다. WAV/FLAC으로 저장해도 이미 잃어버린 음질이 복원되지는 않습니다. JSON→CSV/TSV에서는 값의 자료형과 누락/null 구분이 보존되지 않습니다.

**현재 미지원:** PDF·Word·Excel·PowerPoint 등 문서 변환, HEIC, RAR·7z·TAR, 암호화 ZIP. 확장자 이름만 바꾸는 기능은 제공하지 않습니다. DRM·암호를 해제하지 않습니다.

ZIP 결과의 `conversion-report.json`에는 각 원본 경로, 결과 경로, 변환/보존 여부, 실패 사유 또는 변경 안내가 들어갑니다. ZIP 안에 호환 파일이 하나도 없으면 오류를 표시합니다.

## 제한과 로컬 처리

- 파일당 입력·결과 최대 **100 MB**, 이미지 최대 **2,500만 픽셀**.
- 화면에서 최대 **20개·합계 500 MB**를 선택하며 순서대로 처리합니다. API 동시 작업은 2개까지 허용합니다.
- ZIP 최대 **500개 항목**, 내부 개별 파일 100 MB·합계 256 MB. 과도한 압축 비율, 경로 탈출, 중복 경로, 심볼릭 링크, 암호화 파일을 거부합니다.
- **결과 ZIP 받기**는 변환 완료 파일의 합계 256 MB까지 묶습니다.
- 서버는 `127.0.0.1`에만 바인딩하며 Host·Origin을 확인합니다. 파일이나 변환 이력을 외부에 전송하지 않습니다.
- 미디어 작업에만 OS 임시 디렉터리를 사용하고 완료·실패 시 삭제합니다. 서버 프로세스를 강제 종료하면 OS 임시 파일이 남을 수 있습니다.
- FFmpeg는 셸 없이 인자 배열로 호출하며 입력 프로토콜·포맷 허용 목록과 시간·결과 용량 제한을 적용합니다.

이 앱은 개인 로컬 실행을 위한 도구입니다. 공개 업로드 서버로 제공하려면 별도 인증·사용자 격리·작업 큐·프로세스 격리와 리소스 제한이 필요합니다.

FFmpeg가 비활성화되면 UI에서 미디어 출력을 제외합니다. 시스템 FFmpeg를 설치하거나 `FFMPEG_BINARY`를 실행 파일 경로로 설정할 수 있습니다. `imageio-ffmpeg`와 FFmpeg의 배포·라이선스 조건은 각 프로젝트 문서를 확인하세요.

## 개발·테스트

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

브라우저 ZIP 작성기 테스트는 개발 환경의 Node.js 22 이상에서 실행합니다. 앱 실행에는 Node.js가 필요하지 않습니다.

```bash
node --test tests/test_zip.mjs
```

Python 테스트는 실제 이미지·표 데이터·오디오·동영상 재인코딩/디코딩, ZIP 경로·원본 보존·충돌·압축 제한, API·출처 검증을 다룹니다. GitHub Actions는 Ubuntu/Windows의 Python 3.11/3.13에서 검사합니다.

```text
app/
  converters.py       # 변환 엔진, ZIP 처리와 용량 제한
  main.py             # FastAPI, 스트리밍 입력, 로컬 요청 검사
  static/             # 한국어 UI, CSS, 브라우저 ZIP 작성기
tests/                # 실제 파일·API·ZIP 테스트
run.py                # 로컬 서버와 브라우저 실행
start.command         # macOS 실행
start.bat             # Windows 실행
```

API는 원본 바이트를 요청 본문으로 받습니다. 예:

```bash
curl -X POST \
  'http://127.0.0.1:8765/api/convert?filename=photo.png&target=jpg&quality=90' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @photo.png \
  --output photo.jpg
```

지원 형식 조회: `GET /api/formats`. 변환 응답은 다운로드 파일과 URL 인코딩된 `X-Conversion-Notes` JSON 헤더를 반환합니다.
