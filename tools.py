import re
import math
import glob
import numpy as np
import pandas as pd

# 집계 행 식별 키워드
AGGREGATE_KEYWORDS = [
    "world", "oecd members", "euro area", "european union", "high income",
    "low income", "middle income", "upper middle income", "lower middle income",
    "income", "area", "total", "aggregate", "dividend", "sub-saharan",
    "latin america", "caribbean", "middle east", "north america", "south asia",
    "east asia & pacific", "europe & central asia", "small states"
]

def sanitize_for_json(obj):
    """
    NaN 및 Infinity 값을 JSON 전송 가능한 None으로 안전하게 변환
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 4)
    elif isinstance(obj, np.generic):
        item = obj.item()
        return sanitize_for_json(item)
    elif isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    elif pd.isna(obj):
        return None
    return obj

def extract_year_columns(df):
    """4자리 연도 형태(1900~2099)의 컬럼 추출"""
    return [
        str(c).strip() for c in df.columns 
        if re.match(r"^(19|20)\d{2}$", str(c).strip())
    ]

def filter_aggregates(df, id_column=None):
    """
    집계 행(World, High income 등)을 식별하여
    (개별국가_df, 집계행_df, 제외된_행_수) 튜플 반환
    """
    if id_column is None:
        id_column = df.columns[0]
        
    mask = df[id_column].astype(str).str.lower().apply(
        lambda val: any(k in val for k in AGGREGATE_KEYWORDS)
    )
    non_agg_df = df[~mask].copy()
    agg_df = df[mask].copy()
    return non_agg_df, agg_df, int(mask.sum())

# ==========================================
# 도구 1: reshape_wide_to_long
# ==========================================
def reshape_wide_to_long(df, id_vars=None, value_vars=None, var_name="year", value_name="value", drop_na=True):
    """도구 1. 연도 열을 행으로 접기 (Wide -> Long 형식 변환)"""
    year_cols = extract_year_columns(df)
    if value_vars is None:
        value_vars = year_cols
    if id_vars is None:
        id_vars = [c for c in df.columns if c not in value_vars and not str(c).startswith("Unnamed:")]
    if not value_vars:
        raise ValueError("변환할 연도 열(value_vars)이 감지되지 않았습니다.")

    melted = pd.melt(df, id_vars=id_vars, value_vars=value_vars, var_name=var_name, value_name=value_name)
    total_melted_rows = len(melted)
    if drop_na:
        melted_valid = melted.dropna(subset=[value_name])
        rows_excluded = total_melted_rows - len(melted_valid)
        exclusion_reason = "결측치(NaN) 값을 가진 행 제외"
        final_df = melted_valid
    else:
        final_df = melted
        rows_excluded = 0
        exclusion_reason = "제외 없음"

    rows_used = len(final_df)
    preview = final_df.head(20).replace({np.nan: None}).to_dict(orient="records")

    return sanitize_for_json({
        "tool": "reshape_wide_to_long",
        "result": {
            "total_reshaped_rows": rows_used,
            "id_columns": id_vars,
            "value_columns_count": len(value_vars),
            "preview_rows": preview
        },
        "reference_period": None,
        "rows_used": rows_used,
        "rows_excluded": rows_excluded,
        "exclusion_reasons": exclusion_reason,
        "columns_used": id_vars + value_vars,
        "unit": "행 (Long format 레코드)",
        "caution": "Wide 형태를 Long 형태로 변환하면 연도별 행 수가 급증하므로 필터링 후 분석하는 것이 효율적입니다."
    })

# ==========================================
# 도구 2: quality_report
# ==========================================
def quality_report(df):
    """도구 2. 결측·중복·타입·이상한 열 이름 진단"""
    total_rows = len(df)
    total_cols = len(df.columns)
    total_cells = int(df.size)
    missing_cells = int(df.isna().sum().sum())
    missing_rate = round((missing_cells / total_cells * 100), 2) if total_cells > 0 else 0.0
    duplicate_rows = int(df.duplicated().sum())

    column_types = {str(col): str(dtype) for col, dtype in df.dtypes.items()}
    columns_missing = {str(col): int(df[col].isna().sum()) for col in df.columns}
    unusual_columns = [str(c) for c in df.columns if str(c).startswith("Unnamed:") or str(c).strip() == ""]

    return sanitize_for_json({
        "tool": "quality_report",
        "result": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "total_cells": total_cells,
            "missing_cells": missing_cells,
            "missing_rate_pct": missing_rate,
            "duplicate_rows": duplicate_rows,
            "column_types": column_types,
            "columns_missing_count": columns_missing,
            "unusual_columns": unusual_columns
        },
        "reference_period": None,
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reasons": "제외된 행 없음",
        "columns_used": [str(c) for c in df.columns],
        "unit": "% 및 개수",
        "caution": "결측 비율이 지나치게 높은 열은 통계 분석에서 왜곡을 초래하므로 주의가 필요합니다."
    })

# ==========================================
# 도구 3: year_coverage
# ==========================================
def year_coverage(df):
    """도구 3. 연도별 값 개수와 권장 기준연도"""
    year_cols = extract_year_columns(df)
    coverage = {}
    for y in year_cols:
        val_count = int(df[y].dropna().count())
        if val_count > 0:
            coverage[y] = val_count

    recommended_year = None
    if coverage:
        max_count = max(coverage.values())
        candidates = [y for y, cnt in coverage.items() if cnt >= max_count * 0.85]
        if candidates:
            recommended_year = max(candidates, key=lambda x: int(x))
        else:
            recommended_year = max(coverage.keys(), key=lambda x: (coverage[x], int(x)))

    total_rows = len(df)
    return sanitize_for_json({
        "tool": "year_coverage",
        "result": {
            "year_columns_count": len(year_cols),
            "coverage_by_year": coverage,
            "recommended_year": recommended_year,
            "max_coverage_count": max(coverage.values()) if coverage else 0
        },
        "reference_period": recommended_year,
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reasons": "제외된 행 없음",
        "columns_used": year_cols,
        "unit": "개 (유효 관측치 수)",
        "caution": "최신 연도일수록 집계 시점 차이로 인해 미보고 국가의 결측 비율이 높을 수 있습니다."
    })

# ==========================================
# 도구 4: detect_aggregates
# ==========================================
def detect_aggregates(df, id_column=None):
    """도구 4. 집계 행 후보 탐지"""
    if id_column is None:
        id_column = df.columns[0]

    agg_candidates = []
    for idx, val in df[id_column].items():
        val_str = str(val).lower()
        matched = [k for k in AGGREGATE_KEYWORDS if k in val_str]
        if matched:
            agg_candidates.append({
                "row_index": int(idx),
                "name": str(val),
                "matched_keyword": matched[0]
            })

    total_rows = len(df)
    return sanitize_for_json({
        "tool": "detect_aggregates",
        "result": {
            "aggregate_count": len(agg_candidates),
            "aggregate_rows": agg_candidates,
            "individual_entity_count": total_rows - len(agg_candidates)
        },
        "reference_period": None,
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reasons": "제외된 행 없음 (진단 탐지 목적)",
        "columns_used": [str(id_column)],
        "unit": "행 (개)",
        "caution": "대륙, 소득분위, 세계 전체 등 집계 행을 국가 순위에 포함하면 데이터가 중복 반영되어 심각한 왜곡이 발생합니다."
    })

# ==========================================
# 도구 5: describe_numeric
# ==========================================
def describe_numeric(df, column=None, reference_period=None, exclude_aggregates=True):
    """도구 5. 개수·평균·중앙값·최소·최대·표준편차"""
    target_col = column if column else reference_period
    if not target_col:
        year_cols = extract_year_columns(df)
        target_col = year_cols[-1] if year_cols else None

    if not target_col or target_col not in df.columns:
        raise ValueError(f"분석 대상 수치 열({target_col})을 찾을 수 없습니다.")

    working_df = df.copy()
    excluded_agg_count = 0
    exclusion_reasons = []

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행(대륙, 소득그룹 등) {excluded_agg_count}개 제외")

    series = pd.to_numeric(working_df[target_col], errors="coerce").dropna()
    nan_count = len(working_df) - len(series)
    if nan_count > 0:
        exclusion_reasons.append(f"결측치(NaN) {nan_count}개 제외")

    total_excluded = excluded_agg_count + nan_count
    rows_used = len(series)
    if rows_used == 0:
        raise ValueError(f"열 '{target_col}'에 유효한 수치 데이터가 존재하지 않습니다.")

    stats = {
        "column": target_col,
        "count": int(series.count()),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "std": float(series.std()) if rows_used > 1 else 0.0,
        "min": float(series.min()),
        "max": float(series.max()),
        "q25": float(series.quantile(0.25)),
        "q75": float(series.quantile(0.75))
    }

    return sanitize_for_json({
        "tool": "describe_numeric",
        "result": stats,
        "reference_period": target_col if re.match(r"^(19|20)\d{2}$", str(target_col)) else None,
        "rows_used": rows_used,
        "rows_excluded": total_excluded,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [target_col],
        "unit": "수치 단위 (백분율 % 등)",
        "caution": "표준편차가 크거나 왜도가 심한 경우 평균보다 중앙값을 주요 지표로 참조하는 것이 적절합니다."
    })

# ==========================================
# 도구 6: trend_line
# ==========================================
def trend_line(df, items=None, id_column=None, years=None, exclude_aggregates=False):
    """도구 6. 선택 항목들의 연도별 추이 (선 차트 데이터)"""
    if id_column is None:
        id_column = df.columns[0]

    all_years = extract_year_columns(df)
    target_years = [y for y in (years if years else all_years) if y in df.columns]

    if not target_years:
        raise ValueError("시계열 추이를 표시할 연도 열이 없습니다.")

    working_df = df.copy()
    if exclude_aggregates:
        working_df, _, _ = filter_aggregates(working_df, id_column=id_column)

    if not items:
        popular_candidates = ["Korea, Rep.", "United States", "Japan", "World", "China"]
        available = working_df[id_column].dropna().unique()
        items = [c for c in popular_candidates if c in available]
        if not items:
            items = list(available[:3])

    series_data = []
    for item in items:
        row_match = working_df[working_df[id_column] == item]
        if row_match.empty:
            continue
        row = row_match.iloc[0]
        points = []
        for y in target_years:
            val = pd.to_numeric(row.get(y), errors="coerce")
            points.append({"year": y, "value": float(val) if pd.notna(val) else None})

        series_data.append({"label": str(item), "points": points})

    return sanitize_for_json({
        "tool": "trend_line",
        "result": {
            "id_column": id_column,
            "items_count": len(series_data),
            "years_count": len(target_years),
            "series": series_data
        },
        "reference_period": f"{target_years[0]}~{target_years[-1]}" if target_years else None,
        "rows_used": len(series_data),
        "rows_excluded": len(df) - len(series_data),
        "exclusion_reasons": f"선택 항목({', '.join(items)}) 외 나머지 행 제외",
        "columns_used": [id_column] + target_years,
        "unit": "% (지표 단위)",
        "caution": "시계열 구간 중 과거 연도일수록 미보고에 따른 결측(None) 지점이 존재할 수 있습니다."
    })

# ==========================================
# 도구 7: top_bottom_n (공통규칙: 기준시점 필수)
# ==========================================
def top_bottom_n(df, reference_period, n=10, value_column=None, label_column=None, exclude_aggregates=True):
    """도구 7. 기준연도 기준 상위·하위 N (수평 막대)"""
    if not reference_period:
        raise ValueError("도구 7(top_bottom_n)은 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column if value_column else reference_period
    lbl_col = label_column if label_column else df.columns[0]

    if val_col not in df.columns:
        raise ValueError(f"기준 시점 또는 값 열 '{val_col}'이 데이터프레임에 존재하지 않습니다.")

    working_df = df.copy()
    exclusion_reasons = []
    excluded_agg_count = 0

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df, id_column=lbl_col)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    working_df["_numeric_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    valid_df = working_df.dropna(subset=["_numeric_val"]).copy()
    nan_count = len(working_df) - len(valid_df)
    if nan_count > 0:
        exclusion_reasons.append(f"기준 시점 결측치(NaN) {nan_count}개 제외")

    rows_used = len(valid_df)
    if rows_used == 0:
        raise ValueError(f"기준 시점 '{reference_period}'에 유효한 값이 존재하는 행이 없습니다.")

    sorted_df = valid_df.sort_values(by="_numeric_val", ascending=False)
    actual_n = min(n, rows_used)

    top_rows = sorted_df.head(actual_n)
    bottom_rows = sorted_df.tail(actual_n).sort_values(by="_numeric_val", ascending=True)

    top_list = [
        {"rank": idx + 1, "label": str(row[lbl_col]), "value": float(row["_numeric_val"])}
        for idx, (_, row) in enumerate(top_rows.iterrows())
    ]
    bottom_list = [
        {"rank": idx + 1, "label": str(row[lbl_col]), "value": float(row["_numeric_val"])}
        for idx, (_, row) in enumerate(bottom_rows.iterrows())
    ]

    return sanitize_for_json({
        "tool": "top_bottom_n",
        "result": {
            "reference_period": str(reference_period),
            "n": actual_n,
            "total_valid_items": rows_used,
            "top_n": top_list,
            "bottom_n": bottom_list
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [lbl_col, val_col],
        "unit": "% (비율 지표)",
        "caution": "인구 극소 국가나 특수 경제구역의 경우 극단적 수치가 나타날 수 있으므로 표본 규모를 고려해야 합니다."
    })

# ==========================================
# 도구 8: group_summary (공통규칙: 기준시점 필수)
# ==========================================
def group_summary(df, reference_period, group_column=None, value_column=None, exclude_aggregates=True):
    """도구 8. 그룹별 평균·합계·개수 (막대 차트)"""
    if not reference_period:
        raise ValueError("도구 8(group_summary)은 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column if value_column else reference_period
    working_df = df.copy()

    if (group_column is None or group_column not in working_df.columns):
        if "Country Code" in working_df.columns:
            base_d = os.path.dirname(os.path.abspath(__file__))
            meta_files = glob.glob(os.path.join(base_d, "data", "Metadata_Country*.csv")) or glob.glob("data/Metadata_Country*.csv")
            if meta_files:
                try:
                    meta_df = pd.read_csv(meta_files[0])
                    cols_to_use = [c for c in ["Country Code", "Region", "IncomeGroup"] if c in meta_df.columns]
                    working_df = pd.merge(working_df, meta_df[cols_to_use], on="Country Code", how="left")
                    if group_column is None:
                        group_column = "IncomeGroup" if "IncomeGroup" in working_df.columns else "Region"
                except Exception:
                    pass

    if group_column is None or group_column not in working_df.columns:
        object_cols = [c for c in working_df.columns if working_df[c].dtype == "object" and not str(c).startswith("Unnamed:")]
        if len(object_cols) >= 2:
            group_column = object_cols[1]
        else:
            raise ValueError("그룹화할 범주형 열(group_column)을 찾을 수 없습니다.")

    exclusion_reasons = []
    excluded_agg_count = 0
    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    working_df["_num"] = pd.to_numeric(working_df[val_col], errors="coerce")
    valid_df = working_df.dropna(subset=["_num", group_column]).copy()
    valid_df = valid_df[valid_df[group_column].astype(str).str.strip() != ""]

    nan_count = len(working_df) - len(valid_df)
    if nan_count > 0:
        exclusion_reasons.append(f"값 또는 그룹 결측치 {nan_count}개 제외")

    rows_used = len(valid_df)
    if rows_used == 0:
        raise ValueError(f"기준 시점 '{reference_period}'에 유효한 그룹 데이터가 없습니다.")

    grouped = valid_df.groupby(group_column)["_num"].agg(
        count="count", mean="mean", median="median", min="min", max="max", sum="sum"
    ).reset_index().sort_values(by="mean", ascending=False)

    group_list = [
        {
            "group": str(row[group_column]),
            "count": int(row["count"]),
            "mean": float(row["mean"]),
            "median": float(row["median"]),
            "min": float(row["min"]),
            "max": float(row["max"]),
            "sum": float(row["sum"])
        }
        for _, row in grouped.iterrows()
    ]

    return sanitize_for_json({
        "tool": "group_summary",
        "result": {
            "group_column": group_column,
            "value_column": val_col,
            "reference_period": str(reference_period),
            "groups_count": len(group_list),
            "groups": group_list
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [group_column, val_col],
        "unit": "% (평균 및 중앙값)",
        "caution": "그룹별 표본 크기(포함 국가 수)가 상이하므로 합계보다는 평균 및 중앙값 비교에 중점을 두어야 합니다."
    })

# ==========================================
# 도구 9: change_rate (공통규칙: 기준시점 필수)
# ==========================================
def change_rate(df, reference_period, base_period=None, n=10, label_column=None, exclude_aggregates=True):
    """도구 9. 두 시점 사이 변화량·변화율 (막대 차트)"""
    if not reference_period:
        raise ValueError("도구 9(change_rate)는 기준 시점(reference_period)이 필수 파라미터입니다.")

    lbl_col = label_column if label_column else df.columns[0]
    year_cols = extract_year_columns(df)

    if not base_period:
        # 기준 시점보다 이전 연도 중 10년 전 또는 5년 전 자동 선택
        if reference_period in year_cols:
            ref_idx = year_cols.index(reference_period)
            if ref_idx >= 10:
                base_period = year_cols[ref_idx - 10]
            elif ref_idx >= 5:
                base_period = year_cols[ref_idx - 5]
            elif ref_idx > 0:
                base_period = year_cols[0]
            else:
                raise ValueError("비교할 이전 기준연도(base_period)가 부족합니다.")
        else:
            raise ValueError("기준 시점이 연도 열에 존재하지 않습니다.")

    if base_period not in df.columns or reference_period not in df.columns:
        raise ValueError(f"시점 열 '{base_period}' 또는 '{reference_period}'을 찾을 수 없습니다.")

    working_df = df.copy()
    exclusion_reasons = []
    excluded_agg_count = 0

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df, id_column=lbl_col)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    working_df["_base"] = pd.to_numeric(working_df[base_period], errors="coerce")
    working_df["_ref"] = pd.to_numeric(working_df[reference_period], errors="coerce")

    # 두 시점 모두 유효한 행만 분석
    valid_df = working_df.dropna(subset=["_base", "_ref"]).copy()
    nan_count = len(working_df) - len(valid_df)
    if nan_count > 0:
        exclusion_reasons.append(f"시점 결측치 {nan_count}개 제외")

    rows_used = len(valid_df)
    if rows_used == 0:
        raise ValueError(f"두 시점({base_period} -> {reference_period})에 모두 유효한 값이 있는 데이터가 없습니다.")

    valid_df["_diff"] = valid_df["_ref"] - valid_df["_base"]
    # 변화율(%) 계산 (초기값이 0보다 클 때만)
    valid_df["_rate"] = np.where(
        valid_df["_base"] > 0,
        ((valid_df["_ref"] - valid_df["_base"]) / valid_df["_base"]) * 100,
        None
    )

    actual_n = min(n, rows_used)
    top_inc = valid_df.sort_values(by="_diff", ascending=False).head(actual_n)
    top_dec = valid_df.sort_values(by="_diff", ascending=True).head(actual_n)

    top_increase_list = [
        {
            "rank": idx + 1,
            "label": str(row[lbl_col]),
            "base_val": float(row["_base"]),
            "ref_val": float(row["_ref"]),
            "diff_pct_points": float(row["_diff"]),
            "growth_rate_pct": float(row["_rate"]) if row["_rate"] is not None else None
        }
        for idx, (_, row) in enumerate(top_inc.iterrows())
    ]

    top_decrease_list = [
        {
            "rank": idx + 1,
            "label": str(row[lbl_col]),
            "base_val": float(row["_base"]),
            "ref_val": float(row["_ref"]),
            "diff_pct_points": float(row["_diff"]),
            "growth_rate_pct": float(row["_rate"]) if row["_rate"] is not None else None
        }
        for idx, (_, row) in enumerate(top_dec.iterrows())
    ]

    return sanitize_for_json({
        "tool": "change_rate",
        "result": {
            "base_period": str(base_period),
            "reference_period": str(reference_period),
            "n": actual_n,
            "total_valid_countries": rows_used,
            "average_diff": float(valid_df["_diff"].mean()),
            "median_diff": float(valid_df["_diff"].median()),
            "top_increases": top_increase_list,
            "top_decreases": top_decrease_list
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [lbl_col, base_period, reference_period],
        "unit": "%p(퍼센트포인트 변화량) 및 %(변화율)",
        "caution": "시작 시점(초기값)이 매우 작은 국가의 경우 성장률(%) 수치가 극단적으로 크게 나타날 수 있으므로 절대 변화량(%p)을 반드시 병행 검토해야 합니다."
    })

# ==========================================
# 도구 10: distribution (공통규칙: 기준시점 필수)
# ==========================================
def distribution(df, reference_period, bins=10, value_column=None, exclude_aggregates=True):
    """도구 10. 구간별 분포 (히스토그램)"""
    if not reference_period:
        raise ValueError("도구 10(distribution)은 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column if value_column else reference_period
    if val_col not in df.columns:
        raise ValueError(f"분석 대상 열 '{val_col}'을 찾을 수 없습니다.")

    working_df = df.copy()
    exclusion_reasons = []
    excluded_agg_count = 0

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    series = pd.to_numeric(working_df[val_col], errors="coerce").dropna()
    nan_count = len(working_df) - len(series)
    if nan_count > 0:
        exclusion_reasons.append(f"결측치 {nan_count}개 제외")

    rows_used = len(series)
    if rows_used == 0:
        raise ValueError(f"열 '{val_col}'에 유효한 수치 데이터가 없습니다.")

    # 0~100% 지표 특성 고려 (범위 내인 경우 0~100 고정 또는 동적 계산)
    min_v, max_v = float(series.min()), float(series.max())
    if 0.0 <= min_v and max_v <= 100.0:
        bin_range = (0.0, 100.0)
    else:
        bin_range = (min_v, max_v)

    counts, bin_edges = np.histogram(series, bins=bins, range=bin_range)
    intervals = []
    for i in range(len(counts)):
        b_start = round(float(bin_edges[i]), 1)
        b_end = round(float(bin_edges[i+1]), 1)
        intervals.append({
            "bin_index": i + 1,
            "bin_start": b_start,
            "bin_end": b_end,
            "label": f"{b_start}% ~ {b_end}%",
            "count": int(counts[i]),
            "percentage": round(int(counts[i]) / rows_used * 100, 2)
        })

    return sanitize_for_json({
        "tool": "distribution",
        "result": {
            "column": val_col,
            "bins_count": len(intervals),
            "total_items": rows_used,
            "min_value": min_v,
            "max_value": max_v,
            "intervals": intervals
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [val_col],
        "unit": "개 (구간별 빈도 수)",
        "caution": "구간(Bin) 설정 크기에 따라 히스토그램의 형태가 달라질 수 있으므로 전체 왜도 및 최빈 구간을 종합적으로 파악해야 합니다."
    })

# ==========================================
# 도구 11: correlation_scatter (공통규칙: 기준시점 필수 + 인과관계 주의 문구 필수)
# ==========================================
def correlation_scatter(df, reference_period, compare_column=None, id_column=None, exclude_aggregates=True):
    """도구 11. 두 숫자 열 상관계수 (산점도)"""
    if not reference_period:
        raise ValueError("도구 11(correlation_scatter)은 기준 시점(reference_period)이 필수 파라미터입니다.")

    x_col = compare_column
    y_col = reference_period
    id_col = id_column if id_column else df.columns[0]
    year_cols = extract_year_columns(df)

    if not x_col:
        # 기본 비교열: 기준시점 10년 전 연도 (시계열 자기상관)
        if reference_period in year_cols:
            ref_idx = year_cols.index(reference_period)
            if ref_idx >= 10:
                x_col = year_cols[ref_idx - 10]
            elif ref_idx > 0:
                x_col = year_cols[0]
            else:
                x_col = year_cols[-2] if len(year_cols) >= 2 else None

    if not x_col or x_col not in df.columns or y_col not in df.columns:
        raise ValueError(f"비교할 수치 열('{x_col}' 및 '{y_col}')을 찾을 수 없습니다.")

    working_df = df.copy()
    exclusion_reasons = []
    excluded_agg_count = 0

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df, id_column=id_col)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    working_df["_x"] = pd.to_numeric(working_df[x_col], errors="coerce")
    working_df["_y"] = pd.to_numeric(working_df[y_col], errors="coerce")

    valid_df = working_df.dropna(subset=["_x", "_y"]).copy()
    nan_count = len(working_df) - len(valid_df)
    if nan_count > 0:
        exclusion_reasons.append(f"결측치 {nan_count}개 제외")

    rows_used = len(valid_df)
    if rows_used < 2:
        raise ValueError("상관계수를 계산하기 위한 유효 관측치가 부족합니다(최소 2개 이상 필요).")

    corr = float(valid_df["_x"].corr(valid_df["_y"]))

    # 산점도 포인트 생성
    points = [
        {
            "label": str(row[id_col]),
            "x": float(row["_x"]),
            "y": float(row["_y"])
        }
        for _, row in valid_df.iterrows()
    ]

    return sanitize_for_json({
        "tool": "correlation_scatter",
        "result": {
            "x_column": x_col,
            "y_column": y_col,
            "correlation_coefficient": corr,
            "interpretation": "강한 양의 상관관계" if corr >= 0.7 else ("뚜렷한 양의 상관관계" if corr >= 0.4 else "약한 상관관계 또는 무상관"),
            "points_count": len(points),
            "points": points
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [id_col, x_col, y_col],
        "unit": "피어슨 상관계수 r (-1.0 ~ +1.0)",
        "caution": "상관관계는 인과관계가 아닙니다. 두 변수 간의 높은 상관계수가 하나의 변수가 다른 변수의 직접적인 원인임을 증명하지는 않으며, 제3의 잠재 요인(예: 경제 성장, 국가 인프라 등)이 동시에 영향을 미쳤을 가능성을 항상 유념해야 합니다."
    })

# ==========================================
# 도구 12: compare_one_vs_all (공통규칙: 기준시점 필수)
# ==========================================
def compare_one_vs_all(df, reference_period, item="Korea, Rep.", value_column=None, id_column=None, exclude_aggregates=True):
    """도구 12. 특정 항목 vs 전체 평균·중앙값 (강조 막대)"""
    if not reference_period:
        raise ValueError("도구 12(compare_one_vs_all)는 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column if value_column else reference_period
    id_col = id_column if id_column else df.columns[0]

    if val_col not in df.columns:
        raise ValueError(f"값 열 '{val_col}'을 찾을 수 없습니다.")

    working_df = df.copy()
    exclusion_reasons = []
    excluded_agg_count = 0

    if exclude_aggregates:
        working_df, _, excluded_agg_count = filter_aggregates(working_df, id_column=id_col)
        if excluded_agg_count > 0:
            exclusion_reasons.append(f"집계 행 {excluded_agg_count}개 제외")

    working_df["_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    valid_df = working_df.dropna(subset=["_val"]).copy()
    nan_count = len(working_df) - len(valid_df)
    if nan_count > 0:
        exclusion_reasons.append(f"결측치 {nan_count}개 제외")

    rows_used = len(valid_df)
    if rows_used == 0:
        raise ValueError(f"기준 시점 '{reference_period}'에 유효한 값이 없습니다.")

    target_match = valid_df[valid_df[id_col].astype(str) == str(item)]
    if target_match.empty:
        raise ValueError(f"분석 대상 항목 '{item}'을 데이터에서 찾을 수 없거나 해당 시점의 값이 결측되었습니다.")

    item_val = float(target_match.iloc[0]["_val"])
    all_mean = float(valid_df["_val"].mean())
    all_median = float(valid_df["_val"].median())
    all_min = float(valid_df["_val"].min())
    all_max = float(valid_df["_val"].max())

    # 순위 계산 (내림차순)
    valid_df["_rank"] = valid_df["_val"].rank(ascending=False, method="min")
    item_rank = int(valid_df[valid_df[id_col].astype(str) == str(item)].iloc[0]["_rank"])
    percentile = round(((rows_used - item_rank + 1) / rows_used) * 100, 2)

    diff_from_mean = round(item_val - all_mean, 2)
    diff_from_median = round(item_val - all_median, 2)

    comparison_bars = [
        {"label": f"{item} (선택 대상)", "value": item_val, "is_target": True},
        {"label": "전체 평균 (Mean)", "value": round(all_mean, 2), "is_target": False},
        {"label": "전체 중앙값 (Median)", "value": round(all_median, 2), "is_target": False}
    ]

    return sanitize_for_json({
        "tool": "compare_one_vs_all",
        "result": {
            "target_item": str(item),
            "reference_period": str(reference_period),
            "target_value": item_val,
            "target_rank": item_rank,
            "total_items": rows_used,
            "percentile": percentile,
            "overall_mean": all_mean,
            "overall_median": all_median,
            "overall_min": all_min,
            "overall_max": all_max,
            "diff_from_mean": diff_from_mean,
            "diff_from_median": diff_from_median,
            "chart_bars": comparison_bars
        },
        "reference_period": str(reference_period),
        "rows_used": rows_used,
        "rows_excluded": excluded_agg_count + nan_count,
        "exclusion_reasons": ", ".join(exclusion_reasons) if exclusion_reasons else "제외 없음",
        "columns_used": [id_col, val_col],
        "unit": "% (비율 지표)",
        "caution": "단순 평균은 일부 극단치의 영향을 크게 받을 수 있으므로 중앙값과의 비교 차이를 반드시 병행하여 확인해야 합니다."
    })

# ==========================================
# 12종 도구 함수 레지스트리
# ==========================================
TOOL_REGISTRY = {
    "reshape_wide_to_long": reshape_wide_to_long,
    "quality_report": quality_report,
    "year_coverage": year_coverage,
    "detect_aggregates": detect_aggregates,
    "describe_numeric": describe_numeric,
    "trend_line": trend_line,
    "top_bottom_n": top_bottom_n,
    "group_summary": group_summary,
    "change_rate": change_rate,
    "distribution": distribution,
    "correlation_scatter": correlation_scatter,
    "compare_one_vs_all": compare_one_vs_all
}
