/* global React */
const { useState: useStateT, useEffect: useEffectT } = React;

function MBTweaks() {
  const [open, setOpen] = useStateT(false);
  const [paper, setPaper] = useStateT("cream");
  const [density, setDensity] = useStateT("standard");
  const [edition, setEdition] = useStateT("morning");
  const [accent, setAccent] = useStateT("red+navy");

  useEffectT(() => {
    function handler(e) {
      if (!e.data) return;
      if (e.data.type === "__activate_edit_mode") setOpen(true);
      if (e.data.type === "__deactivate_edit_mode") setOpen(false);
    }
    window.addEventListener("message", handler);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", handler);
  }, []);

  // Apply
  useEffectT(() => { document.body.dataset.paper = paper; }, [paper]);
  useEffectT(() => { document.body.dataset.density = density; }, [density]);
  useEffectT(() => {
    const root = document.documentElement.style;
    if (accent === "none") { root.setProperty("--red", "#1a1814"); root.setProperty("--navy", "#1a1814"); }
    else if (accent === "red") { root.setProperty("--red", "#9c2a1f"); root.setProperty("--navy", "#1a1814"); }
    else { root.setProperty("--red", "#9c2a1f"); root.setProperty("--navy", "#1f3a5f"); }
  }, [accent]);
  useEffectT(() => {
    const tag = document.querySelector(".edition-tag");
    if (!tag) return;
    if (edition === "morning") tag.textContent = "Morning Edition · 6:00 AM";
    else if (edition === "afternoon") tag.textContent = "Afternoon Edition · 2:00 PM";
    else tag.textContent = "Evening Edition · 8:00 PM";
  }, [edition]);

  if (!open) return null;

  return (
    <div style={{
      position: "fixed", bottom: 18, right: 18, zIndex: 200,
      background: "var(--paper)", border: "1px solid var(--rule)",
      boxShadow: "0 10px 30px rgba(0,0,0,0.25)", width: 280, fontFamily: "var(--serif-display)"
    }}>
      <div style={{ borderBottom: "3px double var(--rule)", padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ letterSpacing: ".18em", textTransform: "uppercase", fontSize: 12 }}>Tweaks</strong>
        <button onClick={() => { setOpen(false); window.parent.postMessage({ type: "__edit_mode_dismissed" }, "*"); }} style={{ background: "transparent", border: "1px solid var(--rule)", width: 24, height: 24, cursor: "pointer" }}>×</button>
      </div>
      <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12, fontSize: 11, letterSpacing: ".1em", textTransform: "uppercase" }}>
        <Field label="Paper">
          <Seg value={paper} setValue={setPaper} options={[["cream","Cream"],["white","White"],["sepia","Sepia"]]} />
        </Field>
        <Field label="Ink Accents">
          <Seg value={accent} setValue={setAccent} options={[["none","None"],["red","Red"],["red+navy","Both"]]} />
        </Field>
        <Field label="Density">
          <Seg value={density} setValue={setDensity} options={[["loose","Loose"],["standard","Std"],["tight","Tight"]]} />
        </Field>
        <Field label="Edition">
          <Seg value={edition} setValue={setEdition} options={[["morning","6 AM"],["afternoon","2 PM"],["evening","8 PM"]]} />
        </Field>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <div style={{ fontSize: 9.5, color: "var(--ink-faint)", marginBottom: 4, letterSpacing: ".22em" }}>{label}</div>
      {children}
    </div>
  );
}

function Seg({ value, setValue, options }) {
  return (
    <div style={{ display: "flex", border: "1px solid var(--rule)" }}>
      {options.map(([v, l]) => (
        <button
          key={v}
          onClick={() => setValue(v)}
          style={{
            flex: 1, padding: "6px 4px", cursor: "pointer",
            background: value === v ? "var(--ink)" : "transparent",
            color: value === v ? "var(--paper)" : "var(--ink)",
            border: "none", borderRight: "1px solid var(--rule)",
            fontFamily: "var(--serif-display)", fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase"
          }}
        >{l}</button>
      ))}
    </div>
  );
}

window.MBTweaks = MBTweaks;
