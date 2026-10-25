import json, sys, re, csv
from rdkit import Chem
from rdkit.Chem import rdDepictor, Descriptors, rdMolDescriptors, Lipinski, FindMolChiralCenters, Crippen
from rdkit.Chem.Draw import rdMolDraw2D

DRUGS_CSV = "drugs.csv"
PATTERNS_CSV = "patterns.csv"

def load_drugs(path):
    drugs = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"generic_name", "brand_example", "drug_class", "smiles"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"ERROR: {path} is missing required column(s): {', '.join(sorted(missing))}\n"
                     f"Found columns: {reader.fieldnames}")
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            name = (row.get("generic_name") or "").strip()
            if not name:
                continue  # skip blank rows (common when editing in Excel)
            smi = (row.get("smiles") or "").strip()
            if not smi:
                sys.exit(f"ERROR: {path} row {i} ('{name}') has no SMILES.")
            drugs.append((name, (row.get("brand_example") or "").strip(),
                          (row.get("drug_class") or "").strip(), smi))
    return drugs

def load_patterns(path):
    patterns = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"label", "category", "smarts", "acid_base", "pka_note"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"ERROR: {path} is missing required column(s): {', '.join(sorted(missing))}\n"
                     f"Found columns: {reader.fieldnames}")
        for i, row in enumerate(reader, start=2):
            label = (row.get("label") or "").strip()
            if not label:
                continue
            smarts = (row.get("smarts") or "").strip()
            if not smarts:
                sys.exit(f"ERROR: {path} row {i} ('{label}') has no SMARTS string.")
            ab = (row.get("acid_base") or "").strip()
            if ab not in ("acidic", "basic", "neutral"):
                sys.exit(f"ERROR: {path} row {i} ('{label}') has acid_base='{ab}' — "
                         f"must be exactly 'acidic', 'basic', or 'neutral'.")
            patterns.append((label, (row.get("category") or "").strip(), smarts, ab,
                             (row.get("pka_note") or "").strip()))
    return patterns

DRUGS = load_drugs(DRUGS_CSV)
PATTERNS = load_patterns(PATTERNS_CSV)

# ---------------------------------------------------------------------------
# "Most basic nitrogen" classifier — a rule-based RELATIVE ranking (not a
# real pKa calculation; RDKit has no pKa predictor). Classifies each N atom
# into a basicity tier using the same structural cues a chemist reasons
# with by eye: aliphatic vs. aromatic, adjacent to a carbonyl, adjacent to
# an aromatic ring, part of a guanidine/amidine system, ring size (more
# ring nitrogens -> weaker base via inductive withdrawal).
# ---------------------------------------------------------------------------
def classify_nitrogen(mol, idx):
    atom = mol.GetAtomWithIdx(idx)
    neighbors = atom.GetNeighbors()
    if any(mol.GetBondBetweenAtoms(idx, n.GetIdx()).GetBondTypeAsDouble() == 3 for n in neighbors):
        return ('Nitrile-type nitrogen — non-basic', -2)
    if atom.GetFormalCharge() > 0 and any(n.GetSymbol() == 'O' and mol.GetBondBetweenAtoms(idx, n.GetIdx()).GetBondTypeAsDouble() == 2 for n in neighbors):
        return ('Nitro-type nitrogen — non-basic', -2)
    if any(n.GetSymbol() == 'S' and any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(n).GetSymbol() == 'O' for b in n.GetBonds()) for n in neighbors):
        return ('Sulfonamide-type nitrogen — non-basic', -1)
    if any(n.GetSymbol() == 'C' and any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(n).GetSymbol() == 'O' for b in n.GetBonds()) for n in neighbors):
        return ('Amide-type nitrogen — non-basic (lone pair delocalized into the carbonyl)', 0)
    if any(n.GetSymbol() == 'C' and any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(n).GetSymbol() == 'N' for b in n.GetBonds())
           and mol.GetBondBetweenAtoms(idx, n.GetIdx()).GetBondTypeAsDouble() == 1 for n in neighbors):
        return ('Guanidine/amidine-type nitrogen — very strongly basic (charge delocalized across multiple N)', 13)
    if atom.GetIsAromatic():
        if atom.GetTotalNumHs() == 0 and atom.GetDegree() == 3 and atom.GetFormalCharge() == 0:
            return ('Pyrrole-type nitrogen — non-basic (lone pair is part of the aromatic sextet)', -1)
        ri = mol.GetRingInfo()
        ring_n_count = 1
        for ring in ri.AtomRings():
            if idx in ring:
                ring_n_count = max(ring_n_count, sum(1 for i in ring if mol.GetAtomWithIdx(i).GetSymbol() == 'N'))
        score = max(1, 6 - ring_n_count)
        return (f'Aromatic "pyridine-type" nitrogen ({ring_n_count} N in the ring — more ring N = weaker base)', score)
    if any(n.GetIsAromatic() for n in neighbors):
        return ('Aniline-type nitrogen — weakly basic (lone pair pulled into the aromatic ring)', 4)
    return ('Simple aliphatic amine — strongly basic, lone pair fully available', 10)

def basic_n_candidates(mol):
    return [{'idx': a.GetIdx(), 'label': classify_nitrogen(mol, a.GetIdx())[0], 'score': classify_nitrogen(mol, a.GetIdx())[1]}
            for a in mol.GetAtoms() if a.GetSymbol() == 'N']

def basic_n_eligible(candidates):
    """Only molecules with a clear, unambiguous top pick qualify as a fair quiz question."""
    if len(candidates) < 2:
        return False, None
    scores = sorted(set(c['score'] for c in candidates), reverse=True)
    if len(scores) < 2 or scores[0] - scores[1] < 3:
        return False, None
    top = [c for c in candidates if c['score'] == scores[0]]
    if len(top) != 1:
        return False, None
    return True, top[0]

def pick_diverse_candidates(candidates, top, max_n=4):
    """Selects up to max_n candidates for display, prioritizing distinct
    basicity tiers over multiple examples from the same tier."""
    chosen = [top]
    remaining = sorted([c for c in candidates if c is not top], key=lambda c: -c['score'])
    seen_scores = {top['score']}
    for c in remaining:
        if len(chosen) >= max_n:
            break
        if c['score'] not in seen_scores:
            chosen.append(c)
            seen_scores.add(c['score'])
    for c in remaining:
        if len(chosen) >= max_n:
            break
        if c not in chosen:
            chosen.append(c)
    return chosen

compiled = []
for label, cat, smarts, acid_base, pka in PATTERNS:
    q = Chem.MolFromSmarts(smarts)
    if q is None:
        print(f"BAD SMARTS: {label} -> {smarts}", file=sys.stderr)
        continue
    compiled.append((label, cat, q, acid_base, pka))

def slugify(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

W, H = 260, 200

results = []
errors = []
svg_by_drug = {}

for name, brand, cls, smi in DRUGS:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        errors.append((name, smi))
        continue
    rdDepictor.Compute2DCoords(mol)

    drawer = rdMolDraw2D.MolDraw2DSVG(W, H)
    opts = drawer.drawOptions()
    opts.clearBackground = True
    opts.padding = 0.1
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    slug = slugify(name)
    svg_by_drug[slug] = svg

    matched = []
    for label, cat, q, acid_base, pka in compiled:
        matches = mol.GetSubstructMatches(q)
        if not matches:
            continue
        boxes = []
        for m in matches:
            xs, ys = [], []
            for idx in m:
                pt = drawer.GetDrawCoords(idx)
                xs.append(pt.x); ys.append(pt.y)
            pad = 10
            x0, x1 = max(0, min(xs) - pad), min(W, max(xs) + pad)
            y0, y1 = max(0, min(ys) - pad), min(H, max(ys) + pad)
            boxes.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
        matched.append({
            "label": label, "category": cat,
            "acidBase": acid_base, "pka": pka,
            "boxes": boxes,
        })

    stereo_centers = FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False)
    stereo_points = []
    for atom_idx, chirality in stereo_centers:
        pt = drawer.GetDrawCoords(atom_idx)
        stereo_points.append({"x": round(pt.x, 1), "y": round(pt.y, 1), "chirality": chirality})

    basic_n_options = None
    all_n_candidates = basic_n_candidates(mol)
    eligible, top_candidate = basic_n_eligible(all_n_candidates)
    if eligible:
        chosen = pick_diverse_candidates(all_n_candidates, top_candidate)
        basic_n_options = []
        for c in chosen:
            pt = drawer.GetDrawCoords(c['idx'])
            basic_n_options.append({
                "x": round(pt.x, 1), "y": round(pt.y, 1),
                "label": c['label'], "correct": c is top_candidate,
            })

    # HBD/HBA counts are defined here as direct atom-substructure matches (rather than
    # RDKit's more elaborate CalcNumHBD/CalcNumHBA) so the displayed count and the
    # revealed atom positions are *always* identical by construction — this is closer
    # to the original textbook Lipinski Rule-of-Five definition anyway. Note this means
    # HBA numbers here can run 1-2 higher (occasionally more) than RDKit's default
    # Lipinski.NumHAcceptors() for some molecules.
    hbd_matches = mol.GetSubstructMatches(Lipinski.HDonorSmarts)
    hbd_points = []
    for m in hbd_matches:
        pt = drawer.GetDrawCoords(m[0])
        hbd_points.append({"x": round(pt.x, 1), "y": round(pt.y, 1)})

    hba_matches = mol.GetSubstructMatches(Lipinski.HAcceptorSmarts)
    hba_points = []
    for m in hba_matches:
        pt = drawer.GetDrawCoords(m[0])
        hba_points.append({"x": round(pt.x, 1), "y": round(pt.y, 1)})

    results.append({
        "name": name,
        "brand": brand,
        "class": cls,
        "smiles": smi,
        "mw": round(Descriptors.MolWt(mol), 1),
        "logp": round(Crippen.MolLogP(mol), 2),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "hbd": len(hbd_points),
        "hba": len(hba_points),
        "hbdAtoms": hbd_points,
        "hbaAtoms": hba_points,
        "stereocenters": stereo_points,
        "basicNOptions": basic_n_options,
        "slug": slug,
        "matches": matched,
    })

print(f"Processed {len(results)} drugs OK, {len(errors)} failed to parse.", file=sys.stderr)
for n, s in errors:
    print(f"  FAILED: {n} -> {s}", file=sys.stderr)

with open("data.json", "w") as f:
    json.dump({"drugs": results, "canvas": [W, H]}, f)

with open("svgs.json", "w") as f:
    json.dump(svg_by_drug, f)

from collections import Counter
c = Counter()
for d in results:
    for m in d["matches"]:
        c[m["label"]] += 1
print("\n--- Tag coverage ---", file=sys.stderr)
for label, cat, _, acid_base, pka in compiled:
    print(f"{label:35s} {c.get(label,0):4d}   {acid_base}", file=sys.stderr)
