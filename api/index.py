import os
import sys
import traceback

# 프로젝트 루트 디렉터리를 sys.path에 추가하여 app 및 tools 모듈 임포트 가능하도록 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from app import app
except Exception as e:
    err_tb = traceback.format_exc()
    print(f"[Vercel Cold-Start Error]\n{err_tb}", file=sys.stderr)
    try:
        from flask import Flask
        app = Flask(__name__)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serverless_error_fallback(path):
            return f"""
            <!DOCTYPE html>
            <html lang="ko">
            <head>
                <meta charset="utf-8">
                <title>Vercel 초기화 오류</title>
                <style>
                    body {{ font-family: monospace; background: #0f172a; color: #f87171; padding: 2rem; }}
                    pre {{ background: #1e293b; color: #fca5a5; padding: 1.5rem; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }}
                    h1 {{ color: #ef4444; }}
                </style>
            </head>
            <body>
                <h1>Vercel Serverless Initialization Exception</h1>
                <p>앱 모듈 초기화 중 예외가 발생했습니다:</p>
                <pre>{err_tb}</pre>
            </body>
            </html>
            """, 500
    except Exception:
        raise e

if __name__ == "__main__":
    app.run()
