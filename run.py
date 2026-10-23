"""Run with python run.py, optionally --no-browser or --port 8765."""

import argparse
import threading
import webbrowser

import uvicorn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="파일 변환 — 내 컴퓨터에서 실행하는 파일 변환 앱")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535 사이여야 합니다.")
    if not args.no_browser:
        timer = threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}"))
        timer.daemon = True
        timer.start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")
