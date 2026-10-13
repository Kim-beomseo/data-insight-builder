import io
import os
import re
import csv
import json
import logging
import inspect
import numpy as np
import pandas as pd
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools

# 환경변수 로드
load_dotenv()

# 로깅 설정 (print() 대신 logging 모듈 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

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

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Flask server on port 5000...")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
