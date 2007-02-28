# Copyright (C) 2006 CSC-Scientific Computing Ltd.

# Please see the accompanying LICENSE file for further information.

import os
import sys
import re
from distutils.util import get_platform
from distutils.sysconfig import get_config_var, get_config_vars
from distutils.command.config import config
from glob import glob
from os.path import join
from stat import ST_MTIME

def check_packages(packages, msg, force_inclusion_of_ase):
    """Check the python version and required extra packages

    If ASE is not installed, the `packages` list is extended with the
    ASE modules if they are found."""
    
    if sys.version_info < (2, 3, 0, 'final', 0):
        raise SystemExit('Python 2.3.1 or later is required!')
    
    try:
        import Numeric
    except ImportError:
        raise SystemExit('Numeric is not installed!')

    try:
        import Scientific.IO.NetCDF
    except ImportError:
        try:
            import Scientific
        except ImportError:
            msg += ['* Scientific is not installed.']
        else:
            msg += ['* Scientific.IO.NetCDF is not installed (the NetCDF',
                    '  C-library is probably missing).']
        msg += ['  You will not be able to write and read wave functions',
                '  in the netCDF format.']

    if not force_inclusion_of_ase:
        try:
            import ASE
        except ImportError:
            include_ase = True
        else:
            include_ase = False
            
    if force_inclusion_of_ase or include_ase:
        # Find ASE directories:
        ase = []
        for root, dirs, files in os.walk('ASE'):
            if 'CVS' in dirs:
                dirs.remove('CVS')
            if '__init__.py' in files:
                ase.append(root.replace('/', '.'))

        if len(ase) == 0:
            msg += ['* ASE is not installed!  You may be able to install',
                    "  gpaw, but you can't use it without ASE!"]
        else:
            packages += ase

def find_file(arg, dir, files):
    #looks if the first element of the list arg is contained in the list files
    # and if so, appends dir to to arg. To be used with the os.path.walk
    if arg[0] in files:
        arg.append(dir)

    
def get_system_config(define_macros, undef_macros,
                      include_dirs, libraries, library_dirs, extra_link_args,
                      extra_compile_args, runtime_library_dirs, extra_objects,
                      msg):
    
    undef_macros += ['NDEBUG']
    
    machine = os.uname()[4]
    if machine == 'sun4u':

        #  _
        # |_ | ||\ |
        #  _||_|| \|
        #

        include_dirs += ['/opt/SUNWhpc/include']
        extra_compile_args += ['-KPIC', '-fast']

        # Suppress warning from -fast (-xarch=native):
        f = open('cc-test.c', 'w')
        f.write('int main(){}\n')
        f.close()
        stderr = os.popen3('cc cc-test.c -fast')[2].read()
        arch = re.findall('-xarch=(\S+)', stderr)
        os.remove('cc-test.c')
        if len(arch) > 0:
            extra_compile_args += ['-xarch=%s' % arch[-1]]
            
        library_dirs += ['/opt/SUNWspro/lib',
                         '/opt/SUNWhpc/lib']
        runtime_library_dirs += ['/opt/SUNWspro/lib',
                                '/opt/SUNWhpc/lib']
        extra_objects += ['/opt/SUNWhpc/lib/shmpm.so.2',
                         '/opt/SUNWhpc/lib/rsmpm.so.2',
                         '/opt/SUNWhpc/lib/tcppm.so.2']

        # We need the -Bstatic before the -lsunperf and -lfsu:
        extra_link_args += ['-Bstatic', '-lsunperf', '-lfsu']
        cc_version = os.popen3('cc -V')[2].readline().split()[3]
        if cc_version > '5.6':
            libraries.append('mtsk')
        else:
            extra_link_args.append('-lmtsk')
            define_macros.append(('NO_C99_COMPLEX', '1'))

        

        msg += ['* Using SUN high performance library']

    elif sys.platform == 'aix5':

        #
        # o|_  _ _
        # ||_)| | |
        #

        extra_compile_args += ['-qlanglvl=stdc99']
        extra_link_args += ['-bmaxdata:0x80000000', '-bmaxstack:0x80000000']

        libraries += ['f', 'essl', 'lapack']
        define_macros.append(('GPAW_AIX', '1'))
        #    mpicompiler = 'mpcc_r'
        #    custom_interpreter = True

    elif machine == 'x86_64':

        #    _ 
        # \/|_||_    |_ |_|
        # /\|_||_| _ |_|  |
        #
    
        extra_compile_args += ['-Wall', '-std=c99']

        # Look for ACML libraries:
        acml = glob('/opt/acml*/gnu64/lib')
        if len(acml) > 0:
            libraries += ['acml', 'g2c']
            library_dirs += [acml[-1]]
            #extra_link_args += ['-Wl,-rpath=' + acml]
            msg += ['* Using ACML library']

    elif machine =='ia64':

        #  _  _
        # |_ |  o
        #  _||_||
        #
        
        extra_compile_args += ['-Wall', '-std=c99']

    elif machine == 'i686':

        #      _
        # o|_ |_||_
        # ||_||_||_|
        #
    
        extra_compile_args += ['-Wall', '-std=c99']

        mklbasedir = glob('/opt/intel/mkl*')
        libs = ['libmkl_ia32.a']
        if mklbasedir != []:
            os.path.walk(mklbasedir[0],find_file, libs)
        libs.pop(0)
        if libs != []:
            libs.sort()
            libraries += ['mkl_lapack',
                          'mkl_ia32', 'guide', 'pthread', 'mkl']#, 'mkl_def']
            library_dirs += libs
            msg +=  ['* Using MKL library: %s' % library_dirs[-1]]
            #extra_link_args += ['-Wl,-rpath=' + library_dirs[-1]]
        else:
            atlas = False
            for dir in ['/usr/lib', 'usr/local/lib']:
                if glob(join(dir, 'libatlas.a')) != []:
                    atlas = True
                    break
            if atlas:
                libraries += ['lapack', 'atlas', 'blas']
                library_dirs += [dir]
                msg +=  ['* Using ATLAS library']
            else:
                libraries += ['blas', 'lapack']
                msg +=  ['* Using standard lapack']
                
            # add libg2c if available
            g2c=False
            for dir in ['/usr/lib', 'usr/local/lib']:
                if glob(join(dir, 'libg2c.so')) != []:
                    g2c=True
                    break
                if glob(join(dir, 'libg2c.a')) != []:
                    g2c=True
                    break
            if g2c: libraries += ['g2c']

    elif sys.platform == 'darwin':

        extra_compile_args += ['-Wall', '-std=c99']
        include_dirs += ['/usr/include/malloc']
        
        if glob('/System/Library/Frameworks/vecLib.framework') != []:
            extra_link_args += ['-framework vecLib']
            msg += ['* Using vecLib']
        else:
            libraries += ['blas', 'lapack']
            msg +=  ['* Using standard lapack']

    return msg


def get_parallel_config(mpi_libraries,mpi_library_dirs,mpi_include_dirs,
                        mpi_runtime_library_dirs,mpi_define_macros):

    globals = {}
    execfile('gpaw/mpi/config.py', globals)
    mpi = globals['get_mpi_implementation']()
    
    if mpi == '':
        mpicompiler = None
        custom_interpreter = False

    elif mpi == 'sun':
        mpi_libraries += ['mpi']
        mpi_define_macros.append(('PARALLEL', '1'))
        mpicompiler = None
        custom_interpreter = False

    elif mpi == 'poe':
        #On IBM we need a custom interpreter
        mpicompiler = 'mpcc_r'
        custom_interpreter = True

    elif mpi in ['mpich', 'mvapich']:
        #With mpich, a custom compiler is needed
        #Do not know with mvapich, but cannot test with shared libraries
        #at the moment...
        mpicompiler = 'mpicc'   
        custom_interpreter = True            
        mpi_define_macros.append(('PARALLEL', '1'))

    else:
        #Try to build the shared library with mpicc
        mpicompiler = 'mpicc'   
        custom_interpreter = False
        mpi_define_macros.append(('PARALLEL', '1'))

    return mpicompiler, custom_interpreter

def mtime(path, name, mtimes):
    """Return modification time.

    The modification time of a source file is returned.  If one of its
    dependencies is newer, the mtime of that file is returned."""

#    global mtimes
    include = re.compile('^#\s*include "(\S+)"', re.MULTILINE)

    if mtimes.has_key(name):
        return mtimes[name]
    t = os.stat(path + name)[ST_MTIME]
    for name2 in include.findall(open(path + name).read()):
        if name2 != name:
            t = max(t, mtime(path, name2,mtimes))
    mtimes[name] = t
    return t

def check_dependencies(sources):
    # Distutils does not do deep dependencies correctly.  We take care of
    # that here so that "python setup.py build_ext" always does the right
    # thing!
    mtimes = {}  # modification times

    # Remove object files if any dependencies have changed:
    plat = get_platform() + '-' + sys.version[0:3]
    remove = False
    for source in sources:
        path, name = os.path.split(source)
        t = mtime(path + '/', name, mtimes)
        o = 'build/temp.%s/%s.o' % (plat, source[:-2])  # object file
        if os.path.exists(o) and t > os.stat(o)[ST_MTIME]:
            print 'removing', o
            os.remove(o)
            remove = True

    so = 'build/lib.%s/_gpaw.so' % plat
    if os.path.exists(so) and remove:
        # Remove shared object C-extension:
        # print 'removing', so
        os.remove(so)

def test_configuration():
    raise NotImplementedError


def write_configuration(define_macros, include_dirs, libraries, library_dirs,
                        extra_link_args, extra_compile_args,
                        runtime_library_dirs,extra_objects):    

    # Write the compilation configuration into a file
    try:
        out = open('configuration.log', 'w')
    except IOError, x:
        print x
        return
    print >> out, "Current configuration"
    print >> out, "libraries", libraries
    print >> out, "library_dirs", library_dirs
    print >> out, "include_dirs", include_dirs
    print >> out, "define_macros", define_macros
    print >> out, "extra_link_args", extra_link_args
    print >> out, "extra_compile_args", extra_compile_args
    print >> out, "runtime_library_dirs", runtime_library_dirs
    print >> out, "extra_objects", extra_objects
    out.close()


def build_interpreter(define_macros, include_dirs, libraries, library_dirs,
                      extra_link_args, extra_compile_args,mpicompiler):

    #Build custom interpreter which is needed for parallel calculations on
    #IBM and with mpich mpi library. Also, when shared mpi-libraries are
    #not available, a custom interpreter is needed
        

    cfgDict = get_config_vars()
    plat = get_platform() + '-' + sys.version[0:3]

    parallel_sources = [ 'c/bc.c', 'c/localized_functions.c', 'c/mpi.c']
    cfiles = glob('c/[a-zA-Z]*.c') + ['c/bmgs/bmgs.c']
    for src in parallel_sources:
        cfiles.remove(src)
    sources = ' '.join(parallel_sources+['c/_gpaw.c'])
    objects = ' '.join(['build/temp.%s/' % plat + x[:-1] + 'o'
                        for x in cfiles])

    if not os.path.isdir('build/bin.%s/' % plat):
        os.makedirs('build/bin.%s/' % plat)    
    exefile = 'build/bin.%s/' % plat + '/gpaw-python'

    define_macros.append(('PARALLEL', '1'))
    define_macros.append(('GPAW_INTERPRETER', '1'))
    macros = ' '.join(['-D%s=%s' % x for x in define_macros])

    include_dirs.append(cfgDict['INCLUDEPY'])
    includes = ' '.join(['-I' + incdir for incdir in include_dirs])

    library_dirs.append(cfgDict['LIBPL'])
    lib_dirs = ' '.join(['-L' + lib for lib in library_dirs])

    libs = ' '.join(['-l' + lib for lib in libraries])
    libs += ' -lpython%s' % cfgDict['VERSION']
    libs = ' '.join([libs, cfgDict['LIBS'], cfgDict['LIBM']])
                   
    if sys.platform == 'aix5':
        extra_link_args.append(cfgDict['LINKFORSHARED'].replace('Modules', cfgDict['LIBPL']))
    else:
        extra_link_args.append(cfgDict['LINKFORSHARED'])

    cmd = ('%s -o %s %s %s %s %s %s %s %s %s' ) % \
           (mpicompiler,
            exefile,
            macros,
            ' '.join(extra_compile_args),
            includes,
            sources,
            objects,
            lib_dirs,
            libs,            
            ' '.join(extra_link_args))
    
    msg = ['* Building a custom interpreter']
    print cmd
    error=os.system(cmd)
    if error != 0:
        msg += ['* FAILED!  Only serial version of code will work.']

    #remove the few object files from this directory
    for file in glob('*.o'):
        os.remove(file)
    

    return msg
        
