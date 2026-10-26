"""
Post-build validation for the Rx Substructure Atlas pipeline.

Run this AFTER process.py + minify_svg.py and BEFORE build.py. It catches the
failure modes that are silent at runtime — a new group that never appears in a
quiz, a renamed drug that wipes out students' saved progress for it, a pattern
that matches nothing.

Usage:
    python3 validate.py
    python3 validate.py --strict        # warnings also exit non-zero

Exit codes:  0 = clean (or warnings only)   1 = errors found
"""

import argparse, csv, json, os, re, subprocess, sys
from collections import Counter

# --- pretty output ---------------------------------------------------------
ERRORS, WARNINGS, NOTES = [], [], []
def error(msg, detail=""): ERRORS.append((msg, detail))
def warn(msg, detail=""): WARNINGS.append((msg, detail))
def note(msg, detail=""): NOTES.append((msg, detail))

def slugify(name):
    """Must stay identical to slugify() in process.py."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def read_csv(path):
    if not os.path.exists(path):
        sys.exit(f"ERROR: {path} not found. Run this from the pipeline directory.")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def extract_confuse_groups(template_path):
    """Parses CONFUSE_GROUPS out of app_template.html so the quiz's distractor
    table can be checked against patterns.csv. Returns None if it can't be found."""
    if not os.path.exists(template_path):
        return None
    src = open(template_path, encoding="utf-8").read()
    try:
        block = src[src.index("const CONFUSE_GROUPS"):src.index("function confusablesFor")]
    except ValueError:
        return None
    return [re.findall(r'"([^"]+)"', line) for line in block.split("\n") if '["' in line]


def confusables_for(label, groups, match_counts=None):
    """Mirrors confusablesFor() in app_template.html, which skips labels that
    match zero drugs."""
    for g in groups:
        if label in g:
            return [x for x in g if x != label and (match_counts is None or match_counts[x] > 0)]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="app_template.html")
    ap.add_argument("--drugs", default="drugs.csv")
    ap.add_argument("--patterns", default="patterns.csv")
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--svgs", default="svgs_min.json")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    drugs_csv = read_csv(args.drugs)
    patterns_csv = read_csv(args.patterns)

    for p in (args.data, args.svgs):
        if not os.path.exists(p):
            sys.exit(f"ERROR: {p} not found — run process.py and minify_svg.py first.")
    data = json.load(open(args.data))
    svgs = json.load(open(args.svgs))
    drugs = data["drugs"]

    # ---- 1. source CSV integrity ------------------------------------------
    names = [d["generic_name"].strip() for d in drugs_csv if d.get("generic_name", "").strip()]
    for name, n in Counter(names).items():
        if n > 1:
            error(f"duplicate generic_name in drugs.csv: {name!r} appears {n}x")

    slug_owners = {}
    for name in names:
        slug_owners.setdefault(slugify(name), []).append(name)
    for slug, owners in slug_owners.items():
        if len(owners) > 1:
            error(f"slug collision: {' and '.join(repr(o) for o in owners)} both slugify to {slug!r}",
                  "One will silently overwrite the other's structure drawing.")

    labels = [p["label"].strip() for p in patterns_csv if p.get("label", "").strip()]
    for label, n in Counter(labels).items():
        if n > 1:
            error(f"duplicate label in patterns.csv: {label!r} appears {n}x")

    for p in patterns_csv:
        label = p.get("label", "").strip()
        if not label:
            continue
        cat = p.get("category", "").strip()
        if cat not in ("Heterocycle", "Functional group"):
            error(f"{label!r} has category={cat!r}",
                  "Must be exactly 'Heterocycle' or 'Functional group' — anything else "
                  "vanishes from the sidebar and the quiz category filter.")
        if not p.get("pka_note", "").strip():
            warn(f"{label!r} has a blank pka_note", "Feedback text will show an empty parenthetical.")

    # ---- 2. did every drug survive processing? ----------------------------
    processed = {d["name"] for d in drugs}
    for name in names:
        if name not in processed:
            error(f"{name!r} is in drugs.csv but not in data.json",
                  "RDKit could not parse its SMILES — check process.py's stderr output.")

    # ---- 3. data.json <-> svgs_min.json coherence -------------------------
    data_slugs = {d["slug"] for d in drugs}
    svg_slugs = set(svgs)
    if data_slugs - svg_slugs:
        error(f"{len(data_slugs - svg_slugs)} drug(s) have no SVG: {sorted(data_slugs - svg_slugs)[:5]}",
              "Structures will render blank. Re-run minify_svg.py.")
    if svg_slugs - data_slugs:
        warn(f"{len(svg_slugs - data_slugs)} orphan SVG(s) with no drug record",
             "Harmless, but they inflate the payload — regenerate both files together.")

    W, H = data["canvas"]
    for d in drugs:
        for m in d["matches"]:
            for box in m["boxes"]:
                x0, y0, x1, y1 = box
                if not (0 <= x0 <= x1 <= W and 0 <= y0 <= y1 <= H):
                    error(f"{d['name']}: highlight box {box} falls outside the {W}x{H} canvas",
                          "data.json and svgs_min.json are probably from different runs.")
                    break

    # ---- 4. drug stability vs. the last committed version -----------------
    # Students' saved progress refers to drugs by slug, and their question banks
    # by name. A drug that disappears takes that saved history with it.
    try:
        committed = subprocess.run(["git", "show", f"HEAD:{args.data}"], capture_output=True, text=True, check=True).stdout
        old_drugs = json.loads(committed)["drugs"]
    except Exception:
        old_drugs = None
    if old_drugs is not None:
        lost = {d["slug"] for d in old_drugs} - data_slugs
        if lost:
            warn(f"{len(lost)} drug(s) in the last committed version have disappeared: {sorted(lost)[:8]}",
                 "Students' saved progress and question-bank entries for these drugs will be dropped "
                 "the next time they open the page. Fine if intended; otherwise check for a renamed drug.")
        added = data_slugs - {d["slug"] for d in old_drugs}
        if added:
            note(f"{len(added)} new drug(s) since the last commit")
    else:
        note("no committed data.json found to compare against — skipping drug-stability check")

    # ---- 5. quiz reachability (the silent one) ----------------------------
    match_counts = Counter()
    for d in drugs:
        for m in d["matches"]:
            match_counts[m["label"]] += 1

    for label in labels:
        if match_counts[label] == 0:
            warn(f"{label!r} matches zero drugs",
                 "Its SMARTS may be wrong, or no drug in the set contains it. "
                 "It will not appear anywhere in the app.")

    groups = extract_confuse_groups(args.template)
    if groups is None:
        warn(f"could not read CONFUSE_GROUPS from {args.template} — skipping quiz-reachability check")
    else:
        # The six degree-of-substitution labels are deliberately excluded: they're
        # quizzed by the 'degree' question type instead of 'identify'.
        DEGREE_LABELS = {'Primary amine', 'Secondary amine', 'Tertiary amine',
                         'Primary alcohol', 'Secondary alcohol', 'Tertiary alcohol'}
        in_groups = {x for g in groups for x in g}

        for label in labels:
            if label in DEGREE_LABELS or match_counts[label] == 0:
                continue
            n = len(confusables_for(label, groups, match_counts))
            if n < 3:
                warn(f"{label!r} ({match_counts[label]} drugs) can never appear in an identify-type quiz",
                     f"It has {n} confusable(s) in CONFUSE_GROUPS; buildCandidatePool() requires 3. "
                     f"Add it to a row in CONFUSE_GROUPS in app_template.html. (It is still reachable in "
                     f"'Click the Group' mode, which needs no confusables.)")

        for stale in sorted(in_groups - set(labels)):
            warn(f"CONFUSE_GROUPS lists {stale!r}, which is not in patterns.csv",
                 "The app skips it automatically, so it is never offered as an answer; "
                 "remove it or fix the spelling.")

        for label in labels:
            if label in DEGREE_LABELS and match_counts[label] == 0:
                warn(f"degree-of-substitution label {label!r} matches no drugs",
                     "The 'Degree of Substitution' quiz mode depends on these six exact labels.")

    # ---- 5b. "Most Basic Nitrogen" answers must actually be basic ------------
    # process.py only offers a question when its correct answer scores as a real
    # base. This guards against the classifier regressing to the old behavior of
    # calling a non-basic N (isoxazole, pyridinium, imine...) "the most basic".
    BASIC_FAMILIES = ("Simple aliphatic amine", "Amine next to a carbonyl",
                      "Imidazole-type nitrogen", "Pyridine-type nitrogen —")
    for d in drugs:
        for o in d.get("basicNOptions") or []:
            if o["correct"] and not o["label"].startswith(BASIC_FAMILIES):
                error(f"{d['name']}: 'Most Basic Nitrogen' answer is not a basic group",
                      f"The marked correct answer is: {o['label']!r}. Students would be told a "
                      f"non-basic nitrogen is the most basic. Check classify_nitrogen() in process.py.")

    # ---- 6. coverage summary ---------------------------------------------
    basic_n = sum(1 for d in drugs if d.get("basicNOptions"))
    stereo = sum(1 for d in drugs if d["stereocenters"])
    ro5_eligible = sum(1 for d in drugs
                       if sum([d["mw"] > 500, d["logp"] > 5, d["hbd"] > 5, d["hba"] > 10]) <= 1)
    payload = (os.path.getsize(args.data) + os.path.getsize(args.svgs)) / 1e6

    print(f"\n{'='*66}")
    print(f"  {len(drugs)} drugs | {len(labels)} patterns "
          f"({sum(1 for p in patterns_csv if p.get('category','').strip()=='Heterocycle')} heterocycles, "
          f"{sum(1 for p in patterns_csv if p.get('category','').strip()=='Functional group')} functional groups)")
    print(f"  quiz pools: {basic_n} basic-N | {stereo} stereo | {ro5_eligible} Rule-of-5")
    print(f"  payload: {payload:.2f} MB uncompressed ({payload/max(len(drugs),1)*1000:.1f} KB per drug)")
    print(f"{'='*66}")

    for bucket, tag in ((ERRORS, "ERROR"), (WARNINGS, "WARN"), (NOTES, "note")):
        for msg, detail in bucket:
            print(f"\n[{tag}] {msg}")
            if detail:
                print(f"        {detail}")

    print(f"\n{len(ERRORS)} error(s), {len(WARNINGS)} warning(s).")
    if ERRORS:
        print("Do not deploy until the errors are resolved.")
        return 1
    if WARNINGS and args.strict:
        return 1
    print("Safe to run build.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
