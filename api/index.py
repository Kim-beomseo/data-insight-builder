import os
import sys

# 프로젝트 루트 디렉터리를 sys.path에 추가하여 app 및 tools 모듈 임포트 가능하도록 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app import app

if __name__ == "__main__":
    app.run()
