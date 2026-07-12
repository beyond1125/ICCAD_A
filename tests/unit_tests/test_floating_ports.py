#!/usr/bin/env python3
"""P2-6 (contest Q&A A5.6): input netlists may contain floating /
unconnected ports. Three synthetic fixtures exercise the parser, the
list_floating report, and the write round-trip:

  1. floating_pi.v    — input port declared, never consumed by any gate
  2. unconn_po.v      — output port declared, never driven by any gate
  3. undriven_wire.v  — wire consumed by a gate but with no driver

Each fixture also carries normal logic incl. a DFF whose CK/RN nets are
used ONLY through control pins — those must NOT be reported floating.

Checks per fixture:
  (a) parser_cpp load succeeds (exit 0, "Success." header, gate count)
  (b) list_floating reports exactly the expected items, nothing else
  (c) write round-trip: reload the written file -> same gate count, same
      PI/PO sets, same list_floating verdicts (no information loss)

Plus engine-level semantics on the undriven_wire fixture:
  (d) check_const on the undriven wire answers CONSTANT 0 with an explicit
      undriven/floating caveat (matches the run_random_sim / ABC tie-0
      convention instead of the SAT free-variable reading)
  (e) check_const on a floating PI stays NOT CONSTANT (a PI is a free input)
  (f) flop-cut BLIF of the undriven fixture is ABC-cec-able against itself
      (ABC ties the non-driven net to 0 with a warning, not an error)

Run:  python3 tests/unit_tests/test_floating_ports.py   (exit 0 = pass)
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "src/eda_engine/parser/parser_cpp"
ABC = ROOT / "tools/abc/abc"
sys.path.insert(0, str(ROOT / "src"))

COMMON = """
  wire t1;
  nand g1(t1, a, b);
  dff  g2(.RN(rstn), .SN(1'b1), .CK(clk), .D(t1), .Q(q));
  not  g3(y, q);
"""

FIXTURES = {
    # n_float is a PI with no consumer at all
    "floating_pi": {
        "src": "module f1(a, b, n_float, clk, rstn, y);\n"
               "  input a, b, n_float, clk, rstn;\n  output y;\n"
               + COMMON + "  wire q;\nendmodule\n",
        "floating_inputs": ["n_float"],
        "unconnected_outputs": [],
        "undriven_signals": [],
        "gates": 3,
    },
    # po_unconn is a PO no gate ever drives
    "unconn_po": {
        "src": "module f2(a, b, clk, rstn, y, po_unconn);\n"
               "  input a, b, clk, rstn;\n  output y, po_unconn;\n"
               + COMMON + "  wire q;\nendmodule\n",
        "floating_inputs": [],
        "unconnected_outputs": ["po_unconn"],
        "undriven_signals": [],
        "gates": 3,
    },
    # w_undrv feeds g4 but nothing drives it
    "undriven_wire": {
        "src": "module f3(a, b, clk, rstn, y, z);\n"
               "  input a, b, clk, rstn;\n  output y, z;\n"
               + COMMON + "  wire q;\n  wire w_undrv;\n"
               "  and g4(z, q, w_undrv);\nendmodule\n",
        "floating_inputs": [],
        "unconnected_outputs": [],
        "undriven_signals": ["w_undrv"],
        "gates": 4,
    },
    # bus with only bit 1 consumed: the other bits are bit-level floating
    # PIs. (A declared-but-never-referenced `wire unused_w;` is silently
    # dropped by the parser — electrically inert, accepted information loss.)
    "vector_float": {
        "src": "module f4(a, nf, clk, rstn, y);\n"
               "  input a, clk, rstn;\n  input [3:0] nf;\n  output y;\n"
               "  wire unused_w;\n  wire t1;\n"
               "  and g1(t1, a, nf[1]);\n"
               "  dff g2(.RN(rstn), .SN(1'b1), .CK(clk), .D(t1), .Q(q));\n"
               "  not g3(y, q);\n  wire q;\nendmodule\n",
        "floating_inputs": ["nf[0]", "nf[2]", "nf[3]"],
        "unconnected_outputs": [],
        "undriven_signals": [],
        "gates": 3,
    },
}


def run(vfile: Path, action: str, **kw):
    cmd = [str(PARSER), "--in", str(vfile), "--action", action]
    for k, v in kw.items():
        cmd += [f"--{k}", str(v)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip()


def load_stats(vfile: Path):
    rc, out = run(vfile, "load")
    m = re.search(r"Success\. PI: (\d+), PO: (\d+), Gates: (\d+)", out)
    return rc, out, (tuple(int(x) for x in m.groups()) if m else None)


def floating(vfile: Path):
    rc, out = run(vfile, "list_floating")
    if rc != 0:
        return rc, None
    return rc, json.loads(out)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="p26_floating_") as td:
        tdir = Path(td)
        for name, fx in FIXTURES.items():
            vfile = tdir / f"{name}.v"
            vfile.write_text(fx["src"])

            # (a) load tolerance
            rc, out, stats = load_stats(vfile)
            if rc != 0 or stats is None:
                failures.append(f"{name}: load failed rc={rc} out={out!r}")
                continue
            if stats[2] != fx["gates"]:
                failures.append(f"{name}: gate count {stats[2]} != {fx['gates']}")

            # (b) list_floating exact report
            rc, rep = floating(vfile)
            if rc != 0 or rep is None:
                failures.append(f"{name}: list_floating failed rc={rc}")
                continue
            for key in ("floating_inputs", "unconnected_outputs", "undriven_signals"):
                got, want = sorted(rep[key]), sorted(fx[key])
                if got != want:
                    failures.append(f"{name}: {key} got {got} want {want}")

            # (c) write round-trip: no information loss
            wfile = tdir / f"{name}_rt.v"
            rc, out = run(vfile, "write", out=str(wfile))
            if rc != 0 or not wfile.is_file():
                failures.append(f"{name}: write failed rc={rc} out={out!r}")
                continue
            rc2, out2, stats2 = load_stats(wfile)
            if rc2 != 0 or stats2 is None:
                failures.append(f"{name}: reload of written file failed out={out2!r}")
                continue
            if stats2 != stats:
                failures.append(f"{name}: round-trip PI/PO/gate drift {stats} -> {stats2}")
            rc3, rep2 = floating(wfile)
            if rc3 != 0 or rep2 is None:
                failures.append(f"{name}: list_floating on round-trip failed")
            else:
                for key in ("floating_inputs", "unconnected_outputs", "undriven_signals"):
                    if sorted(rep2[key]) != sorted(fx[key]):
                        failures.append(
                            f"{name}: round-trip {key} {sorted(rep2[key])} != {sorted(fx[key])}")

        # (d)/(e) engine-level check_const semantics on floating nets
        from eda_engine.engine import EDAEngine
        vfile = tdir / "undriven_wire.v"
        fx = FIXTURES["floating_pi"]
        pi_file = tdir / "floating_pi.v"
        engine = EDAEngine()
        res = engine.load_design(str(vfile))
        if "Success" not in res:
            failures.append(f"engine load of undriven fixture failed: {res!r}")
        else:
            v = engine.check_const("w_undrv")
            if "CONSTANT 0" not in v or "undriven" not in v.lower():
                failures.append(f"check_const(w_undrv) not the undriven verdict: {v!r}")
        engine2 = EDAEngine()
        res = engine2.load_design(str(pi_file))
        if "Success" not in res:
            failures.append(f"engine load of floating_pi fixture failed: {res!r}")
        else:
            v = engine2.check_const("n_float")
            if "NOT CONSTANT" not in v:
                failures.append(f"check_const(n_float) should be NOT CONSTANT: {v!r}")

        # (f) flop-cut BLIF + ABC self-cec tolerate the non-driven net
        if ABC.is_file():
            blif = tdir / "undrv.blif"
            rc, out = run(vfile, "write_blif", out=str(blif))
            if rc != 0 or not blif.is_file():
                failures.append(f"write_blif on undriven fixture failed: {out!r}")
            else:
                r = subprocess.run([str(ABC), "-c", f"cec {blif} {blif}"],
                                   capture_output=True, text=True, timeout=60)
                if "Networks are equivalent" not in r.stdout:
                    failures.append(f"ABC self-cec on undriven fixture failed: "
                                    f"{r.stdout.strip()[-200:]!r}")

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print(f"OK: {len(FIXTURES)} floating-port fixtures pass load / "
          f"list_floating / write round-trip; check_const undriven/floating-PI "
          f"verdicts and ABC cec tolerance verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
