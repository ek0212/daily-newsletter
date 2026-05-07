/* global React, ReactDOM */
const { useState, useEffect, useMemo, useRef } = React;
const D = window.BRIEFING_DATA;

// ── localStorage helpers ────────────────────────────────
const LS = {
  get(k, fallback) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

async function sha256(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// ── Star button (save to stash) ─────────────────────────
function Star({ id, section, title, meta, onAuthRequired }) {
  const { stash, toggle, user } = useStash();
  const saved = !!stash.find(x => x.id === id);
  return (
    <button
      className="star-btn"
      aria-pressed={saved}
      title={saved ? "Remove from stash" : "Save to stash"}
      onClick={(e) => {
        e.preventDefault();
        if (!user) { onAuthRequired(); return; }
        toggle({ id, section, title, meta, savedFrom: D.issue, savedAt: new Date().toISOString() });
      }}
    />
  );
}

// ── Stash + auth context (simple module-level store) ───
const stashListeners = new Set();
let _stash = LS.get("mb.stash", []);
let _user = LS.get("mb.user", null);
function useStash() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force(x => x + 1);
    stashListeners.add(fn);
    return () => stashListeners.delete(fn);
  }, []);
  return {
    stash: _stash,
    user: _user,
    toggle(item) {
      const exists = _stash.find(x => x.id === item.id);
      _stash = exists ? _stash.filter(x => x.id !== item.id) : [item, ..._stash];
      LS.set("mb.stash", _stash);
      stashListeners.forEach(fn => fn());
    },
    remove(ids) {
      _stash = _stash.filter(x => !ids.includes(x.id));
      LS.set("mb.stash", _stash);
      stashListeners.forEach(fn => fn());
    },
    setUser(u) { _user = u; LS.set("mb.user", u); stashListeners.forEach(fn => fn()); },
  };
}

// ── Auth modal ──────────────────────────────────────────
function AuthModal({ onClose }) {
  const [tab, setTab] = useState("login");
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [msg, setMsg] = useState("");
  const { setUser } = useStash();

  async function submit(e) {
    e.preventDefault();
    setMsg("");
    if (!u || p.length < 4) { setMsg("Username required, password ≥ 4 chars."); return; }
    const hash = await sha256(p);
    const users = LS.get("mb.users", {});
    if (tab === "register") {
      if (users[u]) { setMsg("That username is taken."); return; }
      users[u] = hash;
      LS.set("mb.users", users);
      setUser({ name: u });
      onClose();
    } else {
      if (!users[u]) { setMsg("No such user. Try registering."); return; }
      if (users[u] !== hash) { setMsg("Wrong password."); return; }
      setUser({ name: u });
      onClose();
    }
  }

  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 440 }} onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h3>The Subscriber's Desk</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="auth-tabs">
            <button className={tab === "login" ? "on" : ""} onClick={() => setTab("login")}>Sign In</button>
            <button className={tab === "register" ? "on" : ""} onClick={() => setTab("register")}>Register</button>
          </div>
          <form className="auth-form" onSubmit={submit}>
            <label>Username</label>
            <input value={u} onChange={e => setU(e.target.value)} autoFocus />
            <label>Password</label>
            <input type="password" value={p} onChange={e => setP(e.target.value)} />
            {msg && <div className="auth-msg">{msg}</div>}
            <p style={{ fontSize: 12, fontStyle: "italic", color: "var(--ink-faint)", margin: 0 }}>
              Credentials are hashed (SHA-256) and stored locally. No server, no transmission.
            </p>
            <button className="btn btn-primary" type="submit" style={{ alignSelf: "flex-start" }}>
              {tab === "login" ? "Sign In" : "Create Account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

// ── Stash modal (with select/copy/delete + script gen) ─
function StashModal({ onClose }) {
  const { stash, remove } = useStash();
  const [selected, setSelected] = useState(new Set());
  const [genOpen, setGenOpen] = useState(false);

  const groups = useMemo(() => {
    const g = {};
    stash.forEach(x => { (g[x.savedFrom] = g[x.savedFrom] || []).push(x); });
    return Object.entries(g).sort((a, b) => b[0].localeCompare(a[0]));
  }, [stash]);

  function toggle(id) {
    setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }

  function copy() {
    const items = stash.filter(x => selected.has(x.id));
    const text = items.map(x => `[${x.section}] ${x.title}\n  ${x.meta || ""}`).join("\n\n");
    navigator.clipboard.writeText(text).then(() => alert(`Copied ${items.length} item${items.length === 1 ? "" : "s"} to clipboard.`));
  }

  function del() {
    if (!selected.size) return;
    if (!confirm(`Delete ${selected.size} item${selected.size === 1 ? "" : "s"} from stash?`)) return;
    remove([...selected]);
    setSelected(new Set());
  }

  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h3>My Stash · {stash.length} item{stash.length === 1 ? "" : "s"}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {!stash.length && (
            <p style={{ fontStyle: "italic", color: "var(--ink-soft)" }}>
              Nothing saved yet. Tap the ☆ next to any article, video, or paper.
            </p>
          )}
          {stash.length > 0 && (
            <div className="stash-controls">
              <button className="btn" onClick={() => setSelected(new Set(stash.map(x => x.id)))}>Select All</button>
              <button className="btn" onClick={() => setSelected(new Set())}>Select None</button>
              <button className="btn" disabled={!selected.size} onClick={copy}>Copy</button>
              <button className="btn btn-danger" disabled={!selected.size} onClick={del}>Delete</button>
              <span className="count">{selected.size} selected</span>
            </div>
          )}
          {groups.map(([date, items]) => (
            <div className="stash-group" key={date}>
              <h4>Issue · {date}</h4>
              {items.map(it => (
                <label className="stash-item" key={it.id}>
                  <input type="checkbox" checked={selected.has(it.id)} onChange={() => toggle(it.id)} />
                  <div>
                    <span className="stash-section-badge">{it.section}</span>
                    <span className="ttl">{it.title}</span>
                    {it.meta && <div className="meta">{it.meta}</div>}
                  </div>
                  <span className="meta">{new Date(it.savedAt).toLocaleDateString()}</span>
                </label>
              ))}
            </div>
          ))}
          {genOpen && <ScriptGen items={stash.filter(x => selected.has(x.id))} onClose={() => setGenOpen(false)} />}
        </div>
        <div className="modal-foot">
          <button
            className="btn btn-primary"
            disabled={!selected.size}
            onClick={() => setGenOpen(true)}
            title={selected.size ? "Generate spoken script from selection" : "Select items first"}
          >
            ✦ Generate Script ({selected.size})
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Script gen (uses Gemini key from localStorage; falls back to mock) ──
function ScriptGen({ items, onClose }) {
  const [key, setKey] = useState(LS.get("mb.geminiKey", ""));
  const [script, setScript] = useState("");
  const [loading, setLoading] = useState(false);

  async function generate() {
    LS.set("mb.geminiKey", key);
    setLoading(true);
    try {
      // Use built-in Claude helper as a stand-in so the prototype actually produces output
      const sources = items.map((x, i) => `${i + 1}. [${x.section}] ${x.title}${x.meta ? "\n   " + x.meta : ""}`).join("\n");
      const prompt = `Write a 2-3 minute spoken educational script (conversational, first-person, ~350 words) drawing from these saved items. No bullet points. Open with a hook, weave the items into a narrative, close with a takeaway.\n\nSAVED ITEMS:\n${sources}`;
      let out = "";
      if (window.claude && window.claude.complete) {
        out = await window.claude.complete(prompt);
      } else {
        out = mockScript(items);
      }
      setScript(out);
    } catch (e) {
      setScript(mockScript(items));
    }
    setLoading(false);
  }

  return (
    <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--rule)" }}>
      <h4 style={{ fontFamily: "var(--serif-display)", fontSize: 13, letterSpacing: ".18em", textTransform: "uppercase", margin: "0 0 10px" }}>
        Script Generator · {items.length} source{items.length === 1 ? "" : "s"}
      </h4>
      <p style={{ fontSize: 13, color: "var(--ink-soft)", margin: "0 0 8px", fontStyle: "italic" }}>
        Stored locally only. Used to call Gemini in the deployed site.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          className="auth-form"
          placeholder="Gemini API key (sk-...)"
          value={key}
          onChange={e => setKey(e.target.value)}
          style={{ flex: 1, minWidth: 220, padding: "8px 10px", border: "1px solid var(--rule)", background: "var(--paper)", fontFamily: "var(--mono)", fontSize: 13 }}
        />
        <button className="btn btn-primary" onClick={generate} disabled={loading || !items.length}>
          {loading ? "Composing…" : "Generate"}
        </button>
        <button className="btn" onClick={onClose}>Hide</button>
      </div>
      {script && (
        <>
          <div className="script-out">{script}</div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn" onClick={() => navigator.clipboard.writeText(script)}>Copy Script</button>
          </div>
        </>
      )}
    </div>
  );
}

function mockScript(items) {
  const t = items.map(x => x.title).slice(0, 3).join(", ");
  return `Good morning. I want to walk you through three threads I've been pulling on this week — ${t}. \n\nWhat ties them together is a quiet but real shift in how risk is being priced and modeled across very different domains…\n\n[Generated script would continue here. Provide a Gemini key above to produce a real one.]`;
}

// ── Sections ────────────────────────────────────────────
function SectionHead({ kicker, title, right }) {
  return (
    <div className="section-head">
      <span className="rule" />
      <h2>{title}</h2>
      <span className="rule" />
    </div>
  );
}

function Weather() {
  const w = D.weather;
  return (
    <section className="section">
      <SectionHead kicker="§ I" title="The Weather Watch" />
      <div className="weather">
        <div className="weather-now">
          <span className="weather-city">Manhattan · 6:00 AM EST</span>
          <span className="weather-temp">{w.temp}<span className="deg">°</span></span>
          <span className="weather-feels">Feels like {w.feels}°</span>
          <span className="weather-cond">{w.cond}</span>
          <div className="weather-stats">
            <div className="stat"><span className="lbl">High / Low</span><span className="val">{w.high}° / {w.low}°</span></div>
            <div className="stat"><span className="lbl">Humidity</span><span className="val">{w.humidity}%</span></div>
            <div className="stat"><span className="lbl">Wind</span><span className="val">{w.wind}</span></div>
            <div className="stat"><span className="lbl">Sunset</span><span className="val">{w.sunset}</span></div>
          </div>
        </div>
        <table className="weather-table">
          <caption>Hourly forecast — five-point</caption>
          <thead>
            <tr><th>Hour</th><th>Conditions</th><th>Temp</th><th>Feels</th><th>Precip</th><th>Hum.</th><th>Wind</th></tr>
          </thead>
          <tbody>
            {w.hourly.map((h, i) => (
              <tr key={i}>
                <td className="time">{h.t}</td>
                <td><span className="glyph">{h.glyph}</span>{h.cond}</td>
                <td>{h.temp}°</td>
                <td>{h.feels}°</td>
                <td>{h.prec}</td>
                <td>{h.hum}%</td>
                <td>{h.wind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Health() {
  const h = D.health;
  const rows = [
    { name: "Influenza", level: h.flu.level, text: h.flu.text },
    { name: "COVID-19",  level: h.covid.level, text: h.covid.text },
    { name: "RSV",       level: h.rsv.level, text: h.rsv.text },
  ];
  return (
    <section className="section">
      <SectionHead kicker="§ II" title="Public Health Watch" />
      <table className="health-table">
        <caption>NYC DOHMH · Respiratory illness, week of May 4</caption>
        <thead>
          <tr><th>Illness</th><th>Level</th></tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td><span className="health-dot" data-level={r.level} /> {r.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Events({ onAuthRequired }) {
  return (
    <section className="section">
      <SectionHead kicker="§ III" title="On the Block" />
      <div className="events">
        {D.events.map(ev => (
          <div className="event" key={ev.id}>
            <div className="event-date">
              <span className="mon">{ev.mon}</span>
              <span className="day">{ev.day}</span>
            </div>
            <div>
              <div className="event-name">
                <a href={`https://www.google.com/search?q=${encodeURIComponent(ev.name)}`} target="_blank" rel="noreferrer">
                  {ev.name}
                </a>
              </div>
              <div className="event-meta">{ev.meta}</div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
              <span className="event-time">{ev.time}</span>
              <Star id={ev.id} section="Events" title={ev.name} meta={ev.meta} onAuthRequired={onAuthRequired} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function News({ onAuthRequired }) {
  const lead = D.newsLead;
  return (
    <section className="section news">
      <SectionHead kicker="§ IV" title="The World This Morning" />
      <div className="news-grid">
        <div className="lead">
          <div className="story-cat" style={{ color: "var(--red)" }}><span style={{ marginRight: 6, fontSize: 14 }}>{lead.g}</span>{lead.cat}</div>
          <h3>{lead.h}</h3>
          <p className="deck">{lead.deck}</p>
          <p className="dropcap">{lead.body}</p>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
            <span className="byline">— {lead.by}</span>
            <Star id={lead.id} section="News" title={lead.h} meta={lead.by} onAuthRequired={onAuthRequired} />
          </div>
        </div>
        <div className="news-side">
          {D.newsSide.map(s => (
            <div className="story" key={s.id}>
              <div className="story-cat"><span style={{ marginRight: 5, fontSize: 13 }}>{s.g}</span>{s.cat}</div>
              <h4>{s.h}</h4>
              <p>{s.p}</p>
              <div className="story-foot">
                <span>{s.src} · {s.time}</span>
                <Star id={s.id} section="News" title={s.h} meta={s.src} onAuthRequired={onAuthRequired} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function YouTube({ onAuthRequired }) {
  return (
    <section className="section">
      <SectionHead kicker="§ V" title="From the Subscriptions" />
      <div className="tube-list">
        {D.videos.map(v => (
          <div className="tube" key={v.id}>
            <div className="tube-channel">{v.channel}</div>
            <h4>{v.h}</h4>
            <span className="tube-time">{v.time}</span>
            <Star id={v.id} section="Video" title={v.h} meta={v.channel} onAuthRequired={onAuthRequired} />
          </div>
        ))}
      </div>
    </section>
  );
}

function AISec({ onAuthRequired }) {
  return (
    <section className="section">
      <SectionHead kicker="§ VI" title="The Adversary's Desk" />
      <div className="ai-tldr">
        <span className="lbl">TL;DR</span>{D.aiTldr}
      </div>
      <div className="ai-grid">
        {D.ai.map(a => (
          <div className="paper-item" key={a.id}>
            <div className="src">{a.src}</div>
            <h4>{a.h}</h4>
            <p>{a.p}</p>
            <div className="badges">
              {a.badges.map((b, i) => <span className="badge" data-tone={b.tone} key={i}><span className="glyph">{b.g}</span>{b.t}</span>)}
            </div>
            <div className="paper-foot">
              <span className="cite-count">{a.cites > 0 ? `${a.cites} citations` : "Press · ungated"}</span>
              <Star id={a.id} section="AI Sec" title={a.h} meta={a.src} onAuthRequired={onAuthRequired} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Masthead + nav ──────────────────────────────────────
function Masthead() {
  return (
    <header className="mast">
      <h1 className="mast-title">The Midtown <em>Briefing</em></h1>
      <div className="mast-meta">
        <div>{D.date}</div>
        <div className="center">— ❖ —</div>
        <div className="right">
          <span className="edition-tag">{D.edition} · {D.editionTime}</span>
        </div>
      </div>
    </header>
  );
}

function ShellNav({ onStash, onAuth, onArchive }) {
  const { user, setUser, stash } = useStash();
  return (
    <nav className="shell-nav">
      <div className="brand">The Midtown Briefing</div>
      <div className="actions">
        <a href="index.html">Latest</a>
        <button onClick={onArchive}>Archive</button>
        <button onClick={onStash}>
          ★ My Stash{stash.length ? <span className="stash-count">{stash.length}</span> : null}
        </button>
        {user
          ? <button onClick={() => { if (confirm(`Sign out ${user.name}?`)) setUser(null); }}>{user.name} · Sign Out</button>
          : <button onClick={onAuth}>Sign In</button>}
      </div>
    </nav>
  );
}

// ── Archive modal (issue switcher) ──────────────────────
function ArchiveModal({ onClose }) {
  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Back Issues</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="archive">
            {D.archive.map(a => (
              <div className="archive-row" key={a.date}>
                <span className="date">
                  {a.label}
                  {a.latest && <span style={{ marginLeft: 8, color: "var(--red)", fontSize: 10 }}>● LATEST</span>}
                </span>
                <span className="blurb">{a.blurb}</span>
                <a className="go" href="#" onClick={e => { e.preventDefault(); alert(`In production this would navigate to posts/${a.date}.html`); }}>
                  Read
                </a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── App ────────────────────────────────────────────────
function App() {
  const [auth, setAuth] = useState(false);
  const [stash, setStash] = useState(false);
  const [archive, setArchive] = useState(false);

  return (
    <>
      <ShellNav
        onStash={() => setStash(true)}
        onAuth={() => setAuth(true)}
        onArchive={() => setArchive(true)}
      />
      <main className="paper">
        <Masthead />
        <Weather />
        <Health />
        <Events onAuthRequired={() => setAuth(true)} />
        <News onAuthRequired={() => setAuth(true)} />
        <YouTube onAuthRequired={() => setAuth(true)} />
        <AISec onAuthRequired={() => setAuth(true)} />
        <footer className="footer" />

      </main>
      {auth && <AuthModal onClose={() => setAuth(false)} />}
      {stash && <StashModal onClose={() => setStash(false)} />}
      {archive && <ArchiveModal onClose={() => setArchive(false)} />}
    </>
  );
}

window.MB_App = App;
