// AI Data Insight Builder Frontend Application
document.addEventListener("DOMContentLoaded", () => {
    // ==========================================
    // 상태 관리 변수
    // ==========================================
    let currentFile = null;
    let inspectionData = null;
    let lastCalculationResult = null;
    let activeChartInstance = null;
    let currentExplainMode = "B";

    // ==========================================
    // DOM 요소 캐싱
    // ==========================================
    const serverStatusBadge = document.getElementById("serverStatusBadge");
    const serverStatusText = document.getElementById("serverStatusText");

    const dropzone = document.getElementById("dropzone");
    const csvFileInput = document.getElementById("csvFileInput");
    const dropzoneTrigger = document.getElementById("dropzoneTrigger");
    const selectedFileName = document.getElementById("selectedFileName");
    const inspectBtn = document.getElementById("inspectBtn");
    const loadSampleBtn = document.getElementById("loadSampleBtn");

    const inspectSection = document.getElementById("inspectSection");
    const encodingVal = document.getElementById("encodingVal");
    const skippedVal = document.getElementById("skippedVal");
    const dimensionVal = document.getElementById("dimensionVal");
    const missingRateVal = document.getElementById("missingRateVal");
    const duplicateVal = document.getElementById("duplicateVal");
    const recYearVal = document.getElementById("recYearVal");
    const aggCountVal = document.getElementById("aggCountVal");
    const warningsAlert = document.getElementById("warningsAlert");
    const warningsList = document.getElementById("warningsList");
    const togglePreviewBtn = document.getElementById("togglePreviewBtn");
    const previewTableContainer = document.getElementById("previewTableContainer");
    const previewThead = document.getElementById("previewThead");
    const previewTbody = document.getElementById("previewTbody");
    const requestSuggestBtn = document.getElementById("requestSuggestBtn");

    const nlpQuerySection = document.getElementById("nlpQuerySection");
    const nlpExampleChips = document.getElementById("nlpExampleChips");
    const nlpQueryInput = document.getElementById("nlpQueryInput");
    const sendNlpQueryBtn = document.getElementById("sendNlpQueryBtn");
    const nlpLoading = document.getElementById("nlpLoading");
    const nlpAnswerBox = document.getElementById("nlpAnswerBox");
    const nlpMatchedToolBadge = document.getElementById("nlpMatchedToolBadge");
    const nlpAnswerContent = document.getElementById("nlpAnswerContent");
    const nlpVisualizeBtn = document.getElementById("nlpVisualizeBtn");
    let lastNlpResult = null;

    const suggestSection = document.getElementById("suggestSection");
    const suggestionsContainer = document.getElementById("suggestionsContainer");

    const runSection = document.getElementById("runSection");
    const toolSelect = document.getElementById("toolSelect");
    const refPeriodInput = document.getElementById("refPeriodInput");
    const targetCountryInput = document.getElementById("targetCountryInput");
    const excludeAggCheckbox = document.getElementById("excludeAggCheckbox");
    const executeRunBtn = document.getElementById("executeRunBtn");

    const resultSection = document.getElementById("resultSection");
    const metaTool = document.getElementById("metaTool");
    const metaRef = document.getElementById("metaRef");
    const metaRowsUsed = document.getElementById("metaRowsUsed");
    const metaRowsExcluded = document.getElementById("metaRowsExcluded");
    const cautionText = document.getElementById("cautionText");
    const resultChartCanvas = document.getElementById("resultChart");
    const calcThead = document.getElementById("calcThead");
    const calcTbody = document.getElementById("calcTbody");
    const scrollToExplainBtn = document.getElementById("scrollToExplainBtn");

    const explainSection = document.getElementById("explainSection");
    const tabModeB = document.getElementById("tabModeB");
    const tabModeA = document.getElementById("tabModeA");
    const generateExplainBtn = document.getElementById("generateExplainBtn");
    const modeDescText = document.getElementById("modeDescText");
    const explainLoading = document.getElementById("explainLoading");
    const reportContainer = document.getElementById("reportContainer");

    const logConsole = document.getElementById("logConsole");
    const toggleLogBtn = document.getElementById("toggleLogBtn");
    const logBody = document.getElementById("logBody");

    // ==========================================
    // 표준 프론트엔드 콘솔 로거 함수
    // ==========================================
    function logEvent(tag, message) {
        const timeStr = new Date().toLocaleTimeString();
        console.log(`[${tag}] ${message}`);

        if (logConsole) {
            const entry = document.createElement("div");
            entry.className = "log-entry";
            entry.innerHTML = `<span style="color:#64748b;">${timeStr}</span> <span class="log-tag ${tag}">[${tag}]</span> <span>${escapeHtml(message)}</span>`;
            logConsole.appendChild(entry);
            logConsole.scrollTop = logConsole.scrollHeight;
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    // 1. 페이지 로드 초기화
    logEvent("PAGE", "페이지 로드 완료");
    checkServerHealth();

    // ==========================================
    // 헬스체크
    // ==========================================
    async function checkServerHealth() {
        try {
            const res = await fetch("/health");
            const data = await res.json();
            if (data.status === "ok") {
                serverStatusBadge.classList.add("connected");
                serverStatusText.textContent = `연결됨 (${data.model})`;
            }
        } catch (e) {
            serverStatusText.textContent = "서버 연결 실패";
            logEvent("ERROR", `헬스체크 실패: ${e.message}`);
        }
    }

    // ==========================================
    // 파일 선택 및 드래그 앤 드롭
    // ==========================================
    dropzoneTrigger.addEventListener("click", () => csvFileInput.click());

    csvFileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
            handleSelectedFile(e.target.files[0]);
        }
    });

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("dragover");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleSelectedFile(e.dataTransfer.files[0]);
        }
    });

    function handleSelectedFile(file) {
        if (!file.name.toLowerCase().endsWith(".csv")) {
            alert("CSV 파일만 업로드할 수 있습니다.");
            logEvent("ERROR", `잘못된 파일 확장자: ${file.name}`);
            return;
        }
        currentFile = file;
        selectedFileName.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        inspectBtn.disabled = false;
        logEvent("UPLOAD", `파일 선택 (파일명: ${file.name}, 크기: ${file.size} bytes)`);
    }

    // 샘플 데이터 불러오기 버튼
    loadSampleBtn.addEventListener("click", () => {
        currentFile = null;
        selectedFileName.textContent = "World Bank 인터넷 보급률 샘플 (서버 data 폴더 내장)";
        inspectBtn.disabled = false;
        logEvent("UPLOAD", "서버 내장 World Bank 샘플 데이터 지정");
    });

    // ==========================================
    // 2단계: 데이터 진단 실행 (/inspect)
    // ==========================================
    inspectBtn.addEventListener("click", async () => {
        inspectBtn.disabled = true;
        inspectBtn.innerHTML = "<span>⏳ 정밀 진단 중...</span>";
        logEvent("INSPECT", "진단 요청 시작 (POST /inspect)");

        const formData = new FormData();
        if (currentFile) {
            formData.append("file", currentFile);
        }

        try {
            const res = await fetch("/inspect", {
                method: "POST",
                body: formData
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "진단 처리 중 오류 발생");
            }

            inspectionData = data;
            const h = data.header_info;
            const q = data.quality_report;
            const y = data.year_coverage;
            const a = data.aggregate_detection;

            logEvent("INSPECT", `응답 수신 (행 수: ${h.total_rows}, 열 수: ${h.total_columns}, 경고 수: ${data.warnings.length})`);

            // 대시보드 메트릭 채우기
            encodingVal.textContent = data.file_info.encoding.toUpperCase();
            skippedVal.textContent = `상단 ${h.skipped_rows}줄 건너뜀`;

            dimensionVal.textContent = `${h.total_rows}행 × ${h.total_columns}열`;
            missingRateVal.textContent = `${q.missing_rate_pct}%`;
            duplicateVal.textContent = `중복행 ${q.duplicate_rows}개`;

            recYearVal.textContent = `${y.recommended_year || 'N/A'}년`;
            aggCountVal.textContent = `집계행 ${a.aggregate_count}개 감지`;

            // 경고 표시
            if (data.warnings && data.warnings.length > 0) {
                warningsList.innerHTML = data.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("");
                warningsAlert.style.display = "block";
            } else {
                warningsAlert.style.display = "none";
            }

            // 미리보기 테이블 채우기
            renderPreviewTable(data.preview_rows);

            // 기본 기준연도 폼에 자동 입력
            if (y.recommended_year) {
                refPeriodInput.value = y.recommended_year;
            }

            inspectSection.style.display = "block";
            nlpQuerySection.style.display = "block";
            runSection.style.display = "block";
            inspectSection.scrollIntoView({ behavior: "smooth" });

        } catch (e) {
            alert(`진단 오류: ${e.message}`);
            logEvent("ERROR", `진단 실패: ${e.message}`);
        } finally {
            inspectBtn.disabled = false;
            inspectBtn.innerHTML = "<span>🔍 데이터 정밀 진단 시작</span>";
        }
    });

    function renderPreviewTable(rows) {
        if (!rows || rows.length === 0) return;
        const columns = Object.keys(rows[0]);
        previewThead.innerHTML = `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
        previewTbody.innerHTML = rows.map(r => {
            return `<tr>${columns.map(c => `<td>${escapeHtml(r[c] !== null ? r[c] : "")}</td>`).join("")}</tr>`;
        }).join("");
    }

    togglePreviewBtn.addEventListener("click", () => {
        const isHidden = previewTableContainer.style.display === "none";
        previewTableContainer.style.display = isHidden ? "block" : "none";
        document.getElementById("previewToggleIcon").textContent = isHidden ? "▲" : "▼";
    });

    // ==========================================
    // 3단계: 자연어 질문 분석 (POST /query)
    // ==========================================
    async function executeNlpQuery(queryText) {
        const text = (queryText || nlpQueryInput.value).trim();
        if (!text) {
            alert("질문 내용을 입력해주세요.");
            nlpQueryInput.focus();
            return;
        }

        nlpQueryInput.value = text;
        sendNlpQueryBtn.disabled = true;
        nlpLoading.style.display = "block";
        nlpAnswerBox.style.display = "none";
        logEvent("NLP_QUERY", `자연어 질문 실행: "${text}"`);

        try {
            const res = await fetch("/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: text })
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "자연어 질문 분석 중 오류가 발생했습니다.");
            }

            lastNlpResult = data;
            logEvent("NLP_QUERY", `답변 생성 완료 (도구: ${data.tool})`);

            // 답변 및 뱃지 표시
            nlpMatchedToolBadge.textContent = `실행 도구: ${data.tool}`;
            nlpAnswerContent.innerHTML = marked.parse(data.answer);
            nlpAnswerBox.style.display = "block";

            // 답변 영역으로 스크롤
            nlpAnswerBox.scrollIntoView({ behavior: "smooth", block: "nearest" });

        } catch (e) {
            alert(`질의 분석 오류: ${e.message}`);
            logEvent("ERROR", `자연어 질의 실패: ${e.message}`);
        } finally {
            sendNlpQueryBtn.disabled = false;
            nlpLoading.style.display = "none";
        }
    }

    sendNlpQueryBtn.addEventListener("click", () => executeNlpQuery());

    nlpQueryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            executeNlpQuery();
        }
    });

    // 추천 질문 칩 클릭 이벤트 위임
    if (nlpExampleChips) {
        nlpExampleChips.addEventListener("click", (e) => {
            const chip = e.target.closest(".chip-btn");
            if (chip && chip.dataset.query) {
                executeNlpQuery(chip.dataset.query);
            }
        });
    }

    // 시각화 차트 보기 버튼 클릭 시 결과 섹션으로 연동
    nlpVisualizeBtn.addEventListener("click", () => {
        if (!lastNlpResult || !lastNlpResult.calculation_result) {
            alert("먼저 자연어 질문을 실행해주세요.");
            return;
        }

        const calc = lastNlpResult.calculation_result;
        lastCalculationResult = calc;
        logEvent("VISUALIZE", `자연어 질문 기반 차트 시각화 활성화 (도구: ${calc.tool})`);

        // 메타 배너 갱신
        metaTool.textContent = `도구: ${calc.tool}`;
        metaRef.textContent = `기준시점: ${calc.reference_period || 'N/A'}`;
        metaRowsUsed.textContent = `사용 관측치: ${calc.rows_used || '-'}개`;
        metaRowsExcluded.textContent = `제외 행: ${calc.rows_excluded || '0'}개 (${calc.exclusion_reasons || '없음'})`;
        cautionText.textContent = calc.caution || "없음";

        // 차트 및 테이블 렌더링
        renderChart(calc);
        renderCalcTable(calc);

        // 결과 및 AI 설명 섹션 활성화
        resultSection.style.display = "block";
        explainSection.style.display = "block";
        resultSection.scrollIntoView({ behavior: "smooth" });
    });

    // ==========================================
    // 4단계: AI 추천 분석 (/suggest)
    // ==========================================
    requestSuggestBtn.addEventListener("click", async () => {
        if (!inspectionData) return;
        requestSuggestBtn.disabled = true;
        requestSuggestBtn.innerHTML = "<span>🤖 Gemini AI 추천 생성 중...</span>";
        logEvent("SUGGEST", "제안 요청 시작 (POST /suggest)");

        try {
            const res = await fetch("/suggest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ summary: inspectionData })
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "추천 생성 오류");
            }

            logEvent("SUGGEST", `응답 수신 (제안 개수: ${data.count}개)`);
            renderSuggestions(data.suggestions);

            suggestSection.style.display = "block";
            suggestSection.scrollIntoView({ behavior: "smooth" });

        } catch (e) {
            alert(`추천 오류: ${e.message}`);
            logEvent("ERROR", `추천 요청 실패: ${e.message}`);
        } finally {
            requestSuggestBtn.disabled = false;
            requestSuggestBtn.innerHTML = "<span>🤖 Gemini AI에게 맞춤 분석 추천받기</span>";
        }
    });

    function renderSuggestions(suggestions) {
        suggestionsContainer.innerHTML = "";
        suggestions.forEach((sugg, idx) => {
            const card = document.createElement("div");
            card.className = "suggestion-card";
            card.innerHTML = `
                <div>
                    <span class="sugg-tool-tag">${escapeHtml(sugg.tool)}</span>
                    <p class="sugg-why"><strong>💡 추천 이유:</strong> ${escapeHtml(sugg.why)}</p>
                    <p class="sugg-caution"><strong>⚠️ 주의사항:</strong> ${escapeHtml(sugg.caution)}</p>
                </div>
                <button class="btn btn-primary run-sugg-btn" data-index="${idx}">
                    <span>이 분석 바로 실행</span>
                </button>
            `;

            card.querySelector(".run-sugg-btn").addEventListener("click", () => {
                executeSpecificSuggestion(sugg);
            });

            suggestionsContainer.appendChild(card);
        });
    }

    function executeSpecificSuggestion(sugg) {
        toolSelect.value = sugg.tool;
        if (sugg.params) {
            if (sugg.params.reference_period) {
                refPeriodInput.value = sugg.params.reference_period;
            }
            if (sugg.params.target_country || sugg.params.item) {
                targetCountryInput.value = sugg.params.target_country || sugg.params.item;
            }
        }
        executeRun();
    }

    // ==========================================
    // 4단계: 도구 실행 (/run)
    // ==========================================
    executeRunBtn.addEventListener("click", () => executeRun());

    async function executeRun() {
        const toolName = toolSelect.value;
        const refPeriod = refPeriodInput.value.trim();
        const targetItem = targetCountryInput.value.trim() || "Korea, Rep.";
        const excludeAgg = excludeAggCheckbox.checked;

        logEvent("RUN", `도구 실행 시작 (도구명: ${toolName}, 기준시점: ${refPeriod || '없음'})`);
        executeRunBtn.disabled = true;
        executeRunBtn.innerHTML = "<span>⏳ 계산 중...</span>";

        const params = {
            reference_period: refPeriod,
            exclude_aggregates: excludeAgg,
            item: targetItem,
            n: 10
        };

        try {
            const res = await fetch("/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tool: toolName,
                    params: params
                })
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "계산 오류 발생");
            }

            lastCalculationResult = data;
            logEvent("RUN", `결과 수신 (사용 행 수: ${data.rows_used}, 제외 행 수: ${data.rows_excluded})`);

            // 메타 배너 업데이트
            metaTool.textContent = `도구: ${data.tool}`;
            metaRef.textContent = `기준시점: ${data.reference_period || 'N/A'}`;
            metaRowsUsed.textContent = `사용 관측치: ${data.rows_used}개`;
            metaRowsExcluded.textContent = `제외 행: ${data.rows_excluded}개 (${data.exclusion_reasons})`;
            cautionText.textContent = data.caution || "없음";

            // 시각화 차트 렌더링
            renderChart(data);

            // 결과 표 렌더링
            renderCalcTable(data);

            resultSection.style.display = "block";
            explainSection.style.display = "block";
            resultSection.scrollIntoView({ behavior: "smooth" });

        } catch (e) {
            alert(`실행 오류: ${e.message}`);
            logEvent("ERROR", `도구 실행 실패: ${e.message}`);
        } finally {
            executeRunBtn.disabled = false;
            executeRunBtn.innerHTML = "<span>▶ Pandas 계산 실행</span>";
        }
    }

    // ==========================================
    // Chart.js 시각화 렌더러
    // ==========================================
    function renderChart(data) {
        if (activeChartInstance) {
            activeChartInstance.destroy();
            activeChartInstance = null;
        }

        const ctx = resultChartCanvas.getContext("2d");
        const tool = data.tool;
        const res = data.result;

        let chartType = "bar";
        let chartData = { labels: [], datasets: [] };
        let chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "top" }
            }
        };

        const chartWrapper = document.getElementById("chartWrapper");
        if (chartWrapper && tool !== "top_bottom_n") {
            chartWrapper.style.height = "400px";
        }

        const chartPlugins = [];

        if (tool === "top_bottom_n") {
            chartType = "bar";
            chartOptions.indexAxis = "y"; // 수평 막대

            const topItems = (res.top_n || []).filter(item => !item.is_target);
            const targetItems = (res.top_n || []).filter(item => item.is_target);
            const bottomItems = (res.bottom_n || []).filter(item => !item.is_target);
            const allItems = [...topItems, ...targetItems, ...bottomItems];

            // 21개 국가가 잘리지 않고 각 행마다 충분한 높이(32px)를 갖도록 동적 확장
            const dynamicHeight = Math.max(480, allItems.length * 32 + 80);
            if (chartWrapper) {
                chartWrapper.style.height = `${dynamicHeight}px`;
            }

            // 라벨 포맷: 순위 및 구분([상위 N위], [순위] 비교국가, [하위 N위]) 명시
            chartData.labels = allItems.map(item => {
                if (item.is_target) {
                    return `⭐ [${item.rank || '-'}위] ${item.label}`;
                }
                if (topItems.includes(item)) {
                    return `[상위 ${item.rank}위] ${item.label}`;
                }
                return `[하위 ${item.rank}위] ${item.label}`;
            });

            // 비교 대상 국가들의 이름 추출 (예: "미국", "대한민국", "일본" 등)
            let targetLegendLabel = "비교 대상 국가";
            if (targetItems.length > 0) {
                const names = targetItems.map(t => {
                    const match = t.label.match(/\((.*?)\s*📍?\)/);
                    return match ? match[1].replace('📍', '').trim() : t.label;
                });
                targetLegendLabel = `비교 대상 국가 (${names.join(', ')})`;
            }

            // 3개 데이터셋 분리 (상위 Top 국가 / 비교 대상 / 하위 Bottom 국가)
            chartData.datasets = [
                {
                    label: `상위 Top 국가 (1~${topItems.length}위)`,
                    data: allItems.map(item => topItems.includes(item) ? item.value : null),
                    backgroundColor: "#2563eb",
                    borderColor: "#1d4ed8",
                    borderWidth: 1,
                    borderRadius: 4
                },
                {
                    label: targetLegendLabel,
                    data: allItems.map(item => item.is_target ? item.value : null),
                    backgroundColor: "#f59e0b",
                    borderColor: "#d97706",
                    borderWidth: 2,
                    borderRadius: 4
                },
                {
                    label: `하위 Bottom 국가 (하위 1~${bottomItems.length}위)`,
                    data: allItems.map(item => bottomItems.includes(item) ? item.value : null),
                    backgroundColor: "#ef4444",
                    borderColor: "#dc2626",
                    borderWidth: 1,
                    borderRadius: 4
                }
            ];

            chartOptions.scales = {
                x: {
                    stacked: true,
                    beginAtZero: true,
                    max: 108,
                    title: {
                        display: true,
                        text: "인터넷 이용률 (%)",
                        font: { size: 12, weight: "bold" }
                    },
                    ticks: {
                        callback: (val) => val + "%"
                    },
                    grid: {
                        color: "#f1f5f9"
                    }
                },
                y: {
                    stacked: true,
                    ticks: {
                        autoSkip: false, // 모든 국가 절대 생략 없이 100% 온전하게 표시!
                        font: (ctx) => {
                            const isTarget = allItems[ctx.index] && allItems[ctx.index].is_target;
                            return {
                                size: isTarget ? 13 : 11,
                                weight: isTarget ? "bold" : "normal"
                            };
                        },
                        color: (ctx) => {
                            const isTarget = allItems[ctx.index] && allItems[ctx.index].is_target;
                            return isTarget ? "#b45309" : "#334155";
                        }
                    },
                    grid: {
                        display: false
                    }
                }
            };

            chartOptions.plugins = {
                legend: {
                    display: true,
                    position: "top",
                    labels: {
                        usePointStyle: true,
                        boxWidth: 10,
                        font: { size: 12, weight: "bold" },
                        padding: 14
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            if (ctx.raw === null || ctx.raw === undefined) return null;
                            return ` ${ctx.dataset.label}: ${ctx.raw}%`;
                        }
                    }
                }
            };

            // 차트 막대 우측에 정확한 백분율 수치 직접 표기 플러그인
            chartPlugins.push({
                id: "valueLabels",
                afterDatasetsDraw(chart) {
                    const c = chart.ctx;
                    c.save();
                    chart.data.datasets.forEach((dataset, datasetIdx) => {
                        const meta = chart.getDatasetMeta(datasetIdx);
                        meta.data.forEach((bar, index) => {
                            const val = dataset.data[index];
                            if (val !== null && val !== undefined) {
                                c.font = datasetIdx === 1 ? "bold 12px Pretendard, sans-serif" : "bold 11px Pretendard, sans-serif";
                                c.fillStyle = datasetIdx === 1 ? "#b45309" : (datasetIdx === 0 ? "#1e40af" : "#991b1b");
                                c.textAlign = "left";
                                c.textBaseline = "middle";
                                c.fillText(`${Number(val).toFixed(2)}%`, bar.x + 6, bar.y);
                            }
                        });
                    });
                    c.restore();
                }
            });

        } else if (tool === "trend_line") {
            chartType = "line";
            const seriesList = res.series || [];
            const years = seriesList.length > 0 ? seriesList[0].points.map(p => p.year) : [];
            const colors = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

            chartData.labels = years;
            chartData.datasets = seriesList.map((s, idx) => ({
                label: s.label,
                data: s.points.map(p => p.value),
                borderColor: colors[idx % colors.length],
                backgroundColor: colors[idx % colors.length],
                fill: false,
                tension: 0.2
            }));

        } else if (tool === "compare_one_vs_all") {
            chartType = "bar";
            const bars = res.chart_bars || [];
            chartData.labels = bars.map(b => b.label);
            chartData.datasets = [{
                label: "비교 수치 (%)",
                data: bars.map(b => b.value),
                backgroundColor: bars.map(b => b.is_target ? "#2563eb" : "#94a3b8")
            }];

        } else if (tool === "group_summary") {
            chartType = "bar";
            const groups = res.groups || [];
            chartData.labels = groups.map(g => g.group);
            chartData.datasets = [
                {
                    label: "그룹 평균 (%)",
                    data: groups.map(g => g.mean),
                    backgroundColor: "#2563eb"
                },
                {
                    label: "그룹 중앙값 (%)",
                    data: groups.map(g => g.median),
                    backgroundColor: "#10b981"
                }
            ];

        } else if (tool === "change_rate") {
            chartType = "bar";
            const topInc = res.top_increases || [];
            chartData.labels = topInc.map(item => item.label);
            chartData.datasets = [{
                label: `10년간 변화량 (%p)`,
                data: topInc.map(item => item.diff_pct_points),
                backgroundColor: "#10b981"
            }];

        } else if (tool === "distribution") {
            chartType = "bar";
            const intervals = res.intervals || [];
            chartData.labels = intervals.map(intv => intv.label);
            chartData.datasets = [{
                label: "국가 수 (빈도)",
                data: intervals.map(intv => intv.count),
                backgroundColor: "#8b5cf6"
            }];

        } else if (tool === "correlation_scatter") {
            chartType = "scatter";
            const points = (res.points || []).map(p => ({ x: p.x, y: p.y }));
            chartData.datasets = [{
                label: `${res.x_column} vs ${res.y_column} 산점도 (r = ${res.correlation_coefficient})`,
                data: points,
                backgroundColor: "#2563eb"
            }];
            chartOptions.scales = {
                x: { title: { display: true, text: `${res.x_column}년 보급률 (%)` } },
                y: { title: { display: true, text: `${res.y_column}년 보급률 (%)` } }
            };

        } else {
            // 기본 수치 요약
            chartType = "bar";
            chartData.labels = ["평균", "중앙값", "최소", "최대"];
            chartData.datasets = [{
                label: "기초 통계",
                data: [res.mean || 0, res.median || 0, res.min || 0, res.max || 0],
                backgroundColor: "#2563eb"
            }];
        }

        activeChartInstance = new Chart(ctx, {
            type: chartType,
            data: chartData,
            options: chartOptions,
            plugins: chartPlugins
        });

        logEvent("CHART", `차트 렌더 완료 (종류: ${chartType}, 도구: ${tool})`);
    }

    function renderCalcTable(data) {
        const res = data.result;
        calcThead.innerHTML = "";
        calcTbody.innerHTML = "";

        if (res.top_n || res.bottom_n) {
            calcThead.innerHTML = `<tr><th>구분</th><th>순위</th><th>국가/지역</th><th>인터넷 사용률 (%)</th></tr>`;
            let rowsHtml = "";
            if (res.top_n) {
                rowsHtml += res.top_n.map(item => {
                    const rowStyle = item.is_target ? ' style="background-color: #fef3c7; font-weight: bold;"' : '';
                    const badge = item.is_target ? ' <span style="background:#f59e0b; color:#ffffff; font-size:11px; padding:2px 6px; border-radius:4px; margin-left:6px;">📍 비교대상</span>' : '';
                    const catLabel = item.is_target ? '⭐ 비교 대상' : '상위 Top';
                    return `<tr${rowStyle}><td>${catLabel}</td><td>${item.rank || '-'}</td><td>${escapeHtml(item.label)}${badge}</td><td>${item.value}%</td></tr>`;
                }).join("");
            }
            if (res.bottom_n) {
                rowsHtml += res.bottom_n.map(item => {
                    const rowStyle = item.is_target ? ' style="background-color: #fef3c7; font-weight: bold;"' : '';
                    const badge = item.is_target ? ' <span style="background:#f59e0b; color:#ffffff; font-size:11px; padding:2px 6px; border-radius:4px; margin-left:6px;">📍 비교대상</span>' : '';
                    const catLabel = item.is_target ? '⭐ 비교 대상' : '하위 Bottom';
                    return `<tr${rowStyle}><td>${catLabel}</td><td>${item.rank || '-'}</td><td>${escapeHtml(item.label)}${badge}</td><td>${item.value}%</td></tr>`;
                }).join("");
            }
            calcTbody.innerHTML = rowsHtml;
        } else if (res.chart_bars) {
            calcThead.innerHTML = `<tr><th>비교 대상</th><th>수치 (%)</th><th>구분</th></tr>`;
            calcTbody.innerHTML = res.chart_bars.map(b => {
                const rowStyle = b.is_target ? ' style="background-color: #fef3c7; font-weight: bold;"' : '';
                return `<tr${rowStyle}><td>${escapeHtml(b.label)}</td><td>${b.value}%</td><td>${b.is_target ? '타깃 국가' : '기준치'}</td></tr>`;
            }).join("");
        } else if (res.groups) {
            calcThead.innerHTML = `<tr><th>그룹명</th><th>포함 국가 수</th><th>평균 (%)</th><th>중앙값 (%)</th><th>최소</th><th>최대</th></tr>`;
            calcTbody.innerHTML = res.groups.map(g => `<tr><td>${escapeHtml(g.group)}</td><td>${g.count}</td><td>${g.mean}%</td><td>${g.median}%</td><td>${g.min}%</td><td>${g.max}%</td></tr>`).join("");
        } else if (res.intervals) {
            calcThead.innerHTML = `<tr><th>구간</th><th>국가 수</th><th>비율 (%)</th></tr>`;
            calcTbody.innerHTML = res.intervals.map(i => `<tr><td>${escapeHtml(i.label)}</td><td>${i.count}개</td><td>${i.percentage}%</td></tr>`).join("");
        } else {
            calcThead.innerHTML = `<tr><th>항목</th><th>값</th></tr>`;
            const rows = Object.entries(res).filter(([k, v]) => typeof v !== "object").map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join("");
            calcTbody.innerHTML = rows;
        }
    }

    scrollToExplainBtn.addEventListener("click", () => {
        explainSection.scrollIntoView({ behavior: "smooth" });
    });

    // ==========================================
    // 6단계: AI 해설 보고서 (/explain)
    // ==========================================
    tabModeB.addEventListener("click", () => {
        currentExplainMode = "B";
        tabModeB.classList.add("active");
        tabModeA.classList.remove("active");
        modeDescText.textContent = "모드 B (정식): Pandas가 계산한 숫자만 사용하여 절대 추정/환각하지 않고 7개 섹션으로 객관적 서술.";
    });

    tabModeA.addEventListener("click", () => {
        currentExplainMode = "A";
        tabModeA.classList.add("active");
        tabModeB.classList.remove("active");
        modeDescText.textContent = "모드 A (비교용 허술한 모드): Pandas 계산 결과 없이 단순 메타데이터만 전달하여 일반 AI처럼 임의 추정 작성.";
    });

    generateExplainBtn.addEventListener("click", async () => {
        if (!lastCalculationResult) {
            alert("먼저 4단계 또는 3단계에서 분석을 한 번 실행해주세요.");
            return;
        }

        generateExplainBtn.disabled = true;
        explainLoading.style.display = "block";
        reportContainer.style.display = "none";
        logEvent("EXPLAIN", `해석 요청 시작 (모드: ${currentExplainMode}, 도구: ${lastCalculationResult.tool})`);

        try {
            const res = await fetch("/explain", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mode: currentExplainMode,
                    tool: lastCalculationResult.tool,
                    calculation_result: lastCalculationResult,
                    inspection_summary: inspectionData
                })
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "보고서 생성 실패");
            }

            logEvent("EXPLAIN", `응답 수신 (모드: ${data.mode})`);

            // Marked.js 마크다운 렌더링
            reportContainer.innerHTML = marked.parse(data.explanation);
            reportContainer.style.display = "block";
            latestReportText = data.explanation;

            // 후속 질문 대화창 표시 및 추천 말풍선 칩 렌더링
            followupBox.style.display = "block";
            renderSuggestedChips(lastCalculationResult.tool, lastCalculationResult.result);

            reportContainer.scrollIntoView({ behavior: "smooth" });

        } catch (e) {
            alert(`보고서 오류: ${e.message}`);
            logEvent("ERROR", `보고서 생성 실패: ${e.message}`);
        } finally {
            generateExplainBtn.disabled = false;
            explainLoading.style.display = "none";
        }
    });

    // ==========================================
    // 7단계: 후속 질문 대화창 & 말풍선 칩 로직
    // ==========================================
    const followupBox = document.getElementById("followupBox");
    const chipsContainer = document.getElementById("chipsContainer");
    const chatMessages = document.getElementById("chatMessages");
    const chatEmptyHint = document.getElementById("chatEmptyHint");
    const followupInput = document.getElementById("followupInput");
    const sendFollowupBtn = document.getElementById("sendFollowupBtn");

    let latestReportText = "";
    let chatHistory = [];

    function renderSuggestedChips(tool, result) {
        chipsContainer.innerHTML = "";

        // 필수 포함 질문: "중학생도 이해할 수 있게 쉽게 설명해줘"
        const mandatoryQuestion = "중학생도 이해할 수 있게 쉽게 설명해줘";

        // 결과 및 도구에 맞춘 추천 질문 목록
        const toolQuestions = [];
        if (tool === "top_bottom_n") {
            toolQuestions.push("1위와 꼴찌의 격차가 왜 이렇게 큰지 쉽게 설명해줘");
            toolQuestions.push("여기서 가장 의외이거나 주목할 만한 나라는 어디야?");
        } else if (tool === "trend_line") {
            toolQuestions.push("어느 시점에 가장 급격하게 증가했는지 쉽게 설명해줘");
            toolQuestions.push("앞으로 향후 5년 뒤는 어떻게 변화할지 전망해줘");
        } else if (tool === "compare_one_vs_all") {
            toolQuestions.push("한국의 순위가 갖는 의미를 쉽게 설명해줘");
            toolQuestions.push("상위권 나라들과 한국의 차이점은 뭐야?");
        } else if (tool === "correlation_scatter") {
            toolQuestions.push("상관계수가 높은 게 왜 인과관계가 아닌지 쉽게 설명해줘");
            toolQuestions.push("이 산점도 점들이 현실에서 뜻하는 바를 쉽게 설명해줘");
        } else if (tool === "change_rate") {
            toolQuestions.push("지난 10년 동안 가장 빠르게 성장한 나라와 그 이유를 쉽게 설명해줘");
        } else if (tool === "group_summary") {
            toolQuestions.push("소득 그룹별 격차가 발생하는 이유를 쉽게 설명해줘");
        } else if (tool === "distribution") {
            toolQuestions.push("대부분의 나라가 어느 구간에 몰려있는지 쉽게 설명해줘");
        }

        // 공통 유용한 질문
        toolQuestions.push("이 통계 결과를 한 문장으로 핵심 요약해줘");
        toolQuestions.push("이 데이터를 바탕으로 어떤 정책이나 행동 결정을 내릴 수 있어?");

        const allChips = [
            { text: mandatoryQuestion, isHighlight: true, icon: "💡" },
            ...toolQuestions.map(q => ({ text: q, isHighlight: false, icon: "💬" }))
        ];

        allChips.forEach(chip => {
            const btn = document.createElement("button");
            btn.className = `chip-btn ${chip.isHighlight ? 'highlight-chip' : ''}`;
            btn.innerHTML = `<span>${chip.icon}</span> <span>${escapeHtml(chip.text)}</span>`;
            btn.addEventListener("click", () => {
                followupInput.value = chip.text;
                sendFollowup(chip.text);
            });
            chipsContainer.appendChild(btn);
        });
    }

    async function sendFollowup(questionText) {
        const text = questionText || followupInput.value.trim();
        if (!text) return;

        followupInput.value = "";
        if (chatEmptyHint) chatEmptyHint.style.display = "none";

        // 사용자 말풍선 추가
        appendChatMessage("user", text);
        chatHistory.push({ role: "user", content: text });

        // AI 로딩 버블 추가
        const loadingBubble = appendChatMessage("assistant", "🤔 분석 결과를 검토하여 답변을 작성하고 있습니다...", true);

        sendFollowupBtn.disabled = true;
        logEvent("EXPLAIN", `후속 질문 전송: "${text}"`);

        try {
            const res = await fetch("/followup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: text,
                    mode: currentExplainMode,
                    tool: lastCalculationResult ? lastCalculationResult.tool : "",
                    current_explanation: latestReportText,
                    calculation_result: lastCalculationResult,
                    history: chatHistory
                })
            });
            const data = await res.json();

            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "답변 생성 실패");
            }

            loadingBubble.innerHTML = marked.parse(data.answer);
            chatHistory.push({ role: "assistant", content: data.answer });
            logEvent("EXPLAIN", "후속 답변 수신 완료");

        } catch (e) {
            loadingBubble.innerHTML = `<span style="color:#ef4444;">⚠️ 오류: ${escapeHtml(e.message)}</span>`;
            logEvent("ERROR", `후속 질문 실패: ${e.message}`);
        } finally {
            sendFollowupBtn.disabled = false;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    function appendChatMessage(role, content, isLoading = false) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `chat-message ${role}`;

        const senderLabel = document.createElement("div");
        senderLabel.className = "chat-sender-label";
        senderLabel.textContent = role === "user" ? "나의 질문" : "AI 데이터 분석가";

        const bubbleDiv = document.createElement("div");
        bubbleDiv.className = `chat-bubble ${role}`;
        if (isLoading) {
            bubbleDiv.innerHTML = `<span style="color:#64748b;">${escapeHtml(content)}</span>`;
        } else if (role === "user") {
            bubbleDiv.textContent = content;
        } else {
            bubbleDiv.innerHTML = marked.parse(content);
        }

        msgDiv.appendChild(senderLabel);
        msgDiv.appendChild(bubbleDiv);
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return bubbleDiv;
    }

    sendFollowupBtn.addEventListener("click", () => sendFollowup());
    followupInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            sendFollowup();
        }
    });

    // 로그 콘솔 접기 토글
    toggleLogBtn.addEventListener("click", () => {
        const isHidden = logBody.style.display === "none";
        logBody.style.display = isHidden ? "block" : "none";
        document.getElementById("logToggleIcon").textContent = isHidden ? "▼" : "▲";
    });
});

