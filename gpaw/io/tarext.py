
import numpy as np

from gpaw.io.tar import Writer, Reader

class IncrementalWriter(Writer):
    _iterkey = 'niter'
    _partkey = 'part'
    _iterpattern = '/%06d.part'

    def __init__(self, name):
        Writer.__init__(self, name)

        self.dims[self._iterkey] = 0
        self.dims[self._partkey] = 1
        self.partitions = {}
        self.xml3 = []

    def partition(self, name, shape, array=None, dtype=None, units=None):

        if array is not None:
            array = np.asarray(array)
        if dtype is None:
            dtype = array.dtype

        if dtype in [int, bool]:
            dtype = np.int32

        dtype = np.dtype(dtype)
        self.dtype = dtype

        type = {np.int32: 'int',
                np.float64: 'float',
                np.complex128: 'complex'}[dtype.type]

        assert self._partkey not in shape
        shape = (self._partkey,) + shape

        if name not in self.partitions.keys():
            self.xml3 += ['  <partition name="%s" type="%s">' % (name, type)]
            self.xml3 += ['    <dimension length="%s" name="%s"/>' %
                          (self.dims[dim], dim)
                          for dim in shape]
            self.xml3 += ['  </partition>']
            self.partitions[name] = shape

            self.shape = [self.dims[dim] for dim in shape]
        else:
            assert self.partitions[name] == shape

        size = dtype.itemsize * np.product([self.dims[dim] for dim in shape])

        name += self._iterpattern % self.dims[self._iterkey]
        self.write_header(name, size)
        if array is not None:
            self.fill(array)

    def next(self):
        self.dims[self._iterkey] += self.dims[self._partkey]

    def close(self):
        partdim = '    <dimension length="%s" name="%s"/>' % \
                  (self.dims[self._partkey], self._partkey)
        iterdim = '    <dimension length="%s" name="%s"/>' % \
                  (self.dims[self._iterkey], self._iterkey)

        while partdim in self.xml3:
            i = self.xml3.index(partdim)
            self.xml3[i] = iterdim

        self.xml2 += self.xml3
        self.xml3 = []
        Writer.close(self)


# -------------------------------------------------------------------

class FakeFileObj(object):
    def __init__(self, fileparts, partsize):
        self.fileparts = fileparts
        self.partsize = partsize
        self.fileobj = None

        for fileobj in self.fileparts:
            assert fileobj.size == partsize

        self.seek(0)

    def seek(self, pos, whence=0):
        self.part, partpos = divmod(pos, self.partsize)
        self.fileobj = self.fileparts[self.part]
        self.fileobj.seek(partpos, whence)

    def tell(self):
        return self.fileobj.tell() + self.part*self.partsize

    def read(self, size=None):
        self.part, partpos = divmod(self.tell(), self.partsize)

        buf = str()
        n = self.tell()

        # read some of initial part
        partrem = min(self.partsize - partpos, size)
        buf += self.fileobj.read(partrem)
        n += partrem

        # read whole parts
        while size - n > self.partsize:
            self.seek(n)
            buf += self.fileobj.read(self.partsize)
            n += self.partsize

        # read some of final part
        self.seek(n)
        rem = size - n
        buf += self.fileobj.read(rem)

        return buf

    def close(self):
        for fileobj in self.fileparts:
            fileobj.close()


class IncrementalReader(Reader):
    _iterkey = 'niter'
    _partkey = 'part'
    _iterpattern = '/%06d.part'

    def __init__(self, name):
        self.partitions = {}
        Reader.__init__(self, name)
        self.dims[self._partkey] = 1

    def startElement(self, tag, attrs):
        if tag == 'partition':
            print 'attrs=', attrs
            name = attrs['name']
            assert name not in self.partitions.keys()
            self.dtypes[name] = attrs['type']
            self.shapes[name] = []
            self.name = name
            self.partitions[name] = tuple() #TODO?!
        else:
            if tag == 'dimension' and self.name in self.partitions.keys():
                n = int(attrs['length'])
                if attrs['name'] == self._iterkey:
                    self.partitions[self.name] += (self._partkey,)
                else:
                    self.partitions[self.name] += (attrs['name'],)

            Reader.startElement(self, tag, attrs)

    def get_file_object(self, name, indices):
        if name in self.partitions.keys():
            # first index is the partition iterable
            if len(indices) == 0:
                return self.get_partition_object(name)

            i, indices = indices[0], indices[1:]
            dtype = self.dtypes[name] #HACK
            partshape = [self.dims[dim] for dim in self.partitions[name]] #HACK
            name += self._iterpattern % i
            self.dtypes[name] = dtype #HACK
            self.shapes[name] = partshape[1:] #HACK

        return Reader.get_file_object(self, name, indices)

    def get_partition_object(self, name):
        assert name in self.partitions.keys()

        dtype = np.dtype({'int': np.int32,
                           'float': float,
                           'complex': complex}[self.dtypes[name]])

        shape = self.shapes[name]
        size = dtype.itemsize * np.prod(shape, dtype=int)

        partshape = [self.dims[dim] for dim in self.partitions[name]]
        partsize = dtype.itemsize * np.prod(partshape, dtype=int)

        fileobjs = []
        for i in range(niter):
            fileobj = self.tar.extractfile(name + self._iterpattern % i)
            fileobjs.append(fileobj)

        return FakeFileObj(fileobjs, partsize), shape, size, dtype

