"""Module defining  ``Eigensolver`` classes."""

import Numeric as num
from multiarray import innerproduct as inner # avoid the dotblas version!

import LinearAlgebra as linalg
from gpaw.operators import Laplace
from gpaw.preconditioner import Preconditioner
from gpaw.utilities.lapack import diagonalize
from gpaw.utilities.blas import axpy, r2k, gemm
from gpaw.utilities.complex import cc, real
from gpaw.utilities.tools import apply_subspace_mask
from gpaw.utilities import unpack

class Eigensolver:
    def __init__(self, timer, kpt_comm, gd, kin, typecode, nbands):
        self.timer = timer
        self.kpt_comm = kpt_comm
        self.typecode = typecode
        self.gd = gd
        self.comm = gd.comm
        self.nbands = nbands

        # Preconditioner for the electronic gradients:
        self.preconditioner = Preconditioner(gd, kin, typecode)

        # Soft part of the Hamiltonian times psit
        self.Htpsit_nG = self.gd.empty(nbands, typecode)

        # Work array for e.g. subspace rotations
        self.work = self.gd.empty(nbands, typecode)

        # Hamiltonian matrix
        self.H_nn = num.empty((nbands, nbands), self.typecode)

    def set_convergence_criteria(self, convergeall, tolerance, nvalence):
        self.convergeall = convergeall
        self.tolerance = tolerance
        self.nvalence = nvalence
        
    def iterate(self, hamiltonian, kpt_u):
        """Solves eigenvalue problem iteratively

        This method is inherited by the actual eigensolver which should
        implement ``iterate_one_k_point`` method for a single iteration of
        a single kpoint.
        """

        if self.nvalence == 0:
            return self.tolerance, True
        
        error = 0.0
        for kpt in kpt_u:
            error += self.iterate_one_k_point(hamiltonian, kpt)
            
        if self.convergeall:
            error = self.comm.sum(self.kpt_comm.sum(error)) / kpt_u[0].nbands
        else:
            error = self.comm.sum(self.kpt_comm.sum(error)) / self.nvalence
        
        return error, error <= self.tolerance

    def iterate_one_k_point(self, hamiltonian, kpt):
        """Implemented in subclasses."""
        return 0.0
    
    def diagonalize(self, hamiltonian, kpt):
        """Diagonalize the Hamiltonian in the subspace of kpt.psit_nG

        ``Htpsit_nG`` is working array of same size as psit_nG which contains
        the local part of the Hamiltonian times psit on exit

        First, the Hamiltonian (defined by ``kin``, ``vt_sG``, and
        ``my_nuclei``) is applied to the wave functions, then the
        ``H_nn`` matrix is calculated and diagonalized, and finally,
        the wave functions are rotated.  Also the projections
        ``P_uni`` (an attribute of the nuclei) are rotated.
        
        It is assumed that the wave functions ``psit_n`` are orthonormal
        and that the integrals of projector functions and wave functions
        ``P_uni`` are already calculated
        """        
           
        self.timer.start('Subspace diag.')

        if self.nbands != kpt.nbands:
            raise RuntimeError('Bands: %d != %d' % (self.nbands, kpt.nbands))
        
        Htpsit_nG = self.Htpsit_nG
        psit_nG = kpt.psit_nG
        eps_n = kpt.eps_n
        H_nn = self.H_nn

        hamiltonian.kin.apply(psit_nG, Htpsit_nG, kpt.phase_cd)
            
        Htpsit_nG += psit_nG * hamiltonian.vt_sG[kpt.s]

        H_nn[:] = 0.0  # r2k fails without this!
        hamiltonian.xc.xcfunc.apply_non_local(kpt, Htpsit_nG, H_nn)

        r2k(0.5 * self.gd.dv, psit_nG, Htpsit_nG, 1.0, H_nn)
        
        for nucleus in hamiltonian.my_nuclei:
            P_ni = nucleus.P_uni[kpt.u]
            H_nn += num.dot(P_ni, num.dot(unpack(nucleus.H_sp[kpt.s]),
                                          cc(num.transpose(P_ni))))

        self.comm.sum(H_nn, kpt.root)

        # Uncouple occupied and unoccupied subspaces
        if hamiltonian.xc.xcfunc.hybrid > 0.0:
            apply_subspace_mask(H_nn, kpt.f_n)

        if self.comm.rank == kpt.root:
            info = diagonalize(H_nn, eps_n)
            if info != 0:
                raise RuntimeError, 'Very Bad!!'

        self.comm.broadcast(H_nn, kpt.root)
        self.comm.broadcast(eps_n, kpt.root)

        # Rotate psit_nG:
        gemm(1.0, psit_nG, H_nn, 0.0, self.work)
        
        # Rotate Htpsit_nG:
        gemm(1.0, Htpsit_nG, H_nn, 0.0, psit_nG)

        #Switch the references
        kpt.psit_nG, self.Htpsit_nG, self.work = self.work, psit_nG, Htpsit_nG
        
        # Rotate P_uni:
        for nucleus in hamiltonian.my_nuclei:
            P_ni = nucleus.P_uni[kpt.u]
            gemm(1.0, P_ni.copy(), H_nn, 0.0, P_ni)

        if hamiltonian.xc.xcfunc.hybrid > 0.0:
            vxxt_nG = hamiltonian.xc.xcfunc.exx.vt_snG[kpt.s]
            gemm(1.0, vxxt_nG.copy(), H_nn, 0.0, vxxt_nG)
            for nucleus in hamiltonian.my_nuclei:
                v_ni = nucleus.vxx_uni[kpt.u]
                gemm(1.0, v_ni.copy(), H_nn, 0.0, v_ni)
                v_nii = nucleus.vxx_unii[kpt.u]
                gemm(1.0, v_nii.copy(), H_nn, 0.0, v_nii)

        self.timer.stop()
