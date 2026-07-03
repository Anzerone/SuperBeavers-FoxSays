const API = "/api/v1";

const state = {
  nodes: [],
  edges: [],
  ingestLimit: 2000,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  return response.json();
}

function bindTabs() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      $$(".view").forEach((panel) => {
        panel.classList.toggle("is-visible", panel.dataset.panel === button.dataset.view);
      });
      if (button.dataset.view === "gaps") loadGaps();
      if (button.dataset.view === "admin") loadStatus();
    });
  });
}

function geographyLabel(value) {
  return {
    world: "мировая практика",
    foreign: "мировая практика",
    ru: "Россия",
    russia: "Россия",
    domestic: "Россия",
    all: "все",
    unknown: "не определено",
  }[value] || value;
}

function renderIntent(intent) {
  const groups = [
    ["материалы", intent.materials],
    ["процессы", intent.processes],
    ["свойства", intent.properties],
    ["условия", intent.conditions],
    ["география", intent.geography ? [geographyLabel(intent.geography)] : []],
    ["диапазоны", intent.numeric_constraints],
  ];
  $("#intentChips").innerHTML = groups
    .filter(([, values]) => values && values.length)
    .flatMap(([key, values]) => values.map((value) => `<span class="chip"><strong>${key}</strong>${value}</span>`))
    .join("") || `<span class="chip"><strong>статус</strong>нужны уточнения</span>`;
}

function renderEvidence(items) {
  $("#evidenceRow").innerHTML = items
    .slice(0, 3)
    .map((item) => `<div class="evidence"><strong>${item.title}</strong><span>${item.snippet} · ${item.confidence}</span></div>`)
    .join("");
}

function renderFacts(items) {
  $("#factsTable").innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.topic}</td>
          <td>${item.condition}</td>
          <td>${item.conclusion}</td>
          <td>${item.source}</td>
          <td>${item.confidence}</td>
        </tr>
      `
    )
    .join("");
}

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function shortLabel(value, limit = 46) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function wrapLabel(value, limit = 22, maxLines = 2) {
  const words = shortLabel(value, limit * maxLines + 4).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    const next = line ? `${line} ${word}` : word;
    if (next.length > limit && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  });
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    kept[maxLines - 1] = `${kept[maxLines - 1].slice(0, Math.max(6, limit - 1))}…`;
    return kept;
  }
  return lines.length ? lines : ["—"];
}

function renderGraph(nodes, edges) {
  state.nodes = nodes;
  state.edges = edges;
  const svg = $("#knowledgeGraph");
  const width = 1520;
  const cardWidth = 128;
  const cardHeight = 52;
  const rowGap = 22;
  const topPad = 82;
  const coords = new Map();

  svg.setAttribute("viewBox", `0 0 ${width} 680`);

  if (!nodes.length) {
    svg.classList.add("is-empty");
    svg.innerHTML = `<text class="graph-empty" x="${width / 2}" y="220" text-anchor="middle">Подграф появится после запроса</text>`;
    return;
  }

  svg.classList.remove("is-empty");

  const typeConfig = {
    Material: { x: 32, title: "Материалы", limit: 4 },
    Process: { x: 192, title: "Процессы", limit: 4 },
    Equipment: { x: 352, title: "Оборудование", limit: 5 },
    Property: { x: 512, title: "Показатели", limit: 5 },
    Experiment: { x: 672, title: "Факты", limit: 4 },
    Conclusion: { x: 832, title: "Результаты", limit: 8 },
    Document: { x: 1018, title: "Источники", limit: 6 },
    Expert: { x: 1200, title: "Эксперты", limit: 4 },
    Facility: { x: 1360, title: "Лаборатории", limit: 4 },
    Tag: { x: 672, title: "Пробелы", limit: 5 },
  };

  const typeOrder = ["Material", "Process", "Equipment", "Property", "Experiment", "Conclusion", "Document", "Expert", "Facility", "Tag"];
  const grouped = nodes.reduce((acc, node) => {
    const key = typeConfig[node.type] ? node.type : "Experiment";
    acc[key] = acc[key] || [];
    acc[key].push(node);
    return acc;
  }, {});

  const visibleNodes = [];
  const hiddenCounts = {};
  typeOrder.forEach((type) => {
    const config = typeConfig[type];
    const items = (grouped[type] || [])
      .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
      .slice(0, config.limit);
    visibleNodes.push(...items);
    hiddenCounts[type] = Math.max(0, (grouped[type] || []).length - items.length);
  });
  const visibleIds = new Set(visibleNodes.map((node) => node.id));

  typeOrder.forEach((type) => {
    const config = typeConfig[type];
    const items = visibleNodes.filter((node) => node.type === type);
    if (!items.length) return;
    const totalHeight = items.length * cardHeight + (items.length - 1) * rowGap;
    const top = Math.max(topPad + 18, (650 - totalHeight) / 2);
    items.forEach((node, index) => {
      coords.set(node.id, { x: config.x, y: Math.round(top + index * (cardHeight + rowGap)) });
    });
  });

  const colors = {
    Material: { fill: "#d9fff5", stroke: "#00c99b" },
    Process: { fill: "#e3f8ff", stroke: "#38bde0" },
    Equipment: { fill: "#eef4ff", stroke: "#7aa5f8" },
    Property: { fill: "#fff3d8", stroke: "#f2a11d" },
    Experiment: { fill: "#f1eaff", stroke: "#7442d8" },
    Document: { fill: "#f6f8fb", stroke: "#c7d0de" },
    Conclusion: { fill: "#fff0f2", stroke: "#e94a5d" },
    Expert: { fill: "#eefbf3", stroke: "#37aa64" },
    Facility: { fill: "#f4f1ff", stroke: "#8d6ae8" },
    Tag: { fill: "#fff7d6", stroke: "#d99a00" },
  };

  const mainEdgeTypes = new Set([
    "CHAIN_MATERIAL_PROCESS",
    "USES_EQUIPMENT",
    "EQUIPMENT_RESULT",
    "MISSING_COMBINATION",
    "CONTRADICTS",
    "RELATED_FACILITY",
    "AUTHORED_OR_MENTIONED",
  ]);
  const visibleEdges = edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .sort((a, b) => Number(mainEdgeTypes.has(b.type)) - Number(mainEdgeTypes.has(a.type)))
    .slice(0, 72);
  const showEdgeLabels = visibleEdges.length <= 14;
  const edgeMarkup = visibleEdges
    .map((edge) => {
      const source = coords.get(edge.source);
      const target = coords.get(edge.target);
      if (!source || !target) return "";
      const secondary = mainEdgeTypes.has(edge.type) ? "" : " is-secondary";
      const sx = source.x + cardWidth;
      const sy = source.y + cardHeight / 2;
      const tx = target.x;
      const ty = target.y + cardHeight / 2;
      const curve = Math.max(40, Math.abs(tx - sx) * 0.42);
      const d = `M ${sx} ${sy} C ${sx + curve} ${sy}, ${tx - curve} ${ty}, ${tx} ${ty}`;
      const mx = (sx + tx) / 2;
      const my = (sy + ty) / 2;
      return `<path class="graph-link${secondary}" d="${d}"></path>${showEdgeLabels ? `<text class="edge-label" x="${mx}" y="${my - 6}" text-anchor="middle">${escapeXml(edge.label)}</text>` : ""}`;
    })
    .join("");

  const layerMarkup = typeOrder
    .filter((type) => (grouped[type] || []).length)
    .map((type) => {
      const config = typeConfig[type];
      return `
        <g class="graph-layer">
          <text x="${config.x + cardWidth / 2}" y="34" text-anchor="middle">${config.title}</text>
          ${hiddenCounts[type] ? `<text class="graph-layer-more" x="${config.x + cardWidth / 2}" y="56" text-anchor="middle">ещё ${hiddenCounts[type]}</text>` : ""}
        </g>
      `;
    })
    .join("");

  const nodeMarkup = visibleNodes
    .map((node) => {
      const point = coords.get(node.id);
      if (!point) return "";
      const color = colors[node.type] || colors.Experiment;
      const limit = node.type === "Document" || node.type === "Conclusion" ? 19 : 18;
      const lines = wrapLabel(node.label, limit, 2);
      return `
        <g class="graph-node ${node.type.toLowerCase()}">
          <rect x="${point.x}" y="${point.y}" width="${cardWidth}" height="${cardHeight}" rx="8" fill="${color.fill}" stroke="${color.stroke}"></rect>
          <text x="${point.x + 12}" y="${point.y + 21}">
            ${lines.map((line, index) => `<tspan x="${point.x + 12}" dy="${index ? 15 : 0}">${escapeXml(line)}</tspan>`).join("")}
          </text>
          <title>${escapeXml(node.label)}</title>
        </g>
      `;
    })
    .join("");

  const legend = `
    <g class="graph-legend">
      <text x="24" y="650">Показаны самые релевантные узлы. Второстепенные связи приглушены, полный текст доступен при наведении.</text>
    </g>
  `;

  svg.setAttribute("viewBox", `0 0 ${width} 680`);
  svg.innerHTML = layerMarkup + edgeMarkup + nodeMarkup + legend;
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question) {
    $("#answerText").textContent = "Выберите подсказку или введите вопрос.";
    renderGraph([], []);
    return;
  }
  const payload = {
    question,
    geography: $("#geography").value,
    years: $("#years").value,
    verified_only: $("#verifiedOnly").checked,
  };
  $("#answerText").textContent = "Ищу факты, источники и связи...";
  const data = await request("/ask", { method: "POST", body: JSON.stringify(payload) });
  $("#answerText").textContent = data.answer;
  $("#metricSources").textContent = data.metrics.sources;
  $("#metricFacts").textContent = data.metrics.facts;
  $("#metricConfidence").textContent = data.metrics.confidence;
  renderIntent(data.intent);
  renderEvidence(data.evidence);
  renderFacts(data.facts);
  renderGraph(data.nodes, data.edges);
}

function bindSuggestions() {
  $$(".suggestions button").forEach((button) => {
    button.addEventListener("click", () => {
      $("#question").value = button.dataset.query;
      ask().catch((error) => {
        $("#answerText").textContent = error.message;
      });
    });
  });
}

async function loadGaps() {
  const data = await request("/gaps");
  const max = Math.max(...data.cells.map((cell) => cell.count), 1);
  const statusText = {
    covered: "изучено",
    weak: "мало данных",
    gap: "нет данных",
  };
  const totals = data.cells.reduce((acc, cell) => {
    acc[cell.status] = (acc[cell.status] || 0) + 1;
    return acc;
  }, {});
  const gapCount = totals.gap || 0;
  const weakCount = totals.weak || 0;
  const coveredCount = totals.covered || 0;
  $("#gapsSummary").textContent =
    `Матрица показывает покрытие связок «материал × процесс»: изучено ${coveredCount}, мало данных ${weakCount}, без данных ${gapCount}. ` +
    "Белые ячейки — пробелы для планирования исследований; светло-зелёные — есть 1-2 записи; насыщенные зелёные — хорошо представлены в корпусе.";
  const header = ["", ...data.cols].map((col) => `<div class="heatmap-head">${col}</div>`).join("");
  const rows = data.rows
    .map((row) => {
      const cells = data.cols
        .map((col) => data.cells.find((cell) => cell.row === row && cell.col === col))
        .map((cell) => {
          const light = cell.count === 0 ? 100 : Math.max(30, 92 - (cell.count / max) * 50);
          const color = cell.count === 0 ? "#fff" : `hsl(165 100% ${light}%)`;
          return `<div class="heatmap-cell ${cell.status}" style="background:${color}"><strong>${cell.count}</strong><span>${statusText[cell.status] || cell.status}</span></div>`;
        })
        .join("");
      return `<div class="heatmap-row-title">${row}</div>${cells}`;
    })
    .join("");
  $("#heatmap").innerHTML = header + rows;
}

async function loadStatus() {
  const status = await request("/admin/status");
  renderLoadStatus(status);
}

async function startIngest() {
  state.ingestLimit = Number($("#ingestLimit").value) || state.ingestLimit;
  const payload = {
    corpus_dir: $("#corpusDir").value,
    limit: state.ingestLimit,
    reset: false,
  };
  const scheduled = await request("/admin/load", { method: "POST", body: JSON.stringify(payload) });
  renderLoadStatus({ state: "scheduled", files_seen: 0, documents_loaded: 0, experiments_loaded: 0 });
  setTimeout(loadStatus, 1200);
}

function renderLoadStatus(status) {
  const stateLabel = {
    idle: "Ожидает запуска",
    scheduled: "Загрузка поставлена в очередь",
    running: "Идёт загрузка корпуса",
    done: "Корпус загружен",
    error: "Ошибка загрузки",
  }[status.state] || "Состояние неизвестно";
  const files = Number(status.files_seen || 0);
  const docs = Number(status.documents_loaded || 0);
  const facts = Number(status.experiments_loaded || 0);
  const limit = Math.max(Number($("#ingestLimit")?.value || state.ingestLimit || files || 1), 1);
  const pct = status.state === "done" ? 100 : Math.min(99, Math.round((files / limit) * 100));
  $("#loadProgress").style.width = `${pct}%`;
  $("#adminStatus").textContent =
    status.state === "done"
      ? `Готово: обработано ${files} файлов, найдено ${facts} фактов.`
      : `${stateLabel}: обработано ${files} из ${limit} файлов.`;
  $("#statusFiles").textContent = files;
  $("#statusDocs").textContent = docs;
  $("#statusExperiments").textContent = facts;
  if (status.state === "running" || status.state === "scheduled") {
    setTimeout(loadStatus, 1500);
  }
}

function changeLimit(delta) {
  const input = $("#ingestLimit");
  const min = Number(input.min || 1);
  const max = Number(input.max || 5000);
  const next = Math.min(max, Math.max(min, Number(input.value || 0) + delta));
  input.value = next;
  state.ingestLimit = next;
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    $("#healthStatus").textContent = data.status === "ok" ? "API online" : "API";
  } catch {
    $("#healthStatus").textContent = "API offline";
  }
}

$("#askForm").addEventListener("submit", (event) => {
  event.preventDefault();
  ask().catch((error) => {
    $("#answerText").textContent = error.message;
  });
});

$("#startIngest").addEventListener("click", () => {
  startIngest().catch((error) => {
    $("#adminStatus").textContent = error.message;
  });
});

$("#limitMinus").addEventListener("click", () => changeLimit(-10));
$("#limitPlus").addEventListener("click", () => changeLimit(10));
$("#ingestLimit").addEventListener("change", () => {
  const input = $("#ingestLimit");
  input.value = Math.min(Number(input.max || 5000), Math.max(Number(input.min || 1), Number(input.value || 1)));
  state.ingestLimit = Number(input.value);
});

bindTabs();
bindSuggestions();
checkHealth();
renderIntent({ materials: [], processes: [], properties: [], conditions: [], geography: null, numeric_constraints: [] });
renderGraph([], []);
loadStatus().catch(() => {});
