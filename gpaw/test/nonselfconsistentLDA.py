import os
from ase import *
from gpaw.test import equal
from gpaw import GPAW

a = 7.5 * Bohr
n = 16
atoms = Atoms([Atom('He', (0.0, 0.0, 0.0))], cell=(a, a, a), pbc=True)
calc = GPAW(gpts=(n, n, n), nbands=1, xc='LDA')
atoms.set_calculator(calc)
e1 = atoms.get_potential_energy()
e1ref = calc.get_reference_energy()
de12 = calc.get_xc_difference('PBE')
calc.set(xc='PBE')
e2 = atoms.get_potential_energy()
e2ref = calc.get_reference_energy()
de21 = calc.get_xc_difference('LDA')
print e1ref + e1 + de12, e2ref + e2
print e1ref + e1, e2ref + e2 + de21
print de12, de21
equal(e1ref + e1 + de12, e2ref + e2, 0.02)
equal(e1ref + e1, e2ref + e2 + de21, 0.025)

calc.write('PBE.gpw')

de21b = GPAW('PBE.gpw').get_xc_difference('LDA')
print de21, de21b
equal(de21, de21b, 9e-8)
