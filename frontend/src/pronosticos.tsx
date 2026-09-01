import { useEffect, useMemo, useState } from "react";
import type { components } from "./api/generated";
import "./pronosticos.css";

type S = components["schemas"];
type FixturePredictions = S["FixturePredictionsResponse"];
type FixtureRow = S["FixturePredictionRowResponse"];
type History = S["PredictionHistoryResponse"];
type HistoryRow = S["PredictionHistoryRowResponse"];
type CalibrationCurve = S["CalibrationCurveResponse"];
type Rankings = S["ModelRankingResponse"];
type MatchDetail = S["MatchDetailResponse"];

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const HISTORY_MODEL = "market_avg_odds";

const LEAGUES: ReadonlyArray<readonly [string, string]> = [
  ["E0", "Premier League"], ["SP1", "LaLiga"], ["I1", "Serie A"],
  ["D1", "Bundesliga"], ["F1", "Ligue 1"],
];
const SECTIONS: ReadonlyArray<readonly [string, string]> = [
  ["proximos", "Próximos"], ["resultados", "Resultados"],
  ["calibracion", "Calibración"], ["modelos", "Modelos"],
];
const OUT = ["h", "d", "aw"] as const;

function useJson<T>(url: string | null): { data: T | null; loading: boolean; error: string | null } {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null, loading: Boolean(url), error: null,
  });
  useEffect(() => {
    if (!url) { setState({ data: null, loading: false, error: null }); return; }
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => { if (alive) setState({ data: d as T, loading: false, error: null }); })
      .catch((e: unknown) => {
        if (alive) setState({ data: null, loading: false, error: e instanceof Error ? e.message : "error" });
      });
    return () => { alive = false; };
  }, [url]);
  return state;
}

const pct = (x: number) => Math.round(x * 100);
const recIndex = (p: number[]) => p.indexOf(Math.max(...p));
const confLabel = (m: number) => (m >= 60 ? "confianza alta" : m >= 45 ? "confianza media" : "muy parejo");

function MatchCard(props: {
  league: string; when: string; home: string; away: string; probs: number[]; onClick?: () => void;
}) {
  const { league, when, home, away, probs, onClick } = props;
  const i = recIndex(probs);
  const rec = `var(--${OUT[i]})`;
  const pickText = i === 0 ? `Gana ${home}` : i === 2 ? `Gana ${away}` : "Empate";
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className="pro-match" style={{ ["--rec" as string]: rec }} onClick={onClick} type={onClick ? "button" : undefined}>
      <div className="pro-meta"><span className="pro-lg" style={{ ["--rec" as string]: rec }}>{league}</span><span>· {when}</span></div>
      <div className="pro-teams">
        <span className="pro-team h">{home}</span><span className="pro-vs">vs</span><span className="pro-team a">{away}</span>
      </div>
      <div className="pro-legend">
        {(["Local", "Empate", "Visita"] as const).map((label, k) => (
          <span key={label} className={`pro-o ${OUT[k]} ${k === 1 ? "c" : k === 2 ? "r" : ""} ${i === k ? "is-rec" : ""}`}>
            <span className="pro-dot" />{label} <b>{pct(probs[k])}%</b>
          </span>
        ))}
      </div>
      <div className="pro-bar">
        {probs.map((p, k) => (
          <span key={k} className={`pro-seg ${OUT[k]} ${i === k ? "is-rec" : ""}`} style={{ width: `${pct(p)}%` }} />
        ))}
      </div>
      <div className="pro-pick">
        <span className="pro-badge" style={{ ["--rec" as string]: rec }}>✓ Recomendado</span>
        <span className="pro-picklabel">{pickText} · <b>{pct(probs[i])}%</b></span>
        <span className="pro-conf">{confLabel(pct(probs[i]))}</span>
      </div>
    </Tag>
  );
}

function fmtKickoff(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("es-PE", { weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Proximos({ onOpen }: { onOpen: (id: number) => void }) {
  const [division, setDivision] = useState("E0");
  const { data, loading, error } = useJson<FixturePredictions>(
    `${apiBaseUrl}/fixtures/predictions?days=30&limit=80&model=best_available`,
  );
  const byLeague = useMemo(() => (data?.rows ?? []).filter((r) => r.fixture.division === division), [data, division]);
  const leagueName = LEAGUES.find((l) => l[0] === division)?.[1] ?? division;

  return (
    <div>
      <div className="pro-head"><h1>Próxima jornada</h1><p>Elige una liga y mira el pronóstico de cada partido. Toca una tarjeta para ver la ficha.</p></div>
      <div className="pro-tabs" role="tablist" aria-label="Ligas">
        {LEAGUES.map(([code, name]) => (
          <button key={code} type="button" className="pro-tab" aria-selected={division === code} onClick={() => setDivision(code)}>{name}</button>
        ))}
      </div>
      {loading && <div className="pro-state">Cargando pronósticos…</div>}
      {error && <div className="pro-state">No se pudo cargar: {error}</div>}
      {!loading && !error && (
        <>
          <p className="pro-count">{leagueName} · <b>{byLeague.length}</b> partidos</p>
          {byLeague.length === 0 && <div className="pro-state">No hay fixtures cargados para esta liga todavía.</div>}
          <div className="pro-list">
            {byLeague.map((row: FixtureRow) => {
              const pred = row.predictions[0];
              if (!pred) return null;
              const probs = [pred.prob_home, pred.prob_draw, pred.prob_away];
              return (
                <MatchCard key={row.fixture.match_id ?? `${row.fixture.home_team}-${row.fixture.kickoff_utc}`}
                  league={leagueName} when={fmtKickoff(row.fixture.kickoff_utc)}
                  home={row.fixture.home_team} away={row.fixture.away_team} probs={probs}
                  onClick={row.fixture.match_id ? () => onOpen(row.fixture.match_id as number) : undefined} />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function ResRow({ r }: { r: HistoryRow }) {
  const wait = r.hit === null;
  const flag = wait ? "wait" : r.hit ? "good" : "bad";
  const mark = wait ? "…" : r.hit ? "✓" : "✗";
  return (
    <div className="pro-res">
      <div className={`pro-flag ${flag}`}>{mark}</div>
      <div>
        <div className="teams">{r.home_team} vs {r.away_team}</div>
        <div className="sub">Pronóstico: <b>{r.predicted_pick}</b>{wait ? " · pendiente" : r.hit ? " · acertó" : " · falló"}</div>
      </div>
      {wait
        ? <div className="pro-score wait">{fmtKickoff(r.kickoff_utc)}</div>
        : <div className="pro-score">{r.home_goals}-{r.away_goals}</div>}
    </div>
  );
}

function Resultados() {
  const { data, loading, error } = useJson<History>(`${apiBaseUrl}/predictions/history?model=${HISTORY_MODEL}&limit=40`);
  const rows = data?.rows ?? [];
  const pending = rows.filter((r) => r.hit === null);
  const played = rows.filter((r) => r.hit !== null);
  const s = data?.summary;
  return (
    <div>
      <div className="pro-head"><h1>Historial y resultados</h1><p>Cada pronóstico pasado con si acertó o falló, y los que aún están por jugarse.</p></div>
      {loading && <div className="pro-state">Cargando historial…</div>}
      {error && <div className="pro-state">No se pudo cargar: {error}</div>}
      {s && (
        <div className="pro-stats">
          <div className="pro-stat"><div className="k">Acierto</div><div className="v">{s.accuracy === null ? "—" : `${(s.accuracy * 100).toFixed(1)}%`}</div><div className="s">{s.hits} / {s.evaluated}</div></div>
          <div className="pro-stat"><div className="k">RPS medio</div><div className="v">{s.avg_rps === null ? "—" : s.avg_rps.toFixed(3)}</div><div className="s">menor es mejor</div></div>
          <div className="pro-stat"><div className="k">Evaluadas</div><div className="v">{s.evaluated.toLocaleString("es-PE")}</div><div className="s">+{s.pending} pendientes</div></div>
        </div>
      )}
      {pending.length > 0 && (<><div className="pro-subhead">Pendientes</div><div className="pro-rows">{pending.map((r) => <ResRow key={r.match_id} r={r} />)}</div></>)}
      {played.length > 0 && (<><div className="pro-subhead">Ya jugados</div><div className="pro-rows">{played.map((r) => <ResRow key={r.match_id} r={r} />)}</div></>)}
    </div>
  );
}

function Calibracion() {
  const { data, loading, error } = useJson<CalibrationCurve>(`${apiBaseUrl}/calibration/curves?bins=10&model=${HISTORY_MODEL}`);
  const points = useMemo(() => {
    const rows = data?.rows ?? [];
    const byBin = new Map<number, { pred: number; obs: number; n: number }>();
    for (const row of rows) {
      const cur = byBin.get(row.bin_index) ?? { pred: 0, obs: 0, n: 0 };
      cur.pred += row.avg_predicted_probability * row.n_predictions;
      cur.obs += row.observed_frequency * row.n_predictions;
      cur.n += row.n_predictions;
      byBin.set(row.bin_index, cur);
    }
    return [...byBin.values()].filter((b) => b.n > 0).map((b) => ({ x: b.pred / b.n, y: b.obs / b.n }))
      .sort((a, b) => a.x - b.x);
  }, [data]);
  const err = points.length ? points.reduce((a, p) => a + Math.abs(p.x - p.y), 0) / points.length : null;
  const Sz = 200, pad = 26, span = Sz - pad * 2;
  const X = (v: number) => pad + v * span, Y = (v: number) => Sz - pad - v * span;
  return (
    <div>
      <div className="pro-head"><h1>¿Son honestas las probabilidades?</h1><p>Cuando el modelo dice "60%", ¿pasa de verdad ~60% de las veces? Eso es calibración.</p></div>
      {loading && <div className="pro-state">Cargando calibración…</div>}
      {error && <div className="pro-state">No se pudo cargar: {error}</div>}
      {!loading && !error && (
        <div className="pro-panel"><div className="pro-calib">
          <svg viewBox="0 0 200 200" role="img" aria-label="Curva de calibración">
            <rect x={pad} y={pad} width={span} height={span} fill="none" stroke="var(--line)" />
            <line x1={pad} y1={Sz - pad} x2={Sz - pad} y2={pad} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1.5} />
            {points.map((p, k) => <circle key={k} cx={X(p.x)} cy={Y(p.y)} r={4.5} fill="var(--brand)" />)}
            <text x={Sz / 2} y={Sz - 6} textAnchor="middle" fill="var(--muted)" fontSize={9}>probabilidad dicha →</text>
          </svg>
          <div className="note">
            <p style={{ margin: "0 0 8px" }}>Cada punto compara lo que el modelo <b>dijo</b> con lo que <b>pasó</b>.</p>
            <p style={{ margin: "0 0 8px" }}>Cuanto más cerca de la <b>diagonal</b>, más honesto.</p>
            {err !== null && <p style={{ margin: 0 }}>Error medio de calibración: <b>{(err * 100).toFixed(1)}%</b>.</p>}
          </div>
        </div></div>
      )}
    </div>
  );
}

function Modelos() {
  const { data, loading, error } = useJson<Rankings>(`${apiBaseUrl}/models/rankings?min_matches=100`);
  const rows = data?.rows ?? [];
  return (
    <div>
      <div className="pro-head"><h1>¿Qué modelo predice mejor?</h1><p>Ranking honesto por RPS (menor = mejor). El mercado sigue siendo el más difícil de vencer.</p></div>
      {loading && <div className="pro-state">Cargando modelos…</div>}
      {error && <div className="pro-state">No se pudo cargar: {error}</div>}
      <div className="pro-models" style={{ marginTop: 14 }}>
        {rows.map((m, i) => (
          <div key={m.model} className={`pro-mrow ${i === 0 ? "top" : ""}`}>
            <div className="rank">{i + 1}</div>
            <div className="name">{m.model}{m.model === "market_avg_odds" && <span className="pro-tagm"> mercado</span>}<small>{m.algorithm}</small></div>
            <div className="metric"><b>{m.weighted_rps.toFixed(4)}</b><span>RPS</span></div>
            <div className="metric"><b>{m.weighted_accuracy === null || m.weighted_accuracy === undefined ? "—" : `${(m.weighted_accuracy * 100).toFixed(1)}%`}</b><span>acierto</span></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Ficha({ id, onBack }: { id: number; onBack: () => void }) {
  const { data, loading, error } = useJson<MatchDetail>(`${apiBaseUrl}/matches/${id}`);
  const forms = (arr: string[]) => (
    <span className="pro-form">{arr.map((r, k) => <span key={k} className={`pro-fdot ${r}`}>{r}</span>)}</span>
  );
  return (
    <div>
      <button type="button" className="pro-back" onClick={onBack}>← Volver</button>
      <div className="pro-head"><h1>Ficha del partido</h1></div>
      {loading && <div className="pro-state">Cargando ficha…</div>}
      {error && <div className="pro-state">No se pudo cargar: {error}</div>}
      {data && (
        <>
          <MatchCard league={data.league} when={fmtKickoff(data.kickoff_utc)} home={data.home_team} away={data.away_team}
            probs={data.implied ?? [0.34, 0.28, 0.38]} />
          <div className="pro-dgrid">
            <div className="pro-dcard"><div className="k">Forma (últimos 5)</div>
              <div className="pro-drow"><span>{data.home_team}</span>{forms(data.home_form)}</div>
              <div className="pro-drow"><span>{data.away_team}</span>{forms(data.away_form)}</div></div>
            <div className="pro-dcard"><div className="k">xG a favor (últimos 5)</div>
              <div className="pro-drow"><span>{data.home_team}</span><b>{fmtXg(data.xg.home_xg_for_per_match_last_5)}</b></div>
              <div className="pro-drow"><span>{data.away_team}</span><b>{fmtXg(data.xg.away_xg_for_per_match_last_5)}</b></div></div>
            <div className="pro-dcard"><div className="k">Elo previo</div>
              <div className="pro-drow"><span>{data.home_team}</span><b>{fmtNum(data.home_elo_before)}</b></div>
              <div className="pro-drow"><span>{data.away_team}</span><b>{fmtNum(data.away_elo_before)}</b></div></div>
            <div className="pro-dcard"><div className="k">Cuota del mercado (1 · X · 2)</div>
              <div className="pro-drow"><span>Local / Empate / Visita</span><b>{fmtOdd(data.odds_home)} · {fmtOdd(data.odds_draw)} · {fmtOdd(data.odds_away)}</b></div></div>
          </div>
          {data.head_to_head.length > 0 && (
            <>
              <div className="pro-subhead">Cara a cara</div>
              <div className="pro-rows">
                {data.head_to_head.map((h, k) => (
                  <div key={k} className="pro-res">
                    <div className="pro-flag wait" style={{ background: "var(--surface-2)", color: "var(--muted)" }}>vs</div>
                    <div><div className="teams">{h.home_team} vs {h.away_team}</div></div>
                    <div className="pro-score">{h.home_goals}-{h.away_goals}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

const fmtNum = (v: number | null) => (v === null ? "—" : Math.round(v).toString());
const fmtXg = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(2));
const fmtOdd = (v: number | null) => (v === null ? "—" : v.toFixed(2));

export function PronosticosApp() {
  const [section, setSection] = useState("proximos");
  const [detailId, setDetailId] = useState<number | null>(null);
  return (
    <div className="pro-app">
      <div className="pro-wrap">
        {detailId !== null ? (
          <Ficha id={detailId} onBack={() => setDetailId(null)} />
        ) : (
          <>
            <nav className="pro-nav" role="tablist" aria-label="Secciones">
              {SECTIONS.map(([k, label]) => (
                <button key={k} type="button" className="pro-navbtn" aria-selected={section === k} onClick={() => setSection(k)}>{label}</button>
              ))}
            </nav>
            {section === "proximos" && <Proximos onOpen={setDetailId} />}
            {section === "resultados" && <Resultados />}
            {section === "calibracion" && <Calibracion />}
            {section === "modelos" && <Modelos />}
          </>
        )}
      </div>
    </div>
  );
}
