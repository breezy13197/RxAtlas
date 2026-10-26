"""Generate the curated, symmetry-free stereochemistry bank with RDKit.
Run only when changing exercises; build.py embeds the checked-in stereo.json.
"""
import json
from rdkit import Chem
from rdkit.Chem import rdCIPLabeler, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point3D
import math

# Simple acyclic molecules with distinct ends: no meso or equivalent-center cases.
MOLECULES = [
    ('2-butanol', 'C[C@H](O)CC'),
    ('Lactic acid', 'C[C@H](O)C(=O)O'),
    ('Alanine', 'C[C@H](N)C(=O)O'),
    ('3-bromobutan-2-ol', 'C[C@H](O)[C@H](Br)C'),
    ('2,3-dihydroxybutanoic acid', 'C[C@H](O)[C@H](O)C(=O)O'),
    ('2-amino-3-hydroxybutanoic acid', 'C[C@H](O)[C@H](N)C(=O)O'),
]

def labels(m):
    rdCIPLabeler.AssignCIPLabels(m)
    return [a.GetProp('_CIPCode') for a in m.GetAtoms() if a.HasProp('_CIPCode')]

def draw(m, centers, angle, reveal=False):
    m = Chem.Mol(m)
    # Rotate coordinates, never reflect: reflection would change stereochemistry.
    conf = m.GetConformer()
    for i in range(m.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(p.x*math.cos(angle)-p.y*math.sin(angle),
                                      p.x*math.sin(angle)+p.y*math.cos(angle), 0))
    for n, idx in enumerate(centers, 1):
        m.GetAtomWithIdx(idx).SetProp('atomNote', f'{n}: {m.GetAtomWithIdx(idx).GetProp("_CIPCode")}' if reveal else str(n))
    d = rdMolDraw2D.MolDraw2DSVG(440, 300)
    d.drawOptions().annotationFontScale = 0.85
    rdMolDraw2D.PrepareAndDrawMolecule(d, m)
    d.FinishDrawing()
    return d.GetDrawingText().split('</svg>')[0] + '</svg>'

def generate():
    bank = []
    for mi, (name, smiles) in enumerate(MOLECULES):
        a = Chem.MolFromSmiles(smiles)
        rdDepictor.Compute2DCoords(a)
        centers = [i for i, _ in Chem.FindMolChiralCenters(a)]
        for relation in ['Identical', 'Enantiomers'] + (['Diastereomers'] if len(centers)==2 else []):
            b = Chem.Mol(a)
            changed = [] if relation=='Identical' else list(range(len(centers))) if relation=='Enantiomers' else [mi % 2]
            for n in changed:
                b.GetAtomWithIdx(centers[n]).InvertChirality()
            la, lb = labels(a), labels(b)
            assert [n for n,(x,y) in enumerate(zip(la,lb)) if x!=y] == changed
            same = Chem.MolToSmiles(a) == Chem.MolToSmiles(b)
            assert same == (relation=='Identical')
            bank.append(dict(id=f'pair-{mi}-{relation.lower()}', name=name, centers=len(centers),
                smilesA=Chem.MolToSmiles(a), smilesB=Chem.MolToSmiles(b), relation=relation,
                changed=[n+1 for n in changed], labelsA=la, labelsB=lb,
                a=draw(a,centers,0), b=draw(b,centers,math.pi*2/3),
                revealA=draw(a,centers,0,True), revealB=draw(b,centers,math.pi*2/3,True)))
    return bank

if __name__ == '__main__':
    bank = generate()
    with open('stereo.json','w') as f:
        json.dump(bank,f,separators=(',', ':'))
    print(f'Generated {len(bank)} checked stereochemistry pairs.')
