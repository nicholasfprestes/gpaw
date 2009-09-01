scalapack = True
compiler = 'gcc43'
libraries =[
        'gfortran','scalapack','mpiblacsF77init','mpiblacs','scalapack',
        'f77blas','cblas','atlas','lapack','f77blas','cblas',
        'mpi','mpi_f77'
        ]
library_dirs =[
        '/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/lib64',
        '/opt/atlas/3.8.3/1.el5.fys.gfortran43.4.3.2/lib64',
        '/opt/blacs/1.1/24.el5.fys.gfortran43.4.3.2.openmpi.1.3.3/lib64',
        '/opt/scalapack/1.8.0/1.el5.fys.gfortran43.4.3.2.openmpi.1.3.3.atlas.3.8.3.atlas.3.8.3/lib64'
        ]
include_dirs +=['/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/include']
extra_link_args =[
        '-Wl,-rpath=/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/lib64,'
        '-rpath=/opt/atlas/3.8.3/1.el5.fys.gfortran43.4.3.2/lib64,'
        '-rpath=/opt/blacs/1.1/24.el5.fys.gfortran43.4.3.2.openmpi.1.3.3/lib64,'
        '-rpath=/opt/scalapack/1.8.0/1.el5.fys.gfortran43.4.3.2.openmpi.1.3.3.atlas.3.8.3.atlas.3.8.3/lib64'
        ]
extra_compile_args =['-O3', '-std=c99', '-funroll-all-loops', '-fPIC']
define_macros +=[('GPAW_MKL', '1')]
mpicompiler = '/opt/openmpi/1.3.3-1.el5.fys.gfortran43.4.3.2/bin/mpicc'
mpilinker = mpicompiler
platform_id = 'xeon'
