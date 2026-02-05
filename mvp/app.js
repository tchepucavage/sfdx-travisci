const SAMPLE_CSV = `timestamp,inletTemp,outletTemp,cpuLoad,power,ambientTemp,humidity,fanSpeed,pumpSpeed,flowRate,coolantTemp
2026-02-05T00:00:00Z,27.1,33.5,0.62,420,24.5,46,58,44,28,20.5
2026-02-05T00:05:00Z,27.4,33.9,0.68,445,24.7,47,60,45,29,20.7
2026-02-05T00:10:00Z,27.8,34.6,0.74,468,24.8,48,63,46,30,20.9
2026-02-05T00:15:00Z,28.0,35.1,0.79,490,25.0,49,66,48,31,21.2
2026-02-05T00:20:00Z,27.6,34.4,0.71,460,24.6,46,62,47,30,21.0
2026-02-05T00:25:00Z,27.2,33.8,0.64,435,24.4,45,59,45,29,20.6`;

const $ = (id) => document.getElementById(id);

const datasetFile = $("datasetFile");
const datasetText = $("datasetText");
const output = $("output");
const datasetSummary = $("datasetSummary");
const runBtn = $("runBtn");
const loadSample = $("loadSample");

const ACTION_LIBRARY = [
  { id: "hold", label: "Hold settings", vector: { fan: 0, pump: 0, valve: 0, setpoint: 0 } },
  { id: "fan_up", label: "Increase fan speed", vector: { fan: 1, pump: 0, valve: 0, setpoint: -0.2 } },
  { id: "fan_down", label: "Decrease fan speed", vector: { fan: -1, pump: 0, valve: 0, setpoint: 0.2 } },
  { id: "pump_up", label: "Increase pump speed", vector: { fan: 0, pump: 1, valve: 0, setpoint: -0.1 } },
  { id: "pump_down", label: "Decrease pump speed", vector: { fan: 0, pump: -1, valve: 0, setpoint: 0.1 } },
  { id: "valve_open", label: "Open valve", vector: { fan: 0, pump: 0, valve: 1, setpoint: -0.1 } },
  { id: "valve_close", label: "Close valve", vector: { fan: 0, pump: 0, valve: -1, setpoint: 0.1 } },
  { id: "setpoint_down", label: "Lower supply setpoint", vector: { fan: 0, pump: 0, valve: 0, setpoint: -0.5 } },
  { id: "setpoint_up", label: "Raise supply setpoint", vector: { fan: 0, pump: 0, valve: 0, setpoint: 0.5 } },
  { id: "efficiency_mix", label: "Efficiency mix", vector: { fan: -1, pump: 1, valve: 1, setpoint: -0.2 } },
];

class DQN {
  constructor(stateSize, actionSize, hiddenSize, learningRate) {
    this.stateSize = stateSize;
    this.actionSize = actionSize;
    this.hiddenSize = hiddenSize;
    this.learningRate = learningRate;
    this.W1 = this.randomMatrix(hiddenSize, stateSize);
    this.b1 = new Array(hiddenSize).fill(0);
    this.W2 = this.randomMatrix(actionSize, hiddenSize);
    this.b2 = new Array(actionSize).fill(0);
  }

  randomMatrix(rows, cols) {
    const data = [];
    for (let r = 0; r < rows; r += 1) {
      const row = [];
      for (let c = 0; c < cols; c += 1) {
        row.push((Math.random() * 2 - 1) * 0.1);
      }
      data.push(row);
    }
    return data;
  }

  predict(state) {
    return this.forward(state).q;
  }

  forward(state) {
    const z1 = this.W1.map((row, idx) => dot(row, state) + this.b1[idx]);
    const a1 = z1.map((value) => Math.max(0, value));
    const q = this.W2.map((row, idx) => dot(row, a1) + this.b2[idx]);
    return { z1, a1, q };
  }

  train(state, actionIndex, target) {
    const { z1, a1, q } = this.forward(state);
    const error = q[actionIndex] - target;
    const dQ = 2 * error;
    const prevW2Row = this.W2[actionIndex].slice();

    for (let j = 0; j < this.hiddenSize; j += 1) {
      this.W2[actionIndex][j] -= this.learningRate * dQ * a1[j];
    }
    this.b2[actionIndex] -= this.learningRate * dQ;

    for (let j = 0; j < this.hiddenSize; j += 1) {
      const reluGrad = z1[j] > 0 ? 1 : 0;
      const dz = prevW2Row[j] * dQ * reluGrad;
      for (let i = 0; i < this.stateSize; i += 1) {
        this.W1[j][i] -= this.learningRate * dz * state[i];
      }
      this.b1[j] -= this.learningRate * dz;
    }

    return error * error;
  }
}

function dot(a, b) {
  let total = 0;
  for (let i = 0; i < a.length; i += 1) {
    total += a[i] * b[i];
  }
  return total;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function readConfig() {
  const stepSize = Number($("stepSize").value) || 5;
  return {
    episodes: Number($("episodes").value) || 5,
    learningRate: Number($("learningRate").value) || 0.02,
    discount: Number($("discount").value) || 0.9,
    epsilon: Number($("epsilon").value) || 0.4,
    targetTemp: Number($("targetTemp").value) || 26,
    fanMax: Number($("fanMax").value) || 100,
    pumpMax: Number($("pumpMax").value) || 100,
    valveMax: Number($("valveMax").value) || 100,
    baseFan: Number($("baseFan").value) || 55,
    basePump: Number($("basePump").value) || 45,
    baseValve: Number($("baseValve").value) || 40,
    baseSupplyTemp: Number($("targetTemp").value) || 26,
    stepSize,
    setpointStep: 0.5,
  };
}

function buildActions(mode, stepSize) {
  const filtered = ACTION_LIBRARY.filter((action) => {
    const usesPump = action.vector.pump !== 0 || action.vector.valve !== 0;
    const usesFan = action.vector.fan !== 0;
    if (mode === "air") {
      return !usesPump;
    }
    if (mode === "liquid") {
      return !usesFan;
    }
    return true;
  });

  return filtered.map((action) => ({
    ...action,
    vector: {
      fan: action.vector.fan * stepSize,
      pump: action.vector.pump * stepSize,
      valve: action.vector.valve * stepSize,
      setpoint: action.vector.setpoint,
    },
  }));
}

function parseDataset(text) {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("Dataset is empty.");
  }

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return parseJsonDataset(trimmed);
  }
  return parseCsvDataset(trimmed);
}

function parseJsonDataset(text) {
  const parsed = JSON.parse(text);
  let rows = parsed;
  if (parsed && typeof parsed === "object") {
    if (Array.isArray(parsed.rows)) {
      rows = parsed.rows;
    } else if (Array.isArray(parsed.data)) {
      rows = parsed.data;
    }
  }

  if (!Array.isArray(rows)) {
    throw new Error("JSON dataset must be an array of rows.");
  }

  if (rows.length === 0) {
    throw new Error("JSON dataset has no rows.");
  }

  if (Array.isArray(rows[0])) {
    const firstRow = rows[0];
    const headers = firstRow.every((value) => typeof value === "string")
      ? firstRow
      : firstRow.map((_, index) => `feature_${index + 1}`);
    rows = rows.slice(1).map((row) => rowToObject(headers, row));
  }

  return rows.map((row) => normalizeRowValues(row));
}

function parseCsvDataset(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length < 2) {
    throw new Error("CSV dataset must include a header and at least one row.");
  }
  const headers = splitCsvLine(lines[0]).map((header) => header.trim());
  const rows = lines.slice(1).map((line) => {
    const values = splitCsvLine(line);
    return rowToObject(headers, values);
  });
  return rows.map((row) => normalizeRowValues(row));
}

function splitCsvLine(line) {
  const values = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

function rowToObject(headers, values) {
  const row = {};
  headers.forEach((header, index) => {
    row[header] = values[index] !== undefined ? values[index] : "";
  });
  return row;
}

function normalizeRowValues(row) {
  const outputRow = {};
  Object.keys(row).forEach((key) => {
    const value = row[key];
    const numeric = Number(value);
    outputRow[key] = Number.isFinite(numeric) && value !== "" ? numeric : value;
  });
  return outputRow;
}

function getNumericKeys(rows) {
  const keys = Object.keys(rows[0] || {});
  const filtered = keys.filter((key) => !/time|date/i.test(key));
  return filtered.filter((key) =>
    rows.every((row) => typeof row[key] === "number" && Number.isFinite(row[key]))
  );
}

function buildNormalizer(rows, keys) {
  const min = {};
  const max = {};
  keys.forEach((key) => {
    min[key] = Number.POSITIVE_INFINITY;
    max[key] = Number.NEGATIVE_INFINITY;
  });
  rows.forEach((row) => {
    keys.forEach((key) => {
      const value = row[key];
      if (typeof value === "number" && Number.isFinite(value)) {
        if (value < min[key]) min[key] = value;
        if (value > max[key]) max[key] = value;
      }
    });
  });
  return {
    normalize: (row) =>
      keys.map((key) => {
        const value = row[key];
        if (typeof value !== "number" || !Number.isFinite(value)) {
          return 0;
        }
        if (max[key] === min[key]) {
          return 0.5;
        }
        return (value - min[key]) / (max[key] - min[key]);
      }),
    min,
    max,
  };
}

function pickFirst(row, keys) {
  for (const key of keys) {
    if (typeof row[key] === "number" && Number.isFinite(row[key])) {
      return row[key];
    }
  }
  return null;
}

function computeReward(row, mode, config) {
  const temp = pickFirst(row, [
    "outletTemp",
    "inletTemp",
    "cpuTemp",
    "temperature",
    "ambientTemp",
    "coolantTemp",
  ]);
  const power = pickFirst(row, ["power", "powerKW", "power_kW", "watts"]);
  const fan = pickFirst(row, ["fanSpeed", "fanRPM", "fan_rpm"]);
  const pump = pickFirst(row, ["pumpSpeed", "pumpRPM", "pump_rpm"]);
  const humidity = pickFirst(row, ["humidity", "rh"]);

  const tempPenalty = temp === null ? 0 : Math.abs(temp - config.targetTemp);
  const powerPenalty = power === null ? 0 : power * 0.01;
  const fanPenalty = fan === null ? 0 : fan * 0.002;
  const pumpPenalty = pump === null ? 0 : pump * 0.002;
  const humidityPenalty = humidity === null ? 0 : Math.max(0, humidity - 55) * 0.03;

  let reward = -(tempPenalty * 2.5 + powerPenalty + fanPenalty + pumpPenalty + humidityPenalty);
  if (mode === "air") {
    reward -= pumpPenalty * 0.4;
  }
  if (mode === "liquid") {
    reward -= fanPenalty * 0.4;
  }
  return reward;
}

function selectAction(model, state, epsilon, actionCount) {
  if (Math.random() < epsilon) {
    return Math.floor(Math.random() * actionCount);
  }
  const qValues = model.predict(state);
  return indexOfMax(qValues);
}

function indexOfMax(values) {
  let bestIndex = 0;
  let bestValue = values[0];
  for (let i = 1; i < values.length; i += 1) {
    if (values[i] > bestValue) {
      bestValue = values[i];
      bestIndex = i;
    }
  }
  return bestIndex;
}

function trainModel(rows, normalizer, actions, config, mode) {
  const model = new DQN(normalizer.normalize(rows[0]).length, actions.length, 10, config.learningRate);
  let epsilon = config.epsilon;
  const epsilonDecay = 0.92;
  let rewardTotal = 0;
  let lossTotal = 0;
  let steps = 0;

  for (let ep = 0; ep < config.episodes; ep += 1) {
    for (let i = 0; i < rows.length - 1; i += 1) {
      const state = normalizer.normalize(rows[i]);
      const nextState = normalizer.normalize(rows[i + 1]);
      const reward = computeReward(rows[i], mode, config);
      const actionIndex = selectAction(model, state, epsilon, actions.length);
      const nextQ = model.predict(nextState);
      const target = reward + config.discount * Math.max(...nextQ);
      const loss = model.train(state, actionIndex, target);

      rewardTotal += reward;
      lossTotal += loss;
      steps += 1;
    }
    epsilon = Math.max(0.05, epsilon * epsilonDecay);
  }

  return {
    model,
    stats: {
      averageReward: rewardTotal / Math.max(1, steps),
      averageLoss: lossTotal / Math.max(1, steps),
      finalEpsilon: epsilon,
    },
  };
}

function buildCommand(action, config, mode) {
  const base = {
    fanSpeed: config.baseFan,
    pumpSpeed: config.basePump,
    valve: config.baseValve,
    supplyTemp: config.baseSupplyTemp,
  };

  const next = {
    fanSpeed: clamp(base.fanSpeed + action.vector.fan, 0, config.fanMax),
    pumpSpeed: clamp(base.pumpSpeed + action.vector.pump, 0, config.pumpMax),
    valve: clamp(base.valve + action.vector.valve, 0, config.valveMax),
    supplyTemp: clamp(base.supplyTemp + action.vector.setpoint, config.targetTemp - 6, config.targetTemp + 6),
  };

  if (mode === "air") {
    next.pumpSpeed = base.pumpSpeed;
    next.valve = base.valve;
  }
  if (mode === "liquid") {
    next.fanSpeed = base.fanSpeed;
  }

  return {
    action: action.id,
    description: action.label,
    commands: {
      set_fan_speed: Math.round(next.fanSpeed),
      set_pump_speed: Math.round(next.pumpSpeed),
      set_valve: Math.round(next.valve),
      set_supply_temp_c: Number(next.supplyTemp.toFixed(2)),
    },
  };
}

function buildPlan(rows, normalizer, actions, model, config, mode, featureKeys, stats) {
  const lastRow = rows[rows.length - 1];
  const lastState = normalizer.normalize(lastRow);
  const qValues = model.predict(lastState);
  const bestIndex = indexOfMax(qValues);
  const sortedActions = actions
    .map((action, idx) => ({ id: action.id, label: action.label, score: qValues[idx] }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  return {
    mode,
    dataset: {
      rows: rows.length,
      features: featureKeys,
      normalization: {
        min: normalizer.min,
        max: normalizer.max,
      },
    },
    training: {
      episodes: config.episodes,
      learning_rate: config.learningRate,
      discount: config.discount,
      epsilon_final: Number(stats.finalEpsilon.toFixed(3)),
      average_reward: Number(stats.averageReward.toFixed(3)),
      average_loss: Number(stats.averageLoss.toFixed(6)),
    },
    recommended: buildCommand(actions[bestIndex], config, mode),
    top_actions: sortedActions.map((action) => ({
      id: action.id,
      label: action.label,
      score: Number(action.score.toFixed(3)),
    })),
    notes: [
      "This MVP uses a lightweight deep Q network trained on the uploaded dataset.",
      "Commands are generated from the last row as the current state estimate.",
      "Tune base speeds and target temperature to match your facility.",
    ],
  };
}

async function readDatasetText() {
  const pasted = datasetText.value.trim();
  if (pasted) {
    return pasted;
  }
  if (datasetFile.files && datasetFile.files.length > 0) {
    return readFileAsText(datasetFile.files[0]);
  }
  return "";
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Unable to read file."));
    reader.readAsText(file);
  });
}

async function runOptimization() {
  output.textContent = "Loading dataset...";
  datasetSummary.textContent = "Reading dataset...";

  try {
    const datasetContent = await readDatasetText();
    if (!datasetContent.trim()) {
      throw new Error("No dataset provided.");
    }

    const rows = parseDataset(datasetContent);
    if (rows.length < 2) {
      throw new Error("Dataset needs at least two rows.");
    }

    const numericKeys = getNumericKeys(rows);
    if (numericKeys.length < 2) {
      throw new Error("Need at least two numeric columns for training.");
    }

    const mode = $("coolingMode").value;
    const config = readConfig();
    const actions = buildActions(mode, config.stepSize);
    const normalizer = buildNormalizer(rows, numericKeys);

    const { model, stats } = trainModel(rows, normalizer, actions, config, mode);
    const plan = buildPlan(rows, normalizer, actions, model, config, mode, numericKeys, stats);

    datasetSummary.textContent = `Loaded ${rows.length} rows with ${numericKeys.length} numeric features.`;
    output.textContent = JSON.stringify(plan, null, 2);
  } catch (error) {
    datasetSummary.textContent = "Dataset error. See output for details.";
    output.textContent = `Error: ${error.message}`;
  }
}

loadSample.addEventListener("click", () => {
  datasetText.value = SAMPLE_CSV;
  datasetSummary.textContent = "Sample dataset loaded.";
});

runBtn.addEventListener("click", () => {
  runOptimization();
});
