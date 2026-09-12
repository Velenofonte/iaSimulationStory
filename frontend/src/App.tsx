import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  createSession,
  deleteSession,
  getArcTimeline,
  getChat,
  getConfig,
  getCanUndo,
  getPlayerSheet,
  getSpellbook,
  getState,
  listFronts,
  listPlayable,
  getPlayableSheet,
  listRaces,
  listSessions,
  listStories,
  sendChat,
  undoLastTurn,
  type AppConfig,
  type ArcTimeline,
  type CharacterSheet,
  type FrontOption,
  type GameState,
  type PlayableCharacter,
  type RaceOption,
  type SessionSummary,
  type Spellbook,
  type StorySummary,
} from "./api";
import { OfflineBanner, PwaInstall } from "./pwa";
import "./App.css";

type Message = { role: "user" | "assistant"; content: string };

type PanelSection = "arc" | "situations" | "sheet" | "spellbook";

type WizardStep = "story" | "origin" | "details" | "mode";

type StartView = "home" | "create";

const ARC_STATUS_LABEL: Record<string, string> = {
  done: "fatto",
  current: "in corso",
  upcoming: "prossimo",
  skipped: "saltato",
};

/** Hide wiki link syntax: [[id|Label]] / [[id]] → Label / id */
function stripWikiLinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, id: string, label?: string) =>
    (label || id).trim(),
  );
}

function SheetMetaChips({ sheet }: { sheet: CharacterSheet }) {
  const chips: { label: string; value: string }[] = [];
  if (sheet.race) chips.push({ label: "Razza", value: String(sheet.race) });
  if (sheet.job) chips.push({ label: "Job", value: String(sheet.job) });
  if (sheet.affiliation) chips.push({ label: "Affiliazione", value: String(sheet.affiliation) });
  if (sheet.residence) chips.push({ label: "Residenza", value: String(sheet.residence) });
  if (sheet.level != null && sheet.level !== "") chips.push({ label: "Livello", value: String(sheet.level) });
  if (!chips.length) return null;
  return (
    <ul className="sheet-meta-chips">
      {chips.map((c) => (
        <li key={c.label}>
          <span className="sheet-meta-label">{c.label}</span>
          <span>{stripWikiLinks(c.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function SheetBody({
  body,
  layout = "stack",
  hideTitles = [],
}: {
  body: string;
  layout?: "stack" | "grid";
  hideTitles?: string[];
}) {
  const hide = new Set(
    hideTitles.map((t) => t.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim()),
  );
  const cleaned = stripWikiLinks(body);
  // Accetta # / ## / ###: l'LLM a volte usa heading annidati; la UI spezza su qualsiasi livello.
  const sections = cleaned
    .split(/(?=^#{1,6}\s+)/m)
    .filter(Boolean)
    .map((block) => {
      const [titleLine, ...rest] = block.split("\n");
      const title = titleLine.replace(/^#+\s*/, "").trim();
      const text = rest
        .join("\n")
        .replace(/^#{1,6}\s+/gm, "") // safety: heading rimasti nel corpo
        .trim();
      return { title, text };
    })
    .filter((section) => {
      if (!section.title) return false;
      const key = section.title.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
      if (key === "incantesimi noti" || key === "incantesimi") return false;
      if (hide.has(key)) return false;
      // Nascondi sezioni vuote / placeholder LLM
      const plain = section.text
        .replace(/[-*]\s*/g, "")
        .replace(/\*+/g, "")
        .replace(/[()]/g, "")
        .trim()
        .toLowerCase();
      if (!plain || plain === "vuoto" || plain === "n/d" || plain === "nd") return false;
      // Sul PG la relazione con se stesso e' rumore
      if (key === "relazione col giocatore" && plain === "0") return false;
      return true;
    });

  return (
    <div className={`sheet-sections sheet-sections--${layout}`}>
      {sections.map((section) => (
        <article className="sheet-section" key={section.title}>
          <h3>{section.title}</h3>
          {section.text ? (
            <p style={{ whiteSpace: "pre-wrap" }}>{section.text}</p>
          ) : (
            <p className="muted">—</p>
          )}
        </article>
      ))}
    </div>
  );
}

function CollapsibleBlock({
  title,
  open,
  onToggle,
  children,
  className = "",
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`block${className ? ` ${className}` : ""}${open ? "" : " collapsed"}`}>
      <button
        type="button"
        className="block-toggle"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="block-chevron" aria-hidden>
          ▸
        </span>
        <h2>{title}</h2>
      </button>
      {open ? <div className="block-body">{children}</div> : null}
    </section>
  );
}

function turnsLeft(everyN: number, since: number): number {
  return Math.max(0, everyN - since);
}

function TurnCounters({
  reviewSince,
  consSince,
  reviewEvery,
  consEvery,
}: {
  reviewSince: number;
  consSince: number;
  reviewEvery: number;
  consEvery: number;
}) {
  const reviewLeft = turnsLeft(reviewEvery, reviewSince);
  const consLeft = turnsLeft(consEvery, consSince);
  const reviewOverdue = reviewSince >= reviewEvery;
  const consOverdue = consSince >= consEvery;
  return (
    <span className="turn-counters" aria-label="Contatori review">
      <span
        className={`turn-chip${reviewOverdue ? " overdue" : ""}`}
        title={
          reviewOverdue
            ? "Present review in ritardo (retry al prossimo turno)"
            : `Present review tra ${reviewLeft} turni`
        }
      >
        R {reviewOverdue ? "!" : reviewLeft}
      </span>
      <span
        className={`turn-chip${consOverdue ? " overdue" : ""}`}
        title={
          consOverdue
            ? "Consolidamento in ritardo (retry al prossimo turno)"
            : `Consolidamento tra ${consLeft} turni`
        }
      >
        C {consOverdue ? "!" : consLeft}
      </span>
    </span>
  );
}

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [playerName, setPlayerName] = useState("Avventuriero");
  const [state, setState] = useState<GameState | null>(null);
  const [config, setConfig] = useState<AppConfig>({
    present_review_every_n: 5,
    consolidate_every_n: 12,
  });
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [waitingReply, setWaitingReply] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [undoCount, setUndoCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saves, setSaves] = useState<SessionSummary[]>([]);
  const [stories, setStories] = useState<StorySummary[]>([]);
  const [storyId, setStoryId] = useState("overlord");
  const [startView, setStartView] = useState<StartView>("home");
  const [wizardStep, setWizardStep] = useState<WizardStep>("story");
  const [origin, setOrigin] = useState<"lore" | "custom">("custom");
  const [playable, setPlayable] = useState<PlayableCharacter[]>([]);
  const [races, setRaces] = useState<RaceOption[]>([]);
  const [fronts, setFronts] = useState<FrontOption[]>([]);
  const [loreCharacterId, setLoreCharacterId] = useState("");
  const [loreSheet, setLoreSheet] = useState<CharacterSheet | null>(null);
  const [loreSheetLoading, setLoreSheetLoading] = useState(false);
  const [raceId, setRaceId] = useState("");
  const [details, setDetails] = useState("");
  const [startMode, setStartMode] = useState<"arc" | "free">("arc");
  const [frontId, setFrontId] = useState("");
  const [sheet, setSheet] = useState<CharacterSheet | null>(null);
  const [spellbook, setSpellbook] = useState<Spellbook | null>(null);
  const [arcTimeline, setArcTimeline] = useState<ArcTimeline | null>(null);
  const [inputTokens, setInputTokens] = useState<number | null>(null);
  const [prevInputTokens, setPrevInputTokens] = useState<number | null>(null);
  const [cachedTokens, setCachedTokens] = useState<number>(0);
  const [reviewTokens, setReviewTokens] = useState<number>(0);
  const [panelOpen, setPanelOpen] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 861px)").matches,
  );
  const [openSections, setOpenSections] = useState<Record<PanelSection, boolean>>({
    arc: true,
    situations: true,
    sheet: true,
    spellbook: true,
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  function toggleSection(key: PanelSection) {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 861px)");
    const sync = () => {
      if (mq.matches) setPanelOpen(true);
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    getConfig().then(setConfig).catch(() => {
      /* fallback già in state iniziale */
    });
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, waitingReply]);

  useEffect(() => {
    if (sessionId) return;
    Promise.all([listSessions(), listStories()])
      .then(([nextSaves, nextStories]) => {
        setSaves(nextSaves);
        setStories(nextStories);
        if (nextStories.length && !nextStories.some((s) => s.id === storyId)) {
          setStoryId(nextStories[0].id);
        }
      })
      .catch((e) => {
        setSaves([]);
        setStories([]);
        setError(
          `API non raggiungibile (${String(e)}). Riavvia il frontend dopo l'update, backend su --host 0.0.0.0.`,
        );
      });
  }, [sessionId]);

  useEffect(() => {
    if (sessionId || !storyId) return;
    let cancelled = false;
    Promise.all([listPlayable(storyId), listRaces(storyId), listFronts(storyId)])
      .then(([nextPlayable, nextRaces, nextFronts]) => {
        if (cancelled) return;
        setPlayable(nextPlayable);
        setRaces(nextRaces);
        setFronts(nextFronts);
        setLoreCharacterId((prev) =>
          nextPlayable.some((p) => p.id === prev) ? prev : nextPlayable[0]?.id ?? "",
        );
        setRaceId((prev) => (nextRaces.some((r) => r.id === prev) ? prev : nextRaces[0]?.id ?? ""));
        const story = stories.find((s) => s.id === storyId);
        const preferred = story?.default_front || nextFronts[0]?.id || "";
        setFrontId((prev) => (nextFronts.some((f) => f.id === prev) ? prev : preferred));
      })
      .catch(() => {
        if (cancelled) return;
        setPlayable([]);
        setRaces([]);
        setFronts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, storyId, stories]);

  useEffect(() => {
    if (sessionId || startView !== "create" || origin !== "lore" || !storyId || !loreCharacterId) {
      return;
    }
    let cancelled = false;
    setLoreSheetLoading(true);
    getPlayableSheet(storyId, loreCharacterId)
      .then((sheet) => {
        if (!cancelled) setLoreSheet(sheet);
      })
      .catch(() => {
        if (!cancelled) setLoreSheet(null);
      })
      .finally(() => {
        if (!cancelled) setLoreSheetLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, startView, origin, storyId, loreCharacterId]);

  useEffect(() => {
    if (!sessionId) return;
    Promise.all([
      getState(sessionId),
      getChat(sessionId),
      getPlayerSheet(sessionId).catch(() => null),
      getSpellbook(sessionId).catch(() => null),
      getArcTimeline(sessionId).catch(() => null),
      getCanUndo(sessionId).catch(() => ({ can_undo: false, undo_count: 0 })),
    ])
      .then(([nextState, chat, nextSheet, nextBook, nextArc, undo]) => {
        setState(nextState);
        setMessages(chat.map((m) => ({ role: m.role, content: m.content })));
        setSheet(nextSheet);
        setSpellbook(nextBook);
        setArcTimeline(nextArc);
        setCanUndo(undo.can_undo);
        setUndoCount(undo.undo_count);
      })
      .catch((e) => {
        setError(String(e));
        setSessionId(null);
      });
  }, [sessionId]);

  function resumeGame(id: string) {
    setSessionId(id);
    setPanelOpen(false);
  }

  async function refreshSaves() {
    try {
      setSaves(await listSessions());
    } catch {
      /* ignore list refresh errors on home */
    }
  }

  async function removeSave(id: string, playerLabel: string) {
    const ok = window.confirm(
      `Eliminare l'avventura di ${playerLabel}?\nVerranno cancellati chat, stato e wiki di sessione. Irreversibile.`,
    );
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      await deleteSession(id);
      if (sessionId === id) leaveGame();
      await refreshSaves();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function leaveGame() {
    setSessionId(null);
    setState(null);
    setSheet(null);
    setSpellbook(null);
    setArcTimeline(null);
    setMessages([]);
    setInputTokens(null);
    setPrevInputTokens(null);
    setCachedTokens(0);
    setReviewTokens(0);
    setCanUndo(false);
    setUndoCount(0);
    setPanelOpen(false);
    setStartView("home");
    setWizardStep("story");
    void refreshSaves();
  }

  function openCreateView() {
    setError(null);
    setWizardStep("story");
    setStartView("create");
  }

  function closeCreateView() {
    setStartView("home");
    setWizardStep("story");
    setError(null);
  }

  function canAdvanceDetails(): boolean {
    if (origin === "lore") return Boolean(loreCharacterId);
    return Boolean(playerName.trim() && raceId);
  }

  async function startGame() {
    setLoading(true);
    setError(null);
    try {
      const res = await createSession({
        player_name: origin === "lore" ? "—" : playerName.trim() || "Avventuriero",
        story_id: storyId,
        origin,
        character_id: origin === "lore" ? loreCharacterId : null,
        race: origin === "custom" ? raceId : null,
        details: origin === "custom" ? details : "",
        start_mode: startMode,
        front_id:
          startMode === "arc"
            ? frontId || null
            : startMode === "free" && frontId
              ? frontId
              : null,
      });
      setSessionId(res.session_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleSend() {
    if (!sessionId || !input.trim() || waitingReply) return;
    const text = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setWaitingReply(true);
    setError(null);
    try {
      const res = await sendChat(sessionId, text);
      setState({ ...res.state });
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
      setPrevInputTokens(inputTokens);
      setInputTokens(res.input_tokens ?? null);
      setCachedTokens(res.input_tokens_cached ?? 0);
      setReviewTokens(res.review_tokens ?? 0);
      setCanUndo(Boolean(res.can_undo));
      setUndoCount(Number(res.undo_count ?? 0));
      setSheet(await getPlayerSheet(sessionId));
      setSpellbook(await getSpellbook(sessionId).catch(() => null));
      setArcTimeline(await getArcTimeline(sessionId).catch(() => null));
    } catch (e) {
      setError(String(e));
      setMessages((prev) => prev.slice(0, -1));
      const undo = await getCanUndo(sessionId).catch(() => ({ can_undo: false, undo_count: 0 }));
      setCanUndo(undo.can_undo);
      setUndoCount(undo.undo_count);
    } finally {
      setWaitingReply(false);
    }
  }

  async function handleUndoLastTurn() {
    if (!sessionId || !canUndo || waitingReply || loading) return;
    const ok = window.confirm(
      "Annullare l'ultimo turno?\nTornerai allo stato precedente (chat, mondo e wiki di sessione).",
    );
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      const res = await undoLastTurn(sessionId);
      setState({ ...res.state });
      setMessages(res.messages.map((m) => ({ role: m.role, content: m.content })));
      setCanUndo(Boolean(res.can_undo));
      setUndoCount(Number(res.undo_count ?? 0));
      setSheet(await getPlayerSheet(sessionId));
      setSpellbook(await getSpellbook(sessionId).catch(() => null));
      setArcTimeline(await getArcTimeline(sessionId).catch(() => null));
    } catch (e) {
      setError(String(e));
      const undo = await getCanUndo(sessionId).catch(() => ({ can_undo: false, undo_count: 0 }));
      setCanUndo(undo.can_undo);
      setUndoCount(undo.undo_count);
    } finally {
      setLoading(false);
    }
  }

  if (!sessionId) {
    const storyName = stories.find((s) => s.id === storyId)?.name ?? "Overlord";

    if (startView === "create") {
      const stepIndex = (["story", "origin", "details", "mode"] as const).indexOf(wizardStep);
      return (
        <div className="create-screen">
          <div className="create-veil" />
          <header className="create-top">
            <button type="button" className="btn ghost" onClick={closeCreateView} disabled={loading}>
              ← Esci
            </button>
            <div className="create-top-copy">
              <p className="create-kicker">{storyName}</p>
              <h1>Crea personaggio</h1>
            </div>
            <ol className="wizard-steps" aria-label="Passi creazione">
              {(
                [
                  ["story", "Storia"],
                  ["origin", "Origine"],
                  ["details", "Personaggio"],
                  ["mode", "Partenza"],
                ] as const
              ).map(([key, label], i) => (
                <li
                  key={key}
                  className={`wizard-step${wizardStep === key ? " active" : ""}${i < stepIndex ? " done" : ""}`}
                >
                  <span className="wizard-step-num">{i + 1}</span>
                  <span className="wizard-step-label">{label}</span>
                </li>
              ))}
            </ol>
          </header>

          <main className={`create-main${wizardStep === "details" && origin === "lore" ? " create-main--sheet" : ""}`}>
            {wizardStep === "story" && (
              <section className="create-card create-card--narrow">
                <label className="field">
                  <span>Ambientazione</span>
                  <select value={storyId} onChange={(e) => setStoryId(e.target.value)} disabled={!stories.length}>
                    {(stories.length ? stories : [{ id: "overlord", name: "Overlord" }]).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              </section>
            )}

            {wizardStep === "origin" && (
              <section className="create-card">
                <h2>Origine del personaggio</h2>
                <p className="lede">Vuoi interpretare qualcuno della lore, oppure crearne uno nuovo?</p>
                <div className="choice-row choice-row--wide">
                  <button
                    type="button"
                    className={`choice-card${origin === "lore" ? " selected" : ""}`}
                    onClick={() => setOrigin("lore")}
                  >
                    <strong>Personaggio lore</strong>
                    <span>Scheda canonica già scritta: nome, poteri e relazioni restano fissi.</span>
                  </button>
                  <button
                    type="button"
                    className={`choice-card${origin === "custom" ? " selected" : ""}`}
                    onClick={() => setOrigin("custom")}
                  >
                    <strong>Personaggio libero</strong>
                    <span>Scegli razza e dettagli; la scheda viene generata per questa partita.</span>
                  </button>
                </div>
              </section>
            )}

            {wizardStep === "details" && origin === "lore" && (
              <section className="lore-create">
                <div className="lore-create-toolbar">
                  <label className="field">
                    <span>Personaggio</span>
                    <select
                      value={loreCharacterId}
                      onChange={(e) => setLoreCharacterId(e.target.value)}
                      disabled={!playable.length}
                    >
                      {playable.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {loreSheet ? (
                    <div className="lore-create-meta">
                      <h2>{loreSheet.name}</h2>
                      <p className="muted">Scheda canonica · sola lettura</p>
                      <SheetMetaChips sheet={loreSheet} />
                    </div>
                  ) : null}
                </div>
                <div className="lore-create-body">
                  {loreSheetLoading ? (
                    <p className="muted">Caricamento scheda…</p>
                  ) : loreSheet ? (
                    <>
                      <SheetBody
                        body={loreSheet.body}
                        layout="grid"
                        hideTitles={["Personalità", "Personalita", "Obiettivi", "Obiettivo", "Allineamento"]}
                      />
                      {loreSheet.spells && loreSheet.spells.length > 0 ? (
                        <section className="lore-spellbook">
                          <h3>Spellbook (seed lore)</h3>
                          <p className="muted small">
                            Magie documentate: base di partenza, espandibile in chat.
                          </p>
                          <ul className="spell-list">
                            {loreSheet.spells.map((sp) => (
                              <li key={sp.name}>
                                <strong>{sp.name}</strong>
                                {sp.description ? <span className="muted"> — {sp.description}</span> : null}
                              </li>
                            ))}
                          </ul>
                        </section>
                      ) : (
                        <p className="muted lore-spellbook-empty">Nessuno spellbook seed per questo personaggio.</p>
                      )}
                    </>
                  ) : (
                    <p className="muted">Scheda non disponibile.</p>
                  )}
                </div>
              </section>
            )}

            {wizardStep === "details" && origin === "custom" && (
              <section className="create-card create-card--form">
                <h2>Definisci il personaggio</h2>
                <p className="lede">
                  Indica razza e ciò che conta per te; il resto della scheda verrà completato in coerenza col setting.
                </p>
                <div className="create-form-grid">
                  <label className="field">
                    <span>Nome</span>
                    <input
                      value={playerName}
                      onChange={(e) => setPlayerName(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <label className="field">
                    <span>Razza</span>
                    <select value={raceId} onChange={(e) => setRaceId(e.target.value)} disabled={!races.length}>
                      {races.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field create-form-span">
                    <span>Dettagli (classe, livello, equip, tono di gioco…)</span>
                    <textarea
                      className="details-input"
                      value={details}
                      onChange={(e) => setDetails(e.target.value)}
                      rows={8}
                      placeholder="Es. player YGGDRASIL lv 100, classi necromancer, equip da dungeon…"
                    />
                  </label>
                </div>
              </section>
            )}

            {wizardStep === "mode" && (
              <section className="create-card">
                <h2>Come vuoi iniziare?</h2>
                <p className="lede">
                  Puoi seguire un arco narrativo oppure muoverti liberamente, anche dopo un arco già accaduto.
                </p>
                <div className="choice-row choice-row--wide">
                  <button
                    type="button"
                    className={`choice-card${startMode === "arc" ? " selected" : ""}`}
                    onClick={() => {
                      setStartMode("arc");
                      if (!frontId && fronts[0]) setFrontId(fronts[0].id);
                    }}
                  >
                    <strong>Arco narrativo</strong>
                    <span>Eventi e cursori d&apos;arco attivi fin dall&apos;inizio.</span>
                  </button>
                  <button
                    type="button"
                    className={`choice-card${startMode === "free" ? " selected" : ""}`}
                    onClick={() => {
                      setStartMode("free");
                      setFrontId("");
                    }}
                  >
                    <strong>Mondo libero</strong>
                    <span>Nessuno script beat: puoi collocare la partita dopo un arco già vissuto.</span>
                  </button>
                </div>
                {startMode === "arc" && (
                  <label className="field create-arc-field">
                    <span>Arco</span>
                    <select value={frontId} onChange={(e) => setFrontId(e.target.value)} disabled={!fronts.length}>
                      {fronts.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {startMode === "free" && (
                  <label className="field create-arc-field">
                    <span>Collocazione nella storia</span>
                    <select value={frontId} onChange={(e) => setFrontId(e.target.value)} disabled={!fronts.length}>
                      <option value="">Seed iniziale (nessun arco passato)</option>
                      {fronts.map((f) => (
                        <option key={f.id} value={f.id}>
                          Dopo: {f.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </section>
            )}

            <OfflineBanner />
            {error && <p className="error create-error">{error}</p>}
          </main>

          <footer className="create-footer">
            <button
              type="button"
              className="btn ghost"
              disabled={loading}
              onClick={() => {
                if (wizardStep === "story") closeCreateView();
                else if (wizardStep === "origin") setWizardStep("story");
                else if (wizardStep === "details") setWizardStep("origin");
                else setWizardStep("details");
              }}
            >
              Indietro
            </button>
            {wizardStep !== "mode" ? (
              <button
                type="button"
                className="btn primary"
                disabled={
                  loading ||
                  !stories.length ||
                  (wizardStep === "details" && !canAdvanceDetails())
                }
                onClick={() => {
                  if (wizardStep === "story") setWizardStep("origin");
                  else if (wizardStep === "origin") setWizardStep("details");
                  else setWizardStep("mode");
                }}
              >
                Continua
              </button>
            ) : (
              <button
                type="button"
                className="btn primary"
                onClick={startGame}
                disabled={loading || !stories.length || (startMode === "arc" && !frontId)}
              >
                {loading
                  ? origin === "custom"
                    ? "Generazione scheda…"
                    : "Creazione…"
                  : "Inizia avventura"}
              </button>
            )}
          </footer>
        </div>
      );
    }

    return (
      <div className="start-screen">
        <div className="start-veil" />
        <div className="start-panel">
          <OfflineBanner />
          <p className="brand">{storyName}</p>
          <h1>Simulatore narrativo</h1>
          <p className="lede">Esplora il mondo. Ogni avventura ha la sua wiki isolata.</p>
          <label className="field">
            <span>Storia</span>
            <select value={storyId} onChange={(e) => setStoryId(e.target.value)} disabled={!stories.length}>
              {(stories.length ? stories : [{ id: "overlord", name: "Overlord" }]).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn primary"
            onClick={openCreateView}
            disabled={loading || !stories.length}
          >
            Crea personaggio
          </button>
          <section className="saves">
            <h2>Avventure precedenti</h2>
            {saves.length === 0 ? (
              <p className="muted">Nessuna avventura salvata.</p>
            ) : (
              <ul>
                {saves.map((save) => (
                  <li key={save.session_id} className="save-row">
                    <button className="save-card" onClick={() => resumeGame(save.session_id)} disabled={loading}>
                      <span className="save-name">
                        {save.player_name}
                        {save.active ? " · in corso" : ""}
                      </span>
                      <span className="save-meta">
                        {save.story_name} · {save.location} · {save.time}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="save-delete"
                      disabled={loading}
                      aria-label={`Elimina avventura di ${save.player_name}`}
                      onClick={() => void removeSave(save.session_id, save.player_name)}
                    >
                      Elimina
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {error && <p className="error">{error}</p>}
          <PwaInstall />
        </div>
      </div>
    );
  }

  const reviewSince = state?.turns_since_present_review ?? 0;
  const consSince = state?.turns_since_consolidation ?? 0;

  return (
    <div className="shell">
      {panelOpen && (
        <button type="button" className="scrim visible" aria-label="Chiudi pannello" onClick={() => setPanelOpen(false)} />
      )}

      <aside className={`panel ${panelOpen ? "open" : ""}`}>
        <header className="panel-top">
          <button type="button" className="icon-btn panel-close" onClick={() => setPanelOpen(false)} aria-label="Chiudi pannello">
            ✕
          </button>
          <div className="panel-heading">
            <div className="panel-brand-row">
              <span className="panel-brand">
                {stories.find((s) => s.id === (state?.story_id ?? storyId))?.name
                  ?? state?.story_id
                  ?? "Avventura"}
              </span>
              <TurnCounters
                reviewSince={reviewSince}
                consSince={consSince}
                reviewEvery={config.present_review_every_n}
                consEvery={config.consolidate_every_n}
              />
            </div>
            <span className="panel-subtitle">
              {state?.player.name ?? "Avventura"}
              {state?.time ? ` · ${state.time}` : ""}
              {state?.player.location ? ` · ${state.player.location}` : ""}
            </span>
          </div>
          <button type="button" className="icon-btn" onClick={leaveGame} aria-label="Torna alla scelta storia">
            ←
          </button>
        </header>

        <div className="panel-body">
          <section className="block">
            <h2>Stato</h2>
            <dl className="meta">
              <div>
                <dt>Luogo</dt>
                <dd>{state?.player.location ?? "—"}</dd>
              </div>
              <div>
                <dt>Tempo</dt>
                <dd>{state?.time ?? "—"}</dd>
              </div>
              <div>
                <dt>Party</dt>
                <dd>{state?.party_active ?? "—"}</dd>
              </div>
              <div>
                <dt>Presenti</dt>
                <dd>{state?.characters_active?.join(", ") || "—"}</dd>
              </div>
            </dl>
          </section>

          <CollapsibleBlock
            title="Arco canonico"
            open={openSections.arc}
            onToggle={() => toggleSection("arc")}
          >
            {arcTimeline?.fronts?.length ? (
              arcTimeline.fronts.map((front) => (
                <div className="arc-front" key={front.id}>
                  <p className="arc-front-name">
                    {front.name}
                    <span className="muted"> · {front.status}</span>
                  </p>
                  <ol className="arc-timeline">
                    {front.beats.map((beat) => (
                      <li key={beat.id} className={`arc-beat arc-${beat.status}`}>
                        <div className="arc-beat-head">
                          <span className={`arc-badge arc-badge-${beat.status}`}>
                            {ARC_STATUS_LABEL[beat.status] ?? beat.status}
                          </span>
                          <strong>{beat.title}</strong>
                          {beat.due_time ? (
                            <span className="muted"> · {beat.due_time}</span>
                          ) : beat.estimated_day != null ? (
                            <span className="muted"> · ~G{beat.estimated_day}</span>
                          ) : null}
                        </div>
                        <p className="muted arc-beat-meta">
                          {beat.place}
                          {beat.hours_after_previous != null && beat.hours_after_previous >= 24
                            ? ` · +${Math.round(beat.hours_after_previous / 24)}g dal precedente`
                            : ""}
                        </p>
                        {beat.summary ? <p className="arc-beat-summary">{beat.summary}</p> : null}
                      </li>
                    ))}
                  </ol>
                </div>
              ))
            ) : (
              <p className="muted">Nessun arco attivo.</p>
            )}
          </CollapsibleBlock>

          <CollapsibleBlock
            title="Situazioni"
            open={openSections.situations}
            onToggle={() => toggleSection("situations")}
          >
            {state?.situations?.length ? (
              <ul className="chips">
                {state.situations.map((s) => {
                  const id = typeof s === "string" ? s : s.id;
                  const text = typeof s === "string" ? s : s.summary;
                  return <li key={id}>{text}</li>;
                })}
              </ul>
            ) : (
              <p className="muted">Nessuna situazione attiva.</p>
            )}
          </CollapsibleBlock>

          {sheet && (
            <CollapsibleBlock
              key={`${sheet.id}-${sheet.body.length}-${sheet.body.slice(0, 40)}`}
              title="Scheda"
              className="sheet"
              open={openSections.sheet}
              onToggle={() => toggleSection("sheet")}
            >
              <p className="sheet-name">{sheet.name}</p>
              {sheet.location ? <p className="muted">{sheet.location}</p> : null}
              <SheetMetaChips sheet={sheet} />
              <SheetBody body={sheet.body} />
            </CollapsibleBlock>
          )}

          <CollapsibleBlock
            title="Spellbook"
            className="sheet"
            open={openSections.spellbook}
            onToggle={() => toggleSection("spellbook")}
          >
            {spellbook?.spells?.length ? (
              <ul className="spell-list">
                {spellbook.spells.map((sp) => (
                  <li key={sp.name}>
                    <strong>{sp.name}</strong>
                    {sp.description ? <span className="muted"> — {sp.description}</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Nessun incantesimo. Definisci il primo con [Nome — descrizione].</p>
            )}
          </CollapsibleBlock>
        </div>
      </aside>

      <main className="chat">
        <header className="chat-bar">
          <button
            type="button"
            className="icon-btn menu-btn"
            onClick={() => setPanelOpen((open) => !open)}
            aria-label={panelOpen ? "Chiudi menu" : "Apri menu"}
            aria-expanded={panelOpen}
          >
            ☰
          </button>
          <button
            type="button"
            className="btn ghost undo-turn-btn"
            disabled={!canUndo || waitingReply || loading}
            onClick={() => void handleUndoLastTurn()}
            title={
              canUndo
                ? `Annulla l'ultimo turno (${undoCount} disponibili)`
                : "Nessun turno da annullare"
            }
          >
            Annulla turno{undoCount > 0 ? ` (${undoCount})` : ""}
          </button>
          {inputTokens != null && (
            <span
              className="token-chip"
              title={
                [
                  prevInputTokens != null
                    ? `Input narratore. Precedente: ${prevInputTokens.toLocaleString("it-IT")} (Δ ${inputTokens - prevInputTokens >= 0 ? "+" : ""}${(inputTokens - prevInputTokens).toLocaleString("it-IT")})`
                    : "Token in input al narratore (system + contesto JSON)",
                  cachedTokens > 0 ? `Cached: ${cachedTokens.toLocaleString("it-IT")}` : null,
                  reviewTokens > 0 ? `Review questo turno: ${reviewTokens.toLocaleString("it-IT")}` : null,
                ]
                  .filter(Boolean)
                  .join(". ")
              }
            >
              ctx {inputTokens.toLocaleString("it-IT")}
              {prevInputTokens != null && (
                <span className={`token-delta${inputTokens - prevInputTokens > 0 ? " up" : inputTokens - prevInputTokens < 0 ? " down" : ""}`}>
                  {inputTokens - prevInputTokens > 0 ? "+" : ""}
                  {(inputTokens - prevInputTokens).toLocaleString("it-IT")}
                </span>
              )}
              {reviewTokens > 0 && (
                <span className="token-delta up"> +rev {reviewTokens.toLocaleString("it-IT")}</span>
              )}
            </span>
          )}
        </header>
        <OfflineBanner />

        <div className="messages">
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.content}
            </div>
          ))}
          {waitingReply && (
            <div className="msg assistant typing" aria-label="In attesa di risposta">
              <span />
              <span />
              <span />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onFocus={() => setPanelOpen(false)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Cosa fai?"
            rows={2}
            disabled={waitingReply}
          />
          <button className="btn primary" onClick={handleSend} disabled={waitingReply || !input.trim()}>
            Invia
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </main>
    </div>
  );
}

export default App;
