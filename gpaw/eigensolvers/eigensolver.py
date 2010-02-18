"""Module defining and eigensolver base-class."""

from math import ceil

import numpy as np

from gpaw.fd_operators import Laplace
from gpaw.preconditioner import Preconditioner
from gpaw.utilities.lapack import diagonalize, sldiagonalize
from gpaw.utilities.blas import axpy, r2k, gemm
from gpaw.utilities.tools import apply_subspace_mask
from gpaw.utilities import unpack
from gpaw.utilities import scalapack
from gpaw import sl_diagonalize
from gpaw import debug


class BaseDiagonalizer:
    def __init__(self, world, gd, bd, kpt_comm):
        self.world = world
        self.gd = gd
        self.bd = bd
        self.kpt_comm = kpt_comm

    def diagonalize(self, H_NN, eps_n):
        nbands = self.bd.nbands
        eps_N = np.empty(nbands)
        info = self._diagonalize(H_NN, eps_N)
        if info != 0:
            raise RuntimeError('Failed to diagonalize: %d' % info)

        if self.gd.comm.rank == 0:
            self.bd.distribute(eps_N, eps_n)
            self.bd.comm.broadcast(H_NN, 0)

        self.gd.comm.broadcast(H_NN, 0)
        self.gd.comm.broadcast(eps_n, 0)

    def _diagonalize(self, H_NN, eps_n):
        raise NotImplementedError


class SLDiagonalizer(BaseDiagonalizer):
    """Original ScaLAPACK diagonalizer using 
    redundantly distributed arrays."""
    def __init__(self, world, gd, bd, kpt_comm, root=0):
        BaseDiagonalizer.__init__(self, world, gd, bd, kpt_comm)
        bcommsize = bd.comm.size
        gcommsize = gd.comm.size
        shiftks = kpt_comm.rank * bcommsize * gcommsize
        block_ranks = shiftks + np.arange(bcommsize * gcommsize)
        blockcomm = world.new_communicator(block_ranks)
        self.blockcomm = blockcomm
        self.root = root
        # Keep buffers?

    def _diagonalize(self, H_NN, eps_N):
        # Work is done on BLACS grid, but one processor still collects
        # all eigenvectors. Only processors on the BLACS grid return
        # meaningful values of info.
        return sldiagonalize(H_NN, eps_N, self.blockcomm, root=self.root)


class LapackDiagonalizer(BaseDiagonalizer):
    """Serial diagonalizer."""
    def _diagonalize(self, H_NN, eps_N):
        # Only one processor really does any work.
        if self.gd.comm.rank == 0 and self.bd.comm.rank == 0:
            return diagonalize(H_NN, eps_N)
        else:
            return 0

class Eigensolver:
    def __init__(self, keep_htpsit=True):
        self.keep_htpsit = keep_htpsit
        self.initialized = False
        self.Htpsit_nG = None
        self.error = np.inf
        
    def initialize(self, wfs):
        self.timer = wfs.timer
        self.world = wfs.world
        self.kpt_comm = wfs.kpt_comm
        self.band_comm = wfs.band_comm
        self.dtype = wfs.dtype
        self.bd = wfs.bd
        self.gd = wfs.gd
        self.nbands = wfs.nbands
        self.mynbands = wfs.mynbands

        self.operator = wfs.overlap.operator

        if self.mynbands != self.nbands or self.operator.nblocks != 1:
            self.keep_htpsit = False

        # Belows this will eventually be a BLACS matrix
        # and will be used as a ScaLAPACK workspace.
        # self.U_nn = np.empty((self.nbands, self.nbands), dtype=self.dtype)

        # Preconditioner for the electronic gradients:
        self.preconditioner = Preconditioner(self.gd, wfs.kin, self.dtype)

        if self.keep_htpsit:
            # Soft part of the Hamiltonian times psit:
            self.Htpsit_nG = self.gd.zeros(self.nbands, self.dtype)

        for kpt in wfs.kpt_u:
            if kpt.eps_n is None:
                kpt.eps_n = np.empty(self.mynbands)
        
        if sl_diagonalize:
            self.diagonalizer = SLDiagonalizer(self.world, self.gd, 
                                               self.bd, self.kpt_comm)
        else:
            self.diagonalizer = LapackDiagonalizer(self.world, self.gd,
                                                   self.bd, self.kpt_comm)

        self.initialized = True

    def iterate(self, hamiltonian, wfs):
        """Solves eigenvalue problem iteratively

        This method is inherited by the actual eigensolver which should
        implement *iterate_one_k_point* method for a single iteration of
        a single kpoint.
        """

        if not self.initialized:
            self.initialize(wfs)

        if not self.preconditioner.allocated:
            self.preconditioner.allocate()

        if not wfs.orthonormalized:
            wfs.orthonormalize()
            
        error = 0.0
        for kpt in wfs.kpt_u:
            error += self.iterate_one_k_point(hamiltonian, wfs, kpt)

        wfs.orthonormalize()

        self.error = self.band_comm.sum(self.kpt_comm.sum(error))

    def iterate_one_k_point(self, hamiltonian, kpt):
        """Implemented in subclasses."""
        raise NotImplementedError

    def calculate_residuals(self, wfs, hamiltonian, kpt, eps_n, R_nG, psit_nG,
                            n=None):
        B = len(eps_n)  # block size
        wfs.kin.apply(psit_nG, R_nG, kpt.phase_cd)
        hamiltonian.apply_local_potential(psit_nG, R_nG, kpt.s)
        P_ani = dict([(a, np.zeros((B, wfs.setups[a].ni), wfs.dtype))
                      for a in kpt.P_ani])
        wfs.pt.integrate(psit_nG, P_ani, kpt.q)
        self.calculate_residuals2(wfs, hamiltonian, kpt, R_nG,
                                  eps_n, psit_nG, P_ani, n=n)
        
    def calculate_residuals2(self, wfs, hamiltonian, kpt, R_nG,
                             eps_n=None, psit_nG=None, P_ani=None, n=None):
        if eps_n is None:
            eps_n = kpt.eps_n
        if psit_nG is None:
            psit_nG = kpt.psit_nG
        if P_ani is None:
            P_ani = kpt.P_ani
        for R_G, eps, psit_G in zip(R_nG, eps_n, psit_nG):
            axpy(-eps, psit_G, R_G)
        c_ani = {}
        for a, P_ni in P_ani.items():
            dH_ii = unpack(hamiltonian.dH_asp[a][kpt.s])
            dO_ii = hamiltonian.setups[a].dO_ii
            c_ni = (np.dot(P_ni, dH_ii) -
                    np.dot(P_ni * eps_n[:, np.newaxis], dO_ii))

            if hamiltonian.xc.xcfunc.hybrid > 0.0 and hasattr(kpt, 'vxx_ani'):
                if n is None:
                    c_ni += kpt.vxx_ani[a]
                else:
                    assert len(P_ni) == 1
                    c_ni[0] += np.dot(kpt.vxx_anii[a][n], P_ni[0])

            c_ani[a] = c_ni

        wfs.pt.add(R_nG, c_ani, kpt.q)

    def subspace_diagonalize(self, hamiltonian, wfs, kpt, rotate=True):
        """Diagonalize the Hamiltonian in the subspace of kpt.psit_nG

        *Htpsit_nG* is a work array of same size as psit_nG which contains
        the local part of the Hamiltonian times psit on exit

        First, the Hamiltonian (defined by *kin*, *vt_sG*, and
        *my_nuclei*) is applied to the wave functions, then the
        *H_nn* matrix is calculated and diagonalized, and finally,
        the wave functions are rotated.  Also the projections
        *P_uni* (an attribute of the nuclei) are rotated.

        It is assumed that the wave functions *psit_n* are orthonormal
        and that the integrals of projector functions and wave functions
        *P_uni* are already calculated.
        """

        if self.band_comm.size > 1 and wfs.bd.strided:
            raise NotImplementedError

        self.timer.start('Subspace diag')

        # U_nn = self.U_nn
        psit_nG = kpt.psit_nG
        P_ani = kpt.P_ani

        if self.keep_htpsit:
            Htpsit_xG = self.Htpsit_nG
        else:
            Htpsit_xG = self.operator.suggest_temporary_buffer(psit_nG.dtype)

        def H(psit_xG):
            wfs.kin.apply(psit_xG, Htpsit_xG, kpt.phase_cd)
            hamiltonian.apply_local_potential(psit_xG, Htpsit_xG, kpt.s)
            hamiltonian.xc.add_non_local_terms(psit_xG, Htpsit_xG, kpt.s)
            return Htpsit_xG
                
        dH_aii = dict([(a, unpack(dH_sp[kpt.s]))
                       for a, dH_sp in hamiltonian.dH_asp.items()])

        self.timer.start('calc_matrix')
        if hamiltonian.xc.xcfunc.hybrid == 0.0:
            H_nn = self.operator.calculate_matrix_elements(psit_nG, P_ani,
                                                           H, dH_aii)
        else:
            if self.band_comm.size > 1:
                raise NotImplementedError
            else:
                H_nn = hamiltonian.xc.xcfunc.exx.grr(wfs, kpt, Htpsit_xG,
                                                 hamiltonian)
        self.timer.stop('calc_matrix')

        diagonalizationstring = self.diagonalizer.__class__.__name__
        wfs.timer.start(diagonalizationstring)
        self.diagonalizer.diagonalize(H_nn, kpt.eps_n)
        # The two lines below will go away soon
        U_nn = H_nn
        del H_nn
        wfs.timer.stop(diagonalizationstring)
        
        if not rotate:
            self.timer.stop('Subspace diag')
            return

        self.timer.start('rotate_psi')
        kpt.psit_nG = self.operator.matrix_multiply(U_nn, psit_nG, P_ani)
        if self.keep_htpsit:
            self.Htpsit_nG = self.operator.matrix_multiply(U_nn, Htpsit_xG)
        self.timer.stop('rotate_psi')

        # Rotate EXX related stuff
        if hamiltonian.xc.xcfunc.hybrid > 0.0:
            hamiltonian.xc.xcfunc.exx.rotate(kpt, U_nn)

        self.timer.stop('Subspace diag')

    def estimate_memory(self, mem, gd, dtype, mynbands, nbands):
        gridmem = gd.bytecount(dtype)

        keep_htpsit = self.keep_htpsit and (mynbands == nbands)

        if keep_htpsit:
            mem.subnode('Htpsit', nbands * gridmem)
        else:
            mem.subnode('No Htpsit', 0)

        # mem.subnode('U_nn', nbands*nbands*mem.floatsize)
        mem.subnode('eps_n', nbands*mem.floatsize)
        mem.subnode('Preconditioner', 4 * gridmem)
        mem.subnode('Work', gridmem)

