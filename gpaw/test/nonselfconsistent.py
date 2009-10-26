import os
from ase import *
from ase.parallel import rank, barrier
from gpaw import GPAW
from gpaw.xc_functional import XCFunctional
from gpaw.test import equal, gen

# Generate setup
gen('He', xcname='revPBE')

a = 7.5 * Bohr
n = 16
atoms = Atoms('He', [(0.0, 0.0, 0.0)], cell=(a, a, a), pbc=True)
calc = GPAW(gpts=(n, n, n), nbands=1, xc='PBE')
atoms.set_calculator(calc)
e1 = atoms.get_potential_energy()
niter1 = calc.get_number_of_iterations()
e1ref = calc.get_reference_energy()
de12 = calc.get_xc_difference('revPBE')
calc.set(xc='revPBE')
e2 = atoms.get_potential_energy()
niter2 = calc.get_number_of_iterations()
e2ref = calc.get_reference_energy()
de21 = calc.get_xc_difference('PBE')
print e1ref + e1 + de12 - (e2ref + e2)
print e1ref + e1 - (e2ref + e2 + de21)
print de12, de21
equal(e1ref + e1 + de12, e2ref + e2, 8e-4)
equal(e1ref + e1, e2ref + e2 + de21, 3e-3)

calc.write('revPBE.gpw')

de21b = GPAW('revPBE.gpw').get_xc_difference('PBE')
equal(de21, de21b, 9e-8)

energy_tolerance = 0.000001
niter_tolerance = 0
equal(e1, -0.0790191103842, energy_tolerance) # svnversion 5252
equal(niter1, 13, niter_tolerance) # svnversion 5252
equal(e2, -0.0814873123761, energy_tolerance) # svnversion 5252
equal(niter2, 10, niter_tolerance) # svnversion 5252
