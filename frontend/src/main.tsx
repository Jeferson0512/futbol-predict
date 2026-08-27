import { StrictMode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Database,
  Gauge,
  LineChart as LineChartIcon,
  RefreshCw,
  Target,
  Trophy,
} from "lucide-react";
import { createRoot } from "react-dom/client";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { components } from "./api/generated";
import "./styles.css";

type Schemas = components["schemas"];
type MetricRow = Schemas["BacktestMetricResponse"];
type BacktestResponse = Schemas["BacktestResponse"];
type BreakdownRow = Schemas["BacktestBreakdownResponse"];
type PredictionStatusRow = Schemas["PredictionStatusRowResponse"];
type PredictionStatusResponse = Schemas["PredictionStatusResponse"];
type CalibrationStatusRow = Schemas["CalibrationStatusRowResponse"];
type CalibrationStatusResponse = Schemas["CalibrationStatusResponse"];
type CalibrationCurvePoint = Schemas["CalibrationCurvePointResponse"];
type CalibrationCurveResponse = Schemas["CalibrationCurveResponse"];
type ModelRankingRow = Schemas["ModelRankingRowResponse"];
type Fixture = Schemas["FixtureResponse"];
type FixturePredictionRow = Schemas["FixturePredictionRowResponse"];
type FixturePredictionsResponse = Schemas["FixturePredictionsResponse"];

type Scope = "premier" | "big-five";
type Outcome = "H" | "D" | "A";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const endpoints: Record<Scope, string> = {
  premier: `${apiBaseUrl}/backtests/db/football-data-uk?season=2526&division=E0`,
  "big-five": `${apiBaseUrl}/backtests/db/big-five?start_season=1617&end_season=2526`,
};

const scopeLabels: Record<Scope, string> = {
  premier: "Premier 25/26",
  "big-five": "Big-5 10 temporadas",
};

const outcomeLabels: Record<Outcome, string> = {
  H: "Local",
  D: "Empate",
  A: "Visita",
};

const outcomeColors: Record<Outcome, string> = {
  H: "#1f6f62",
  D: "#b7791f",
  A: "#285e8e",
};

const numberFormat = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 4 });
const compactFormat = new Intl.NumberFormat("es-PE");
const percentFormat = new Intl.NumberFormat("es-PE", {
  maximumFractionDigits: 1,
  style: "percent",
});
const signedFormat = new Intl.NumberFormat("es-PE", {
  maximumFractionDigits: 4,
  signDisplay: "always",
});
const dateTimeFormat = new Intl.DateTimeFormat("es-PE", {
  dateStyle: "medium",
  timeStyle: "short",
});

function findMetric(row: BreakdownRow, model: string) {
  return row.metrics.find((metric) => metric.model === model);
}

function metricValue(value: number | null | undefined) {
  return value === undefined || value === null ? "-" : numberFormat.format(value);
}

function metricGap(elo: MetricRow | undefined, market: MetricRow | undefined) {
  if (!elo || !market) {
    return "-";
  }
  return signedFormat.format(elo.rps - market.rps);
}

function bestCalibration(rows: CalibrationStatusRow[]) {
  return rows.find((row) => row.calibration_error !== null);
}

function probabilityTicks() {
  return [0, 0.25, 0.5, 0.75, 1];
}

function curveData(points: CalibrationCurvePoint[]) {
  const byBin = new Map<number, { probability: number; [key: string]: number }>();
  for (const point of points) {
    const current =
      byBin.get(point.bin_index) ??
      {
        probability: (point.bin_lower + point.bin_upper) / 2,
      };
    current[`${point.outcome}_observed`] = point.observed_frequency;
    byBin.set(point.bin_index, current);
  }
  return [...byBin.values()].sort((left, right) => left.probability - right.probability);
}

function chartTooltipValue(value: unknown, name: unknown): [string, string] {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return [percentFormat.format(numericValue), String(name ?? "")];
}

function kickoffValue(value: string) {
  return dateTimeFormat.format(new Date(value));
}

function oddsValue(fixture: Fixture) {
  if (
    fixture.avg_home_odds === null ||
    fixture.avg_draw_odds === null ||
    fixture.avg_away_odds === null
  ) {
    return "-";
  }
  return [
    numberFormat.format(fixture.avg_home_odds),
    numberFormat.format(fixture.avg_draw_odds),
    numberFormat.format(fixture.avg_away_odds),
  ].join(" / ");
}

function BreakdownTable({
  title,
  rows,
}: {
  title: string;
  rows: BreakdownRow[];
}) {
  if (rows.length === 0) {
    return null;
  }

  return (
    <section className="table-section">
      <div className="section-heading compact">
        <h2>{title}</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Grupo</th>
              <th>Partidos</th>
              <th>Mejor modelo</th>
              <th>Mejor RPS</th>
              <th>Mercado RPS</th>
              <th>Elo RPS</th>
              <th>Gap Elo-Mercado</th>
              <th>Accuracy mejor</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const best = row.metrics[0];
              const market = findMetric(row, "market_avg_odds");
              const elo = findMetric(row, "elo_simple");

              return (
                <tr key={`${row.group_type}-${row.group_key}`}>
                  <td>{row.group_key}</td>
                  <td>{row.n_matches}</td>
                  <td>{best?.model ?? "-"}</td>
                  <td>{metricValue(best?.rps)}</td>
                  <td>{metricValue(market?.rps)}</td>
                  <td>{metricValue(elo?.rps)}</td>
                  <td>{metricGap(elo, market)}</td>
                  <td>{best ? percentFormat.format(best.accuracy) : "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PredictionStatusTable({ rows }: { rows: PredictionStatusRow[] }) {
  return (
    <section className="table-section">
      <div className="section-heading">
        <Database size={20} />
        <h2>Predicciones evaluadas</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Modelo</th>
              <th>Predicciones</th>
              <th>Evaluadas</th>
              <th>RPS</th>
              <th>Log-loss</th>
              <th>Brier</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.model}-${row.algorithm}`}>
                <td>{row.model}</td>
                <td>{compactFormat.format(row.predictions)}</td>
                <td>{compactFormat.format(row.evaluated)}</td>
                <td>{metricValue(row.avg_rps)}</td>
                <td>{metricValue(row.avg_log_loss)}</td>
                <td>{metricValue(row.avg_brier)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CalibrationTable({ rows }: { rows: CalibrationStatusRow[] }) {
  return (
    <section className="table-section">
      <div className="section-heading">
        <Gauge size={20} />
        <h2>Calibracion</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Modelo</th>
              <th>Versiones</th>
              <th>Bins</th>
              <th>Muestras</th>
              <th>Error calib.</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.model}-${row.algorithm}`}>
                <td>{row.model}</td>
                <td>{row.model_versions}</td>
                <td>{row.bins}</td>
                <td>{compactFormat.format(row.class_samples)}</td>
                <td>{metricValue(row.calibration_error)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FuturePredictionsTable({ rows }: { rows: FixturePredictionRow[] }) {
  return (
    <section className="table-section">
      <div className="section-heading">
        <CalendarDays size={20} />
        <h2>Proximos partidos</h2>
      </div>
      {rows.length === 0 ? (
        <div className="state">No hay fixtures proximos cargados.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Liga</th>
                <th>Local</th>
                <th>Visita</th>
                <th>Modelo</th>
                <th>Local</th>
                <th>Empate</th>
                <th>Visita</th>
                <th>RPS hist.</th>
                <th>Cuotas H/D/A</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const prediction = row.predictions[0];
                return (
                  <tr
                    key={
                      `${row.fixture.match_id ?? row.fixture.kickoff_utc}-` +
                      row.fixture.home_team
                    }
                  >
                    <td>{kickoffValue(row.fixture.kickoff_utc)}</td>
                    <td>{row.fixture.division}</td>
                    <td>{row.fixture.home_team}</td>
                    <td>{row.fixture.away_team}</td>
                    <td>{prediction?.model ?? "-"}</td>
                    <td>{prediction ? percentFormat.format(prediction.prob_home) : "-"}</td>
                    <td>{prediction ? percentFormat.format(prediction.prob_draw) : "-"}</td>
                    <td>{prediction ? percentFormat.format(prediction.prob_away) : "-"}</td>
                    <td>{metricValue(prediction?.ranking_rps)}</td>
                    <td>{oddsValue(row.fixture)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CalibrationCurve({
  rows,
  model,
  onModelChange,
  models,
}: {
  rows: CalibrationCurvePoint[];
  model: string;
  onModelChange: (model: string) => void;
  models: string[];
}) {
  const chartData = useMemo(() => curveData(rows), [rows]);

  return (
    <section className="table-section">
      <div className="section-heading with-control">
        <div>
          <LineChartIcon size={20} />
          <h2>Curva de calibracion</h2>
        </div>
        <select value={model} onChange={(event) => onModelChange(event.target.value)}>
          {models.map((item) => (
            <option value={item} key={item}>
              {item}
            </option>
          ))}
        </select>
      </div>
      <div className="chart-panel">
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={chartData} margin={{ top: 12, right: 24, bottom: 8, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#dfe6df" />
            <XAxis
              dataKey="probability"
              tickFormatter={(value) => percentFormat.format(Number(value))}
              ticks={probabilityTicks()}
              type="number"
              domain={[0, 1]}
            />
            <YAxis
              tickFormatter={(value) => percentFormat.format(Number(value))}
              ticks={probabilityTicks()}
              type="number"
              domain={[0, 1]}
            />
            <Tooltip
              formatter={chartTooltipValue}
              labelFormatter={(value) => `Prob. ${percentFormat.format(Number(value))}`}
            />
            <Legend />
            <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#66717f" />
            {(["H", "D", "A"] as Outcome[]).map((outcome) => (
              <Line
                key={outcome}
                type="monotone"
                dataKey={`${outcome}_observed`}
                name={`${outcomeLabels[outcome]} obs.`}
                stroke={outcomeColors[outcome]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function App() {
  const [scope, setScope] = useState<Scope>("premier");
  const [curveModel, setCurveModel] = useState("market_avg_odds");
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [predictions, setPredictions] = useState<PredictionStatusResponse | null>(null);
  const [calibration, setCalibration] = useState<CalibrationStatusResponse | null>(null);
  const [curve, setCurve] = useState<CalibrationCurveResponse | null>(null);
  const [championModel, setChampionModel] = useState<ModelRankingRow | null>(null);
  const [futurePredictions, setFuturePredictions] =
    useState<FixturePredictionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadDashboard(selectedScope: Scope = scope, selectedModel = curveModel) {
    setLoading(true);
    setError(null);
    try {
      const [
        backtestResponse,
        predictionsResponse,
        calibrationResponse,
        curveResponse,
        championResponse,
        futureResponse,
      ] = await Promise.all([
        fetch(endpoints[selectedScope]),
        fetch(`${apiBaseUrl}/predictions/status`),
        fetch(`${apiBaseUrl}/calibration/status?bins=10`),
        fetch(`${apiBaseUrl}/calibration/curves?bins=10&model=${selectedModel}`),
        fetch(`${apiBaseUrl}/models/champion`),
        fetch(`${apiBaseUrl}/fixtures/predictions?days=21&limit=40&model=best_available`),
      ]);
      const failed = [
        backtestResponse,
        predictionsResponse,
        calibrationResponse,
        curveResponse,
        championResponse,
        futureResponse,
      ].find((response) => !response.ok);
      if (failed) {
        throw new Error(`API ${failed.status}`);
      }
      setBacktest((await backtestResponse.json()) as BacktestResponse);
      setPredictions((await predictionsResponse.json()) as PredictionStatusResponse);
      const calibrationPayload = (await calibrationResponse.json()) as CalibrationStatusResponse;
      setCalibration(calibrationPayload);
      setCurve((await curveResponse.json()) as CalibrationCurveResponse);
      setChampionModel((await championResponse.json()) as ModelRankingRow);
      setFuturePredictions((await futureResponse.json()) as FixturePredictionsResponse);
      if (!calibrationPayload.rows.some((row) => row.model === selectedModel)) {
        setCurveModel(calibrationPayload.rows[0]?.model ?? selectedModel);
      }
    } catch (unknownError) {
      const message = unknownError instanceof Error ? unknownError.message : "Error desconocido";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard(scope, curveModel);
  }, [scope, curveModel]);

  const champion = backtest?.metrics[0];
  const calibrationLeader = bestCalibration(calibration?.rows ?? []);
  const divisionBreakdowns =
    backtest?.breakdowns.filter((item) => item.group_type === "division") ?? [];
  const seasonBreakdowns =
    backtest?.breakdowns.filter((item) => item.group_type === "season") ?? [];
  const availableCalibrationModels = calibration?.rows.map((row) => row.model) ?? [curveModel];

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">
            <Activity size={16} />
            Predictor 1X2
          </div>
          <h1>Futbol Predict</h1>
        </div>
        <button
          className="icon-button"
          onClick={() => void loadDashboard()}
          title="Actualizar dashboard"
        >
          <RefreshCw size={18} />
        </button>
      </header>

      <nav className="tabs" aria-label="Vista de backtest">
        {(["premier", "big-five"] as Scope[]).map((item) => (
          <button
            className={item === scope ? "active" : ""}
            key={item}
            onClick={() => setScope(item)}
            type="button"
          >
            {scopeLabels[item]}
          </button>
        ))}
      </nav>

      <section className="summary-band">
        <div>
          <span>Fuente</span>
          <strong>{backtest?.source ?? "postgresql:football-data.co.uk"}</strong>
        </div>
        <div>
          <span>Divisiones</span>
          <strong>{backtest?.divisions.join(", ") ?? "E0"}</strong>
        </div>
        <div>
          <span>Periodo</span>
          <strong>{backtest ? `${backtest.start_season}-${backtest.end_season}` : "2526"}</strong>
        </div>
        <div>
          <span>Partidos</span>
          <strong>{backtest?.n_matches ?? "-"}</strong>
        </div>
      </section>

      <section className="kpi-grid">
        {champion && (
          <div className="kpi-card accent-green">
            <Trophy size={22} />
            <span>Mejor RPS</span>
            <strong>{champion.model}</strong>
            <small>{numberFormat.format(champion.rps)}</small>
          </div>
        )}
        {championModel && (
          <div className="kpi-card accent-blue">
            <Target size={22} />
            <span>Campeon DB</span>
            <strong>{championModel.model}</strong>
            <small>{numberFormat.format(championModel.weighted_rps)} RPS</small>
          </div>
        )}
        {predictions?.rows[0] && (
          <div className="kpi-card accent-slate">
            <Database size={22} />
            <span>Predicciones DB</span>
            <strong>
              {compactFormat.format(
                predictions.rows.reduce((total, row) => total + row.predictions, 0),
              )}
            </strong>
            <small>
              {compactFormat.format(
                predictions.rows.reduce((total, row) => total + row.evaluated, 0),
              )}{" "}
              evaluadas
            </small>
          </div>
        )}
        {futurePredictions && (
          <div className="kpi-card accent-teal">
            <CalendarDays size={22} />
            <span>Fixtures 21 dias</span>
            <strong>{compactFormat.format(futurePredictions.rows.length)}</strong>
            <small>modelo disponible</small>
          </div>
        )}
        {calibrationLeader && (
          <div className="kpi-card accent-amber">
            <Gauge size={22} />
            <span>Mejor calibracion</span>
            <strong>{calibrationLeader.model}</strong>
            <small>{metricValue(calibrationLeader.calibration_error)}</small>
          </div>
        )}
      </section>

      {!loading && !error && futurePredictions && (
        <FuturePredictionsTable rows={futurePredictions.rows} />
      )}

      <section className="table-section">
        <div className="section-heading">
          <BarChart3 size={20} />
          <h2>Backtest de baselines</h2>
        </div>

        {loading && <div className="state">Cargando metricas...</div>}
        {error && <div className="state error">No se pudo cargar la API: {error}</div>}
        {!loading && !error && backtest && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Modelo</th>
                  <th>Partidos</th>
                  <th>RPS</th>
                  <th>Log-loss</th>
                  <th>Brier</th>
                  <th>Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {backtest.metrics.map((row) => (
                  <tr key={row.model}>
                    <td>{row.model}</td>
                    <td>{row.n_matches}</td>
                    <td>{numberFormat.format(row.rps)}</td>
                    <td>{numberFormat.format(row.log_loss)}</td>
                    <td>{numberFormat.format(row.brier)}</td>
                    <td>{percentFormat.format(row.accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {!loading && !error && predictions && <PredictionStatusTable rows={predictions.rows} />}
      {!loading && !error && calibration && <CalibrationTable rows={calibration.rows} />}
      {!loading && !error && curve && (
        <CalibrationCurve
          rows={curve.rows}
          model={curveModel}
          onModelChange={setCurveModel}
          models={availableCalibrationModels}
        />
      )}

      {!loading && !error && backtest && (
        <>
          <BreakdownTable title="Desglose por liga" rows={divisionBreakdowns} />
          <BreakdownTable title="Desglose por temporada" rows={seasonBreakdowns} />
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
