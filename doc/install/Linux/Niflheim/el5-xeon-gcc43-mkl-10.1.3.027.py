scalapack = True
compiler = 'gcc43'
libraries = [
    'gfortran', 'mkl', 'guide', 'mkl_lapack', 'mkl_def',
    'mkl_scalapack', 'mkl_blacs_openmpi_lp64', 'mkl_blacs_openmpi_lp64',
    'mpi', 'mpi_f77'
    ]
library_dirs = [
    '/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/lib64',
    '/opt/intel/mkl/10.1.3.027/lib/em64t',
    ]
include_dirs += ['/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/include']
extra_link_args = [
    '-Wl,-rpath=/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/lib64,'
    '-rpath=/opt/intel/mkl/10.1.3.027/lib/em64t'
    ]
extra_compile_args = ['-O3', '-std=c99', '-funroll-all-loops', '-fPIC']
define_macros += [('GPAW_NO_UNDERSCORE_CBLACS', '1')]
define_macros += [('GPAW_NO_UNDERSCORE_CSCALAPACK', '1')]
mpicompiler = '/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/bin/mpicc'
mpilinker = mpicompiler
platform_id = 'xeon'
