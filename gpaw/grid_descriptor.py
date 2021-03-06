# Copyright (C) 2003  CAMP
# Please see the accompanying LICENSE file for further information.

"""Grid-descriptors

This module contains classes defining two kinds of grids:

* Uniform 3D grids.
* Radial grids.
"""

from math import pi, cos, sin, ceil, floor
from cmath import exp

import numpy as np

import _gpaw
import gpaw.mpi as mpi
from gpaw.domain import Domain
from gpaw.utilities import divrl, mlsqr
from gpaw.spline import Spline


# Remove this:  XXX
assert (-1) % 3 == 2
assert (np.array([-1]) % 3)[0] == 2

NONBLOCKING = False

class GridDescriptor(Domain):
    """Descriptor-class for uniform 3D grid

    A ``GridDescriptor`` object holds information on how functions, such
    as wave functions and electron densities, are discreticed in a
    certain domain in space.  The main information here is how many
    grid points are used in each direction of the unit cell.

    There are methods for tasks such as allocating arrays, performing
    symmetry operations and integrating functions over space.  All
    methods work correctly also when the domain is parallelized via
    domain decomposition.

    This is how a 2x2x2 3D array is laid out in memory::

        3-----7
        |\    |\ 
        | \   | \ 
        |  1-----5      z
        2--|--6  |   y  |
         \ |   \ |    \ |
          \|    \|     \|
           0-----4      +-----x

    Example:

     >>> a = np.zeros((2, 2, 2))
     >>> a.ravel()[:] = range(8)
     >>> a
     array([[[0, 1],
             [2, 3]],
            [[4, 5],
             [6, 7]]])
     """
    
    def __init__(self, N_c, cell_cv=(1, 1, 1), pbc_c=True,
                 comm=None, parsize=None):
        """Construct grid-descriptor object.

        parameters:

        N_c: 3 int's
            Number of grid points along axes.
        cell_cv: 3 float's or 3x3 floats
            Unit cell.
        pbc_c: one or three bool's
            Periodic boundary conditions flag(s).
        comm: MPI-communicator
            Communicator for domain-decomposition.
        parsize: tuple of 3 int's, a single int or None
            Number of domains.

        Note that if pbc_c[c] is True, then the actual number of gridpoints
        along axis c is one less than N_c[c].

        Attributes:

        ==========  ========================================================
        ``dv``      Volume per grid point.
        ``h_cv``    Array of the grid spacing along the three axes.
        ``N_c``     Array of the number of grid points along the three axes.
        ``n_c``     Number of grid points on this CPU.
        ``beg_c``   Beginning of grid-point indices (inclusive).
        ``end_c``   End of grid-point indices (exclusive).
        ``comm``    MPI-communicator for domain decomposition.
        ==========  ========================================================

        The length unit is Bohr.
        """
        
        if isinstance(pbc_c, int):
            pbc_c = (pbc_c,) * 3
        if comm is None:
            comm = mpi.world
        Domain.__init__(self, cell_cv, pbc_c, comm, parsize, N_c)
        self.rank = self.comm.rank

        self.N_c = np.array(N_c, int)

        parsize_c = self.parsize_c
        n_c, remainder_c = divmod(N_c, parsize_c)

        self.beg_c = np.empty(3, int)
        self.end_c = np.empty(3, int)

        self.n_cp = []
        for c in range(3):
            n_p = np.arange(parsize_c[c] + 1) * float(N_c[c]) / parsize_c[c]
            n_p = np.around(n_p + 0.4999).astype(int)
            
            if not self.pbc_c[c]:
                n_p[0] = 1

            if not np.alltrue(n_p[1:] - n_p[:-1]):
                raise ValueError('Grid too small!')
                    
            self.beg_c[c] = n_p[self.parpos_c[c]]
            self.end_c[c] = n_p[self.parpos_c[c] + 1]
            self.n_cp.append(n_p)
            
        self.n_c = self.end_c - self.beg_c

        self.h_cv = self.cell_cv / self.N_c[:, np.newaxis]
        self.dv = abs(np.linalg.det(self.cell_cv)) / self.N_c.prod()

        self.orthogonal = not (self.cell_cv -
                               np.diag(self.cell_cv.diagonal())).any()

        # Sanity check for grid spacings:
        L_c = (np.linalg.inv(self.cell_cv)**2).sum(0)**-0.5
        h_c = L_c / N_c
        if max(h_c) / min(h_c) > 1.3:
            raise ValueError('Very anisotropic grid spacings: %s' % h_c)

        self.use_fixed_bc = False

    def get_size_of_global_array(self, pad=False):
        if pad:
            return self.N_c
        else:
            return self.N_c - 1 + self.pbc_c

    def flat_index(self, G_c):
        g1, g2, g3 = G_c - self.beg_c
        return g3 + self.n_c[2] * (g2 + g1 * self.n_c[1])
    
    def get_slice(self):
        return [slice(b - 1 + p, e - 1 + p) for b, e, p in
                zip(self.beg_c, self.end_c, self.pbc_c)]

    def zeros(self, n=(), dtype=float, global_array=False, pad=False):
        """Return new zeroed 3D array for this domain.

        The type can be set with the ``dtype`` keyword (default:
        ``float``).  Extra dimensions can be added with ``n=dim``.  A
        global array spanning all domains can be allocated with
        ``global_array=True``."""

        return self._new_array(n, dtype, True, global_array, pad)
    
    def empty(self, n=(), dtype=float, global_array=False, pad=False):
        """Return new uninitialized 3D array for this domain.

        The type can be set with the ``dtype`` keyword (default:
        ``float``).  Extra dimensions can be added with ``n=dim``.  A
        global array spanning all domains can be allocated with
        ``global_array=True``."""

        return self._new_array(n, dtype, False, global_array, pad)
        
    def _new_array(self, n=(), dtype=float, zero=True,
                  global_array=False, pad=False):
        if global_array:
            shape = self.get_size_of_global_array(pad)
        else:
            shape = self.n_c
            
        if isinstance(n, int):
            n = (n,)

        shape = n + tuple(shape)

        if zero:
            return np.zeros(shape, dtype)
        else:
            return np.empty(shape, dtype)
        
    def integrate(self, a_xg, b_xg=None, global_integral=True):
        """Integrate function(s) in array over domain.

        If the array(s) are distributed over several domains, then the
        total sum will be returned.  To get the local contribution
        only, use global_integral=False."""
        
        shape = a_xg.shape
        if len(shape) == 3:
            if b_xg is None:
                assert global_integral
                return self.comm.sum(a_xg.sum()) * self.dv
            else:
                assert not global_integral
                return np.vdot(a_xg, b_xg) * self.dv
        assert b_xg is None and global_integral
        A_x = np.sum(np.reshape(a_xg, shape[:-3] + (-1,)), axis=-1)
        self.comm.sum(A_x)
        return A_x * self.dv
    
    def coarsen(self):
        """Return coarsened `GridDescriptor` object.

        Reurned descriptor has 2x2x2 fewer grid points."""
        
        if np.sometrue(self.N_c % 2):
            raise ValueError('Grid %s not divisible by 2!' % self.N_c)

        gd = GridDescriptor(self.N_c // 2, self.cell_cv,
                            self.pbc_c, self.comm, self.parsize_c)
        gd.use_fixed_bc = self.use_fixed_bc
        return gd

    def refine(self):
        """Return refined `GridDescriptor` object.

        Reurned descriptor has 2x2x2 more grid points."""
        gd = GridDescriptor(self.N_c * 2, self.cell_cv,
                            self.pbc_c, self.comm, self.parsize_c)
        gd.use_fixed_bc = self.use_fixed_bc
        return gd
    
    def get_boxes(self, spos_c, rcut, cut=True):
        """Find boxes enclosing sphere."""
        N_c = self.N_c
        #ncut = rcut / self.h_c
        ncut = rcut * (self.icell_cv**2).sum(axis=1)**0.5 * self.N_c
        npos_c = spos_c * N_c
        beg_c = np.ceil(npos_c - ncut).astype(int)
        end_c = np.ceil(npos_c + ncut).astype(int)

        if cut or self.use_fixed_bc:
            for c in range(3):
                if not self.pbc_c[c]:
                    if beg_c[c] < 0:
                        beg_c[c] = 0
                    if end_c[c] > N_c[c]:
                        end_c[c] = N_c[c]
        else:
            for c in range(3):
                if (not self.pbc_c[c] and
                    (beg_c[c] < 0 or end_c[c] > N_c[c])):
                    raise RuntimeError(('Atom at %.3f %.3f %.3f ' +
                                        'too close to boundary ' +
                                        '(beg. of box %s, end of box %s)') %
                                       (tuple(spos_c) + (beg_c, end_c)))
                    
        range_c = ([], [], [])
        
        for c in range(3):
            b = beg_c[c]
            e = b
            
            while e < end_c[c]:
                b0 = b % N_c[c]
               
                e = min(end_c[c], b + N_c[c] - b0)

                if b0 < self.beg_c[c]:
                    b1 = b + self.beg_c[c] - b0
                else:
                    b1 = b
                    
                e0 = b0 - b + e
                              
                if e0 > self.end_c[c]:
                    e1 = e - (e0 - self.end_c[c])
                else:
                    e1 = e
                if e1 > b1:
                    range_c[c].append((b1, e1))
                b = e
        
        boxes = []

        for b0, e0 in range_c[0]:
            for b1, e1 in range_c[1]:
                for b2, e2 in range_c[2]:
                    b = np.array((b0, b1, b2))
                    e = np.array((e0, e1, e2))
                    beg_c = np.array((b0 % N_c[0], b1 % N_c[1], b2 % N_c[2]))
                    end_c = beg_c + e - b
                    disp = (b - beg_c) / N_c
                    beg_c = np.maximum(beg_c, self.beg_c)
                    end_c = np.minimum(end_c, self.end_c)
                    if (beg_c[0] < end_c[0] and
                        beg_c[1] < end_c[1] and
                        beg_c[2] < end_c[2]):
                        boxes.append((beg_c, end_c, disp))

        return boxes

    def get_nearest_grid_point(self, spos_c, force_to_this_domain=False):
        """Return index of nearest grid point.
        
        The nearest grid point can be on a different CPU than the one the
        nucleus belongs to (i.e. return can be negative, or larger than
        gd.end_c), in which case something clever should be done.
        The point can be forced to the grid descriptors domain to be
        consistent with self.get_rank_from_position(spos_c).
        """
        g_c = np.around(self.N_c * spos_c).astype(int)
        if force_to_this_domain:
            for c in range(3):
                g_c[c] = max(g_c[c], self.beg_c[c])
                g_c[c] = min(g_c[c], self.end_c[c] - 1)
        return g_c - self.beg_c


    def symmetrize(self, a_g, op_scc):
        if len(op_scc) == 1:
            return
        
        A_g = self.collect(a_g)
        if self.comm.rank == 0:
            B_g = np.zeros_like(A_g)
            for op_cc in op_scc:
                _gpaw.symmetrize(A_g, B_g, op_cc)
        else:
            B_g = None
        self.distribute(B_g, a_g)
        a_g /= len(op_scc)
    
    def collect(self, a_xg, broadcast=False):
        """Collect distributed array to master-CPU or all CPU's."""
        if self.comm.size == 1:
            return a_xg

        xshape = a_xg.shape[:-3]

        # Collect all arrays on the master:
        if self.rank != 0:
            # There can be several sends before the corresponding receives
            # are posted, so use syncronous send here
            self.comm.ssend(a_xg, 0, 301)
            if broadcast:
                A_xg = self.empty(xshape, a_xg.dtype, global_array=True)
                self.comm.broadcast(A_xg, 0)
                return A_xg
            else:
                return None

        # Put the subdomains from the slaves into the big array
        # for the whole domain:
        A_xg = self.empty(xshape, a_xg.dtype, global_array=True)
        parsize_c = self.parsize_c
        r = 0
        for n0 in range(parsize_c[0]):
            b0, e0 = self.n_cp[0][n0:n0 + 2] - self.beg_c[0]
            for n1 in range(parsize_c[1]):
                b1, e1 = self.n_cp[1][n1:n1 + 2] - self.beg_c[1]
                for n2 in range(parsize_c[2]):
                    b2, e2 = self.n_cp[2][n2:n2 + 2] - self.beg_c[2]
                    if r != 0:
                        a_xg = np.empty(xshape + 
                                        ((e0 - b0), (e1 - b1), (e2 - b2)),
                                        a_xg.dtype.char)
                        self.comm.receive(a_xg, r, 301)
                    A_xg[..., b0:e0, b1:e1, b2:e2] = a_xg
                    r += 1
        if broadcast:
            self.comm.broadcast(A_xg, 0)
        return A_xg

    def distribute(self, B_xg, b_xg):
        """Distribute full array B_xg to subdomains, result in b_xg.

        B_xg is not used by the slaves (i.e. it should be None on all slaves)
        b_xg must be allocated on all nodes and will be overwritten.
        """

        if self.comm.size == 1:
            b_xg[:] = B_xg
            return
        
        if self.rank != 0:
            self.comm.receive(b_xg, 0, 42)
            return
        else:
            parsize_c = self.parsize_c
            requests = []
            r = 0
            for n0 in range(parsize_c[0]):
                b0, e0 = self.n_cp[0][n0:n0 + 2] - self.beg_c[0]
                for n1 in range(parsize_c[1]):
                    b1, e1 = self.n_cp[1][n1:n1 + 2] - self.beg_c[1]
                    for n2 in range(parsize_c[2]):
                        b2, e2 = self.n_cp[2][n2:n2 + 2] - self.beg_c[2]
                        if r != 0:
                            a_xg = B_xg[..., b0:e0, b1:e1, b2:e2].copy()
                            request = self.comm.send(a_xg, r, 42, NONBLOCKING)
                            # Remember to store a reference to the
                            # send buffer (a_xg) so that is isn't
                            # deallocated:
                            requests.append((request, a_xg))
                        else:
                            b_xg[:] = B_xg[..., b0:e0, b1:e1, b2:e2]
                        r += 1
                        
            for request, a_xg in requests:
                self.comm.wait(request)
        
    def zero_pad(self, a_xg):
        """Pad array with zeros as first element along non-periodic directions.

        Should only be invoked on global arrays.
        """
        assert np.all(a_xg.shape[-3:] == (self.N_c + self.pbc_c - 1))
        if self.pbc_c.all():
            return a_xg

        npbx, npby, npbz = 1 - self.pbc_c
        b_xg = np.zeros(a_xg.shape[:-3] + tuple(self.N_c), dtype=a_xg.dtype)
        b_xg[..., npbx:, npby:, npbz:] = a_xg
        return b_xg

    def calculate_dipole_moment(self, rho_g):
        """Calculate dipole moment of density."""
        rho_01 = rho_g.sum(axis=2)
        rho_02 = rho_g.sum(axis=1)
        rho_cg = [rho_01.sum(axis=1), rho_01.sum(axis=0), rho_02.sum(axis=0)]
        rhog_c = [np.dot(np.arange(self.beg_c[c], self.end_c[c]), rho_cg[c])
                  for c in range(3)]
        d_c = -np.dot(rhog_c, self.h_cv) * self.dv
        self.comm.sum(d_c)
        return d_c

    def wannier_matrix(self, psit_nG, psit_nG1, c, G, nbands=None):
        """Wannier localization integrals

        The soft part of Z is given by (Eq. 27 ref1)::

            ~       ~     -i G.r   ~
            Z   = <psi | e      |psi >
             nm       n             m
                    
        G is 1/N_c (plus 1 if k-points distances should be wrapped over
        the Brillouin zone), where N_c is the number of k-points along
        axis c, psit_nG and psit_nG1 are the set of wave functions for
        the two different spin/kpoints in question.

        ref1: Thygesen et al, Phys. Rev. B 72, 125119 (2005) 
        """
        same_wave = False
        if psit_nG is psit_nG1:
            same_wave = True

        if nbands is None:
            nbands = len(psit_nG)
        
        def get_slice(c, g, psit_nG):
            if c == 0:
                slice_nG = psit_nG[:nbands, g].copy()
            elif c == 1:
                slice_nG = psit_nG[:nbands, :, g].copy()
            else:
                slice_nG = psit_nG[:nbands, :, :, g].copy()
            return slice_nG.reshape((nbands, np.prod(slice_nG.shape[1:])))
        
        Z_nn = np.zeros((nbands, nbands), complex)
        for g in range(self.n_c[c]):
            A_nG = get_slice(c, g, psit_nG)
                
            if same_wave:
                B_nG = A_nG
            else:
                B_nG = get_slice(c, g, psit_nG1)
                
            e = exp(-2.j * pi * G * (g + self.beg_c[c]) / self.N_c[c])
            Z_nn += e * np.dot(A_nG.conj(), B_nG.T) * self.dv
            
        return Z_nn

    def bytecount(self, dtype=float):
        """Get the number of bytes used by a grid of specified dtype."""
        return long(np.prod(self.n_c)) * np.array(1, dtype).itemsize

    def get_grid_point_coordinates(self, dtype=float, global_array=False):
        """Construct cartesian coordinates of grid points in the domain."""
        r_vG = np.dot(np.indices(self.n_c, dtype).T + self.beg_c,
                      self.h_cv).T.copy()
        if global_array:
            return self.collect(r_vG, broadcast=True)  # XXX waste!
        else:
            return r_vG

    def interpolate_grid_points(self, spos_nc, vt_g, target_n, use_mlsqr=True):
        """Return interpolated values.

        Calculate interpolated values from array vt_g based on the
        scaled coordinates on spos_c.

        Uses moving least squares algorithm by default, or otherwise
        trilinear interpolation.
        
        This doesn't work in parallel, since it would require
        communication between neighbouring grid.  """

        assert mpi.world.size == 1

        if use_mlsqr:
            mlsqr(3, 2.3, spos_nc, self.N_c, self.beg_c, vt_g, target_n)     
        else:
            for n, spos_c in enumerate(spos_nc):
                g_c = self.N_c * spos_c - self.beg_c

                # The begin and end of the array slice
                bg_c = np.floor(g_c).astype(int)
                Bg_c = np.ceil(g_c).astype(int)

                # The coordinate within the box (bottom left = 0,
                # top right = h_c)
                dg_c = g_c - bg_c
                Bg_c %= self.N_c

                target_n[n] = (
                    vt_g[bg_c[0],bg_c[1],bg_c[2]] *
                    (1.0 - dg_c[0]) * (1.0 - dg_c[1]) * (1.0 - dg_c[2]) + 
                    vt_g[Bg_c[0],bg_c[1],bg_c[2]] *
                    (0.0 + dg_c[0]) * (1.0 - dg_c[1]) * (1.0 - dg_c[2]) + 
                    vt_g[bg_c[0],Bg_c[1],bg_c[2]] *
                    (1.0 - dg_c[0]) * (0.0 + dg_c[1]) * (1.0 - dg_c[2]) +  
                    vt_g[Bg_c[0],Bg_c[1],bg_c[2]] *
                    (0.0 + dg_c[0]) * (0.0 + dg_c[1]) * (1.0 - dg_c[2]) + 
                    vt_g[bg_c[0],bg_c[1],Bg_c[2]] *
                    (1.0 - dg_c[0]) * (1.0 - dg_c[1]) * (0.0 + dg_c[2]) + 
                    vt_g[Bg_c[0],bg_c[1],Bg_c[2]] *
                    (0.0 + dg_c[0]) * (1.0 - dg_c[1]) * (0.0 + dg_c[2]) + 
                    vt_g[bg_c[0],Bg_c[1],Bg_c[2]] *
                    (1.0 - dg_c[0]) * (0.0 + dg_c[1]) * (0.0 + dg_c[2]) + 
                    vt_g[Bg_c[0],Bg_c[1],Bg_c[2]] *
                    (0.0 + dg_c[0]) * (0.0 + dg_c[1]) * (0.0 + dg_c[2]))

    def __eq__(self, other):
        return (self.dv == other.dv and
                (self.h_cv == other.h_cv).all() and
                (self.N_c == other.N_c).all() and
                (self.n_c == other.n_c).all() and
                (self.beg_c == other.beg_c).all() and
                (self.end_c == other.end_c).all()
                )
               
class RadialGridDescriptor:
    """Descriptor-class for radial grid."""
    def __init__(self, r_g, dr_g):
        """Construct `RadialGridDescriptor`.

        The one-dimensional array ``r_g`` gives the radii of the grid
        points according to some possibly non-linear function:
        ``r_g[g]`` = *f(g)*.  The array ``dr_g[g]`` = *f'(g)* is used
        for forming derivatives."""

        self.rcut = r_g[-1]
        self.ng = len(r_g)
        
        self.r_g = r_g
        self.dr_g = dr_g
        self.dv_g = 4 * pi * r_g**2 * dr_g

    def derivative(self, n_g, dndr_g):
        """Finite-difference derivative of radial function."""
        dndr_g[0] = n_g[1] - n_g[0]
        dndr_g[1:-1] = 0.5 * (n_g[2:] - n_g[:-2])
        dndr_g[-1] = n_g[-1] - n_g[-2]
        dndr_g /= self.dr_g

    def derivative2(self, a_g, b_g):
        """Finite-difference derivative of radial function.

        For an infinitely dense grid, this method would be identical
        to the `derivative` method."""
        
        c_g = a_g / self.dr_g
        b_g[0] = 0.5 * c_g[1] + c_g[0]
        b_g[1] = 0.5 * c_g[2] - c_g[0]
        b_g[1:-1] = 0.5 * (c_g[2:] - c_g[:-2])
        b_g[-2] = c_g[-1] - 0.5 * c_g[-3]
        b_g[-1] = -c_g[-1] - 0.5 * c_g[-2]

    def integrate(self, f_g):
        """Integrate over a radial grid."""
        
        return np.dot(self.dv_g, f_g)

    def spline(self, l, f_g):
        raise NotImplementedError

    def reducedspline(self, l, r_g):
        raise NotImplementedError

    def zeros(self, shape=()):
        if isinstance(shape, int):
            shape = (shape,)
        return np.zeros(shape + self.r_g.shape)

    def empty(self, shape=()):
        if isinstance(shape, int):
            shape = (shape,)
        return np.empty(shape + self.r_g.shape)

    def equidistant(self, f_g, points):
        ng = len(f_g)
        r_g = self.r_g[:ng]
        rmax = r_g[-1]
        r = 1.0 * rmax / points * np.arange(points + 1)
        g = (self.N * r / (self.beta + r) + 0.5).astype(int)
        g = np.clip(g, 1, ng - 2)
        r1 = np.take(r_g, g - 1)
        r2 = np.take(r_g, g)
        r3 = np.take(r_g, g + 1)
        x1 = (r - r2) * (r - r3) / (r1 - r2) / (r1 - r3)
        x2 = (r - r1) * (r - r3) / (r2 - r1) / (r2 - r3)
        x3 = (r - r1) * (r - r2) / (r3 - r1) / (r3 - r2)
        f1 = np.take(f_g, g - 1)
        f2 = np.take(f_g, g)
        f3 = np.take(f_g, g + 1)
        f_g = f1 * x1 + f2 * x2 + f3 * x3
        return f_g


class EquidistantRadialGridDescriptor(RadialGridDescriptor):
    def __init__(self, h, ng):
        self.h = h
        r_g = self._get_position_array(h, ng)
        RadialGridDescriptor.__init__(self, r_g, np.ones(ng) * h)

    def _get_position_array(self, h, ng):
        # AtomGridDescriptor overrides this to use r_g = [h, 2h, ... ng h]
        # In this class it is [0, h, ... (ng - 1) h]
        return h * np.arange(ng)

    def r2g_ceil(self, r):
        return int(ceil(r / self.h))

    def r2g_floor(self, r):
        return int(floor(r / self.h))

    def truncate(self, gmax):
        return EquidistantRadialGridDescriptor(self.h, gmax)

    def spline(self, l, f_g):
        ng = len(f_g)
        rmax = self.r_g[ng - 1]
        return Spline(l, rmax, f_g)

    def reducedspline(self, l, f_g):
        f_g = divrl(f_g, l, self.r_g[:len(f_g)])
        return self.spline(l, f_g)


class AERadialGridDescriptor(RadialGridDescriptor):
    """Descriptor-class for non-uniform grid used by setups, all-electron.

    The grid is defined by::
    
          beta g
      r = ------,  g = 0, 1, ..., N - 1
           N - g
      
            r N
      g = --------
          beta + r
    """
    def __init__(self, beta, N, default_spline_points=25, _noarrays=False):
        self.beta = beta
        self.N = N
        self.default_spline_points = default_spline_points
        if _noarrays:
            return

        self.ng = N # different from N only if using truncate()
        g = np.arange(N, dtype=float)
        r_g = beta * g / (N - g)
        dr_g = beta * N / (N - g)**2
        RadialGridDescriptor.__init__(self, r_g, dr_g)
        d2gdr2 = -2 * N * beta / (beta + r_g)**3
        self.d2gdr2 = d2gdr2

    def r2g_ceil(self, r):
        return int(ceil(r * self.N / (self.beta + r)))

    def r2g_floor(self, r):
        return int(floor(r * self.N / (self.beta + r)))

    def truncate(self, gcut):
        """Return a descriptor for a subset of this grid."""
        # Hack to make it possible to create subgrids with smaller arrays
        other = AERadialGridDescriptor(self.beta, self.N, _noarrays=True)
        other.ng = gcut
        other.r_g = self.r_g[:gcut]
        other.dr_g = self.dr_g[:gcut]
        RadialGridDescriptor.__init__(other, other.r_g, other.dr_g)
        other.d2gdr2 = self.d2gdr2[:gcut]
        other.rcut = other.r_g[-1]
        return other

    def spline(self, l, f_g, points=None):
        ng = len(f_g)
        rmax = self.r_g[ng - 1]
        r_g = self.r_g[:ng]
        f_g = self.equidistant(f_g, points=points)
        return Spline(l, rmax, f_g)

    def reducedspline(self, l, f_g, points=None):
        ng = len(f_g)
        return self.spline(l, divrl(f_g, l, self.r_g[:ng]), points=points)

    def equidistant(self, f_g, points=None):
        if points is None:
            points = self.default_spline_points
        return RadialGridDescriptor.equidistant(self, f_g, points)
