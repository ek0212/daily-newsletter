// Sample data for the May 7, 2026 morning edition
window.BRIEFING_DATA = {
  date: "Thursday, May 7, 2026",
  edition: "Morning Edition",
  editionTime: "6:00 AM",
  vol: "Vol. II · No. 127",
  issue: "2026-05-07",

  weather: {
    temp: 58,
    feels: 55,
    cond: "Partly cloudy with a coastal breeze",
    high: 67, low: 52,
    humidity: 64, wind: "NE 9 mph", uv: 5, sunset: "7:54 PM",
    hourly: [
      { t: "7 AM", glyph: "☼", cond: "Cool, clear",       temp: 54, feels: 51, prec: "0%",  hum: 72, wind: "NE 6"  },
      { t: "9 AM", glyph: "◐", cond: "Some clouds",       temp: 60, feels: 58, prec: "5%",  hum: 64, wind: "NE 8"  },
      { t: "3 PM", glyph: "☉", cond: "Sun returns",       temp: 67, feels: 67, prec: "10%", hum: 49, wind: "E 11"  },
      { t: "5 PM", glyph: "◐", cond: "Mostly cloudy",     temp: 65, feels: 64, prec: "20%", hum: 56, wind: "E 10"  },
      { t: "7 PM", glyph: "☁", cond: "Overcast, cooling", temp: 60, feels: 57, prec: "30%", hum: 68, wind: "NE 9"  },
    ],
  },

  health: {
    flu:   { level: "normal",    text: "Normal" },
    covid: { level: "elevated",  text: "Elevated" },
    rsv:   { level: "low",       text: "Low" },
    note: "COVID wastewater up 18% w/w — still below winter peak.",
  },

  events: [
    { id: "ev1", date: "May 7",  day: "07", mon: "MAY", time: "5:30 PM", name: "Hudson Yards Spring Market",       meta: "30th & 10th Ave · Permitted by NYC Parks · 3 hr" },
    { id: "ev2", date: "May 8",  day: "08", mon: "MAY", time: "12:00 PM", name: "Bryant Park Reading Room Opens",  meta: "42nd & 6th Ave · Free public event"               },
    { id: "ev3", date: "May 9",  day: "09", mon: "MAY", time: "All Day",  name: "Ninth Avenue International Food Festival", meta: "37th–57th St · Street fair, ~150 vendors" },
    { id: "ev4", date: "May 10", day: "10", mon: "MAY", time: "2:00 PM",  name: "Mother's Day Concert, Central Park", meta: "Naumburg Bandshell · Free seating"            },
    { id: "ev5", date: "May 11", day: "11", mon: "MAY", time: "7:00 PM",  name: "Lincoln Center Out of Doors Preview", meta: "Damrosch Park · Plaza performance"           },
    { id: "ev6", date: "May 13", day: "13", mon: "MAY", time: "6:30 PM",  name: "Madison Square Park Conservancy Walk", meta: "23rd & Broadway · Guided, 90 min"           },
  ],

  newsLead: {
    id: "n-lead",
    cat: "Geopolitics · Lead",
    g: "⚑",
    h: "Brussels Brokers Tentative Tariff Truce as G7 Convenes in Vancouver",
    deck: "A thirty-six-hour session yields a framework that halts the steepest levies through autumn.",
    body: "Officials announced a provisional accord shortly before dawn. It freezes tariff escalations on industrial goods through October and creates a joint review board for digital services. Ratification remains uncertain. The G7 summit opens Thursday in Vancouver.",
    by: "Reuters · Associated Press",
  },

  newsSide: [
    { id: "n2", cat: "Economy",   g: "$", h: "Fed Holds; Powell Signals Patience",
      p: "Rates unchanged for a fourth meeting. Services inflation firmer than expected.",
      src: "WSJ", time: "1h ago" },
    { id: "n3", cat: "Science",   g: "✧", h: "JWST Detects Phosphine on K2-18b",
      p: "A tentative biosignature in the spectrum — if confirmed, a major exobiology result.",
      src: "Nature", time: "3h ago" },
    { id: "n4", cat: "Domestic",  g: "☆", h: "California Advances Insurance Reform",
      p: "Caps rate hikes tied to wildfire exposure; expands the state's insurer of last resort.",
      src: "LA Times", time: "5h ago" },
    { id: "n5", cat: "Tech",      g: "⌘", h: "Apple Confirms On-Device iOS Model",
      p: "A 3B-parameter foundation model for iPhones with 8GB RAM, framed as privacy-forward.",
      src: "Reuters", time: "6h ago" },
  ],

  videos: [
    { id: "v1", channel: "Veritasium",         h: "The Algorithm That Outsmarted the Lottery", p: "A statistician's exploit of a scratch-ticket printing flaw.",                  time: "18 min · yesterday" },
    { id: "v2", channel: "Kurzgesagt",         h: "What If We Drilled the Mariana Trench?",    p: "Geothermal energy at the seafloor — and the catches.",                          time: "12 min · 2d ago"   },
    { id: "v3", channel: "3Blue1Brown",        h: "Visualizing Optimal Transport",             p: "A geometric tour of the Wasserstein distance.",                                 time: "25 min · 3d ago"   },
    { id: "v4", channel: "Practical Engineering", h: "Why Bridges Hum",                         p: "Vortex shedding and aeroelastic flutter on long spans.",                         time: "16 min · 4d ago"   },
    { id: "v5", channel: "Tom Scott Plus",     h: "Inside the Loudest Anechoic Chamber",        p: "A perceptual record attempt with eerie results.",                                time: "9 min · 5d ago"    },
    { id: "v6", channel: "Acquired",           h: "The TSMC Episode, Pt. III",                  p: "How fab allocation post-CHIPS-Act is reshaping leverage.",                       time: "3h 14m · 6d ago"   },
  ],

  aiTldr: "This week converges on agentic safety: prompt injection, jailbreak transfer, and red-team evals.",

  ai: [
    { id: "a1", src: "arXiv · 2505.04127", h: "Prompt Injection in Computer-Use Agents",
      p: "Twelve injection vectors taxonomized; mitigation via capability scoping.",
      cites: 47, badges: [{ t: "prompt injection", tone: "red", g: "⚠" }, { t: "agentic AI", tone: "navy", g: "⚙" }] },
    { id: "a2", src: "arXiv · 2505.03980", h: "Universal Jailbreak Transfer",
      p: "Suffixes from open weights retain 38–62% transfer to frontier models.",
      cites: 29, badges: [{ t: "jailbreaks", tone: "red", g: "⛓" }, { t: "red teaming", tone: "gold", g: "⚔" }] },
    { id: "a3", src: "Anthropic · Engineering", h: "Constitutional Classifiers v3",
      p: "Q1 production notes: latency, false-positive rates, deployment tradeoffs.",
      cites: 12, badges: [{ t: "alignment", tone: "navy", g: "✦" }, { t: "deployment", tone: "gold", g: "▲" }] },
    { id: "a4", src: "arXiv · 2505.02214", h: "Differentially Private Tool-Use",
      p: "Calibrated noise on tool inputs; utility preserved, third-party leakage bounded.",
      cites: 8, badges: [{ t: "privacy", tone: "navy", g: "🔒" }, { t: "agentic AI", tone: "navy", g: "⚙" }] },
    { id: "a5", src: "Google News · MIT Tech Review", h: "Red Team Breaks Hospital Triage System",
      p: "Field report: an exfiltration path via free-text clinical fields.",
      cites: 0, badges: [{ t: "red teaming", tone: "gold", g: "⚔" }, { t: "healthcare", tone: "navy", g: "✚" }] },
    { id: "a6", src: "arXiv · 2505.01809", h: "Memorization in Long-Context Models",
      p: "Verbatim recall grows sub-linearly with window — eval suites overstate risk.",
      cites: 14, badges: [{ t: "privacy", tone: "navy", g: "🔒" }, { t: "evals", tone: "gold", g: "◉" }] },
  ],

  // mock archive
  archive: [
    { date: "2026-05-07", label: "Thu, May 7",  blurb: "Tariff truce in Brussels; phosphine on K2-18b; Hudson Yards spring market opens." , latest: true },
    { date: "2026-05-06", label: "Wed, May 6",  blurb: "Fed holds; on-device iOS model paper; Central Park concert lineup." },
    { date: "2026-05-05", label: "Tue, May 5",  blurb: "Cinco de Mayo; jobless claims tick up; new computer-use agent benchmark." },
    { date: "2026-05-04", label: "Mon, May 4",  blurb: "Atmospheric river hits PNW; ECB minutes; arXiv weekend roundup." },
    { date: "2026-05-03", label: "Sun, May 3",  blurb: "Met Gala recap; Met Office heat outlook; longform on agentic safety." },
    { date: "2026-05-02", label: "Sat, May 2",  blurb: "May Day protests; SpaceX scrub; new RAG retrieval benchmark." },
    { date: "2026-05-01", label: "Fri, May 1",  blurb: "Tariffs proposal published; cherry blossoms peak; jailbreak transfer paper." },
  ],
};
