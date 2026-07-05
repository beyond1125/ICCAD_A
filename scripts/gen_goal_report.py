#!/usr/bin/env python3
"""Render the transform-goal verification results as a self-contained HTML report.

Reads the per-instruction goal data (goal_check.py --json) and folds in the per-case
equivalence verdict (from eval_harness.py's table), then emits one static HTML file:
a two-axis (equivalence AND goal) report showing exactly which transform instructions
each testcase achieved and which it missed.

Usage:
    python3 scripts/goal_check.py --from 1 --to 40 --skip-equiv --json > goals.json
    python3 scripts/eval_harness.py --from 1 --to 40 --skip-paths > combined.txt
    python3 scripts/gen_goal_report.py goals.json combined.txt report.html
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def parse_equiv(combined_txt: str) -> dict:
    """case-name -> equiv verdict, parsed from the eval_harness table."""
    eq = {}
    for line in combined_txt.splitlines():
        m = re.match(r"(test\d+)\s+\S+\s+(\S+)", line)
        if m:
            eq[m.group(1)] = m.group(2)
    return eq


# rank for ordering: combined failures first, then passes, empties, no-output
_ORDER = {"GOAL-FAIL": 0, "FAIL": 0, "CHECK": 1, "PASS": 2, "NO-OUTPUT": 5}
_EQUIV_BROKEN = {"NOTEQUIV", "BLIF-ERR", "CEC-ERR"}


def combined_status(r: dict) -> str:
    """PASS = equiv AND goal; GOAL-FAIL = equivalent but a goal missed (the whole point)."""
    if r["status"] == "NO-OUTPUT" or r["equiv"] in ("NO-OUTPUT", "—", None):
        return "NO-OUTPUT"
    goal_ok = r["total"] == 0 or r["met"] == r["total"]
    if r["equiv"] in _EQUIV_BROKEN:
        return "FAIL"
    if r["equiv"] == "EQUIV":
        return "PASS" if goal_ok else "GOAL-FAIL"
    return "CHECK"


def prepare(rows: list, equiv: dict) -> dict:
    """Merge equiv, compute the combined verdict per case, sort, and tally summary stats."""
    for r in rows:
        r["equiv"] = equiv.get(r["name"], r.get("equiv") or "—")
        r["combined"] = combined_status(r)
    rows.sort(key=lambda r: (_ORDER.get(r["combined"], 9), int(re.sub(r"\D", "", r["name"]))))
    out_rows = [r for r in rows if r["combined"] != "NO-OUTPUT"]
    return {
        "n_out": len(out_rows),
        "combined_pass": sum(1 for r in out_rows if r["combined"] == "PASS"),
        "goal_fail": [r for r in out_rows if r["combined"] == "GOAL-FAIL"],
        "equiv_ok": sum(1 for r in out_rows if r["equiv"] == "EQUIV"),
        "goals_total": sum(r["total"] for r in out_rows),   # exclude NO-OUTPUT goals
        "goals_met": sum(r["met"] for r in out_rows),
    }


def build_html(rows: list, s: dict) -> str:
    n_out, combined_pass, equiv_ok = s["n_out"], s["combined_pass"], s["equiv_ok"]
    goals_total, goals_met, goal_fail = s["goals_total"], s["goals_met"], s["goal_fail"]
    data = json.dumps(rows)

    stats = [
        ("combined pass", f"{combined_pass}<span class='den'>/{n_out}</span>", "equiv AND goal", "accent"),
        ("goals achieved", f"{goals_met}<span class='den'>/{goals_total}</span>", "scored predicates", "neutral"),
        ("equivalent", f"{equiv_ok}<span class='den'>/{n_out}</span>", "ABC formal cec", "neutral"),
        ("equiv but goal&nbsp;unmet", f"{len(goal_fail)}", "passes cec, misses goal", "fail"),
    ]
    stat_html = "\n".join(
        f'<div class="stat stat--{cls}"><div class="stat__label">{lbl}</div>'
        f'<div class="stat__num">{num}</div><div class="stat__sub">{sub}</div></div>'
        for lbl, num, sub, cls in stats
    )

    return _TEMPLATE.replace("__STATS__", stat_html).replace("__DATA__", data)


_TEMPLATE = r"""<div class="wrap">
<header class="masthead">
  <div class="eyebrow">ICCAD&nbsp;2026&nbsp;·&nbsp;Problem&nbsp;A&nbsp;·&nbsp;transform verification</div>
  <h1>Transform-Goal Report</h1>
  <p class="lede">Equivalence proves a transform didn't <em>break</em> the netlist. It cannot prove
  the transform did its <em>job</em> — a no-op passes formal <code>cec</code> perfectly. Each
  instruction below is scored on both axes: <strong>equivalent</strong> (ABC) <strong>and</strong>
  <strong>goal achieved</strong> (independent structural oracle).</p>
</header>

<section class="panel" aria-label="summary">__STATS__</section>

<section class="legend">
  <span class="chip chip--pass">PASS</span> goal achieved
  <span class="chip chip--fail">FAIL</span> goal not achieved in output
  <span class="chip chip--adv">ADV</span> advisory, not scored
  <span class="sep"></span>
  <span class="axis">EQUIV</span> proven equivalent
  <span class="axis axis--bad">GOAL-FAIL</span> equivalent but a goal missed
</section>

<div class="controls">
  <div class="filters" role="group" aria-label="filter cases">
    <button class="fbtn is-on" data-f="all">All</button>
    <button class="fbtn" data-f="fail">Failures only</button>
    <button class="fbtn" data-f="pass">Full pass</button>
  </div>
  <button class="fbtn" id="toggle">Expand all</button>
</div>

<main id="cases"></main>
<footer>Independent oracle (regex netlist model + BFS/longest-path); goals asserted on the final
output netlist. Advisory items and known final-state caveats documented in
<code>scripts/goal_check.py</code>.</footer>
</div>

<style>
:root{
  --bg:#f6f8f9; --surface:#ffffff; --surface-2:#eef1f3; --ink:#131b21; --ink-2:#4a5a63;
  --ink-3:#7c8b93; --line:#dde3e6; --accent:#0e8f92; --accent-ink:#0a6f72;
  --pass:#1f9d57; --pass-bg:#e5f4ea; --fail:#cf3b34; --fail-bg:#fbe8e6;
  --adv:#a9711a; --adv-bg:#f6edda; --shadow:0 1px 2px rgba(19,27,33,.06),0 4px 16px rgba(19,27,33,.05);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0d1318; --surface:#141c22; --surface-2:#1b252c; --ink:#e7edf0; --ink-2:#a6b6bf;
  --ink-3:#6c7d86; --line:#25313a; --accent:#3dd6c4; --accent-ink:#7fe9dc;
  --pass:#3ad07f; --pass-bg:#12271c; --fail:#ff6a5f; --fail-bg:#2c1512;
  --adv:#e6b23e; --adv-bg:#2a2210; --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
}}
:root[data-theme="light"]{
  --bg:#f6f8f9; --surface:#ffffff; --surface-2:#eef1f3; --ink:#131b21; --ink-2:#4a5a63;
  --ink-3:#7c8b93; --line:#dde3e6; --accent:#0e8f92; --accent-ink:#0a6f72;
  --pass:#1f9d57; --pass-bg:#e5f4ea; --fail:#cf3b34; --fail-bg:#fbe8e6;
  --adv:#a9711a; --adv-bg:#f6edda; --shadow:0 1px 2px rgba(19,27,33,.06),0 4px 16px rgba(19,27,33,.05);
}
:root[data-theme="dark"]{
  --bg:#0d1318; --surface:#141c22; --surface-2:#1b252c; --ink:#e7edf0; --ink-2:#a6b6bf;
  --ink-3:#6c7d86; --line:#25313a; --accent:#3dd6c4; --accent-ink:#7fe9dc;
  --pass:#3ad07f; --pass-bg:#12271c; --fail:#ff6a5f; --fail-bg:#2c1512;
  --adv:#e6b23e; --adv-bg:#2a2210; --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.55;
  font-feature-settings:"kern";-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace}
.wrap{max-width:980px;margin:0 auto;padding:clamp(20px,4vw,56px) clamp(16px,4vw,32px)}
code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.9em;
  background:var(--surface-2);padding:.08em .35em;border-radius:4px}

.eyebrow{font-family:ui-monospace,Menlo,monospace;font-size:12px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent-ink);margin-bottom:14px}
h1{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:650;
  font-size:clamp(30px,5vw,46px);letter-spacing:-.02em;margin:0 0 .35em;text-wrap:balance}
.lede{max-width:64ch;color:var(--ink-2);font-size:clamp(15px,1.6vw,17px);margin:0}
.lede strong{color:var(--ink);font-weight:640}
.lede em{font-style:italic;color:var(--ink)}
.masthead{border-bottom:1px solid var(--line);padding-bottom:28px;margin-bottom:28px}

.panel{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:26px}
@media(max-width:680px){.panel{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.stat::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--ink-3)}
.stat--accent::before{background:var(--accent)}
.stat--fail::before{background:var(--fail)}
.stat__label{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:8px}
.stat__num{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:650;
  font-size:34px;line-height:1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat--accent .stat__num{color:var(--accent-ink)}
.stat--fail .stat__num{color:var(--fail)}
.stat__num .den{font-size:18px;color:var(--ink-3);font-weight:500}
.stat__sub{font-size:12px;color:var(--ink-2);margin-top:7px}

.legend{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;font-size:13px;
  color:var(--ink-2);margin-bottom:22px}
.legend .sep{flex:0 0 1px;height:16px;background:var(--line);margin:0 4px}
.chip,.axis{font-family:ui-monospace,Menlo,monospace;font-size:11px;font-weight:600;
  letter-spacing:.04em;padding:2px 7px;border-radius:5px;line-height:1.5}
.chip--pass{background:var(--pass-bg);color:var(--pass)}
.chip--fail{background:var(--fail-bg);color:var(--fail)}
.chip--adv{background:var(--adv-bg);color:var(--adv)}
.axis{background:var(--surface-2);color:var(--ink-2);border:1px solid var(--line)}
.axis--bad{color:var(--fail);border-color:var(--fail)}

.controls{display:flex;justify-content:space-between;align-items:center;gap:12px;
  flex-wrap:wrap;margin-bottom:16px}
.filters{display:flex;gap:6px}
.fbtn{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ink-2);
  background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:6px 12px;cursor:pointer;transition:.15s}
.fbtn:hover{border-color:var(--accent);color:var(--ink)}
.fbtn.is-on{background:var(--accent);border-color:var(--accent);color:#fff}
@media(prefers-color-scheme:dark){.fbtn.is-on{color:#08201f}}
:root[data-theme="dark"] .fbtn.is-on{color:#08201f}
:root[data-theme="light"] .fbtn.is-on{color:#fff}
.fbtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

.case{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  margin-bottom:12px;box-shadow:var(--shadow);overflow:hidden}
.case__head{display:flex;align-items:center;gap:14px;padding:14px 18px;cursor:pointer;
  user-select:none;width:100%;border:0;background:none;text-align:left;color:inherit}
.case__head:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.case__name{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:650;font-size:16px;
  letter-spacing:-.01em;min-width:76px}
.badge{font-family:ui-monospace,Menlo,monospace;font-size:11px;font-weight:600;
  padding:3px 8px;border-radius:6px;letter-spacing:.03em;white-space:nowrap}
.badge--EQUIV{background:var(--surface-2);color:var(--ink-2)}
.badge--NOTEQUIV{background:var(--fail-bg);color:var(--fail)}
.badge--PASS{background:var(--pass-bg);color:var(--pass)}
.badge--GOALFAIL,.badge--FAIL,.badge--UNMET{background:var(--fail-bg);color:var(--fail)}
.badge--NOGOALS,.badge--ADVISORY,.badge--NOOUTPUT,.badge--CHECK{background:var(--surface-2);color:var(--ink-3)}
.meter{flex:1;display:flex;align-items:center;gap:10px;min-width:120px}
.meter__track{flex:1;height:6px;background:var(--surface-2);border-radius:3px;overflow:hidden}
.meter__fill{height:100%;background:var(--pass);border-radius:3px}
.meter__fill.has-fail{background:linear-gradient(90deg,var(--pass) var(--pct),var(--fail) var(--pct))}
.meter__txt{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ink-2);
  font-variant-numeric:tabular-nums;min-width:34px;text-align:right}
.chevron{color:var(--ink-3);transition:transform .2s;font-size:12px}
.case.open .chevron{transform:rotate(90deg)}

.case__body{display:none;border-top:1px solid var(--line);padding:4px 0}
.case.open .case__body{display:block}
.goal{display:grid;grid-template-columns:56px 1fr;gap:2px 14px;padding:11px 18px;
  border-bottom:1px solid var(--line)}
.goal:last-child{border-bottom:0}
.goal__tag{grid-row:span 2}
.tag{display:inline-block;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;
  font-weight:700;letter-spacing:.04em;padding:2px 6px;border-radius:5px;margin-top:1px}
.tag--pass{background:var(--pass-bg);color:var(--pass)}
.tag--fail{background:var(--fail-bg);color:var(--fail)}
.tag--advisory{background:var(--adv-bg);color:var(--adv)}
.goal__kind{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--accent-ink);
  letter-spacing:.02em}
.goal__detail{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ink);
  word-break:break-word}
.goal__instr{grid-column:2;font-size:12.5px;color:var(--ink-3);max-width:74ch}
.uncl{padding:10px 18px;font-size:12.5px;color:var(--ink-3);font-style:italic}
.empty{padding:14px 18px;font-size:13px;color:var(--ink-3)}

footer{margin-top:32px;padding-top:20px;border-top:1px solid var(--line);
  font-size:12.5px;color:var(--ink-3);max-width:70ch}
.hidden{display:none!important}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<script>
const DATA = __DATA__;
const cases = document.getElementById("cases");
const badgeCls = s => "badge--"+s.replace("-","");
const tagCls = s => "tag--"+s;

function render(){
  cases.innerHTML = "";
  for(const r of DATA){
    const el = document.createElement("section");
    el.className = "case"; el.dataset.status = r.combined;
    const isFail = r.combined==="GOAL-FAIL"||r.combined==="FAIL";
    el.dataset.group = isFail ? "fail" : (r.combined==="PASS" ? "pass" : "other");

    const pct = r.total ? Math.round(100*r.met/r.total) : 100;
    const meter = r.total
      ? `<div class="meter"><div class="meter__track"><div class="meter__fill ${r.met<r.total?'has-fail':''}" style="--pct:${pct}%;width:${r.met<r.total?'100':pct}%"></div></div>
         <span class="meter__txt">${r.met}/${r.total}</span></div>`
      : `<div class="meter"><span class="meter__txt" style="text-align:left;color:var(--ink-3)">no goals</span></div>`;

    const head = document.createElement("button");
    head.className = "case__head"; head.setAttribute("aria-expanded","false");
    head.innerHTML =
      `<span class="case__name">${r.name}</span>`+
      `<span class="badge ${badgeCls(r.equiv)}">${r.equiv}</span>`+
      `<span class="badge ${badgeCls(r.combined)}">${r.combined}</span>`+
      meter+`<span class="chevron mono">▶</span>`;
    head.addEventListener("click",()=>{
      const open = el.classList.toggle("open");
      head.setAttribute("aria-expanded", open);
    });

    const body = document.createElement("div");
    body.className = "case__body";
    if(!r.goals.length && !r.unclassified.length){
      body.innerHTML = `<div class="empty">No transform goals — analysis-only testcase.</div>`;
    } else {
      body.innerHTML = r.goals.map(g=>{
        const st = g.status.toUpperCase().slice(0,4);
        return `<div class="goal">
          <div class="goal__tag"><span class="tag ${tagCls(g.status)}">${g.status==="advisory"?"ADV":st}</span></div>
          <div><span class="goal__kind">${g.kind}</span> &nbsp;<span class="goal__detail">${esc(g.detail)}</span></div>
          <div class="goal__instr">${esc(g.instruction)}</div>
        </div>`;
      }).join("") +
      r.unclassified.map(u=>`<div class="uncl">unclassified: ${esc(u)}</div>`).join("");
    }
    el.appendChild(head); el.appendChild(body);
    if(isFail){ el.classList.add("open"); head.setAttribute("aria-expanded","true"); }
    cases.appendChild(el);
  }
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

document.querySelectorAll(".filters .fbtn").forEach(b=>{
  b.addEventListener("click",()=>{
    document.querySelectorAll(".filters .fbtn").forEach(x=>x.classList.remove("is-on"));
    b.classList.add("is-on");
    const f=b.dataset.f;
    document.querySelectorAll(".case").forEach(c=>{
      const show = f==="all" || c.dataset.group===f;
      c.classList.toggle("hidden",!show);
    });
  });
});
const tgl=document.getElementById("toggle");
tgl.addEventListener("click",()=>{
  const anyClosed=[...document.querySelectorAll(".case:not(.hidden)")].some(c=>!c.classList.contains("open"));
  document.querySelectorAll(".case:not(.hidden)").forEach(c=>{
    c.classList.toggle("open",anyClosed);
    c.querySelector(".case__head").setAttribute("aria-expanded",anyClosed);
  });
  tgl.textContent=anyClosed?"Collapse all":"Expand all";
});
render();
</script>
"""


_MARK = {"pass": "✅", "fail": "❌", "advisory": "🔹"}


def _cell(s) -> str:
    """Escape a value for a Markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def build_md(rows: list, s: dict) -> str:
    out = []
    w = out.append
    w("# Transform-Goal Verification Report\n")
    w("_ICCAD 2026 · Problem A — generated from `goal_check.py` + `eval_harness.py`._\n")
    w("Equivalence (ABC `cec`) proves a transform did not **break** the netlist; it cannot prove "
      "the transform did its **job** — a no-op passes `cec` perfectly. Every instruction below is "
      "scored on both axes: **equivalent** *and* **goal achieved** (an independent structural "
      "oracle, not the tool under test).\n")

    w("## Summary\n")
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Combined pass (equiv **and** goal) | **{s['combined_pass']} / {s['n_out']}** |")
    w(f"| Goals achieved (scored predicates) | {s['goals_met']} / {s['goals_total']} |")
    w(f"| Proven equivalent (ABC `cec`) | {s['equiv_ok']} / {s['n_out']} |")
    w(f"| **Equivalent but goal unmet** | **{len(s['goal_fail'])}** |")
    w("\nLegend: ✅ goal achieved · ❌ goal not achieved in output · 🔹 advisory (not scored)\n")

    if s["goal_fail"]:
        w("## Cases equivalent but goal-unmet\n")
        w("These outputs are formally equivalent yet miss at least one transform goal — the gap "
          "pure equivalence checking cannot see.\n")
        w("| Case | Equiv | Goals | Unmet goals |")
        w("|---|---|---|---|")
        for r in s["goal_fail"]:
            unmet = "; ".join(f"`{g['kind']}` {g['detail']}"
                              for g in r["goals"] if g["status"] == "fail")
            w(f"| {r['name']} | {r['equiv']} | {r['met']}/{r['total']} | {_cell(unmet)} |")
        w("")

    w("## Per-case detail\n")
    analysis_only = []
    for r in rows:
        if not r["goals"] and not r["unclassified"]:
            if r["combined"] != "NO-OUTPUT":
                analysis_only.append(r["name"])
            continue
        head = f"`{r['name']}` — {r['combined']} · equiv {r['equiv']} · goals {r['met']}/{r['total']}"
        w(f"<details><summary>{head}</summary>\n")
        w("| | Goal | Result | Instruction |")
        w("|---|---|---|---|")
        for g in r["goals"]:
            w(f"| {_MARK[g['status']]} | `{g['kind']}` | {_cell(g['detail'])} "
              f"| {_cell(g['instruction'])} |")
        for u in r["unclassified"]:
            w(f"| ⚪ | _unclassified_ | — | {_cell(u)} |")
        w("\n</details>\n")

    if analysis_only:
        w("## Analysis-only testcases\n")
        w("No transform goals (queries only); equivalence still checked: "
          + ", ".join(analysis_only) + ".\n")
    return "\n".join(out)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    goals = json.loads(Path(sys.argv[1]).read_text())
    combined = Path(sys.argv[2]).read_text() if Path(sys.argv[2]).is_file() else ""
    out_path = sys.argv[3]
    stats = prepare(goals, parse_equiv(combined))
    doc = build_md(goals, stats) if out_path.endswith(".md") else build_html(goals, stats)
    Path(out_path).write_text(doc)
    print(f"wrote {out_path} ({len(doc)} bytes, {len(goals)} cases)")


if __name__ == "__main__":
    main()
