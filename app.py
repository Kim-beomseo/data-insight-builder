import io
import os
import re
import csv
import sys
import json
import logging
import inspect
import numpy as np
import pandas as pd
from flask import Flask, render_template, jsonify, request, send_from_directory, make_response
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools

# 환경변수 로드
load_dotenv()

# 기준 디렉터리 경로
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Windows 콘솔 및 로거의 UTF-8 입출력 강제 설정
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 로깅 포맷터 및 핸들러 설정 (콘솔 + 안전한 파일 로깅)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)
handlers = [console_handler]

# 서버리스 환경(Vercel 등)의 읽기 전용 파일시스템 고려 (/tmp 사용)
log_file_path = "/tmp/app.log" if os.environ.get("VERCEL") else os.path.join(BASE_DIR, "app.log")
try:
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_formatter)
    handlers.append(file_handler)
except Exception:
    pass

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in handlers:
    if h not in root_logger.handlers:
        root_logger.addHandler(h)

logger = logging.getLogger("data-insight-builder")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

# 업로드 용량 제한 설정 (기본 10MB)
max_mb = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

# 지원 인코딩 후보 목록 (순차 시도)
SUPPORTED_ENCODINGS = ["utf-8-sig", "utf-8", "cp949", "euc-kr", "latin1"]

# 업로드된 활성 데이터셋 메모리 캐시
CURRENT_DATASET = {
    "df": None,
    "filename": None
}

# 7~12번: 기준 시점 필수 도구 목록
REQUIRES_REFERENCE_PERIOD = [
    "top_bottom_n", "group_summary", "change_rate",
    "distribution", "correlation_scatter", "compare_one_vs_all"
]

# 12종 도구 카탈로그 설명 (Gemini 프롬프트에 제공)
TOOL_CATALOG_PROMPT_INFO = """
1. reshape_wide_to_long: 연도 열들을 행(Long format)으로 접기
2. quality_report: 결측·중복·데이터타입·이상 열 진단
3. year_coverage: 연도별 유효 데이터 개수와 권장 기준연도 확인
4. detect_aggregates: World, High income 등 국가가 아닌 집계 행 탐지
5. describe_numeric: 특정 연도의 평균·중앙값·최소·최대·표준편차 요약 통계
6. trend_line: 주요 국가들의 연도별 시계열 추이 (선 차트)
7. top_bottom_n: 기준연도 기준 상위 N개 및 하위 N개 국가 비교 (수평 막대 차트)
8. group_summary: 소득 그룹(High/Middle/Low) 또는 지역별 평균·중앙값 비교 (막대 차트)
9. change_rate: 두 시점(예: 10년 전 vs 기준연도) 사이 변화량(%p)과 성장률(%) (막대 차트)
10. distribution: 0~100% 구간별 국가 수 빈도포포 (히스토그램)
11. correlation_scatter: 과거 연도와 기준연도 간의 피어슨 상관계수 (산점도)
12. compare_one_vs_all: 특정 관심 국가(예: 한국)와 전체 평균·중앙값 비교 (강조 막대 차트)
"""

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "status": "error",
        "message": f"파일 크기가 너무 큽니다. 최대 업로드 크기는 {max_mb}MB입니다."
    }), 413

@app.route("/", methods=["GET"])
def index():
    """메인 대시보드 웹 화면"""
    return render_template("index.html")

@app.route("/manifest.json", methods=["GET"])
def get_manifest():
    """PWA 매니페스트 파일 제공"""
    return send_from_directory(
        os.path.join(BASE_DIR, "static"),
        "manifest.json",
        mimetype="application/manifest+json"
    )

@app.route("/sw.js", methods=["GET"])
def get_service_worker():
    """PWA 서비스 워커 파일 제공 (루트 스코프 적용)"""
    resp = make_response(send_from_directory(
        os.path.join(BASE_DIR, "static"),
        "sw.js",
        mimetype="application/javascript"
    ))
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

@app.route("/api/auth/verify", methods=["POST"])
def verify_auth_pin():
    """4자리 비밀번호(기본: 0904) 검증 API"""
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()
    target_pin = os.getenv("APP_PASSWORD", "0904")
    if pin == target_pin:
        return jsonify({
            "status": "success",
            "authenticated": True,
            "message": "인증 성공"
        }), 200
    return jsonify({
        "status": "error",
        "authenticated": False,
        "message": "비밀번호가 올바르지 않습니다."
    }), 401

@app.route("/health", methods=["GET"])
def health_check():
    """서버 상태 및 API 키 설정 여부 점검"""
    api_key = os.getenv("GEMINI_API_KEY", "")
    api_key_set = bool(api_key and api_key.strip() != "your_gemini_api_key_here")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    
    return jsonify({
        "status": "ok",
        "api_key_configured": api_key_set,
        "model": model
    }), 200

def try_decode(raw_bytes):
    """여러 인코딩을 순차적으로 시도하여 문자열과 사용된 인코딩을 반환"""
    for enc in SUPPORTED_ENCODINGS:
        try:
            decoded = raw_bytes.decode(enc)
            return decoded, enc
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None

def detect_header_and_parse(content_str):
    """CSV 텍스트에서 헤더 위치(건너뛸 행 수)를 자동 감지하고 데이터프레임 파싱"""
    lines = content_str.splitlines()
    if not lines:
        return None, None, "업로드된 파일이 비어 있습니다."

    max_cols = 0
    header_idx = -1

    for idx, line in enumerate(lines[:25]):
        if not line.strip():
            continue
        try:
            parsed = list(csv.reader([line]))[0]
            non_empty = [c for c in parsed if c.strip()]
            if len(non_empty) > max_cols and len(non_empty) >= 2:
                max_cols = len(non_empty)
                header_idx = idx
        except Exception:
            continue

    if header_idx == -1:
        return None, None, "CSV 파일에서 유효한 헤더(열 이름) 행을 찾을 수 없습니다."

    try:
        df = pd.read_csv(io.StringIO(content_str), skiprows=header_idx)
    except Exception as e:
        return None, None, f"CSV 파싱 중 오류가 발생했습니다: {str(e)}"

    return df, header_idx, None

@app.route("/inspect", methods=["POST"])
def inspect_file():
    """POST /inspect (종합 진단: 인코딩, 헤더, 품질, 충실도, 집계행, 미리보기)"""
    logger.info("[REQUEST] POST /inspect")

    if "file" not in request.files:
        logger.warning("[ERROR] 파일 미선택")
        return jsonify({"status": "error", "message": "파일을 선택해주세요."}), 400

    uploaded_file = request.files["file"]
    filename = uploaded_file.filename

    if not filename or filename.strip() == "":
        logger.warning("[ERROR] 파일명 공백")
        return jsonify({"status": "error", "message": "파일을 선택해주세요."}), 400

    if not filename.lower().endswith(".csv"):
        logger.warning(f"[ERROR] CSV 아님: {filename}")
        return jsonify({"status": "error", "message": "CSV 파일만 업로드할 수 있습니다."}), 400

    raw_bytes = uploaded_file.read()
    file_size = len(raw_bytes)
    logger.info(f"[FILE] name={filename} size={file_size}")

    if file_size == 0:
        logger.warning(f"[ERROR] 빈 파일: {filename}")
        return jsonify({"status": "error", "message": "업로드된 파일이 비어 있습니다."}), 400

    content_str, used_encoding = try_decode(raw_bytes)
    if content_str is None:
        logger.warning(f"[ERROR] 인코딩 전부 실패: {filename}")
        return jsonify({"status": "error", "message": "지원하는 인코딩(UTF-8, CP949 등)으로 파일을 읽을 수 없습니다."}), 400

    logger.info(f"[ENCODING] {used_encoding} 시도 결과: 성공")

    df, skipped_rows, parse_err = detect_header_and_parse(content_str)
    if parse_err:
        logger.warning(f"[ERROR] {parse_err}")
        return jsonify({"status": "error", "message": parse_err}), 400

    logger.info(f"[HEADER] 헤더 줄 감지 결과 (건너뛴 줄 수: {skipped_rows})")

    CURRENT_DATASET["df"] = df
    CURRENT_DATASET["filename"] = filename

    cols = [str(c).strip() for c in df.columns]
    total_rows = len(df)
    total_cols = len(cols)

    quality_res = tools.quality_report(df)["result"]
    year_res = tools.year_coverage(df)["result"]
    agg_res = tools.detect_aggregates(df)["result"]

    warnings = []
    non_unnamed = [c for c in cols if not c.startswith("Unnamed:")]
    if len(non_unnamed) != len(set(non_unnamed)):
        warnings.append("중복된 열 이름이 존재합니다.")
        logger.warning("[DIAGNOSE] 중복된 열 이름 감지됨")

    if quality_res["unusual_columns"]:
        warnings.append(f"비정상 또는 빈 열 이름이 {len(quality_res['unusual_columns'])}개 감지되었습니다: {', '.join(quality_res['unusual_columns'])}")

    if agg_res["aggregate_count"] > 0:
        warnings.append(f"집계 행(World, High income 등 총 {agg_res['aggregate_count']}개)이 포함되어 있습니다. 국가별 분석 시 제외가 권장됩니다.")

    if quality_res["missing_rate_pct"] > 30.0:
        warnings.append(f"전체 데이터의 결측치 비율이 {quality_res['missing_rate_pct']}%로 높은 편입니다.")

    logger.info(f"[CSV] parsing 완료 rows={total_rows} columns={total_cols}")
    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(warnings)}")

    preview_records = df.head(10).replace({np.nan: None}).to_dict(orient="records")

    return jsonify({
        "status": "success",
        "file_info": {
            "name": filename,
            "size_bytes": file_size,
            "encoding": used_encoding
        },
        "header_info": {
            "skipped_rows": skipped_rows,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "columns": cols
        },
        "quality_report": quality_res,
        "year_coverage": year_res,
        "aggregate_detection": agg_res,
        "preview_rows": preview_records,
        "warnings": warnings
    }), 200

COUNTRY_ALIASES = {
    "한국": ("Korea, Rep.", "대한민국"),
    "대한민국": ("Korea, Rep.", "대한민국"),
    "남한": ("Korea, Rep.", "대한민국"),
    "korea": ("Korea, Rep.", "대한민국"),
    "south korea": ("Korea, Rep.", "대한민국"),
    "korea, rep.": ("Korea, Rep.", "대한민국"),
    "korea, rep": ("Korea, Rep.", "대한민국"),
    "미국": ("United States", "미국"),
    "usa": ("United States", "미국"),
    "united states": ("United States", "미국"),
    "us": ("United States", "미국"),
    "일본": ("Japan", "일본"),
    "japan": ("Japan", "일본"),
    "중국": ("China", "중국"),
    "china": ("China", "중국"),
    "영국": ("United Kingdom", "영국"),
    "uk": ("United Kingdom", "영국"),
    "united kingdom": ("United Kingdom", "영국"),
    "독일": ("Germany", "독일"),
    "germany": ("Germany", "독일"),
    "프랑스": ("France", "프랑스"),
    "france": ("France", "프랑스"),
    "러시아": ("Russian Federation", "러시아"),
    "russia": ("Russian Federation", "러시아"),
    "인도": ("India", "인도"),
    "india": ("India", "인도"),
    "캐나다": ("Canada", "캐나다"),
    "canada": ("Canada", "캐나다"),
    "호주": ("Australia", "호주"),
    "australia": ("Australia", "호주"),
    "브라질": ("Brazil", "브라질"),
    "brazil": ("Brazil", "브라질"),
    "이탈리아": ("Italy", "이탈리아"),
    "italy": ("Italy", "이탈리아"),
    "스페인": ("Spain", "스페인"),
    "spain": ("Spain", "스페인"),
    "대만": ("Taiwan, China", "대만"),
    "베트남": ("Viet Nam", "베트남"),
    "싱가포르": ("Singapore", "싱가포르")
}

def resolve_country_name(query_name, df, id_col=None):
    if not query_name:
        return None, None
    if id_col is None:
        id_col = df.columns[0]
    
    clean_q = str(query_name).strip()
    lower_q = clean_q.lower()

    if lower_q in COUNTRY_ALIASES:
        official_name, disp = COUNTRY_ALIASES[lower_q]
        if official_name in df[id_col].values:
            return official_name, disp

    # Exact match in DataFrame
    if clean_q in df[id_col].values:
        return clean_q, clean_q

    # Case-insensitive match in DataFrame
    matches = df[df[id_col].astype(str).str.lower() == lower_q]
    if not matches.empty:
        matched_name = matches.iloc[0][id_col]
        return matched_name, matched_name

    # Partial contains match
    partial = df[df[id_col].astype(str).str.contains(clean_q, case=False, na=False)]
    if not partial.empty:
        matched_name = partial.iloc[0][id_col]
        return matched_name, clean_q

    return clean_q, clean_q

# ==========================================
# POST /query (자연어 질문 분석 엔드포인트)
# ==========================================
@app.route("/query", methods=["POST"])
def query_data():
    """
    POST /query (사용자의 자연어 질문을 해석하여 적합한 도구 실행 및 답변 반환)
    """
    logger.info("[REQUEST] POST /query")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"status": "error", "message": "Gemini API Key가 설정되지 않았습니다."}), 500

    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"status": "error", "message": "질문 내용을 입력해주세요."}), 400

    df = CURRENT_DATASET.get("df")
    if df is None:
        default_csv = os.path.join(BASE_DIR, "data", "API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv")
        if not os.path.exists(default_csv):
            default_csv = "data/API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"
        if os.path.exists(default_csv):
            with open(default_csv, "rb") as f:
                content_str, _ = try_decode(f.read())
                df, _, _ = detect_header_and_parse(content_str)
                CURRENT_DATASET["df"] = df

    if df is None:
        return jsonify({"status": "error", "message": "분석할 데이터가 없습니다. 먼저 CSV 파일을 업로드해주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    logger.info(f"[AI] 자연어 질의 분석 시작: '{question}'")

    year_cols = tools.extract_year_columns(df)
    rec_year = year_cols[-2] if len(year_cols) >= 2 else (year_cols[-1] if year_cols else "2024")

    # 1. 자연어 질문 의도 분석 및 도구 매핑 (Gemini)
    plan_prompt = f"""
당신은 시니어 데이터 과학자입니다. 사용자의 자연어 질문을 분석하여, 데이터셋 분석에 가장 적합한 도구(1개)와 파라미터를 JSON으로 계획하세요.

[사용 가능한 12종 도구 카탈로그]
1. top_bottom_n: 기준연도 기준 상위 N개 및 하위 N개 국가 (수평 막대) -> params: reference_period, n, exclude_aggregates
2. compare_one_vs_all: 특정 대상 국가와 전체 평균·중앙값 비교 (강조 막대) -> params: reference_period, item, exclude_aggregates
3. trend_line: 주요 국가들의 연도별 시계열 추이 (선 차트) -> params: items (리스트)
4. group_summary: 소득/지역 그룹별 통계 -> params: reference_period, exclude_aggregates
5. change_rate: 두 시점 사이 변화량·변화율 -> params: reference_period, base_period
6. distribution: 구간별 빈도 분포 -> params: reference_period
7. correlation_scatter: 연도 간 상관계수 -> params: reference_period, compare_column
8. describe_numeric: 기초 통계 요약 -> params: reference_period

[데이터셋 정보]
- 국가 열: {df.columns[0]}
- 연도 열: {year_cols[0]} ~ {year_cols[-1]} (권장: {rec_year})
- 주요 국가 영문 공식 명칭 예시:
  * 한국: 'Korea, Rep.'
  * 미국: 'United States'
  * 일본: 'Japan', 중국: 'China', 영국: 'United Kingdom', 독일: 'Germany', 프랑스: 'France'

[사용자 질문]
"{question}"

반드시 아래 JSON 형식으로만 응답:
{{
  "tool": "top_bottom_n",
  "params": {{
    "reference_period": "2024",
    "n": 10,
    "exclude_aggregates": true
  }},
  "compare_items": [
    {{"name": "United States", "display": "미국"}}
  ]
}}
(참고: 특정 국가와의 비교나 위치를 질문한 경우 compare_items 목록에 영문 공식명칭(name)과 한글 표기(display)를 작성. 비교 국가가 없으면 빈 리스트 [] 작성)
"""

    client = genai.Client(api_key=api_key)
    try:
        plan_res = client.models.generate_content(
            model=model_name,
            contents=plan_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
        )
        plan_json = json.loads(plan_res.text.strip())
        tool_name = plan_json.get("tool", "top_bottom_n")
        params = plan_json.get("params", {})
        
        # compare_items 파싱 (단일 객체, 문자열, 리스트 모두 유연하게 처리)
        raw_compare = plan_json.get("compare_items") or plan_json.get("compare_item")
        compare_items = []
        if isinstance(raw_compare, list):
            for it in raw_compare:
                if isinstance(it, dict):
                    compare_items.append({"name": it.get("name") or it.get("country"), "display": it.get("display") or it.get("display_name") or it.get("name")})
                elif isinstance(it, str):
                    compare_items.append({"name": it, "display": it})
        elif isinstance(raw_compare, dict):
            compare_items.append({"name": raw_compare.get("name") or raw_compare.get("country"), "display": raw_compare.get("display") or raw_compare.get("display_name") or raw_compare.get("name")})
        elif isinstance(raw_compare, str) and raw_compare.strip():
            compare_items.append({"name": raw_compare.strip(), "display": plan_json.get("target_display_name") or raw_compare.strip()})
    except Exception as e:
        logger.warning(f"[AI] 계획 파싱 실패, 기본 처리: {str(e)}")
        tool_name = "top_bottom_n"
        params = {"reference_period": rec_year, "n": 10, "exclude_aggregates": True}
        compare_items = []

    if tool_name not in tools.TOOL_REGISTRY:
        tool_name = "top_bottom_n"

    # 2. Pandas 엔진으로 계산 실행
    tool_func = tools.TOOL_REGISTRY[tool_name]
    sig = inspect.signature(tool_func)
    valid_args = {k: v for k, v in params.items() if k in sig.parameters}
    if tool_name in REQUIRES_REFERENCE_PERIOD and "reference_period" not in valid_args:
        valid_args["reference_period"] = rec_year

    # trend_line이나 compare_one_vs_all의 국가명 매핑 보정
    if tool_name == "trend_line" and "items" in valid_args and isinstance(valid_args["items"], list):
        valid_args["items"] = [resolve_country_name(c, df)[0] for c in valid_args["items"]]
    elif tool_name == "compare_one_vs_all" and "item" in valid_args:
        valid_args["item"] = resolve_country_name(valid_args["item"], df)[0]

    try:
        calc_result = tool_func(df, **valid_args)
        logger.info(f"[CALC_SUCCESS] 도구 '{tool_name}' 연산 성공 (사용 행 수: {calc_result.get('rows_used')})")
    except Exception as e:
        logger.error(f"[ERROR] 자연어 매핑 도구 실행 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"데이터 분석 중 오류 발생: {str(e)}"}), 500

    # top_bottom_n의 경우 질문 의도에 맞춰 불필요한 반대편 목록(예: 상위만 물었는데 하위 10개국 강제 노출) 제거
    if tool_name == "top_bottom_n" and "result" in calc_result:
        q_lower = question.lower()
        has_bottom = any(k in q_lower for k in ["하위", "낮은", "bottom", "꼴찌", "최하위"])
        has_top = any(k in q_lower for k in ["상위", "높은", "top", "1~", "1등", "순위", "1위"])

        if has_bottom and not has_top:
            calc_result["result"]["top_n"] = []
            logger.info("[FILTER] 질문 의도에 맞춰 하위(Bottom) 목록만 표시")
        elif has_top and not has_bottom:
            calc_result["result"]["bottom_n"] = []
            logger.info("[FILTER] 질문 의도에 맞춰 상위(Top) 목록만 표시")

    # 3. 추가 비교 대상 국가(미국, 한국 등) 정보 보강 및 차트 연동
    if compare_items:
        extra_comparisons = []
        for c_info in compare_items:
            raw_c_name = c_info.get("name")
            official_name, disp_name = resolve_country_name(raw_c_name, df)
            if not official_name:
                continue

            # 사용자 지정 표시명이 있으면 우선 사용
            user_disp = c_info.get("display")
            if user_disp and user_disp != raw_c_name:
                disp_name = user_disp

            try:
                comp_res = tools.compare_one_vs_all(
                    df, 
                    reference_period=valid_args.get("reference_period", rec_year), 
                    item=official_name, 
                    exclude_aggregates=True
                )
                extra = comp_res.get("result", {})
                extra_comparisons.append(extra)
                logger.info(f"[COMPARE_RESOLVE] 비교 국가 '{official_name}' ({disp_name}) 순위: {extra.get('target_rank')}위, 값: {extra.get('target_value')}%")

                # top_bottom_n 인 경우 차트에서 함께 볼 수 있도록 top_n 또는 bottom_n에 타깃 지정
                if tool_name == "top_bottom_n" and "result" in calc_result:
                    top_list = calc_result["result"].get("top_n", [])
                    bot_list = calc_result["result"].get("bottom_n", [])

                    matched_in_top = next((item for item in top_list if item.get("label") == official_name), None)
                    if matched_in_top:
                        matched_in_top["is_target"] = True
                        matched_in_top["label"] = f"{official_name} ({disp_name} 📍)" if disp_name else f"{official_name} (📍)"
                    else:
                        matched_in_bottom = next((item for item in bot_list if item.get("label") == official_name), None)
                        if matched_in_bottom:
                            matched_in_bottom["is_target"] = True
                            matched_in_bottom["label"] = f"{official_name} ({disp_name} 📍)" if disp_name else f"{official_name} (📍)"
                        else:
                            # 목록에 없다면 top_n(또는 bottom_n) 끝에 타깃으로 추가
                            target_entry = {
                                "rank": extra.get("target_rank"),
                                "label": f"{official_name} ({disp_name} 📍)" if disp_name else f"{official_name} (📍)",
                                "value": extra.get("target_value"),
                                "is_target": True
                            }
                            if "top_n" in calc_result["result"] and (calc_result["result"]["top_n"] or not bot_list):
                                calc_result["result"]["top_n"].append(target_entry)
                            elif "bottom_n" in calc_result["result"]:
                                calc_result["result"]["bottom_n"].append(target_entry)
            except Exception as ce:
                logger.warning(f"[WARN] 추가 비교 국가({official_name}) 연산 생략: {str(ce)}")

        if extra_comparisons:
            calc_result["extra_comparison"] = extra_comparisons[0]
            calc_result["extra_comparisons"] = extra_comparisons

    # 4. 정확한 계산 결과를 기반으로 Gemini 자연어 답변 생성
    answer_prompt = f"""
당신은 신뢰할 수 있는 전문 데이터 분석가입니다.
사용자의 질문에 대해 아래 Pandas가 직접 계산한 정확한 통계 수치를 바탕으로 명쾌하고 친절하게 답변하세요.

[사용자 질문]
"{question}"

[Pandas 정확 계산 결과]
- 사용된 도구: {tool_name}
- 기준 시점: {calc_result.get('reference_period')}
- 분석 대상 관측치: {calc_result.get('rows_used')}개국
- 주요 계산 수치:
{json.dumps(calc_result.get('result', {}), ensure_ascii=False, indent=2)}

[답변 가이드]
1. 사용자의 질문에 직접적으로 명쾌한 결론을 먼저 제시하세요.
2. 질문에서 비교를 요청한 특정 대상 국가(예: 미국, 대한민국 등)가 있다면 해당 국가의 정확한 순위와 통계 수치(% 단위)를 명확하게 밝히세요.
3. 숫자를 임의로 바꾸거나 추정하지 말고, 제공된 계산 결과의 숫자만 인용하세요.
4. 마크다운 형식(글머리 기호, 볼드체)을 활용하여 가독성 높게 작성하세요.
"""

    try:
        answer_res = client.models.generate_content(
            model=model_name,
            contents=answer_prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        answer_text = answer_res.text.strip()
    except Exception as e:
        logger.error(f"[ERROR] 답변 생성 실패: {str(e)}", exc_info=True)
        answer_text = "통계 계산은 완료되었으나 설명 생성 중 오류가 발생했습니다."

    logger.info("[AI] 자연어 질의응답 및 시각화 데이터 생성 완료")

    return jsonify({
        "status": "success",
        "question": question,
        "answer": answer_text,
        "tool": tool_name,
        "calculation_result": calc_result
    }), 200

# ==========================================
# POST /suggest (Step 17: Gemini 분석 제안)
# ==========================================
@app.route("/suggest", methods=["POST"])
def suggest_tools():
    """POST /suggest (Gemini 분석 도구 제안 - JSON 강제, 카탈로그 제한)"""
    logger.info("[REQUEST] POST /suggest")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] API Key 미설정")
        return jsonify({
            "status": "error",
            "message": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해주세요."
        }), 500

    data = request.get_json(silent=True) or {}
    summary = data.get("summary") or data.get("inspection_result") or data

    columns = summary.get("columns") or summary.get("header_info", {}).get("columns", [])
    year_info = summary.get("year_coverage", {})
    recommended_year = year_info.get("recommended_year") or "2024"
    coverage_map = year_info.get("coverage_by_year", {}) or year_info.get("coverage", {})
    agg_count = summary.get("aggregate_detection", {}).get("aggregate_count") or summary.get("aggregate_detection", {}).get("count", 0)

    year_cols = [c for c in columns if re.match(r"^(19|20)\d{2}$", str(c).strip())]
    label_col = columns[0] if columns else "Country Name"
    base_year = "2014" if "2014" in year_cols else (year_cols[0] if year_cols else "1990")

    gemini_prompt = f"""
당신은 시니어 데이터 과학자 및 통계 분석 전문가입니다.
제공된 데이터셋 진단 결과를 정밀하게 파악하여, 분석 가치가 가장 높은 분석 도구 3~5개를 추천하세요.

[사용 가능한 12종 도구 카탈로그]
{TOOL_CATALOG_PROMPT_INFO}

[데이터셋 진단 요약]
- 식별/국가 열: {label_col}
- 전체 열 목록: {', '.join(columns[:20])} ... (총 {len(columns)}개 열)
- 감지된 연도 열 범위: {year_cols[0] if year_cols else 'N/A'} ~ {year_cols[-1] if year_cols else 'N/A'} (총 {len(year_cols)}개 연도)
- 권장 기준연도: {recommended_year}
- 10년 전 비교연도: {base_year}
- 감지된 집계 행 수: {agg_count}개
- 연도별 유효 데이터 충실도 샘플: {json.dumps({k: coverage_map[k] for k in list(coverage_map.keys())[-5:]} if coverage_map else {})}

[엄격한 제약 규칙 - 반드시 준수]
1. 반드시 위의 도구 카탈로그에 명시된 12종 도구 이름(tool)만 사용해야 합니다. 다른 도구명을 지어내지 마세요.
2. 데이터셋에 실존하는 열 이름(예: '{label_col}', '{recommended_year}', '{base_year}')만 params로 전달하세요.
3. 7~12번 도구는 reference_period 파라미터가 필수입니다.
4. 추천 항목은 반드시 3개 이상, 5개 이하(suggestions 배열)여야 합니다.
5. why(추천 이유)와 caution(해석 시 주의사항)은 한국어로 구체적이고 전문적으로 작성하세요.
6. 응답은 어떠한 마크다운이나 잡담 없이 반드시 순수 JSON 객체 하나만 출력해야 합니다.

출력 JSON 형식:
{{
  "suggestions": [
    {{
      "tool": "top_bottom_n",
      "params": {{
        "value_column": "{recommended_year}",
        "label_column": "{label_col}",
        "n": 10,
        "reference_period": "{recommended_year}",
        "exclude_aggregates": true
      }},
      "reference_period": "{recommended_year}",
      "why": "2024년 기준 최상위 국가와 최하위 국가의 디지털 정보 격차(디지털 디바이드)를 직관적으로 비교할 수 있습니다.",
      "caution": "인구 규모가 극히 작은 특수 국가들의 극단적 수치가 포함될 수 있으므로 표본 특성을 고려해야 합니다."
    }}
  ]
}}
"""

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=gemini_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[ERROR] Gemini API 호출 실패: {err_msg}", exc_info=True)
        if "API_KEY_INVALID" in err_msg or "PERMISSION_DENIED" in err_msg:
            return jsonify({"status": "error", "message": "Gemini API 인증에 실패했습니다. API Key를 확인해주세요."}), 401
        elif "DEADLINE_EXCEEDED" in err_msg or "timed out" in err_msg.lower():
            return jsonify({"status": "error", "message": "Gemini API 응답 시간이 초과되었습니다."}), 504
        else:
            return jsonify({"status": "error", "message": f"네트워크 또는 API 오류가 발생했습니다: {err_msg}"}), 500

    logger.info("[AI] suggest 응답 수신 완료")

    try:
        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

        parsed_json = json.loads(raw_text)
        suggestions_raw = parsed_json.get("suggestions", [])
    except Exception as e:
        logger.error(f"[ERROR] JSON 파싱 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "AI 응답을 JSON으로 파싱하는 데 실패했습니다."}), 500

    valid_suggestions = []
    for s in suggestions_raw:
        tool_name = s.get("tool")
        if tool_name in tools.TOOL_REGISTRY:
            if not s.get("reference_period"):
                s["reference_period"] = recommended_year
            if "params" in s and not s["params"].get("reference_period"):
                s["params"]["reference_period"] = recommended_year
            valid_suggestions.append(s)
        else:
            logger.warning(f"[AI] 카탈로그 외 도구 무시: {tool_name}")

    if len(valid_suggestions) > 5:
        valid_suggestions = valid_suggestions[:5]

    logger.info(f"[AI] suggest JSON 파싱 결과: 유효 제안 {len(valid_suggestions)}개")

    return jsonify({
        "status": "success",
        "recommended_reference_period": recommended_year,
        "count": len(valid_suggestions),
        "suggestions": valid_suggestions
    }), 200

# ==========================================
# POST /run (Step 18: 도구 실행 엔드포인트)
# ==========================================
@app.route("/run", methods=["POST"])
def run_tool():
    """POST /run (도구 실행 - 기준시점 필수, 제외 행 수 반환)"""
    logger.info("[REQUEST] POST /run")

    payload = request.get_json(silent=True) or {}
    tool_name = payload.get("tool") or request.form.get("tool")
    params = payload.get("params") or {}

    if not params and "params" in request.form:
        try:
            params = json.loads(request.form.get("params"))
        except Exception:
            params = {}

    if not tool_name:
        logger.warning("[ERROR] 도구명 미지정")
        return jsonify({"status": "error", "message": "실행할 도구(tool)를 지정해주세요."}), 400

    if tool_name not in tools.TOOL_REGISTRY:
        logger.warning(f"[ERROR] 도구 목록에 없는 도구 요청: {tool_name}")
        return jsonify({"status": "error", "message": f"도구 목록에 없는 도구입니다: '{tool_name}'"}), 400

    ref_period = params.get("reference_period") or payload.get("reference_period")
    if tool_name in REQUIRES_REFERENCE_PERIOD and not ref_period:
        logger.warning(f"[ERROR] 기준 시점 미입력: {tool_name}")
        return jsonify({"status": "error", "message": f"도구 '{tool_name}'은(는) 기준 시점(reference_period)이 필수 입력값입니다."}), 400

    if ref_period and "reference_period" not in params:
        params["reference_period"] = str(ref_period)

    df = None
    if "file" in request.files:
        uploaded_file = request.files["file"]
        content_str, _ = try_decode(uploaded_file.read())
        if content_str:
            df, _, _ = detect_header_and_parse(content_str)

    if df is None and CURRENT_DATASET.get("df") is not None:
        df = CURRENT_DATASET["df"]

    if df is None:
        default_csv = os.path.join(BASE_DIR, "data", "API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv")
        if not os.path.exists(default_csv):
            default_csv = "data/API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"
        if os.path.exists(default_csv):
            with open(default_csv, "rb") as f:
                content_str, _ = try_decode(f.read())
                df, _, _ = detect_header_and_parse(content_str)
                CURRENT_DATASET["df"] = df

    if df is None:
        logger.warning("[ERROR] 분석할 데이터 없음")
        return jsonify({"status": "error", "message": "분석할 데이터가 없습니다. 먼저 CSV 파일을 업로드해주세요."}), 400

    tool_func = tools.TOOL_REGISTRY[tool_name]
    sig = inspect.signature(tool_func)
    valid_args = {}
    for param_name, val in params.items():
        if param_name in sig.parameters:
            valid_args[param_name] = val

    try:
        execution_result = tool_func(df, **valid_args)
    except ValueError as ve:
        logger.warning(f"[ERROR] 도구 실행 유효성 검사 실패: {str(ve)}")
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 중 예외: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"도구 계산 중 오류가 발생했습니다: {str(e)}"}), 500

    rows_used = execution_result.get("rows_used", 0)
    rows_excluded = execution_result.get("rows_excluded", 0)
    logger.info(f"[TOOL] 도구명={tool_name}, 파라미터={valid_args}, 사용 행 수={rows_used}, 제외 행 수={rows_excluded}")

    return jsonify({
        "status": "success",
        **execution_result
    }), 200

# ==========================================
# POST /explain (Step 19: Gemini 해석 모드 A/B)
# ==========================================
@app.route("/explain", methods=["POST"])
def explain_results():
    """
    POST /explain (Gemini 해석 엔드포인트: 모드 A와 모드 B 지원)
    """
    logger.info("[REQUEST] POST /explain")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] API Key 미설정")
        return jsonify({
            "status": "error",
            "message": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해주세요."
        }), 500

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "B").upper() # "A" 또는 "B"
    tool_name = data.get("tool", "")
    inspection_summary = data.get("inspection_summary", {})
    calc_result = data.get("calculation_result", {})

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    logger.info(f"[AI] explain 요청 시작 (모드={mode}, 도구={tool_name})")

    if mode == "A":
        # 모드 A (비교용, 의도적으로 허술하게): 진단 요약만 전달하고 Pandas 계산 결과는 주지 않음
        explain_prompt = f"""
당신은 일반 AI 어시스턴트입니다.
아래의 데이터셋 정보만 보고 전체적인 데이터 분석 보고서를 작성해주세요.
(참고: 구체적인 계산 결과나 통계 수치는 아직 계산되지 않았습니다.)

[데이터셋 정보]
- 파일명: {inspection_summary.get('file_info', {}).get('name', 'World Bank CSV')}
- 컬럼 목록: {inspection_summary.get('header_info', {}).get('columns', [])[:15]}
- 전체 행/열: {inspection_summary.get('header_info', {}).get('total_rows')}행 / {inspection_summary.get('header_info', {}).get('total_columns')}열
- 경고 사항: {inspection_summary.get('warnings', [])}

요청: 위 정보를 바탕으로 이 데이터가 무엇인지 분석하여 자유롭게 보고서를 작성해주세요.
"""
    else:
        # 모드 B (정식, 엄격한 규칙): Pandas 계산 결과 전달 및 엄격한 8대 규칙 적용
        explain_prompt = f"""
당신은 신뢰성을 최우선으로 하는 수석 데이터 분석가입니다.
Pandas가 직접 계산하여 산출한 아래의 정확한 계산 결과를 바탕으로 엄격하고 객관적인 통계 해석 보고서를 작성하세요.

[Pandas 정확 계산 결과]
- 사용 도구: {tool_name}
- 기준 시점: {calc_result.get('reference_period')}
- 사용한 행 수: {calc_result.get('rows_used')}개
- 제외된 행 수: {calc_result.get('rows_excluded')}개
- 제외 사유: {calc_result.get('exclusion_reasons')}
- 분석 단위: {calc_result.get('unit')}
- 도구 주의사항: {calc_result.get('caution')}
- 상세 수치 결과(표/통계):
{json.dumps(calc_result.get('result', {}), ensure_ascii=False, indent=2)}

[데이터셋 메타 정보]
- 출처/지표: 세계은행(World Bank) World Development Indicators - 인터넷 사용 인구 비율 (Individuals using the Internet (% of population))

[작성 시 절대 준수해야 할 8대 규칙]
1. 반드시 제공된 계산 결과에 존재하는 숫자만 사용하세요. 직접 계산하거나 추정하지 마세요.
2. 데이터에 실존하지 않는 가상의 국가, 연도, 열 이름을 절대 언급하지 마세요.
3. 기준 시점과 제외된 행 수, 제외 사유를 본문 앞부분에 명확히 명시하세요.
4. 상관관계를 인과관계로 표현하지 마세요 (A가 B의 원인이라고 단정 금지).
5. 지표의 정의와 출처를 보고서 앞부분에 표기하세요.
6. 데이터로 확인할 수 없는 원인이나 배경은 "이 데이터로는 확인할 수 없다"라고 솔직하게 기재하세요.
7. 중학생도 명확하게 이해할 수 있도록 쉬운 문장으로 서술하되, 통계적 정확성을 타협하지 마세요.
8. 반드시 아래 7개 마크다운 헤더 섹션 규격을 순서대로 지켜서 작성하세요.

[출력 형식 - 마크다운 헤더 필수]
## 무엇을 봤는가
## 데이터 출처와 정의
## 기준 시점과 제외된 항목
## 계산 결과
## 읽어낼 수 있는 것
## 이 데이터로는 알 수 없는 것
## 다음에 확인해볼 것
"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=explain_prompt,
            config=types.GenerateContentConfig(
                temperature=0.3
            )
        )
        report_text = response.text.strip()
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[ERROR] Gemini API explain 실패: {err_msg}", exc_info=True)
        return jsonify({"status": "error", "message": f"해석 보고서 생성 중 오류가 발생했습니다: {err_msg}"}), 500

    logger.info(f"[AI] explain 응답 수신 완료 (모드={mode})")
    logger.info("[RESPONSE] status=200")

    return jsonify({
        "status": "success",
        "mode": mode,
        "tool": tool_name,
        "explanation": report_text
    }), 200

# ==========================================
# POST /followup (후속 질문 질의응답)
# ==========================================
@app.route("/followup", methods=["POST"])
def followup_chat():
    """
    POST /followup (보고서 결과 기반 대화형 후속 질의응답)
    """
    logger.info("[REQUEST] POST /followup")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"status": "error", "message": "Gemini API Key가 설정되지 않았습니다."}), 500

    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"status": "error", "message": "질문 내용을 입력해주세요."}), 400

    mode = data.get("mode", "B")
    tool_name = data.get("tool", "")
    current_explanation = data.get("current_explanation", "")
    calc_result = data.get("calculation_result", {})
    history = data.get("history", [])

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    logger.info(f"[AI] followup 질의응답 요청 (질문='{question[:30]}...', 모드={mode})")

    conversation_context = ""
    for h in history[-4:]:
        role_label = "사용자" if h.get("role") == "user" else "AI 어시스턴트"
        conversation_context += f"{role_label}: {h.get('content')}\n"

    system_instruction = f"""
당신은 친절하고 전문적인 수석 데이터 과학자이자 통계 교육 전문가입니다.
사용자가 방금 확인한 데이터 분석 보고서 및 Pandas 계산 결과를 바탕으로 후속 질문에 명확하게 답변해야 합니다.

[분석 정보 및 배경 데이터]
- 사용된 분석 도구: {tool_name}
- 분석 모드: 모드 {mode}
- 기준 시점: {calc_result.get('reference_period')}
- 분석 대상 관측치 수: {calc_result.get('rows_used')}개 (제외 행: {calc_result.get('rows_excluded')}개)
- 주의사항: {calc_result.get('caution')}
- 직전에 생성된 보고서 내용 요약:
{current_explanation[:1500]}

[최근 대화 맥락]
{conversation_context}

[사용자 후속 질문]
{question}

[답변 작성 가이드]
1. 사용자가 "쉽게 설명해줘" 또는 "중학생도 이해할 수 있게"라고 요청하거나 쉬운 설명을 원할 경우, 어려운 전문 통계 용어를 피하고 친숙한 비유(학교 성적, 시험 등수, 스마트폰 사용 일상 등)를 들어 눈높이에 맞춰 직관적이고 다정하게 설명하세요.
2. 사실에 기반하여 답변하되, Pandas 계산 결과에 없는 가상의 통계 숫자를 지어내지(환각) 마세요.
3. 데이터로 증명할 수 없는 원인(예: 왜 특정 국가가 더 높은지 등)에 대해서는 "이 데이터만으로는 단정할 수 없으며 ~한 외부 요인이 영향을 미쳤을 수 있습니다"와 같이 균형 잡힌 시각으로 안내하세요.
4. 마크다운 형식을 활용하여 읽기 쉽게 문단을 나누고 핵심 키워드는 볼드체로 강조하세요.
"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=system_instruction,
            config=types.GenerateContentConfig(
                temperature=0.3
            )
        )
        answer_text = response.text.strip()
    except Exception as e:
        logger.error(f"[ERROR] Gemini followup API 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500

    logger.info("[AI] followup 응답 수신 완료")

    return jsonify({
        "status": "success",
        "question": question,
        "answer": answer_text
    }), 200

# ==========================================
# GET /api/logs (서버 최근 로그 조회 API)
# ==========================================
@app.route("/api/logs", methods=["GET"])
def get_recent_logs():
    """최근 서버 실행 로그 목록 반환"""
    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return jsonify({"status": "success", "logs": [l.strip() for l in lines[-100:]]})
        return jsonify({"status": "success", "logs": []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Flask server on port 5000...")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)

