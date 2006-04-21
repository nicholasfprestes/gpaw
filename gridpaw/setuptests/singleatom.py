import sys

import Numeric as num
from ASE.Units import units
from ASE import Atom, ListOfAtoms

from gridpaw.atom.configurations import configurations
from gridpaw import Calculator


assert units.GetLengthUnit() == 'Ang' and units.GetEnergyUnit() == 'eV'

# Special cases:
magmoms = {}


class SingleAtom:
    def __init__(self, symbol, a=None, h=None, spinpaired=False,
                 eggboxtest=False, parameters={}):
        if a is None:
            a = 7.0  # Angstrom

        if eggboxtest:
            spinpaired = True
            
        if spinpaired:
            magmom = 0
            width = 0.01  # 1 meV
            hund = False
        else:
            width = 0
            hund = True
            # Is this a special case?
            magmom = magmoms.get(symbol)
            if magmom is None:
                # No.  Use Hund's rule:
                magmom = 0
                for n, l, f, e in configurations[symbol][1]:
                    magmom += min(f, 2 * (2 * l + 1) - f)
                    
        self.atom = ListOfAtoms([Atom(symbol, [a / 2, a / 2, a / 2],
                                      magmom=magmom)],
                                periodic=eggboxtest,
                                cell=[a, a, a])
        
        calc = Calculator(h=h, width=width, hund=hund, **parameters)
        self.atom.SetCalculator(calc)
        
    def energy(self):
        return self.atom.GetPotentialEnergy()

    def eggboxtest(self, N=30, verbose=False):
        X = num.zeros(N + 1, num.Float)
        e = num.zeros(N + 1, num.Float)
        dedx = num.zeros(N + 1, num.Float)
        self.atom[0].SetCartesianPosition([0, 0, 0])
        self.energy()
        h = self.atom.GetCalculator().GetGridSpacings()[0]
        for g in range(-2, N + 1):
            if verbose:
                sys.stderr.write('.')
            x = g * h / 2 / N
            self.atom[0].SetCartesianPosition([x, 0, 0])
            energy = self.energy()
            forces = self.atom.GetCartesianForces()
            # The two first points are only for warm up.
            if g >= 0:
                X[g] = x
                e[g] = energy
                dedx[g] = -forces[0, 0]
        if verbose:
            sys.stderr.write('\n')
            
        return X, e, dedx
