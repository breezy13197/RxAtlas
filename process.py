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
# real pKa calculation; RDKit has no pKa predictor). Each N atom gets a score
# that is roughly the pKa of its conjugate acid (pKaH), judged from the same
# structural cues a chemist reasons with by eye: does the N have a lone pair
# at all, is it delocalized (amide, aniline, enamine, aromatic ring), and how
# electron-poor is the ring it sits in.
#
# Scores near real pKaH values let basic_n_eligible() insist that the "most
# basic" answer is genuinely basic (MIN_BASIC_SCORE), not just the least
# non-basic of a bad bunch.
# ---------------------------------------------------------------------------
MIN_BASIC_SCORE = 5   # the correct answer must score at least this (≈ pyridine)
MIN_GAP = 3           # ...and beat every other marked N by at least this much

def _has_double(mol, atom, other_symbol):
    """True if `atom` has a double bond to an atom of element `other_symbol`."""
    return any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(atom).GetSymbol() == other_symbol
               for b in atom.GetBonds())

def _smallest_ring(mol, idx):
    rings = [r for r in mol.GetRingInfo().AtomRings() if idx in r]
    return min(rings, key=len) if rings else ()

def _ring_system(mol, idx):
    """All atoms in the fused ring system containing idx."""
    rings = [set(r) for r in mol.GetRingInfo().AtomRings() if idx in r]
    system = set().union(*rings) if rings else set()
    changed = True
    while changed:
        changed = False
        for r in mol.GetRingInfo().AtomRings():
            if system & set(r) and not set(r) <= system:
                system |= set(r); changed = True
    return system

def _electron_poor(mol, ring_atoms):
    """True if the ring carries an electron-withdrawing substituent (halogen,
    CF3, nitro, nitrile, carbonyl, sulfonyl) or has an exocyclic C=O / C=S
    (uracil/xanthine-type rings), which lowers the ring N's basicity a lot."""
    ring = set(ring_atoms)
    for i in ring:
        a = mol.GetAtomWithIdx(i)
        if _has_double(mol, a, 'O') or _has_double(mol, a, 'S'):
            return True
        for n in a.GetNeighbors():
            if n.GetIdx() in ring:
                continue
            sym = n.GetSymbol()
            if sym in ('F', 'Cl', 'Br', 'I'):
                return True
            if sym == 'N' and (n.GetFormalCharge() > 0 or any(b.GetBondTypeAsDouble() == 3 for b in n.GetBonds())):
                return True
            if sym == 'N' and any(m.GetSymbol() in ('C', 'S') and m.GetIdx() != i and
                                  (_has_double(mol, m, 'O') or _has_double(mol, m, 'S'))
                                  for m in n.GetNeighbors()):
                return True            # amide/carbamate/urea/sulfonamide N on the ring (e.g. 2-acylaminopyridine)
            if sym == 'C' and (_has_double(mol, n, 'O') or
                               sum(1 for m in n.GetNeighbors() if m.GetSymbol() == 'F') >= 2 or
                               any(b.GetBondTypeAsDouble() == 3 for b in n.GetBonds())):
                return True
            if sym == 'S' and _has_double(mol, n, 'O'):
                return True
    return False

def _is_amidine_carbon(c):
    """A non-aromatic C with one C=N double bond plus at least one more N attached
    (amidine, guanidine, isothiourea, 2-aminothiazoline...)."""
    if c.GetIsAromatic():
        return False
    n_neighbors = [b for b in c.GetBonds() if b.GetOtherAtom(c).GetSymbol() == 'N']
    return (len(n_neighbors) >= 2 and
            sum(1 for b in n_neighbors if b.GetBondTypeAsDouble() == 2) == 1)

def _acylated(n):
    """True if N atom `n` is attached to a C=O / C=S / S=O group."""
    return any(m.GetSymbol() in ('C', 'S') and
               any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(m).GetSymbol() in ('O', 'S') for b in m.GetBonds())
               for m in n.GetNeighbors())

def classify_nitrogen(mol, idx):
    atom = mol.GetAtomWithIdx(idx)
    neighbors = atom.GetNeighbors()
    bond = lambda n: mol.GetBondBetweenAtoms(idx, n.GetIdx())

    # --- no lone pair available -------------------------------------------
    if any(bond(n).GetBondTypeAsDouble() == 3 for n in neighbors):
        return ('Nitrile-type nitrogen — non-basic', -2)
    if atom.GetFormalCharge() > 0:
        if any(n.GetSymbol() == 'O' for n in neighbors):
            return ('Nitro/N-oxide-type nitrogen — non-basic', -2)
        return ('Quaternary or pyridinium-type nitrogen — permanently charged, no lone pair to accept a proton', -2)
    if any(n.GetSymbol() == 'S' and _has_double(mol, n, 'O') for n in neighbors):
        return ('Sulfonamide-type nitrogen — non-basic', -1)
    if any(n.GetSymbol() == 'C' and (_has_double(mol, n, 'O') or _has_double(mol, n, 'S')) for n in neighbors):
        return ('Amide-type nitrogen — non-basic (lone pair delocalized into the carbonyl)', 0)
    if any(n.GetSymbol() == 'P' for n in neighbors):
        return ('Phosphoramide-type nitrogen — non-basic', 0)

    # --- guanidine / amidine: very strong bases, but the charge is shared --------
    # Every N bonded to a non-aromatic C(=N)N carbon gets the same score on purpose:
    # the protonated form spreads its charge over those N's, so no single one can be
    # called "the most basic" and the eligibility check below rejects the question.
    amidine_cs = [n for n in neighbors if n.GetSymbol() == 'C' and _is_amidine_carbon(n)]
    if amidine_cs:
        if any(_acylated(x.GetOtherAtom(c)) for c in amidine_cs for x in c.GetBonds()
               if x.GetOtherAtom(c).GetSymbol() == 'N'):
            return ('Acyl-amidine/acylguanidine-type nitrogen — only weakly basic (the acyl group pulls electron density away)', 3)
        return ('Guanidine/amidine-type nitrogen — strongly basic, but the charge is shared across its N atoms', 13)

    # --- aromatic nitrogens ---------------------------------------------------
    if atom.GetIsAromatic():
        if atom.GetTotalDegree() == 3:      # [nH] or N-substituted: lone pair is part of the aromatic sextet
            return ('Pyrrole-type nitrogen — non-basic (lone pair is part of the aromatic sextet)', -1)
        ring = _smallest_ring(mol, idx)
        system = _ring_system(mol, idx)
        others = [mol.GetAtomWithIdx(i) for i in ring if i != idx]
        n_n = sum(1 for a in others if a.GetSymbol() == 'N')
        n_o = sum(1 for a in others if a.GetSymbol() == 'O')
        n_s = sum(1 for a in others if a.GetSymbol() == 'S')
        if _electron_poor(mol, system):
            return ('Pyridine-type nitrogen in an electron-poor ring — very weakly basic (lone pair available, but electron-withdrawing groups or C=O in the ring make it a poor base)', 1)
        if len(ring) == 6:
            if n_n == 0:
                return ('Pyridine-type nitrogen — weakly basic (pKaH ~5; lone pair in the plane of the ring)', 5)
            return ('Diazine/triazine-type nitrogen — very weakly basic (the extra ring N lowers pKaH to ~1–2)', 1)
        if n_o:
            return ('Oxazole/isoxazole-type nitrogen — essentially non-basic (the ring O pulls electron density away)', 0)
        if n_s:
            return ('Thiazole/thiadiazole-type nitrogen — very weakly basic (pKaH ≤ ~2.5)', 1)
        system_n = sum(1 for i in system if mol.GetAtomWithIdx(i).GetSymbol() == 'N')
        if system_n >= 3:
            return ('Pyridine-type nitrogen in an electron-poor fused azole (purine-like) — weakly basic (pKaH ~2–4)', 3)
        if n_n == 1 and not any(mol.GetBondBetweenAtoms(idx, a.GetIdx()) for a in others if a.GetSymbol() == 'N'):
            return ('Imidazole-type nitrogen — moderately basic (pKaH ~5–7)', 6)
        return ('Pyrazole/triazole/tetrazole-type nitrogen — very weakly basic (pKaH ≤ ~2.5)', 1)

    # --- non-aromatic sp2 nitrogen (imine, oxime, hydrazone, azo) -------------
    if any(b.GetBondTypeAsDouble() == 2 for b in atom.GetBonds()):
        return ('Imine/oxime-type nitrogen — sp2 N, only weakly basic', 2)

    # --- sp3 nitrogens with a delocalized or electron-poor lone pair ----------
    if any(n.GetIsAromatic() for n in neighbors):
        return ('Aniline-type nitrogen — weakly basic (lone pair pulled into the aromatic ring)', 3)
    if any(n.GetSymbol() == 'C' and any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(n).GetSymbol() == 'C' for b in n.GetBonds())
           for n in neighbors):
        return ('Enamine-type nitrogen — weakly basic (lone pair delocalized into the C=C)', 1)
    if any(n.GetSymbol() == 'N' for n in neighbors):
        return ('Hydrazine-type nitrogen — weaker than a simple amine (pKaH ~6–8) and ambiguous to rank', 4)
    if any(n.GetSymbol() in ('O', 'S') for n in neighbors):
        return ('Hydroxylamine-type nitrogen — weaker than a simple amine and ambiguous to rank', 4)
    for c in neighbors:
        for b in c.GetNeighbors():
            if b.GetIdx() == idx or b.GetIsAromatic():
                continue
            if _has_double(mol, b, 'O'):
                return ('Amine next to a carbonyl (α-amino carbonyl) — less basic than a simple amine (pKaH ~5–8)', 7)
            if any(x.GetSymbol() == 'F' for x in b.GetNeighbors()) or any(bb.GetBondTypeAsDouble() == 3 for bb in b.GetBonds()):
                return ('Amine next to a CF3/CF2 or nitrile — much less basic than a simple amine', 4)
    return ('Simple aliphatic amine — strongly basic, lone pair fully available', 10)

def basic_n_candidates(mol):
    out = []
    for a in mol.GetAtoms():
        if a.GetSymbol() == 'N':
            label, score = classify_nitrogen(mol, a.GetIdx())
            out.append({'idx': a.GetIdx(), 'label': label, 'score': score})
    return out

def basic_n_eligible(candidates):
    """Only molecules with a clear, unambiguous AND genuinely basic top pick
    qualify as a fair quiz question."""
    if len(candidates) < 2:
        return False, None
    scores = sorted(set(c['score'] for c in candidates), reverse=True)
    if scores[0] < MIN_BASIC_SCORE:
        return False, None            # none of the marked N's is actually basic
    if len(scores) < 2 or scores[0] - scores[1] < MIN_GAP:
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
