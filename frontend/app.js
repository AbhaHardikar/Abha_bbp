const batchColors = ["#4f78bd", "#9770b1", "#2d907e", "#c17d32", "#697d96"];
const operationColors = {
  Seed: "#80b79f",
  Bioreactor: "#6595d3",
  TFF: "#9b80c2",
  Spray: "#e1a451",
  Sum: "#8493a4",
};
const writeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const writeTokenStorageKey = "bbpWriteToken";

const state = {
  schedule: null,
  violationsByOperation: new Map(),
  writeToken: sessionStorage.getItem(writeTokenStorageKey) || "",
};

const elements = {
  start: document.querySelector("#schedule-start"),
  end: document.querySelector("#schedule-end"),
  gantt: document.querySelector("#gantt"),
  error: document.querySelector("#schedule-error"),
  violationList: document.querySelector("#violations-list"),
  batchLegend: document.querySelector("#batch-legend"),
  batchCount: document.querySelector("#batch-count"),
  operationCount: document.querySelector("#operation-count"),
  violationCount: document.querySelector("#violation-count"),
  dialog: document.querySelector("#operation-dialog"),
  form: document.querySelector("#operation-form"),
  dialogError: document.querySelector("#dialog-error"),
};

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function dateNumber(value) {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function daysBetween(start, end) {
  return Math.round((dateNumber(end) - dateNumber(start)) / 86_400_000);
}

function addDays(value, count) {
  const date = new Date(dateNumber(value) + count * 86_400_000);
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function displayDate(value) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  if (writeMethods.has(method) && state.writeToken) {
    headers.Authorization = `Bearer ${state.writeToken}`;
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && writeMethods.has(method)) {
      throw new Error(
        "Write access key required or invalid. Close any modal, unlock demo edits above, and retry.",
      );
    }
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return body;
}

async function loadSchedule() {
  elements.error.hidden = true;
  elements.gantt.replaceChildren(makeElement("div", "loading", "Loading schedule…"));
  const start = elements.start.value;
  const end = elements.end.value;
  try {
    if (!start || !end || start >= end) {
      throw new Error("Choose a start date earlier than the exclusive end date.");
    }
    state.schedule = await request(
      `/api/schedule?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`,
    );
    renderSchedule();
  } catch (error) {
    elements.error.textContent = error.message;
    elements.error.hidden = false;
    elements.gantt.replaceChildren(makeElement("div", "loading", "Schedule could not be loaded."));
  }
}

function buildViolationIndex(violations) {
  const index = new Map();
  for (const violation of violations) {
    for (const operationId of violation.operation_ids) {
      const current = index.get(operationId) || [];
      current.push(violation);
      index.set(operationId, current);
    }
  }
  return index;
}

function renderSchedule() {
  const schedule = state.schedule;
  state.violationsByOperation = buildViolationIndex(schedule.violations);
  elements.batchCount.textContent = String(schedule.batches.length);
  elements.operationCount.textContent = String(schedule.unit_operations.length);
  elements.violationCount.textContent = String(schedule.violations.length);
  renderLegend(schedule.batches);
  renderViolations(schedule.violations);
  renderGantt(schedule);
}

function renderLegend(batches) {
  const fragment = document.createDocumentFragment();
  batches.forEach((batch, index) => {
    const item = makeElement("span", "legend-item");
    const swatch = makeElement("span", "legend-swatch");
    swatch.style.backgroundColor = batchColors[index % batchColors.length];
    item.append(swatch, document.createTextNode(batch.name));
    fragment.append(item);
  });
  elements.batchLegend.replaceChildren(fragment);
}

function renderViolations(violations) {
  if (violations.length === 0) {
    elements.violationList.replaceChildren(
      makeElement("li", "empty-state", "No schedule violations in this date range."),
    );
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const violation of violations) {
    const item = makeElement("li", "violation-item");
    item.append(
      makeElement("span", "violation-icon", "!"),
      makeElement("span", "", violation.message),
    );
    fragment.append(item);
  }
  elements.violationList.replaceChildren(fragment);
}

function renderGantt(schedule) {
  const start = elements.start.value;
  const end = elements.end.value;
  const dayCount = daysBetween(start, end);
  const dayWidth = 78;
  const timelineWidth = dayCount * dayWidth;
  const grid = makeElement("div", "gantt-grid");
  grid.style.width = `${150 + timelineWidth}px`;

  const header = makeElement("div", "gantt-header");
  header.append(makeElement("div", "equipment-heading", "Equipment"));
  const axis = makeElement("div", "date-axis");
  axis.style.gridTemplateColumns = `repeat(${dayCount}, ${dayWidth}px)`;
  for (let day = 0; day < dayCount; day += 1) {
    axis.append(makeElement("div", "date-tick", displayDate(addDays(start, day))));
  }
  header.append(axis);
  grid.append(header);

  const body = makeElement("div", "gantt-body");
  const operationsByEquipment = new Map(
    schedule.equipment.map((item) => [item.id, []]),
  );
  for (const operation of schedule.unit_operations) {
    const lane = operationsByEquipment.get(operation.equipment_id);
    if (lane) lane.push(operation);
  }

  for (const equipment of schedule.equipment) {
    const row = makeElement("div", "gantt-row");
    const name = makeElement("div", "equipment-name");
    name.append(makeElement("span", "", equipment.name));
    const lane = makeElement("div", "lane");
    lane.style.width = `${timelineWidth}px`;
    lane.style.backgroundSize = `${dayWidth}px 100%`;

    for (const operation of operationsByEquipment.get(equipment.id) || []) {
      const block = makeElement("button", "operation-block");
      block.type = "button";
      block.style.setProperty(
        "--operation-color",
        operation.color || operationColors[operation.type] || "#4f83cc",
      );
      block.style.backgroundColor = `${operation.color || operationColors[operation.type] || "#4f83cc"}24`;
      const left = Math.max(0, daysBetween(start, operation.start_date)) * dayWidth;
      const right = Math.min(dayCount, daysBetween(start, operation.end_date)) * dayWidth;
      block.style.left = `${left + 3}px`;
      block.style.width = `${Math.max(48, right - left - 6)}px`;
      block.classList.add(`status-${operation.status}`);
      const violations = state.violationsByOperation.get(operation.id) || [];
      if (violations.length > 0) {
        block.classList.add("is-violating");
        block.title = violations.map((item) => item.message).join("\n");
        block.setAttribute("aria-label", `${operation.name}. Violation: ${block.title}`);
      } else {
        block.title = `${operation.name} · ${operation.status}`;
        block.setAttribute("aria-label", `${operation.name}, ${operation.status}`);
      }
      block.append(
        makeElement("strong", "", operation.name),
        makeElement("span", "", `${operation.type} · ${displayDate(operation.start_date)} – ${displayDate(operation.end_date)}`),
      );
      block.addEventListener("click", () => openOperation(operation));
      lane.append(block);
    }

    row.append(name, lane);
    body.append(row);
  }

  const envelopes = makeElement("div", "batch-envelope-layer");
  envelopes.style.width = `${timelineWidth}px`;
  const operationsByBatch = new Map();
  for (const operation of schedule.unit_operations) {
    const current = operationsByBatch.get(operation.batch_id) || [];
    current.push(operation);
    operationsByBatch.set(operation.batch_id, current);
  }
  schedule.batches.forEach((batch, index) => {
    const operations = operationsByBatch.get(batch.id) || [];
    if (operations.length === 0) return;
    const startDate = operations.reduce(
      (earliest, operation) => (operation.start_date < earliest ? operation.start_date : earliest),
      operations[0].start_date,
    );
    const endDate = operations.reduce(
      (latest, operation) => (operation.end_date > latest ? operation.end_date : latest),
      operations[0].end_date,
    );
    const left = Math.max(0, daysBetween(start, startDate)) * dayWidth;
    const right = Math.min(dayCount, daysBetween(start, endDate)) * dayWidth;
    const envelope = makeElement("div", "batch-envelope");
    envelope.style.setProperty("--batch-color", batchColors[index % batchColors.length]);
    envelope.style.left = `${left + 1}px`;
    envelope.style.width = `${Math.max(4, right - left - 2)}px`;
    envelope.style.top = "3px";
    envelope.style.bottom = "3px";
    envelope.append(makeElement("span", "batch-envelope-label", batch.name));
    envelopes.append(envelope);
  });
  body.prepend(envelopes);
  grid.append(body);
  elements.gantt.replaceChildren(grid);
}

function openOperation(operation) {
  document.querySelector("#operation-id").value = String(operation.id);
  document.querySelector("#dialog-title").textContent = operation.name;
  document.querySelector("#dialog-batch").textContent =
    `${operation.batch_name} · ${operation.type}`;
  document.querySelector("#operation-start").value = operation.start_date;
  document.querySelector("#operation-end").value = operation.end_date;
  document.querySelector("#operation-status").value = operation.status;
  elements.dialogError.hidden = true;

  const equipmentSelect = document.querySelector("#operation-equipment");
  equipmentSelect.replaceChildren(
    ...state.schedule.equipment.map((equipment) => {
      const option = makeElement("option", "", equipment.name);
      option.value = String(equipment.id);
      return option;
    }),
  );
  equipmentSelect.value = String(operation.equipment_id);
  const completed = operation.status === "completed";
  document.querySelector("#operation-start").disabled = completed;
  document.querySelector("#operation-end").disabled = completed;
  equipmentSelect.disabled = completed;
  document.querySelector("#operation-status").disabled = completed;
  elements.dialog.showModal();
}

function closeDialog() {
  elements.dialog.close();
}

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
let latestControlState = null;

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function processTimeLabel(timeH) {
  if (!Number.isFinite(timeH)) return "—";
  const totalMinutes = Math.floor(timeH * 60);
  return `${Math.floor(totalMinutes / 60)}h ${String(totalMinutes % 60).padStart(2, "0")}m`;
}

function getSignal(readings, name) {
  return readings
    .filter((reading) => reading.signal_name === name)
    .sort((left, right) => left.time_h - right.time_h);
}

function drawControlChart(controlState) {
  const container = document.querySelector("#control-chart");
  const doReadings = getSignal(controlState.readings, "DO");
  const feedReadings = getSignal(controlState.readings, "feed_rate");
  if (doReadings.length === 0) {
    container.replaceChildren(
      makeElement("p", "loading", "Start the simulator to see process data."),
    );
    return;
  }

  const predictions = controlState.predictions || [];
  const width = 900;
  const height = 300;
  const plot = { left: 52, right: width - 48, top: 18, bottom: height - 34 };
  const times = [
    ...doReadings.map((reading) => reading.time_h),
    ...predictions.map((prediction) => prediction.target_time_h),
  ];
  let minTime = Math.min(...times);
  let maxTime = Math.max(...times);
  if (minTime === maxTime) maxTime = minTime + 1 / 60;
  const x = (time) => plot.left + ((time - minTime) / (maxTime - minTime)) * (plot.right - plot.left);
  const y = (value) => plot.bottom - (value / 100) * (plot.bottom - plot.top);
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "Dissolved oxygen and feed rate over process time",
  });

  for (const value of [0, 25, 50, 75, 100]) {
    const lineY = y(value);
    svg.append(
      svgElement("line", {
        x1: plot.left,
        y1: lineY,
        x2: plot.right,
        y2: lineY,
        stroke: "#e8edf3",
        "stroke-width": 1,
      }),
    );
    const label = svgElement("text", {
      x: plot.left - 10,
      y: lineY + 4,
      "text-anchor": "end",
      fill: "#78879a",
      "font-size": 10,
    });
    label.textContent = String(value);
    svg.append(label);
  }
  const leftLabel = svgElement("text", {
    x: plot.left,
    y: 11,
    fill: "#2865bf",
    "font-size": 10,
    "font-weight": 700,
  });
  leftLabel.textContent = "DO (%)";
  const rightLabel = svgElement("text", {
    x: plot.right,
    y: 11,
    fill: "#9266b5",
    "text-anchor": "end",
    "font-size": 10,
    "font-weight": 700,
  });
  rightLabel.textContent = `Feed (${controlState.limits.feed_rate.unit})`;
  svg.append(leftLabel, rightLabel);

  const doPath = doReadings
    .map((reading, index) => `${index === 0 ? "M" : "L"} ${x(reading.time_h)} ${y(reading.value)}`)
    .join(" ");
  svg.append(
    svgElement("path", {
      d: doPath,
      fill: "none",
      stroke: "#2865bf",
      "stroke-width": 2,
      "stroke-linejoin": "round",
    }),
  );

  const feedMin = controlState.limits.feed_rate.min;
  const feedMax = controlState.limits.feed_rate.max;
  const feedPath = feedReadings
    .map((reading, index) => {
      const scaledValue = ((reading.value - feedMin) / (feedMax - feedMin)) * 100;
      return `${index === 0 ? "M" : "L"} ${x(reading.time_h)} ${y(scaledValue)}`;
    })
    .join(" ");
  svg.append(
    svgElement("path", {
      d: feedPath,
      fill: "none",
      stroke: "#9266b5",
      "stroke-width": 2,
      "stroke-linejoin": "round",
    }),
  );

  if (predictions.length > 0) {
    const forecastPoints = [
      { time_h: doReadings.at(-1).time_h, value: doReadings.at(-1).value },
      ...predictions.map((prediction) => ({
        time_h: prediction.target_time_h,
        value: prediction.value,
      })),
    ];
    const forecastPath = forecastPoints
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.time_h)} ${y(point.value)}`)
      .join(" ");
    svg.append(
      svgElement("path", {
        d: forecastPath,
        fill: "none",
        stroke: "#1a9b71",
        "stroke-width": 2,
        "stroke-dasharray": "5 4",
        "stroke-linejoin": "round",
      }),
    );
  }

  for (const command of controlState.commands) {
    const markerTime =
      command.status === "rejected" || command.status === "cancelled"
        ? command.issued_at_time_h
        : command.apply_at_time_h;
    if (markerTime < minTime || markerTime > maxTime) continue;
    const markerX = x(markerTime);
    const marker = svgElement("line", {
      x1: markerX,
      y1: plot.top,
      x2: markerX,
      y2: plot.bottom,
      stroke:
        command.status === "rejected" || command.status === "cancelled"
          ? "#ce4949"
          : command.status === "applied"
            ? "#1a9b71"
            : "#d88745",
      "stroke-width": 1.5,
      "stroke-dasharray": "4 3",
    });
    const markerTitle = svgElement("title");
    markerTitle.textContent = `${command.status}: ${command.value} ${command.unit}${command.rejection_reason ? ` — ${command.rejection_reason}` : ""}`;
    marker.append(markerTitle);
    svg.append(marker);
  }

  for (let index = 0; index <= 4; index += 1) {
    const time = minTime + ((maxTime - minTime) * index) / 4;
    const label = svgElement("text", {
      x: x(time),
      y: height - 9,
      "text-anchor": index === 0 ? "start" : index === 4 ? "end" : "middle",
      fill: "#78879a",
      "font-size": 9,
    });
    label.textContent = processTimeLabel(time);
    svg.append(label);
  }
  container.replaceChildren(svg);
}

function renderCommandHistory(commands) {
  const body = document.querySelector("#command-history");
  if (commands.length === 0) {
    const row = makeElement("tr");
    const cell = makeElement("td", "empty-cell", "No commands yet.");
    cell.colSpan = 6;
    row.append(cell);
    body.replaceChildren(row);
    return;
  }
  const rows = commands
    .slice()
    .reverse()
    .map((command) => {
      const row = makeElement(
        "tr",
        command.status === "rejected" ? "command-rejected" : "",
      );
      const fields = [
        processTimeLabel(command.issued_at_time_h),
        `${command.value} ${command.unit}`,
        processTimeLabel(command.apply_at_time_h),
        command.source,
        command.status === "pending"
          ? command.source === "controller"
            ? "Proposed · pending"
            : "Pending apply"
          : command.status === "applied"
            ? "Applied"
            : command.status === "rejected"
              ? "Rejected"
              : "Cancelled",
        command.rejection_reason || "—",
      ];
      for (const value of fields) row.append(makeElement("td", "", value));
      return row;
    });
  body.replaceChildren(...rows);
}

function updateSimulatorControls(simulator) {
  const status = simulator?.status || "stopped";
  const statusLabel = document.querySelector("#simulator-status");
  statusLabel.textContent = status;
  statusLabel.className = `simulator-status ${status}`;
  document.querySelector("#simulator-start").disabled = status === "running";
  document.querySelector("#simulator-pause").disabled = status !== "running";
  document.querySelector("#simulator-resume").disabled = status !== "paused";
}

function renderControlState(controlState) {
  latestControlState = controlState;
  const latestDO = getSignal(controlState.readings, "DO").at(-1);
  const latestFeed = getSignal(controlState.readings, "feed_rate").at(-1);
  document.querySelector("#latest-do").textContent = latestDO
    ? `${latestDO.value.toFixed(1)}%`
    : "—";
  document.querySelector("#latest-feed").textContent = latestFeed
    ? `${latestFeed.value.toFixed(1)} mL/h`
    : "—";
  document.querySelector("#latest-process-time").textContent = controlState.simulator
    ? processTimeLabel(controlState.simulator.process_time_h)
    : "—";

  const feedLimit = controlState.limits.feed_rate;
  const feedInput = document.querySelector("#manual-feed-value");
  feedInput.min = String(feedLimit.min);
  feedInput.max = String(feedLimit.max);
  document.querySelector("#feed-limits-label").textContent =
    `Allowed range: ${feedLimit.min}–${feedLimit.max} ${feedLimit.unit}`;

  const controller = controlState.controller;
  document.querySelector("#controller-status").textContent = controller.configured
    ? `Configured · target ${controller.do_target_percent}% DO · dwell ${controller.dwell_minutes} process-minutes`
    : "Automatic control is inactive until a DO target and dwell time are chosen.";
  document.querySelector("#controller-target").value =
    controller.do_target_percent ?? "";
  document.querySelector("#controller-dwell").value = controller.dwell_minutes ?? "";

  updateSimulatorControls(controlState.simulator);
  drawControlChart(controlState);
  renderCommandHistory(controlState.commands);
}

async function loadControlState() {
  try {
    const controlState = await request("/api/control/state");
    renderControlState(controlState);
    document.querySelector("#control-error").hidden = true;
  } catch (error) {
    const status = document.querySelector("#control-error");
    status.textContent = error.message;
    status.hidden = false;
  }
}

async function runSimulator(action, payload = {}) {
  const error = document.querySelector("#control-error");
  error.hidden = true;
  try {
    await request(`/api/simulator/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadControlState();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
}

async function saveManualCommand(event) {
  event.preventDefault();
  const result = document.querySelector("#manual-command-result");
  const payload = {
    value: Number(document.querySelector("#manual-feed-value").value),
    unit: latestControlState?.limits.feed_rate.unit || "mL/h",
    apply_after_minutes: Number(document.querySelector("#manual-apply-delay").value),
  };
  try {
    const response = await request("/api/control/commands", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    result.className = `command-result ${response.accepted ? "accepted" : "rejected"}`;
    result.textContent = response.accepted
      ? `Command #${response.id} accepted. It will apply at ${processTimeLabel(response.apply_at_time_h)}.`
      : `Command rejected: ${response.reason}`;
    result.hidden = false;
  } catch (error) {
    result.className = "command-result rejected";
    result.textContent = error.message;
    result.hidden = false;
  } finally {
    await loadControlState();
  }
}

async function saveControllerConfig(event) {
  event.preventDefault();
  const error = document.querySelector("#control-error");
  error.hidden = true;
  try {
    await request("/api/control/config", {
      method: "PUT",
      body: JSON.stringify({
        do_target_percent: Number(document.querySelector("#controller-target").value),
        dwell_minutes: Number(document.querySelector("#controller-dwell").value),
      }),
    });
    await loadControlState();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
}

async function saveOperation(event) {
  event.preventDefault();
  const operationId = document.querySelector("#operation-id").value;
  const payload = {
    start_date: document.querySelector("#operation-start").value,
    end_date: document.querySelector("#operation-end").value,
    equipment_id: Number(document.querySelector("#operation-equipment").value),
    status: document.querySelector("#operation-status").value,
  };
  const saveButton = document.querySelector("#save-operation");
  saveButton.disabled = true;
  elements.dialogError.hidden = true;
  try {
    const result = await request(`/api/unit_operations/${operationId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    closeDialog();
    await loadSchedule();
    if (result.violations.length > 0) {
      elements.error.textContent = result.violations.map((item) => item.message).join(" ");
      elements.error.hidden = false;
    }
  } catch (error) {
    elements.dialogError.textContent = error.message;
    elements.dialogError.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
}

document.querySelector("#refresh-schedule").addEventListener("click", loadSchedule);
elements.start.addEventListener("change", loadSchedule);
elements.end.addEventListener("change", loadSchedule);
elements.form.addEventListener("submit", saveOperation);
document.querySelector("#close-dialog").addEventListener("click", closeDialog);
document.querySelector("#cancel-dialog").addEventListener("click", closeDialog);
document.querySelector("#simulator-start").addEventListener("click", () => {
  runSimulator("start", {
    run_id: document.querySelector("#simulator-run").value,
    start_minute: Number(document.querySelector("#simulator-start-minute").value),
    process_minutes_per_second: Number(document.querySelector("#simulator-speed").value),
  });
});
document.querySelector("#simulator-pause").addEventListener("click", () => {
  runSimulator("pause");
});
document.querySelector("#simulator-resume").addEventListener("click", () => {
  runSimulator("resume");
});
document.querySelector("#manual-command-form").addEventListener("submit", saveManualCommand);
document.querySelector("#controller-config-form").addEventListener("submit", saveControllerConfig);

const writeAccessForm = document.querySelector("#write-access-form");
const writeAccessKey = document.querySelector("#write-access-key");
const writeAccessStatus = document.querySelector("#write-access-status");

if (state.writeToken) {
  writeAccessStatus.textContent =
    "A write key is stored for this tab; the server checks it when you make a change.";
}

writeAccessForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const token = writeAccessKey.value.trim();
  if (!token) {
    writeAccessStatus.textContent = "Enter the evaluator write key to unlock changes.";
    return;
  }
  state.writeToken = token;
  sessionStorage.setItem(writeTokenStorageKey, token);
  writeAccessKey.value = "";
  writeAccessStatus.textContent =
    "Write key saved for this tab; the server checks it when you make a change.";
});

document.querySelector("#lock-demo-edits").addEventListener("click", () => {
  state.writeToken = "";
  sessionStorage.removeItem(writeTokenStorageKey);
  writeAccessKey.value = "";
  writeAccessStatus.textContent =
    "Viewing is public. A write key is only needed to make changes.";
});

for (const tab of document.querySelectorAll(".nav-tab")) {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector("#schedule-page").hidden = tab.dataset.page !== "schedule";
    document.querySelector("#control-page").hidden = tab.dataset.page !== "control";
    if (tab.dataset.page === "control") loadControlState();
  });
}

setInterval(() => {
  if (!document.querySelector("#control-page").hidden) loadControlState();
}, 3000);

loadSchedule();
