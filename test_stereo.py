"""Chemistry checks for curated exercises (requires RDKit)."""
import json
import unittest
from rdkit import Chem
from rdkit.Chem import rdCIPLabeler
from stereo import generate

class StereoBankTests(unittest.TestCase):
    def test_checked_in_bank_matches_generator(self):
        with open('stereo.json') as f:
            self.assertEqual(json.load(f), generate())

    def test_relations_survive_smiles_round_trip(self):
        with open('stereo.json') as f:
            pairs = json.load(f)
        self.assertEqual(len(pairs), 15)
        for p in pairs:
            with self.subTest(pair=p['id']):
                a, b = [Chem.MolFromSmiles(p['smiles'+side]) for side in ['A','B']]
                # Verify graph identity without relying on drawing position or atom order.
                plain = []
                for m in [a,b]:
                    copy = Chem.Mol(m)
                    Chem.RemoveStereochemistry(copy)
                    plain.append(Chem.MolToSmiles(copy))
                self.assertEqual(*plain)
                self.assertEqual(Chem.MolToSmiles(a)==Chem.MolToSmiles(b),p['relation']=='Identical')
                mirror = Chem.Mol(a)
                for atom in mirror.GetAtoms():
                    if atom.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED:
                        atom.InvertChirality()
                self.assertEqual(Chem.MolToSmiles(mirror)==Chem.MolToSmiles(b),p['relation']=='Enantiomers')
                for side, m in [('A',a),('B',b)]:
                    rdCIPLabeler.AssignCIPLabels(m)
                    codes = sorted(atom.GetProp('_CIPCode') for atom in m.GetAtoms() if atom.HasProp('_CIPCode'))
                    self.assertEqual(codes, sorted(p['labels'+side]))
                expected = [] if p['relation']=='Identical' else list(range(1,p['centers']+1)) if p['relation']=='Enantiomers' else p['changed']
                self.assertEqual(p['changed'],expected)
                self.assertTrue(all(p[k].count('<svg')==1 for k in ['a','b','revealA','revealB']))

if __name__ == '__main__':
    unittest.main()
