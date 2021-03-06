from sympy.core.add import Add
from sympy.core.basic import Basic, C
from sympy.core.expr import Expr
from sympy.core.function import count_ops
from sympy.core.power import Pow
from sympy.core.symbol import Symbol, Dummy
from sympy.core.numbers import Integer, ilcm, Rational, Float
from sympy.core.singleton import S
from sympy.core.sympify import sympify, SympifyError
from sympy.core.compatibility import is_sequence

from sympy.polys import PurePoly, roots, cancel
from sympy.simplify import simplify as _simplify, signsimp, nsimplify
from sympy.utilities.iterables import flatten
from sympy.utilities.misc import default_sort_key
from sympy.functions.elementary.miscellaneous import sqrt, Max, Min
from sympy.printing import sstr
# uncomment the import of as_int and delete the function when merged with 0.7.2
from sympy.core.compatibility import callable, reduce#, as_int
from sympy.utilities.exceptions import SymPyDeprecationWarning

from types import FunctionType

def as_int(i):
    ii = int(i)
    if i != ii:
        raise TypeError()
    return ii

def _iszero(x):
    """Returns True if x is zero."""
    return x.is_zero

class MatrixError(Exception):
    pass

class ShapeError(ValueError, MatrixError):
    """Wrong matrix shape"""
    pass

class NonSquareMatrixError(ShapeError):
    pass

class DeferredVector(Symbol):
    """A vector whose components are deferred (e.g. for use with lambdify)

    >>> from sympy import DeferredVector, lambdify
    >>> X = DeferredVector( 'X' )
    >>> X
    X
    >>> expr = (X[0] + 2, X[2] + 3)
    >>> func = lambdify( X, expr )
    >>> func( [1, 2, 3] )
    (3, 6)
    """
    def __getitem__(self, i):
        if i == -0:
            i = 0
        if i < 0:
            raise IndexError('DeferredVector index out of range')
        component_name = '%s[%d]'%(self.name, i)
        return Symbol(component_name)

    def __str__(self):
        return sstr(self)

    def __repr__(self):
        return "DeferredVector('%s')"%(self.name)


class MatrixBase(object):

    # Added just for numpy compatibility
    # TODO: investigate about __array_priority__
    __array_priority__ = 10.0

    is_Matrix = True
    is_Identity = None
    _class_priority = 3

    def _sympy_(self):
        raise SympifyError('Matrix cannot be sympified')

    @classmethod
    def _handle_creation_inputs(cls, *args, **kwargs):
        """
        >>> from sympy import Matrix, I

        Matrix can be constructed as follows:

        * from a nested list of iterables

        >>> Matrix( ((1, 2+I), (3, 4)) )
        [1, 2 + I]
        [3,     4]

        * from un-nested iterable (interpreted as a column)

        >>> Matrix( [1, 2] )
        [1]
        [2]

        * from un-nested iterable with dimensions

        >>> Matrix(1, 2, [1, 2] )
        [1, 2]

        * from no arguments (a 0 x 0 matrix)

        >>> Matrix()
        []

        * from a rule

        >>> Matrix(2, 2, lambda i, j: i/(j + 1) )
        [0,   0]
        [1, 1/2]

        """
        from sympy.matrices.sparse import SparseMatrix

        # Matrix(SparseMatrix(...))
        if len(args) == 1 and isinstance(args[0], SparseMatrix):
            return args[0].rows, args[0].cols, flatten(args[0].tolist())

        # Matrix(Matrix(...))
        if len(args) == 1 and isinstance(args[0], MatrixBase):
            return args[0].rows, args[0].cols, args[0]._mat

        # Matrix(MatrixSymbol('X', 2, 2))
        if len(args) == 1 and isinstance(args[0], Basic) and args[0].is_Matrix:
            return args[0].rows, args[0].cols, args[0].as_explicit()._mat

        if len(args) == 3:
            rows = as_int(args[0])
            cols = as_int(args[1])

        # Matrix(2, 2, lambda i, j: i+j)
        if len(args) == 3 and callable(args[2]):
            operation = args[2]
            flat_list = []
            for i in range(rows):
                flat_list.extend([sympify(operation(sympify(i), j))
                    for j in range(cols)])

        # Matrix(2, 2, [1, 2, 3, 4])
        elif len(args) == 3 and is_sequence(args[2]):
            flat_list  = args[2]
            if len(flat_list) != rows*cols:
                raise ValueError('List length should be equal to rows*columns')
            flat_list = map(lambda i: sympify(i), flat_list)

        # Matrix(numpy.ones((2, 2)))
        elif len(args) == 1 and hasattr(args[0], "__array__"): #pragma: no cover
            # NumPy array or matrix or some other object that implements
            # __array__. So let's first use this method to get a
            # numpy.array() and then make a python list out of it.
            arr = args[0].__array__()
            if len(arr.shape) == 2:
                rows, cols = arr.shape[0], arr.shape[1]
                flat_list = map(lambda i: sympify(i), arr.ravel())
                return rows, cols, flat_list
            elif len(arr.shape) == 1:
                rows, cols = 1, arr.shape[0]
                flat_list = [0]*cols
                for i in range(len(arr)):
                    flat_list[i] = sympify(arr[i])
                return rows, cols, flat_list
            else:
                raise NotImplementedError("SymPy supports just 1D and 2D matrices")

        # Matrix([1, 2, 3]) or Matrix([[1, 2], [3, 4]])
        elif len(args) == 1 and is_sequence(args[0]):
            in_mat = []
            ncol = set()
            for row in args[0]:
                if isinstance(row, MatrixBase):
                    in_mat.extend(row.tolist())
                    if row.cols or row.rows: # only pay attention if it's not 0x0
                        ncol.add(row.cols)
                else:
                    in_mat.append(row)
                    try:
                        ncol.add(len(row))
                    except TypeError:
                        ncol.add(1)
            if len(ncol) > 1:
                raise ValueError("Got rows of variable lengths: %s" %
                    sorted(list(ncol)))
            rows = len(in_mat)
            if rows:
                if not is_sequence(in_mat[0]):
                    cols = 1
                    flat_list = map(lambda i: sympify(i), in_mat)
                    return rows, cols, flat_list
                cols = ncol.pop()
            else:
                cols = 0
            flat_list = []
            for j in range(rows):
                for i in range(cols):
                    flat_list.append(sympify(in_mat[j][i]))

        # Matrix()
        elif len(args) == 0:
            # Empty Matrix
            rows = cols = 0
            flat_list = []

        else:
            raise TypeError("Data type not understood")

        return rows, cols, flat_list

    def _setitem(self, key, value):
        """
        >>> from sympy import Matrix, I, zeros, ones
        >>> m = Matrix(((1, 2+I), (3, 4)))
        >>> m
        [1, 2 + I]
        [3,     4]
        >>> m[1, 0] = 9
        >>> m
        [1, 2 + I]
        [9,     4]
        >>> m[1, 0] = [[0, 1]]

        To replace row r you assign to position r*m where m
        is the number of columns:

        >>> M = zeros(4)
        >>> m = M.cols
        >>> M[3*m] = ones(1, m)*2; M
        [0, 0, 0, 0]
        [0, 0, 0, 0]
        [0, 0, 0, 0]
        [2, 2, 2, 2]

        And to replace column c you can assign to position c:

        >>> M[2] = ones(m, 1)*4; M
        [0, 0, 4, 0]
        [0, 0, 4, 0]
        [0, 0, 4, 0]
        [2, 2, 4, 2]
        """
        from dense import Matrix

        is_slice = isinstance(key, slice)
        i, j = key = self.key2ij(key)
        is_mat = isinstance(value, MatrixBase)
        if type(i) is slice or type(j) is slice:
            if is_mat:
                self.copyin_matrix(key, value)
                return
            if not isinstance(value, Expr) and is_sequence(value):
                self.copyin_list(key, value)
                return
            raise ValueError('unexpected value: %s' % value)
        else:
            if not is_mat and \
                not isinstance(value, Expr) and is_sequence(value):
                value = Matrix(value)
                is_mat = True
            if is_mat:
                if is_slice:
                    key = (slice(*divmod(i, self.cols)),
                           slice(*divmod(j, self.cols)))
                else:
                    key = (slice(i, i + value.rows),
                           slice(j, j + value.cols))
                self.copyin_matrix(key, value)
            else:
                return i, j, sympify(value)
            return

    def copy(self):
        return self._new(self.rows, self.cols, self._mat)

    def trace(self):
        if not self.is_square:
            raise NonSquareMatrixError()
        return self._eval_trace()

    def inv(self, method=None, **kwargs):
        if not self.is_square:
            raise NonSquareMatrixError()
        if method is not None:
            kwargs['method'] = method
        return self._eval_inverse(**kwargs)

    def transpose(self):
        return self._eval_transpose()

    T = property(transpose, None, None, "Matrix transposition.")

    def conjugate(self):
        return self._eval_conjugate()

    C = property(conjugate, None, None, "By-element conjugation.")

    def adjoint(self):
        """Conjugate transpose or Hermitian conjugation."""
        return self.T.C

    @property
    def H(self):
        """Return Hermite conjugate.

        Examples
        ========

        >>> from sympy import Matrix, I, eye
        >>> m = Matrix((0, 1 + I, 2, 3))
        >>> m
        [    0]
        [1 + I]
        [    2]
        [    3]
        >>> m.H
        [0, 1 - I, 2, 3]

        See Also
        ========

        conjugate: By-element conjugation
        D: Dirac conjugation
        """
        return self.T.C

    @property
    def D(self):
        """Return Dirac conjugate (if self.rows == 4).

        Examples
        ========

        >>> from sympy import Matrix, I, eye
        >>> m = Matrix((0, 1 + I, 2, 3))
        >>> m.D
        [0, 1 - I, -2, -3]
        >>> m = (eye(4) + I*eye(4))
        >>> m[0, 3] = 2
        >>> m.D
        [1 - I,     0,      0,      0]
        [    0, 1 - I,      0,      0]
        [    0,     0, -1 + I,      0]
        [    2,     0,      0, -1 + I]

        If the matrix does not have 4 rows an AttributeError will be raised
        because this property is only defined for matrices with 4 rows.

        >>> Matrix(eye(2)).D
        Traceback (most recent call last):
        ...
        AttributeError: Matrix has no attribute D.

        See Also
        ========

        conjugate: By-element conjugation
        H: Hermite conjugation
        """
        from sympy.physics.matrices import mgamma
        if self.rows != 4:
            # In Python 3.2, properties can only return an AttributeError
            # so we can't raise a ShapeError -- see commit which added the
            # first line of this inline comment. Also, there is no need
            # for a message since MatrixBase will raise the AttributeError
            raise AttributeError
        return self.H * mgamma(0)

    def as_mutable(self):
        """
        Returns a mutable version of this matrix

        >>> from sympy import ImmutableMatrix
        >>> X = ImmutableMatrix([[1, 2], [3, 4]])
        >>> Y = X.as_mutable()
        >>> Y[1, 1] = 5 # Can set values in Y
        >>> Y
        [1, 2]
        [3, 5]
        """
        from dense import Matrix
        if self.rows:
            return Matrix(self.tolist())
        return Matrix(0, self.cols, [])

    def as_immutable(self):
        """
        Returns an Immutable version of this Matrix
        """
        from immutable import ImmutableMatrix as Matrix
        if self.rows:
            return Matrix(self.tolist())
        return Matrix(0, self.cols, [])

    def __array__(self):
        from dense import matrix2numpy
        return matrix2numpy(self)

    def __len__(self):
        """
        Return the number of elements of self.

        Implemented mainly so bool(Matrix()) == False.
        """
        return self.rows * self.cols

    @property
    def shape(self):
        """The shape (dimensions) of the matrix as the 2-tuple (rows, cols).

        Examples
        ========

        >>> from sympy.matrices import zeros
        >>> M = zeros(2, 3)
        >>> M.shape
        (2, 3)
        >>> M.rows
        2
        >>> M.cols
        3
        """
        return (self.rows, self.cols)

    def __sub__(self, a):
        return self + (-a)

    def __rsub__(self, a):
        return (-self) + a

    def __mul__(self, other):
        """Return self*other where other is either a scalar or a matrix
        of compatible dimensions.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> A = Matrix([[1, 2, 3], [4, 5, 6]])
        >>> 2*A == A*2 == Matrix([[2, 4, 6], [8, 10, 12]])
        True
        >>> B = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        >>> A*B
        [30, 36, 42]
        [66, 81, 96]
        >>> B*A
        Traceback (most recent call last):
        ...
        ShapeError: Matrices size mismatch.
        >>>

        See Also
        ========

        matrix_multiply_elementwise
        """
        if getattr(other, 'is_Matrix', False):
            # The following implmentation is equivalent, but about 5% slower
            #ma, na = A.shape
            #mb, nb = B.shape
            #
            #if na != mb:
            #    raise ShapeError()
            #product = Matrix(ma, nb, lambda i, j: 0)
            #for i in range(ma):
            #    for j in range(nb):
            #        s = 0
            #        for k in range(na):
            #            s += A[i, k]*B[k, j]
            #        product[i, j] = s
            #return product
            A = self
            B = other
            if A.shape[1] != B.shape[0]:
                raise ShapeError("Matrices size mismatch.")
            blst = B.T.tolist()
            alst = A.tolist()
            return classof(A, B)._new(A.rows, B.cols, lambda i, j:
                                                reduce(lambda k, l: k+l,
                                                map(lambda n, m: n*m,
                                                alst[i],
                                                blst[j]), 0))
        else:
            return self._new(self.rows, self.cols,
                map(lambda i: i*other, self._mat))

    def __rmul__(self, a):
        if getattr(a, 'is_Matrix', False):
            return self._new(a)*self
        return self*a

    def __pow__(self, num):
        from sympy.matrices import eye

        if not self.is_square:
            raise NonSquareMatrixError()
        if isinstance(num, int) or isinstance(num, Integer):
            n = int(num)
            if n < 0:
                return self.inv() ** -n   # A**-2 = (A**-1)**2
            a = eye(self.cols)
            s = self
            while n:
                if n%2:
                    a *= s
                    n -= 1
                if not n:
                    break
                s *= s
                n //= 2
            return self._new(a)
        elif isinstance(num, Rational):
            try:
                P, D = self.diagonalize()
            except MatrixError:
                raise NotImplementedError("Implemented only for diagonalizable matrices")
            for i in range(D.rows):
                D[i, i] = D[i, i]**num
            return self._new(P * D * P.inv())
        else:
            raise NotImplementedError("Only integer and rational values are supported")

    def __add__(self, other):
        """Return self + other, raising ShapeError if shapes don't match."""
        if getattr(other, 'is_Matrix', False):
            A = self
            B = other
            if A.shape != B.shape:
                raise ShapeError("Matrices size mismatch.")
            alst = A.tolist()
            blst = B.tolist()
            ret = [0]*A.rows
            for i in range(A.shape[0]):
                ret[i] = map(lambda j, k: j+k, alst[i], blst[i])
            return classof(A, B)._new(ret)
        raise TypeError('cannot add matrix and %s' % type(other))

    def __radd__(self, other):
        return self + other

    def __div__(self, other):
        return self * (S.One/other)

    def __truediv__(self, other):
        return self.__div__(other)

    def __neg__(self):
        return -1*self

    def multiply(self, b):
        """Returns self*b

        See Also
        ========

        dot
        cross
        multiply_elementwise
        """
        return self*b

    def add(self, b):
        """Return self + b """
        return self + b

    def _format_str(self, strfunc, rowsep='\n'):
        # Handle zero dimensions:
        if self.rows == 0 or self.cols == 0:
            return '[]'
        # Build table of string representations of the elements
        res = []
        # Track per-column max lengths for pretty alignment
        maxlen = [0] * self.cols
        for i in range(self.rows):
            res.append([])
            for j in range(self.cols):
                string = strfunc(self[i, j])
                res[-1].append(string)
                maxlen[j] = max(len(string), maxlen[j])
        # Patch strings together
        for i, row in enumerate(res):
            for j, elem in enumerate(row):
                # Pad each element up to maxlen so the columns line up
                row[j] = elem.rjust(maxlen[j])
            res[i] = "[" + ", ".join(row) + "]"
        return rowsep.join(res)

    def __str__(self):
        return sstr(self)

    def __repr__(self):
        return sstr(self)

    def cholesky(self):
        """
        Returns the Cholesky decomposition L of a matrix A
        such that L * L.T = A

        A must be a square, symmetric, positive-definite
        and non-singular matrix.

        >>> from sympy.matrices import Matrix
        >>> A = Matrix(((25, 15, -5), (15, 18, 0), (-5, 0, 11)))
        >>> A.cholesky()
        [ 5, 0, 0]
        [ 3, 3, 0]
        [-1, 1, 3]
        >>> A.cholesky() * A.cholesky().T
        [25, 15, -5]
        [15, 18,  0]
        [-5,  0, 11]

        See Also
        ========

        LDLdecomposition
        LUdecomposition
        QRdecomposition
        """

        if not self.is_square:
            raise NonSquareMatrixError("Matrix must be square.")
        if not self.is_symmetric():
            raise ValueError("Matrix must be symmetric.")
        return self._cholesky()

    def LDLdecomposition(self):
        """
        Returns the LDL Decomposition (L, D) of matrix A,
        such that L * D * L.T == A
        This method eliminates the use of square root.
        Further this ensures that all the diagonal entries of L are 1.
        A must be a square, symmetric, positive-definite
        and non-singular matrix.

        >>> from sympy.matrices import Matrix, eye
        >>> A = Matrix(((25, 15, -5), (15, 18, 0), (-5, 0, 11)))
        >>> L, D = A.LDLdecomposition()
        >>> L
        [   1,   0, 0]
        [ 3/5,   1, 0]
        [-1/5, 1/3, 1]
        >>> D
        [25, 0, 0]
        [ 0, 9, 0]
        [ 0, 0, 9]
        >>> L * D * L.T * A.inv() == eye(A.rows)
        True

        See Also
        ========

        cholesky
        LUdecomposition
        QRdecomposition
        """
        if not self.is_square:
            raise NonSquareMatrixError("Matrix must be square.")
        if not self.is_symmetric():
            raise ValueError("Matrix must be symmetric.")
        return self._LDLdecomposition()

    def lower_triangular_solve(self, rhs):
        """
        Solves Ax = B, where A is a lower triangular matrix.

        See Also
        ========

        upper_triangular_solve
        cholesky_solve
        diagonal_solve
        LDLsolve
        LUsolve
        QRsolve
        """

        if not self.is_square:
            raise NonSquareMatrixError("Matrix must be square.")
        if rhs.rows != self.rows:
            raise ShapeError("Matrices size mismatch.")
        if not self.is_lower:
            raise ValueError("Matrix must be lower triangular.")
        return self._lower_triangular_solve(rhs)

    def upper_triangular_solve(self, rhs):
        """
        Solves Ax = B, where A is an upper triangular matrix.

        See Also
        ========

        lower_triangular_solve
        cholesky_solve
        diagonal_solve
        LDLsolve
        LUsolve
        QRsolve
        """
        if not self.is_square:
            raise NonSquareMatrixError("Matrix must be square.")
        if rhs.rows != self.rows:
            raise TypeError("Matrix size mismatch.")
        if not self.is_upper:
            raise TypeError("Matrix is not upper triangular.")
        return self._upper_triangular_solve(rhs)

    def cholesky_solve(self, rhs):
        """
        Solves Ax = B using Cholesky decomposition,
        for a general square non-singular matrix.
        For a non-square matrix with rows > cols,
        the least squares solution is returned.

        See Also
        ========

        lower_triangular_solve
        upper_triangular_solve
        diagonal_solve
        LDLsolve
        LUsolve
        QRsolve
        """
        if self.is_symmetric():
            L = self._cholesky()
        elif self.rows >= self.cols:
            L = (self.T * self)._cholesky()
            rhs = self.T * rhs
        else:
            raise NotImplementedError("Under-determined System.")
        Y = L._lower_triangular_solve(rhs)
        return (L.T)._upper_triangular_solve(Y)

    def diagonal_solve(self, rhs):
        """
        Solves Ax = B efficiently, where A is a diagonal Matrix,
        with non-zero diagonal entries.

        See Also
        ========

        lower_triangular_solve
        upper_triangular_solve
        cholesky_solve
        LDLsolve
        LUsolve
        QRsolve
        """
        if not self.is_diagonal:
            raise TypeError("Matrix should be diagonal")
        if rhs.rows != self.rows:
            raise TypeError("Size mis-match")
        return self._diagonal_solve(rhs)

    def LDLsolve(self, rhs):
        """
        Solves Ax = B using LDL decomposition,
        for a general square and non-singular matrix.

        For a non-square matrix with rows > cols,
        the least squares solution is returned.

        See Also
        ========

        LDLdecomposition
        lower_triangular_solve
        upper_triangular_solve
        cholesky_solve
        diagonal_solve
        LUsolve
        QRsolve
        """
        if self.is_symmetric():
            L, D = self.LDLdecomposition()
        elif self.rows >= self.cols:
            L, D = (self.T * self).LDLdecomposition()
            rhs = self.T * rhs
        else:
            raise NotImplementedError("Under-determined System.")
        Y = L._lower_triangular_solve(rhs)
        Z = D._diagonal_solve(Y)
        return (L.T)._upper_triangular_solve(Z)

    def solve_least_squares(self, rhs, method='CH'):
        """Return the least-square fit to the data.

        By default the cholesky_solve routine is used (method='CH'); other
        methods of matrix inversion can be used. To find out which are
        available, see the docstring of the .inv() method.

        >>> from sympy.matrices import Matrix, Matrix, ones
        >>> A = Matrix([1, 2, 3])
        >>> B = Matrix([2, 3, 4])
        >>> S = Matrix(A.row_join(B))
        >>> S
        [1, 2]
        [2, 3]
        [3, 4]

        If each line of S represent coefficients of Ax + By
        and x and y are [2, 3] then S*xy is:

        >>> r = S*Matrix([2, 3]); r
        [ 8]
        [13]
        [18]

        But let's add 1 to the middle value and then solve for the
        least-squares value of xy:

        >>> xy = S.solve_least_squares(Matrix([8, 14, 18])); xy
        [ 5/3]
        [10/3]

        The error is given by S*xy - r:

        >>> S*xy - r
        [1/3]
        [1/3]
        [1/3]
        >>> _.norm().n(2)
        0.58

        If a different xy is used, the norm will be higher:

        >>> xy += ones(2, 1)/10
        >>> (S*xy - r).norm().n(2)
        1.5

        """
        if method == 'CH':
            return self.cholesky_solve(rhs)
        t = self.T
        return (t*self).inv(method=method)*t*rhs

    def solve(self, rhs, method='GE'):
        """Return solution to self*soln = rhs using given inversion method.

        For a list of possible inversion methods, see the .inv() docstring.
        """
        if not self.is_square:
            if self.rows < self.cols:
                raise ValueError('Under-determined system.')
            elif self.rows > self.cols:
                raise ValueError('For over-determined system, M, having '
                    'more rows than columns, try M.solve_least_squares(rhs).')
        else:
            return self.inv(method=method)*rhs

    def __mathml__(self):
        mml = ""
        for i in range(self.rows):
            mml += "<matrixrow>"
            for j in range(self.cols):
                mml += self[i, j].__mathml__()
            mml += "</matrixrow>"
        return "<matrix>" + mml + "</matrix>"


    def submatrix(self, keys):
        """
        Get a slice/submatrix of the matrix using the given slice.

        >>> from sympy import Matrix
        >>> m = Matrix(4, 4, lambda i, j: i+j)
        >>> m
        [0, 1, 2, 3]
        [1, 2, 3, 4]
        [2, 3, 4, 5]
        [3, 4, 5, 6]
        >>> m[:1, 1]
        [1]
        >>> m[:2, :1]
        [0]
        [1]
        >>> m[2:4, 2:4]
        [4, 5]
        [5, 6]

        See Also
        ========

        extract
        """
        rlo, rhi, clo, chi = self.key2bounds(keys)
        outRows, outCols = rhi - rlo, chi - clo
        outMat = [0]*outRows*outCols
        for i in range(outRows):
            outMat[i*outCols:(i+1)*outCols] = \
            self._mat[(i + rlo)*self.cols + clo:(i + rlo)*self.cols + chi]
        return self._new(outRows, outCols, outMat)

    def extract(self, rowsList, colsList):
        """
        Extract a submatrix by specifying a list of rows and columns.
        Negative indices can be given. All indices must be in the range
        -n <= i < n where n is the number of rows or columns.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(4, 3, range(12))
        >>> m
        [0,  1,  2]
        [3,  4,  5]
        [6,  7,  8]
        [9, 10, 11]
        >>> m.extract([0, 1, 3], [0, 1])
        [0,  1]
        [3,  4]
        [9, 10]

        Rows or columns can be repeated:

        >>> m.extract([0, 0, 1], [-1])
        [2]
        [2]
        [5]

        Every other row can be taken by using range to provide the indices:

        >>> m.extract(range(0, m.rows, 2), [-1])
        [2]
        [8]

        See Also
        ========

        submatrix
        """
        cols = self.cols
        flat_list = self._mat
        rowsList = [a2idx(k, self.rows) for k in rowsList]
        colsList = [a2idx(k, self.cols) for k in colsList]
        return self._new(len(rowsList), len(colsList),
                lambda i, j: flat_list[rowsList[i]*cols + colsList[j]])

    def key2bounds(self, keys):
        """Converts a key with potentially mixed types of keys (integer and slice)
        into a tuple of ranges and raises an error if any index is out of self's
        range.

        See Also
        ========

        key2ij
        """

        islice, jslice = [isinstance(k, slice) for k in keys]
        if islice:
            if not self.rows:
                rlo = rhi = 0
            else:
                rlo, rhi = keys[0].indices(self.rows)[:2]
        else:
            rlo = a2idx(keys[0], self.rows)
            rhi  = rlo + 1
        if jslice:
            if not self.cols:
                clo = chi = 0
            else:
                clo, chi = keys[1].indices(self.cols)[:2]
        else:
            clo = a2idx(keys[1], self.cols)
            chi = clo + 1
        return rlo, rhi, clo, chi


    def key2ij(self, key):
        """Converts key into canonical form, converting integers or indexable
        items into valid integers for self's range or returning slices
        unchanged.

        See Also
        ========

        key2bounds
        """
        if is_sequence(key):
            if not len(key) == 2:
                raise TypeError('key must be a sequence of length 2')
            return [a2idx(i, n) if not isinstance(i, slice) else i
                for i, n in zip(key, self.shape)]
        elif isinstance(key, slice):
            return key.indices(len(self))[:2]
        else:
            return divmod(a2idx(key, len(self)), self.cols)

    def evalf(self, prec=None, **options):
        """
        Evaluate each element of the matrix as a float.
        """
        if prec is None:
            return self.applyfunc(lambda i: i.evalf(**options))
        else:
            return self.applyfunc(lambda i: i.evalf(prec, **options))

    n = evalf

    def subs(self, *args, **kwargs): # should mirror core.basic.subs
        """Return a new matrix with subs applied to each entry.

        Examples
        ========

        >>> from sympy.abc import x, y
        >>> from sympy.matrices import SparseMatrix, Matrix
        >>> SparseMatrix(1, 1, [x])
        [x]
        >>> _.subs(x, y)
        [y]
        >>> Matrix(_).subs(y, x)
        [x]
        """
        return self.applyfunc(lambda x: x.subs(*args, **kwargs))

    def expand(self, deep=True, modulus=None, power_base=True, power_exp=True, \
            mul=True, log=True, multinomial=True, basic=True, **hints):
        """Apply core.function.expand to each entry of the matrix.

        Examples
        ========

        >>> from sympy.abc import x
        >>> from sympy.matrices import Matrix
        >>> Matrix(1, 1, [x*(x+1)])
        [x*(x + 1)]
        >>> _.expand()
        [x**2 + x]
        >>>
        """
        return self.applyfunc(lambda x: x.expand(
        deep, modulus, power_base, power_exp, mul, log, multinomial, basic,
        **hints))

    def simplify(self, ratio=1.7, measure=count_ops):
        """Apply simplify to each element of the matrix.

        Examples
        ========

        >>> from sympy.abc import x, y
        >>> from sympy import sin, cos
        >>> from sympy.matrices import SparseMatrix
        >>> SparseMatrix(1, 1, [x*sin(y)**2 + x*cos(y)**2])
        [x*sin(y)**2 + x*cos(y)**2]
        >>> _.simplify()
        [x]
        """
        return self.applyfunc(lambda x: x.simplify(ratio, measure))

    def print_nonzero (self, symb="X"):
        """
        Shows location of non-zero entries for fast shape lookup.

        Examples
        ========

        >>> from sympy.matrices import Matrix, eye
        >>> m = Matrix(2, 3, lambda i, j: i*3+j)
        >>> m
        [0, 1, 2]
        [3, 4, 5]
        >>> m.print_nonzero()
        [ XX]
        [XXX]
        >>> m = eye(4)
        >>> m.print_nonzero("x")
        [x   ]
        [ x  ]
        [  x ]
        [   x]

        """
        s = []
        for i in range(self.rows):
            line = []
            for j in range(self.cols):
                if self[i, j] == 0:
                    line.append(" ")
                else:
                    line.append(str(symb))
            s.append("[%s]" % ''.join(line))
        print '\n'.join(s)

    def LUsolve(self, rhs, iszerofunc=_iszero):
        """
        Solve the linear system Ax = b for x.
        self is the coefficient matrix A and rhs is the right side b.

        This is for symbolic matrices, for real or complex ones use
        sympy.mpmath.lu_solve or sympy.mpmath.qr_solve.

        See Also
        ========

        lower_triangular_solve
        upper_triangular_solve
        cholesky_solve
        diagonal_solve
        LDLsolve
        QRsolve
        LUdecomposition
        """
        if rhs.rows != self.rows:
            raise ShapeError("`self` and `rhs` must have the same number of rows.")

        A, perm = self.LUdecomposition_Simple(iszerofunc=_iszero)
        n = self.rows
        b = rhs.permuteFwd(perm).as_mutable()
        # forward substitution, all diag entries are scaled to 1
        for i in range(n):
            for j in range(i):
                b.row_op(i, lambda x, k: x - b[j, k]*A[i, j])
        # backward substitution
        for i in range(n - 1, -1, -1):
            for j in range(i+1, n):
                b.row_op(i, lambda x, k: x - b[j, k]*A[i, j])
            b.row_op(i, lambda x, k: x / A[i, i])
        return rhs.__class__(b)

    def LUdecomposition(self, iszerofunc=_iszero):
        """
        Returns the decomposition LU and the row swaps p.

        Examples
        ========

        >>> from sympy import Matrix
        >>> a = Matrix([[4, 3], [6, 3]])
        >>> L, U, _ = a.LUdecomposition()
        >>> L
        [  1, 0]
        [3/2, 1]
        >>> U
        [4,    3]
        [0, -3/2]

        See Also
        ========

        cholesky
        LDLdecomposition
        QRdecomposition
        LUdecomposition_Simple
        LUdecompositionFF
        LUsolve
        """
        combined, p = self.LUdecomposition_Simple(iszerofunc=_iszero)
        L = self.zeros(self.rows)
        U = self.zeros(self.rows)
        for i in range(self.rows):
            for j in range(self.rows):
                if i > j:
                    L[i, j] = combined[i, j]
                else:
                    if i == j:
                        L[i, i] = 1
                    U[i, j] = combined[i, j]
        return L, U, p

    def LUdecomposition_Simple(self, iszerofunc=_iszero):
        """
        Returns A comprised of L, U (L's diag entries are 1) and
        p which is the list of the row swaps (in order).

        See Also
        ========

        LUdecomposition
        LUdecompositionFF
        LUsolve
        """
        if not self.is_square:
            raise NonSquareMatrixError()
        n = self.rows
        A = self.as_mutable()
        p = []
        # factorization
        for j in range(n):
            for i in range(j):
                for k in range(i):
                    A[i, j] = A[i, j] - A[i, k]*A[k, j]
            pivot = -1
            for i in range(j, n):
                for k in range(j):
                    A[i, j] = A[i, j] - A[i, k]*A[k, j]
                # find the first non-zero pivot, includes any expression
                if pivot == -1 and not iszerofunc(A[i, j]):
                    pivot = i
            if pivot < 0:
                # this result is based on iszerofunc's analysis of the possible pivots, so even though
                # the element may not be strictly zero, the supplied iszerofunc's evaluation gave True
                raise ValueError("No nonzero pivot found; inversion failed.")
            if pivot != j: # row must be swapped
                A.row_swap(pivot, j)
                p.append([pivot, j])
            scale = 1 / A[j, j]
            for i in range(j+1, n):
                A[i, j] = A[i, j] * scale
        return A, p


    def LUdecompositionFF(self):
        """
        Compute a fraction-free LU decomposition.

        Returns 4 matrices P, L, D, U such that PA = L D**-1 U.
        If the elements of the matrix belong to some integral domain I, then all
        elements of L, D and U are guaranteed to belong to I.

        **Reference**
            - W. Zhou & D.J. Jeffrey, "Fraction-free matrix factors: new forms
              for LU and QR factors". Frontiers in Computer Science in China,
              Vol 2, no. 1, pp. 67-80, 2008.

        See Also
        ========

        LUdecomposition
        LUdecomposition_Simple
        LUsolve
        """
        from sympy.matrices import SparseMatrix
        zeros = SparseMatrix.zeros
        eye = SparseMatrix.eye

        n, m = self.rows, self.cols
        U, L, P = self.as_mutable(), eye(n), eye(n)
        DD = zeros(n, n)
        oldpivot = 1

        for k in range(n-1):
            if U[k, k] == 0:
                for kpivot in range(k+1, n):
                    if U[kpivot, k]:
                        break
                else:
                    raise ValueError("Matrix is not full rank")
                U[k, k:], U[kpivot, k:] = U[kpivot, k:], U[k, k:]
                L[k, :k], L[kpivot, :k] = L[kpivot, :k], L[k, :k]
                P[k, :], P[kpivot, :] = P[kpivot, :], P[k, :]
            L[k, k] = Ukk = U[k, k]
            DD[k, k] = oldpivot * Ukk
            for i in range(k+1, n):
                L[i, k] = Uik = U[i, k]
                for j in range(k+1, m):
                    U[i, j] = (Ukk * U[i, j] - U[k, j]*Uik) / oldpivot
                U[i, k] = 0
            oldpivot = Ukk
        DD[n - 1, n - 1] = oldpivot
        return P, L, DD, U

    def cofactorMatrix(self, method="berkowitz"):
        """
        Return a matrix containing the cofactor of each element.

        See Also
        ========

        cofactor
        minorEntry
        minorMatrix
        adjugate
        """
        out = self._new(self.rows, self.cols, lambda i, j:
                self.cofactor(i, j, method))
        return out

    def minorEntry(self, i, j, method="berkowitz"):
        """
        Calculate the minor of an element.

        See Also
        ========

        minorMatrix
        cofactor
        cofactorMatrix
        """
        if not 0 <= i < self.rows or not 0 <= j < self.cols:
            raise ValueError("`i` and `j` must satisfy 0 <= i < `self.rows` " +
                "(%d)" % self.rows + "and 0 <= j < `self.cols` (%d)." % self.cols)
        return self.minorMatrix(i, j).det(method)

    def minorMatrix(self, i, j):
        """
        Creates the minor matrix of a given element.

        See Also
        ========

        minorEntry
        cofactor
        cofactorMatrix
        """
        if not 0 <= i < self.rows or not 0 <= j < self.cols:
            raise ValueError("`i` and `j` must satisfy 0 <= i < `self.rows` " +
                "(%d)" % self.rows + "and 0 <= j < `self.cols` (%d)." % self.cols)
        M = self.as_mutable()
        M.row_del(i)
        M.col_del(j)
        return self._new(M)

    def cofactor(self, i, j, method="berkowitz"):
        """
        Calculate the cofactor of an element.

        See Also
        ========

        cofactorMatrix
        minorEntry
        minorMatrix
        """
        if (i+j) % 2 == 0:
            return self.minorEntry(i, j, method)
        else:
            return -1 * self.minorEntry(i, j, method)

    def jacobian(self, X):
        """
        Calculates the Jacobian matrix (derivative of a vectorial function).

        *self*
            A vector of expressions representing functions f_i(x_1, ..., x_n).
        *X*
            The set of x_i's in order, it can be a list or a Matrix

        Both self and X can be a row or a column matrix in any order
        (jacobian() should always work).

        Examples
        ========

            >>> from sympy import sin, cos, Matrix
            >>> from sympy.abc import rho, phi
            >>> X = Matrix([rho*cos(phi), rho*sin(phi), rho**2])
            >>> Y = Matrix([rho, phi])
            >>> X.jacobian(Y)
            [cos(phi), -rho*sin(phi)]
            [sin(phi),  rho*cos(phi)]
            [   2*rho,             0]
            >>> X = Matrix([rho*cos(phi), rho*sin(phi)])
            >>> X.jacobian(Y)
            [cos(phi), -rho*sin(phi)]
            [sin(phi),  rho*cos(phi)]

        See Also
        ========

        hessian
        wronskian
        """
        if not isinstance(X, MatrixBase):
            X = self._new(X)
        # Both X and self can be a row or a column matrix, so we need to make
        # sure all valid combinations work, but everything else fails:
        if self.shape[0] == 1:
            m = self.shape[1]
        elif self.shape[1] == 1:
            m = self.shape[0]
        else:
            raise TypeError("self must be a row or a column matrix")
        if X.shape[0] == 1:
            n = X.shape[1]
        elif X.shape[1] == 1:
            n = X.shape[0]
        else:
            raise TypeError("X must be a row or a column matrix")

        # m is the number of functions and n is the number of variables
        # computing the Jacobian is now easy:
        return self._new(m, n, lambda j, i: self[j].diff(X[i]))

    def QRdecomposition(self):
        """
        Return Q, R where A = Q*R, Q is orthogonal and R is upper triangular.

        Examples
        ========

        This is the example from wikipedia:

        >>> from sympy import Matrix, eye
        >>> A = Matrix([[12, -51, 4], [6, 167, -68], [-4, 24, -41]])
        >>> Q, R = A.QRdecomposition()
        >>> Q
        [ 6/7, -69/175, -58/175]
        [ 3/7, 158/175,   6/175]
        [-2/7,    6/35,  -33/35]
        >>> R
        [14,  21, -14]
        [ 0, 175, -70]
        [ 0,   0,  35]
        >>> A == Q*R
        True

        QR factorization of an identity matrix:

        >>> A = Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        >>> Q, R = A.QRdecomposition()
        >>> Q
        [1, 0, 0]
        [0, 1, 0]
        [0, 0, 1]
        >>> R
        [1, 0, 0]
        [0, 1, 0]
        [0, 0, 1]

        See Also
        ========

        cholesky
        LDLdecomposition
        LUdecomposition
        QRsolve
        """
        cls = self.__class__
        self = self.as_mutable()

        if not self.rows >= self.cols:
            raise MatrixError("The number of rows must be greater than columns")
        n = self.rows
        m = self.cols
        rank = n
        row_reduced = self.rref()[0]
        for i in range(row_reduced.rows):
            if row_reduced.row(i).norm() == 0:
                rank -= 1
        if not rank == self.cols:
            raise MatrixError("The rank of the matrix must match the columns")
        Q, R = self.zeros(n, m), self.zeros(m)
        for j in range(m):      # for each column vector
            tmp = self[:, j]     # take original v
            for i in range(j):
                # subtract the project of self on new vector
                tmp -= Q[:, i] * self[:, j].dot(Q[:, i])
                tmp.expand()
            # normalize it
            R[j, j] = tmp.norm()
            Q[:, j] = tmp / R[j, j]
            if Q[:, j].norm() != 1:
                raise NotImplementedError("Could not normalize the vector %d." % j)
            for i in range(j):
                R[i, j] = Q[:, i].dot(self[:, j])
        return cls(Q), cls(R)

    def QRsolve(self, b):
        """
        Solve the linear system 'Ax = b'.

        'self' is the matrix 'A', the method argument is the vector
        'b'.  The method returns the solution vector 'x'.  If 'b' is a
        matrix, the system is solved for each column of 'b' and the
        return value is a matrix of the same shape as 'b'.

        This method is slower (approximately by a factor of 2) but
        more stable for floating-point arithmetic than the LUsolve method.
        However, LUsolve usually uses an exact arithmetic, so you don't need
        to use QRsolve.

        This is mainly for educational purposes and symbolic matrices, for real
        (or complex) matrices use sympy.mpmath.qr_solve.

        See Also
        ========

        lower_triangular_solve
        upper_triangular_solve
        cholesky_solve
        diagonal_solve
        LDLsolve
        LUsolve
        QRdecomposition
        """

        Q, R = self.as_mutable().QRdecomposition()
        y = Q.T * b

        # back substitution to solve R*x = y:
        # We build up the result "backwards" in the vector 'x' and reverse it
        # only in the end.
        x = []
        n = R.rows
        for j in range(n - 1, -1, -1):
            tmp = y[j, :]
            for k in range(j + 1, n):
                tmp -= R[j, k] * x[n - 1 - k]
            x.append(tmp/R[j, j])
        return self._new([row._mat for row in reversed(x)])

    def cross(self, b):
        """
        Calculate the cross product of ``self`` and ``b``.

        See Also
        ========

        dot
        multiply
        multiply_elementwise
        """
        if not is_sequence(b):
            raise TypeError("`b` must be an ordered iterable or Matrix, not %s." %
                type(b))
        if not (self.rows == 1 and self.cols == 3 or
                self.rows == 3 and self.cols == 1 ) and \
                (b.rows == 1 and b.cols == 3 or
                b.rows == 3 and b.cols == 1):
            raise ShapeError("Dimensions incorrect for cross product.")
        else:
            return self._new(1, 3, ((self[1]*b[2] - self[2]*b[1]),
                               (self[2]*b[0] - self[0]*b[2]),
                               (self[0]*b[1] - self[1]*b[0])))

    def dot(self, b):
        """Return the dot product of Matrix self and b relaxing the condition
        of compatible dimensions: if either the number of rows or columns are
        the same as the length of b then the dot product is returned. If self
        is a row or column vector, a scalar is returned. Otherwise, a list
        of results is returned (and in that case the number of columns in self
        must match the length of b).

        >>> from sympy import Matrix
        >>> M = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        >>> v = [1, 1, 1]
        >>> M.row(0).dot(v)
        6
        >>> M.col(0).dot(v)
        12
        >>> M.dot(v)
        [6, 15, 24]

        See Also
        ========

        cross
        multiply
        multiply_elementwise
        """
        from dense import Matrix

        if not isinstance(b, MatrixBase):
            if is_sequence(b):
                if len(b) != self.cols and len(b) != self.rows:
                    raise ShapeError("Dimensions incorrect for dot product.")
                return self.dot(Matrix(b))
            else:
                raise TypeError("`b` must be an ordered iterable or Matrix, not %s." %
                type(b))
        if self.cols == b.rows:
            if b.cols != 1:
                self = self.T
                b = b.T
            prod = flatten((self*b).tolist())
            if len(prod) == 1:
                return prod[0]
            return prod
        if self.cols == b.cols:
            return self.dot(b.T)
        elif self.rows == b.rows:
            return self.T.dot(b)
        else:
            raise ShapeError("Dimensions incorrect for dot product.")

    def multiply_elementwise(self, b):
        """Return the Hadamard product (elementwise product) of A and B

        >>> from sympy.matrices import Matrix
        >>> A = Matrix([[0, 1, 2], [3, 4, 5]])
        >>> B = Matrix([[1, 10, 100], [100, 10, 1]])
        >>> A.multiply_elementwise(B)
        [  0, 10, 200]
        [300, 40,   5]

        See Also
        ========

        cross
        dot
        multiply
        """
        from sympy.matrices import matrix_multiply_elementwise

        return matrix_multiply_elementwise(self, b)

    def values(self):
        """Return non-zero values of self."""
        return [i for i in flatten(self.tolist()) if not i.is_zero]

    def norm(self, ord=None):
        """Return the Norm of a Matrix or Vector.
        In the simplest case this is the geometric size of the vector
        Other norms can be specified by the ord parameter


        =====  ============================  ==========================
        ord    norm for matrices             norm for vectors
        =====  ============================  ==========================
        None   Frobenius norm                2-norm
        'fro'  Frobenius norm                - does not exist
        inf    --                            max(abs(x))
        -inf   --                            min(abs(x))
        1      --                            as below
        -1     --                            as below
        2      2-norm (largest sing. value)  as below
        -2     smallest singular value       as below
        other  - does not exist              sum(abs(x)**ord)**(1./ord)
        =====  ============================  ==========================

        >>> from sympy import Matrix, Symbol, trigsimp, cos, sin, oo
        >>> x = Symbol('x', real=True)
        >>> v = Matrix([cos(x), sin(x)])
        >>> trigsimp( v.norm() )
        1
        >>> v.norm(10)
        (sin(x)**10 + cos(x)**10)**(1/10)
        >>> A = Matrix([[1, 1], [1, 1]])
        >>> A.norm(2)# Spectral norm (max of |Ax|/|x| under 2-vector-norm)
        2
        >>> A.norm(-2) # Inverse spectral norm (smallest singular value)
        0
        >>> A.norm() # Frobenius Norm
        2
        >>> Matrix([1, -2]).norm(oo)
        2
        >>> Matrix([-1, 2]).norm(-oo)
        1

        See Also
        ========

        normalized
        """
        # Row or Column Vector Norms
        vals = self.values() or [0]
        if self.rows == 1 or self.cols == 1:
            if ord == 2 or ord == None: # Common case sqrt(<x, x>)
                return sqrt(Add(*(abs(i)**2 for i in vals)))

            elif ord == 1: # sum(abs(x))
                return Add(*(abs(i) for i in vals))

            elif ord == S.Infinity: # max(abs(x))
                return Max(*[abs(i) for i in vals])

            elif ord == S.NegativeInfinity: # min(abs(x))
                return Min(*[abs(i) for i in vals])

            # Otherwise generalize the 2-norm, Sum(x_i**ord)**(1/ord)
            # Note that while useful this is not mathematically a norm
            try:
                return Pow( Add(*(abs(i)**ord for i in vals)), S(1)/ord )
            except (NotImplementedError, TypeError):
                raise ValueError("Expected order to be Number, Symbol, oo")

        # Matrix Norms
        else:
            if ord == 2: # Spectral Norm
                # Maximum singular value
                return Max(*self.singular_values())

            elif ord == -2:
                # Minimum singular value
                return Min(*self.singular_values())

            elif (ord == None or isinstance(ord, str) and ord.lower() in
                    ['f', 'fro', 'frobenius', 'vector']):
                # Reshape as vector and send back to norm function
                return self.vec().norm(ord=2)

            else:
                raise NotImplementedError("Matrix Norms under development")

    def normalized(self):
        """
        Return the normalized version of ``self``.

        See Also
        ========

        norm
        """
        if self.rows != 1 and self.cols != 1:
            raise ShapeError("A Matrix must be a vector to normalize.")
        norm = self.norm()
        out = self.applyfunc(lambda i: i / norm)
        return out

    def project(self, v):
        """Return the projection of ``self`` onto the line containing ``v``.

        >>> from sympy import Matrix, S, sqrt
        >>> V = Matrix([sqrt(3)/2, S.Half])
        >>> x = Matrix([[1, 0]])
        >>> V.project(x)
        [sqrt(3)/2, 0]
        >>> V.project(-x)
        [sqrt(3)/2, 0]
        """
        return v * (self.dot(v) / v.dot(v))

    def permuteBkwd(self, perm):
        """
        Permute the rows of the matrix with the given permutation in reverse.

        >>> from sympy.matrices import eye
        >>> M = eye(3)
        >>> M.permuteBkwd([[0, 1], [0, 2]])
        [0, 1, 0]
        [0, 0, 1]
        [1, 0, 0]

        See Also
        ========

        permuteFwd
        """
        copy = self.copy()
        for i in range(len(perm) - 1, -1, -1):
            copy.row_swap(perm[i][0], perm[i][1])
        return copy

    def permuteFwd(self, perm):
        """
        Permute the rows of the matrix with the given permutation.

        >>> from sympy.matrices import eye
        >>> M = eye(3)
        >>> M.permuteFwd([[0, 1], [0, 2]])
        [0, 0, 1]
        [1, 0, 0]
        [0, 1, 0]

        See Also
        ========

        permuteBkwd
        """
        copy = self.copy()
        for i in range(len(perm)):
            copy.row_swap(perm[i][0], perm[i][1])
        return copy

    def exp(self):
        """ Returns the exponentiation of a square matrix."""
        if not self.is_square:
            raise NonSquareMatrixError("Exponentiation is valid only for square matrices")
        try:
            U, D = self.diagonalize()
        except MatrixError:
            raise NotImplementedError("Exponentiation is implemented only for diagonalizable matrices")
        for i in range(0, D.rows):
            D[i, i] = C.exp(D[i, i])
        return U * D * U.inv()

    @classmethod
    def zeros(cls, r, c=None):
        """Returns a matrix of zeros with ``r`` rows and ``c`` columns;
        if ``c`` is omitted a square matrix will be returned.

        See Also
        ========

        ones
        fill
        """
        if is_sequence(r):
            SymPyDeprecationWarning(
                feature="The syntax zeros([%i, %i])" % tuple(r), useinstead="zeros(%i, %i)." % tuple(r),
                issue=3381, deprecated_since_version="0.7.2",
            ).warn()
            r, c = r
        else:
            c = r if c is None else c
        r = as_int(r)
        c = as_int(c)
        return cls._new(r, c, [S.Zero]*r*c)

    @classmethod
    def eye(cls, n):
        """Returns the identity matrix of size n."""
        tmp = cls.zeros(n)
        for i in range(tmp.rows):
            tmp[i, i] = S.One
        return tmp

    @property
    def is_square(self):
        """
        Checks if a matrix is square.

        A matrix is square if the number of rows equals the number of columns.
        The empty matrix is square by definition, since the number of rows and
        the number of columns are both zero.

        Examples
        ========

        >>> from sympy import Matrix
        >>> a = Matrix([[1, 2, 3], [4, 5, 6]])
        >>> b = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        >>> c = Matrix([])
        >>> a.is_square
        False
        >>> b.is_square
        True
        >>> c.is_square
        True
        """
        return self.rows == self.cols

    @property
    def is_zero(self):
        """
        Checks if a matrix is a zero matrix.

        A matrix is zero if every element is zero.  A matrix need not be square
        to be considered zero.  The empty matrix is zero by the principle of
        vacuous truth.

        Examples
        ========

        >>> from sympy import Matrix, zeros
        >>> a = Matrix([[0, 0], [0, 0]])
        >>> b = zeros(3, 4)
        >>> c = Matrix([[0, 1], [0, 0]])
        >>> d = Matrix([])
        >>> a.is_zero
        True
        >>> b.is_zero
        True
        >>> c.is_zero
        False
        >>> d.is_zero
        True
        """
        return not self.values()

    def is_nilpotent(self):
        """
        Checks if a matrix is nilpotent.

        A matrix B is nilpotent if for some integer k, B**k is
        a zero matrix.

        Examples
        ========

        >>> from sympy import Matrix
        >>> a = Matrix([[0, 0, 0], [1, 0, 0], [1, 1, 0]])
        >>> a.is_nilpotent()
        True

        >>> a = Matrix([[1, 0, 1], [1, 0, 0], [1, 1, 0]])
        >>> a.is_nilpotent()
        False
        """
        if not self.is_square:
            raise NonSquareMatrixError("Nilpotency is valid only for square matrices")
        x = Dummy('x')
        if self.charpoly(x).args[0] == x**self.rows:
            return True
        return False

    @property
    def is_upper(self):
        """
        Check if matrix is an upper triangular matrix. True can be returned
        even if the matrix is not square.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(2, 2, [1, 0, 0, 1])
        >>> m
        [1, 0]
        [0, 1]
        >>> m.is_upper
        True

        >>> m = Matrix(4, 3, [5, 1, 9, 0, 4 , 6, 0, 0, 5, 0, 0, 0])
        >>> m
        [5, 1, 9]
        [0, 4, 6]
        [0, 0, 5]
        [0, 0, 0]
        >>> m.is_upper
        True

        >>> m = Matrix(2, 3, [4, 2, 5, 6, 1, 1])
        >>> m
        [4, 2, 5]
        [6, 1, 1]
        >>> m.is_upper
        False

        See Also
        ========

        is_lower
        is_diagonal
        is_upper_hessenberg
        """
        return all(self[i, j].is_zero
            for i in range(1, self.rows)
            for j in range(i))

    @property
    def is_lower(self):
        """
        Check if matrix is a lower triangular matrix. True can be returned
        even if the matrix is not square.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(2, 2, [1, 0, 0, 1])
        >>> m
        [1, 0]
        [0, 1]
        >>> m.is_lower
        True

        >>> m = Matrix(4, 3, [0, 0, 0, 2, 0, 0, 1, 4 , 0, 6, 6, 5])
        >>> m
        [0, 0, 0]
        [2, 0, 0]
        [1, 4, 0]
        [6, 6, 5]
        >>> m.is_lower
        True

        >>> from sympy.abc import x, y
        >>> m = Matrix(2, 2, [x**2 + y, y**2 + x, 0, x + y])
        >>> m
        [x**2 + y, x + y**2]
        [       0,    x + y]
        >>> m.is_lower
        False

        See Also
        ========

        is_upper
        is_diagonal
        is_lower_hessenberg
        """
        return all(self[i, j].is_zero
            for i in range(self.rows)
            for j in range(i + 1, self.cols))

    @property
    def is_upper_hessenberg(self):
        """
        Checks if the matrix is the upper hessenberg form.

        The upper hessenberg matrix has zero entries
        below the first subdiagonal.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> a = Matrix([[1, 4, 2, 3], [3, 4, 1, 7], [0, 2, 3, 4], [0, 0, 1, 3]])
        >>> a
        [1, 4, 2, 3]
        [3, 4, 1, 7]
        [0, 2, 3, 4]
        [0, 0, 1, 3]
        >>> a.is_upper_hessenberg
        True

        See Also
        ========

        is_lower_hessenberg
        is_upper
        """
        return all(self[i, j].is_zero
            for i in range(2, self.rows)
            for j in range(i - 1))

    @property
    def is_lower_hessenberg(self):
        r"""
        Checks if the matrix is in the lower hessenberg form.

        The lower hessenberg matrix has zero entries
        above the first superdiagonal.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> a = Matrix([[1, 2, 0, 0], [5, 2, 3, 0], [3, 4, 3, 7], [5, 6, 1, 1]])
        >>> a
        [1, 2, 0, 0]
        [5, 2, 3, 0]
        [3, 4, 3, 7]
        [5, 6, 1, 1]
        >>> a.is_lower_hessenberg
        True

        See Also
        ========

        is_upper_hessenberg
        is_lower
        """
        return all(self[i, j].is_zero
            for i in range(self.rows)
            for j in range(i + 2, self.cols))

    def is_symbolic(self):
        """
        Checks if any elements are symbols.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> from sympy.abc import x, y
        >>> M = Matrix([[x, y], [1, 0]])
        >>> M.is_symbolic()
        True

        """
        return any(element.has(Symbol) for element in self.values())

    def is_symmetric(self, simplify=True):
        """
        Check if matrix is symmetric matrix,
        that is square matrix and is equal to its transpose.

        By default, simplifications occur before testing symmetry.
        They can be skipped using 'simplify=False'; while speeding things a bit,
        this may however induce false negatives.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(2, 2, [0, 1, 1, 2])
        >>> m
        [0, 1]
        [1, 2]
        >>> m.is_symmetric()
        True

        >>> m = Matrix(2, 2, [0, 1, 2, 0])
        >>> m
        [0, 1]
        [2, 0]
        >>> m.is_symmetric()
        False

        >>> m = Matrix(2, 3, [0, 0, 0, 0, 0, 0])
        >>> m
        [0, 0, 0]
        [0, 0, 0]
        >>> m.is_symmetric()
        False

        >>> from sympy.abc import x, y
        >>> m = Matrix(3, 3, [1, x**2 + 2*x + 1, y, (x + 1)**2 , 2, 0, y, 0, 3])
        >>> m
        [         1, x**2 + 2*x + 1, y]
        [(x + 1)**2,              2, 0]
        [         y,              0, 3]
        >>> m.is_symmetric()
        True

        If the matrix is already simplified, you may speed-up is_symmetric()
        test by using 'simplify=False'.

        >>> m.is_symmetric(simplify=False)
        False
        >>> m1 = m.expand()
        >>> m1.is_symmetric(simplify=False)
        True
        """
        if not self.is_square:
            return False
        if simplify:
            delta = self - self.transpose()
            delta.simplify()
            return delta.equals(self.zeros(self.rows, self.cols))
        else:
            return self == self.transpose()

    def is_anti_symmetric(self, simplify=True):
        """
        Check if matrix M is an antisymmetric matrix,
        that is, M is a square matrix with all M[i, j] == -M[j, i].

        When ``simplify=True`` (default), the sum M[i, j] + M[j, i] is
        simplified before testing to see if it is zero. By default,
        the SymPy simplify function is used. To use a custom function
        set simplify to a function that accepts a single argument which
        returns a simplified expression. To skip simplification, set
        simplify to False but note that although this will be faster,
        it may induce false negatives.

        Examples
        ========

        >>> from sympy import Matrix, symbols
        >>> m = Matrix(2, 2, [0, 1, -1, 0])
        >>> m
        [ 0, 1]
        [-1, 0]
        >>> m.is_anti_symmetric()
        True
        >>> x, y = symbols('x y')
        >>> m = Matrix(2, 3, [0, 0, x, -y, 0, 0])
        >>> m
        [ 0, 0, x]
        [-y, 0, 0]
        >>> m.is_anti_symmetric()
        False

        >>> from sympy.abc import x, y
        >>> m = Matrix(3, 3, [0, x**2 + 2*x + 1, y,
        ...                   -(x + 1)**2 , 0, x*y,
        ...                   -y, -x*y, 0])

        Simplification of matrix elements is done by default so even
        though two elements which should be equal and opposite wouldn't
        pass an equality test, the matrix is still reported as
        anti-symmetric:

        >>> m[0, 1] == -m[1, 0]
        False
        >>> m.is_anti_symmetric()
        True

        If 'simplify=False' is used for the case when a Matrix is already
        simplified, this will speed things up. Here, we see that without
        simplification the matrix does not appear anti-symmetric:

        >>> m.is_anti_symmetric(simplify=False)
        False

        But if the matrix were already expanded, then it would appear
        anti-symmetric and simplification in the is_anti_symmetric routine
        is not needed:

        >>> m = m.expand()
        >>> m.is_anti_symmetric(simplify=False)
        True
        """
        # accept custom simplification
        simpfunc = simplify if isinstance(simplify, FunctionType) else \
                   _simplify if simplify else False

        if not self.is_square:
            return False
        n = self.rows
        if simplify:
            for i in range(n):
                # diagonal
                if not simpfunc(self[i, i]).is_zero:
                    return False
                # others
                for j in range(i + 1, n):
                    diff = self[i, j] + self[j, i]
                    if not simpfunc(diff).is_zero:
                        return False
            return True
        else:
            for i in range(n):
                for j in range(i, n):
                    if self[i, j] != -self[j, i]:
                        return False
            return True


    def is_diagonal(self):
        """
        Check if matrix is diagonal,
        that is matrix in which the entries outside the main diagonal are all zero.

        Examples
        ========

        >>> from sympy import Matrix, diag
        >>> m = Matrix(2, 2, [1, 0, 0, 2])
        >>> m
        [1, 0]
        [0, 2]
        >>> m.is_diagonal()
        True

        >>> m = Matrix(2, 2, [1, 1, 0, 2])
        >>> m
        [1, 1]
        [0, 2]
        >>> m.is_diagonal()
        False

        >>> m = diag(1, 2, 3)
        >>> m
        [1, 0, 0]
        [0, 2, 0]
        [0, 0, 3]
        >>> m.is_diagonal()
        True

        See Also
        ========

        is_lower
        is_upper
        is_diagonalizable
        diagonalize
        """
        for i in range(self.rows):
            for j in range(self.cols):
                if i != j and self[i, j]:
                    return False
        return True

    def det(self, method="bareis"):
        """
        Computes the matrix determinant using the method "method".

        Possible values for "method":
          bareis ... det_bareis
          berkowitz ... berkowitz_det
          lu_decomposition ... det_LU

        See Also
        ========

        det_bareis
        berkowitz_det
        det_LU
        """

        # if methods were made internal and all determinant calculations
        # passed through here, then these lines could be factored out of
        # the method routines
        if not self.is_square:
            raise NonSquareMatrixError()
        if not self:
            return S.One
        if method == "bareis":
            return self.det_bareis()
        elif method == "berkowitz":
            return self.berkowitz_det()
        elif method == "det_LU":
            return self.det_LU_decomposition()
        else:
            raise ValueError("Determinant method unrecognized")

    def det_bareis(self):
        """Compute matrix determinant using Bareis' fraction-free
        algorithm which is an extension of the well known Gaussian
        elimination method. This approach is best suited for dense
        symbolic matrices and will result in a determinant with
        minimal number of fractions. It means that less term
        rewriting is needed on resulting formulae.

        TODO: Implement algorithm for sparse matrices (SFF),
        http://www.eecis.udel.edu/~saunders/papers/sffge/it5.ps.

        See Also
        ========

        det
        berkowitz_det
        """
        if not self.is_square:
            raise NonSquareMatrixError()
        if not self:
            return S.One

        M, n = self.copy(), self.rows

        if n == 1:
            det = M[0, 0]
        elif n == 2:
            det = M[0, 0]*M[1, 1] - M[0, 1]*M[1, 0]
        else:
            sign = 1 # track current sign in case of column swap

            for k in range(n-1):
                # look for a pivot in the current column
                # and assume det == 0 if none is found
                if M[k, k] == 0:
                    for i in range(k+1, n):
                        if M[i, k]:
                            M.row_swap(i, k)
                            sign *= -1
                            break
                    else:
                        return S.Zero

                # proceed with Bareis' fraction-free (FF)
                # form of Gaussian elimination algorithm
                for i in range(k+1, n):
                    for j in range(k+1, n):
                        D = M[k, k]*M[i, j] - M[i, k]*M[k, j]

                        if k > 0:
                            D /= M[k-1, k-1]

                        if D.is_Atom:
                            M[i, j] = D
                        else:
                            M[i, j] = cancel(D)

            det = sign * M[n-1, n-1]

        return det.expand()

    def det_LU_decomposition(self):
        """Compute matrix determinant using LU decomposition

        Note that this method fails if the LU decomposition itself
        fails. In particular, if the matrix has no inverse this method
        will fail.

        TODO: Implement algorithm for sparse matrices (SFF),
        http://www.eecis.udel.edu/~saunders/papers/sffge/it5.ps.

        See Also
        ========

        det
        det_bareis
        berkowitz_det
        """
        if not self.is_square:
            raise NonSquareMatrixError()
        if not self:
            return S.One

        M, n = self.copy(), self.rows
        p, prod = [] , 1
        l, u, p = M.LUdecomposition()
        if  len(p) % 2:
            prod = -1

        for k in range(n):
            prod = prod*u[k, k]*l[k, k]

        return prod.expand()

    def adjugate(self, method="berkowitz"):
        """
        Returns the adjugate matrix.

        Adjugate matrix is the transpose of the cofactor matrix.

        http://en.wikipedia.org/wiki/Adjugate

        See Also
        ========

        cofactorMatrix
        transpose
        berkowitz
        """

        return self.cofactorMatrix(method).T


    def inverse_LU(self, iszerofunc=_iszero):
        """
        Calculates the inverse using LU decomposition.

        See Also
        ========

        inv
        inverse_GE
        inverse_ADJ
        """
        if not self.is_square:
            raise NonSquareMatrixError()

        ok = self.rref(simplify=True)[0]
        if any(iszerofunc(ok[j, j]) for j in range(ok.rows)):
            raise ValueError("Matrix det == 0; not invertible.")

        return self.LUsolve(self.eye(self.rows), iszerofunc=_iszero)

    def inverse_GE(self, iszerofunc=_iszero):
        """
        Calculates the inverse using Gaussian elimination.

        See Also
        ========

        inv
        inverse_LU
        inverse_ADJ
        """
        if not self.is_square:
            raise NonSquareMatrixError()

        big = self.row_join(self.eye(self.rows))
        red = big.rref(iszerofunc=iszerofunc, simplify=True)[0]
        if any(iszerofunc(red[j, j]) for j in range(red.rows)):
            raise ValueError("Matrix det == 0; not invertible.")

        return red[:, big.rows:]

    def inverse_ADJ(self, iszerofunc=_iszero):
        """
        Calculates the inverse using the adjugate matrix and a determinant.

        See Also
        ========

        inv
        inverse_LU
        inverse_GE
        """
        if not self.is_square:
            raise NonSquareMatrixError()

        d = self.berkowitz_det()
        zero = d.equals(0)
        if zero is None:
            # if equals() can't decide, will rref be able to?
            ok = self.rref(simplify=True)[0]
            zero = any(iszerofunc(ok[j, j]) for j in range(ok.rows))
        if zero:
            raise ValueError("Matrix det == 0; not invertible.")

        return self.adjugate()/d

    def rref(self, simplified=False, iszerofunc=_iszero,
            simplify=False):
        """
        Return reduced row-echelon form of matrix and indices of pivot vars.

        To simplify elements before finding nonzero pivots set simplify=True
        (to use the default SymPy simplify function) or pass a custom
        simplify function.

        >>> from sympy import Matrix
        >>> from sympy.abc import x
        >>> m = Matrix([[1, 2], [x, 1 - 1/x]])
        >>> m.rref()
        ([1, 0]
        [0, 1], [0, 1])
        """
        if simplified is not False:
            SymPyDeprecationWarning(
                feature="'simplified' as a keyword to rref",
                useinstead="simplify=True, or set simplify equal to your "
                       "own custom simplification function",
                issue=3382, deprecated_since_version="0.7.2",
            ).warn()
            simplify = simplify or True
        simpfunc = simplify if isinstance(simplify, FunctionType) else _simplify
        pivot, r = 0, self.as_mutable() # pivot: index of next row to contain a pivot
        pivotlist = []                  # indices of pivot variables (non-free)
        for i in range(r.cols):
            if pivot == r.rows:
                break
            if simplify:
                r[pivot, i] = simpfunc(r[pivot, i])
            if iszerofunc(r[pivot, i]):
                for k in range(pivot, r.rows):
                    if simplify and k > pivot:
                        r[k, i] = simpfunc(r[k, i])
                    if not iszerofunc(r[k, i]):
                        break
                if k == r.rows - 1 and iszerofunc(r[k, i]):
                    continue
                r.row_swap(pivot, k)
            scale = r[pivot, i]
            r.row_op(pivot, lambda x, _: x/scale)
            for j in range(r.rows):
                if j == pivot:
                    continue
                scale = r[j, i]
                r.row_op(j, lambda x, k: x - scale*r[pivot, k])
            pivotlist.append(i)
            pivot += 1
        return self._new(r), pivotlist

    def nullspace(self, simplified=False, simplify=False):
        """
        Returns list of vectors (Matrix objects) that span nullspace of self
        """
        from sympy.matrices import zeros

        if simplified is not False:
            SymPyDeprecationWarning(
                feature="'simplified' as a keyword to nullspace",
                useinstead="simplify=True, or set simplify equal to your "
                       "own custom simplification function",
                issue=3382, deprecated_since_version="0.7.2",
            ).warn()
            simplify = simplify or True
        simpfunc = simplify if isinstance(simplify, FunctionType) else _simplify
        reduced, pivots = self.rref(simplify=simpfunc)

        basis = []
        # create a set of vectors for the basis
        for i in range(self.cols - len(pivots)):
            basis.append(zeros(self.cols, 1))
        # contains the variable index to which the vector corresponds
        basiskey, cur = [-1]*len(basis), 0
        for i in range(self.cols):
            if i not in pivots:
                basiskey[cur] = i
                cur += 1
        for i in range(self.cols):
            if i not in pivots: # free var, just set vector's ith place to 1
                basis[basiskey.index(i)][i, 0] = 1
            else:               # add negative of nonpivot entry to corr vector
                for j in range(i+1, self.cols):
                    line = pivots.index(i)
                    v = reduced[line, j]
                    if simplify:
                        v = simpfunc(v)
                    if v:
                        if j in pivots:
                            # XXX: Is this the correct error?
                            raise NotImplementedError("Could not compute the nullspace of `self`.")
                        basis[basiskey.index(j)][i, 0] = -v
        return [self._new(b) for b in basis]

    def berkowitz(self):
        """The Berkowitz algorithm.

           Given N x N matrix with symbolic content, compute efficiently
           coefficients of characteristic polynomials of 'self' and all
           its square sub-matrices composed by removing both i-th row
           and column, without division in the ground domain.

           This method is particularly useful for computing determinant,
           principal minors and characteristic polynomial, when 'self'
           has complicated coefficients e.g. polynomials. Semi-direct
           usage of this algorithm is also important in computing
           efficiently sub-resultant PRS.

           Assuming that M is a square matrix of dimension N x N and
           I is N x N identity matrix,  then the following following
           definition of characteristic polynomial is begin used:

                          charpoly(M) = det(t*I - M)

           As a consequence, all polynomials generated by Berkowitz
           algorithm are monic.

           >>> from sympy import Matrix
           >>> from sympy.abc import x, y, z

           >>> M = Matrix([[x, y, z], [1, 0, 0], [y, z, x]])

           >>> p, q, r = M.berkowitz()

           >>> p # 1 x 1 M's sub-matrix
           (1, -x)

           >>> q # 2 x 2 M's sub-matrix
           (1, -x, -y)

           >>> r # 3 x 3 M's sub-matrix
           (1, -2*x, x**2 - y*z - y, x*y - z**2)

           For more information on the implemented algorithm refer to:

           [1] S.J. Berkowitz, On computing the determinant in small
               parallel time using a small number of processors, ACM,
               Information Processing Letters 18, 1984, pp. 147-150

           [2] M. Keber, Division-Free computation of sub-resultants
               using Bezout matrices, Tech. Report MPI-I-2006-1-006,
               Saarbrucken, 2006

        See Also
        ========

        berkowitz_det
        berkowitz_minors
        berkowitz_charpoly
        berkowitz_eigenvals
        """
        from sympy.matrices import zeros

        if not self.is_square:
            raise NonSquareMatrixError()

        A, N = self, self.rows
        transforms = [0] * (N-1)

        for n in range(N, 1, -1):
            T, k = zeros(n+1, n), n - 1

            R, C = -A[k, :k], A[:k, k]
            A, a = A[:k, :k], -A[k, k]

            items = [ C ]

            for i in range(0, n-2):
                items.append(A * items[i])

            for i, B in enumerate(items):
                items[i] = (R * B)[0, 0]

            items = [ S.One, a ] + items

            for i in range(n):
                T[i:, i] = items[:n-i+1]

            transforms[k-1] = T

        polys = [ self._new([S.One, -A[0, 0]]) ]

        for i, T in enumerate(transforms):
            polys.append(T * polys[i])

        return tuple(map(tuple, polys))

    def berkowitz_det(self):
        """Computes determinant using Berkowitz method.

        See Also
        ========

        det
        berkowitz
        """
        if not self.is_square:
            raise NonSquareMatrixError()
        if not self:
            return S.One
        poly = self.berkowitz()[-1]
        sign = (-1)**(len(poly)-1)
        return sign * poly[-1]

    def berkowitz_minors(self):
        """Computes principal minors using Berkowitz method.

        See Also
        ========

        berkowitz
        """
        sign, minors = S.NegativeOne, []

        for poly in self.berkowitz():
            minors.append(sign*poly[-1])
            sign = -sign

        return tuple(minors)

    def berkowitz_charpoly(self, x=Dummy('lambda'), simplify=_simplify):
        """Computes characteristic polynomial minors using Berkowitz method.

        A PurePoly is returned so using different variables for ``x`` does
        not affect the comparison or the polynomials:

        >>> from sympy import Matrix
        >>> from sympy.abc import x, y
        >>> A = Matrix([[1, 3], [2, 0]])
        >>> A.berkowitz_charpoly(x) == A.berkowitz_charpoly(y)
        True

        Specifying ``x`` is optional; a Dummy with name ``lambda`` is used by
        default (which looks good when pretty-printed in unicode):

        >>> A.berkowitz_charpoly().as_expr()
        _lambda**2 - _lambda - 6

        No test is done to see that ``x`` doesn't clash with an existing
        symbol, so using the default (``lambda``) or your own Dummy symbol is
        the safest option:

        >>> A = Matrix([[1, 2], [x, 0]])
        >>> A.charpoly().as_expr()
        _lambda**2 - _lambda - 2*x
        >>> A.charpoly(x).as_expr()
        x**2 - 3*x

        See Also
        ========

        berkowitz
        """
        return PurePoly(map(simplify, self.berkowitz()[-1]), x)

    charpoly = berkowitz_charpoly

    def berkowitz_eigenvals(self, **flags):
        """Computes eigenvalues of a Matrix using Berkowitz method.

        See Also
        ========

        berkowitz
        """
        return roots(self.berkowitz_charpoly(Dummy('x')), **flags)

    def eigenvals(self, **flags):
        """Return eigen values using the berkowitz_eigenvals routine.

        Since the roots routine doesn't always work well with Floats,
        they will be replaced with Rationals before calling that
        routine. If this is not desired, set flag ``rational`` to False.
        """
        # roots doesn't like Floats, so replace them with Rationals
        # unless the nsimplify flag indicates that this has already
        # been done, e.g. in eigenvects
        if flags.pop('rational', True):
            if any(v.has(Float) for v in self):
                self = self._new(self.rows, self.cols,
                    [nsimplify(v, rational=True) for v in self])

        flags.pop('simplify', None) # pop unsupported flag
        return self.berkowitz_eigenvals(**flags)

    def eigenvects(self, **flags):
        """Return list of triples (eigenval, multiplicity, basis).

        The flag ``simplify`` has two effects:
            1) if bool(simplify) is True, as_content_primitive()
            will be used to tidy up normalization artifacts;
            2) if nullspace needs simplification to compute the
            basis, the simplify flag will be passed on to the
            nullspace routine which will interpret it there.

        If the matrix contains any Floats, they will be changed to Rationals
        for computation purposes, but the answers will be returned after being
        evaluated with evalf. If it is desired to removed small imaginary
        portions during the evalf step, pass a value for the ``chop`` flag.
        """
        from sympy.matrices import eye

        simplify = flags.get('simplify', True)
        primitive = bool(flags.get('simplify', False))
        chop = flags.pop('chop', False)

        flags.pop('multiple', None) # remove this if it's there

        # roots doesn't like Floats, so replace them with Rationals
        float = False
        if any(v.has(Float) for v in self):
            float = True
            self = self._new(self.rows, self.cols, [nsimplify(v, rational=True) for v in self])
            flags['rational'] = False # to tell eigenvals not to do this

        out, vlist = [], self.eigenvals(**flags)
        vlist = vlist.items()
        vlist.sort(key=default_sort_key)
        flags.pop('rational', None)

        for r, k in vlist:
            tmp = self - eye(self.rows)*r
            basis = tmp.nullspace()
            # whether tmp.is_symbolic() is True or False, it is possible that
            # the basis will come back as [] in which case simplification is
            # necessary.
            if not basis:
                # The nullspace routine failed, try it again with simplification
                basis = tmp.nullspace(simplify=simplify)
                if not basis:
                    raise NotImplementedError("Can't evaluate eigenvector for eigenvalue %s" % r)
            if primitive:
                # the relationship A*e = lambda*e will still hold if we change the
                # eigenvector; so if simplify is True we tidy up any normalization
                # artifacts with as_content_primtive (default) and remove any pure Integer
                # denominators.
                l = 1
                for i, b in enumerate(basis[0]):
                    c, p = signsimp(b).as_content_primitive()
                    if c is not S.One:
                        b = c*p
                        l = ilcm(l, c.q)
                    basis[0][i] = b
                if l != 1:
                    basis[0] *= l
            if float:
                out.append((r.evalf(chop=chop), k, [self._new(b).evalf(chop=chop) for b in basis]))
            else:
                out.append((r, k, [self._new(b) for b in basis]))
        return out

    def singular_values(self):
        """
        Compute the singular values of a Matrix

        >>> from sympy import Matrix, Symbol, eye
        >>> x = Symbol('x', real=True)
        >>> A = Matrix([[0, 1, 0], [0, x, 0], [-1, 0, 0]])
        >>> A.singular_values()
        [sqrt(x**2 + 1), 1, 0]

        See Also
        ========

        condition_number
        """
        self = self.as_mutable()
        # Compute eigenvalues of A.H A
        valmultpairs = (self.H*self).eigenvals()

        # Expands result from eigenvals into a simple list
        vals = []
        for k, v in valmultpairs.items():
            vals += [sqrt(k)]*v # dangerous! same k in several spots!
        # sort them in descending order
        vals.sort(reverse=True, key=default_sort_key)

        return vals

    def condition_number(self):
        """
        Returns the condition number of a matrix.

        This is the maximum singular value divided by the minimum singular value

        >>> from sympy import Matrix, S
        >>> A = Matrix([[1, 0, 0], [0, 10, 0], [0, 0, S.One/10]])
        >>> A.condition_number()
        100

        See Also
        ========

        singular_values
        """

        singularvalues = self.singular_values()
        return Max(*singularvalues) / Min(*singularvalues)

    def __getattr__(self, attr):
        if attr in ('diff', 'integrate', 'limit'):
            def doit(*args):
                item_doit = lambda item: getattr(item, attr)(*args)
                return self.applyfunc( item_doit )
            return doit
        else:
            raise AttributeError("Matrix has no attribute %s." % attr)

    def integrate(self, *args):
        """
        Integrate each element of the matrix.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> from sympy.abc import x, y
        >>> M = Matrix([[x, y], [1, 0]])
        >>> M.integrate((x, ))
        [x**2/2, x*y]
        [     x,   0]
        >>> M.integrate((x, 0, 2))
        [2, 2*y]
        [2,   0]

        See Also
        ========

        limit
        diff
        """
        return self._new(self.rows, self.cols,
                lambda i, j: self[i, j].integrate(*args))

    def limit(self, *args):
        """
        Calculate the limit of each element in the matrix.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> from sympy.abc import x, y
        >>> M = Matrix([[x, y], [1, 0]])
        >>> M.limit(x, 2)
        [2, y]
        [1, 0]

        See Also
        ========

        integrate
        diff
        """
        return self._new(self.rows, self.cols,
                lambda i, j: self[i, j].limit(*args))

    def diff(self, *args):
        """
        Calculate the derivative of each element in the matrix.

        Examples
        ========

        >>> from sympy.matrices import Matrix
        >>> from sympy.abc import x, y
        >>> M = Matrix([[x, y], [1, 0]])
        >>> M.diff(x)
        [1, 0]
        [0, 0]

        See Also
        ========

        integrate
        limit
        """
        return self._new(self.rows, self.cols,
                lambda i, j: self[i, j].diff(*args))

    def vec(self):
        """
        Return the Matrix converted into a one column matrix by stacking columns

        >>> from sympy import Matrix
        >>> m=Matrix([[1, 3], [2, 4]])
        >>> m
        [1, 3]
        [2, 4]
        >>> m.vec()
        [1]
        [2]
        [3]
        [4]

        See Also
        ========

        vech
        """
        return self.T.reshape(len(self), 1)

    def vech(self, diagonal=True, check_symmetry=True):
        """
        Return the unique elements of a symmetric Matrix as a one column matrix
        by stacking the elements in the lower triangle.

        Arguments:
        diagonal -- include the diagonal cells of self or not
        check_symmetry -- checks symmetry of self but not completely reliably

        >>> from sympy import Matrix
        >>> m=Matrix([[1, 2], [2, 3]])
        >>> m
        [1, 2]
        [2, 3]
        >>> m.vech()
        [1]
        [2]
        [3]
        >>> m.vech(diagonal=False)
        [2]

        See Also
        ========

        vec
        """
        from sympy.matrices import zeros

        c = self.cols
        if c != self.rows:
            raise ShapeError("Matrix must be square")
        if check_symmetry:
            self.simplify()
            if self != self.transpose():
                raise ValueError("Matrix appears to be asymmetric; consider check_symmetry=False")
        count = 0
        if diagonal:
            v = zeros(c * (c + 1) // 2, 1)
            for j in range(c):
                for i in range(j, c):
                    v[count] = self[i, j]
                    count += 1
        else:
            v = zeros(c * (c - 1) // 2, 1)
            for j in range(c):
                for i in range(j+1, c):
                    v[count] = self[i, j]
                    count += 1
        return v

    def get_diag_blocks(self):
        """Obtains the square sub-matrices on the main diagonal of a square matrix.

        Useful for inverting symbolic matrices or solving systems of
        linear equations which may be decoupled by having a block diagonal
        structure.

        Examples
        ========

        >>> from sympy import Matrix, symbols
        >>> from sympy.abc import x, y, z
        >>> A = Matrix([[1, 3, 0, 0], [y, z*z, 0, 0], [0, 0, x, 0], [0, 0, 0, 0]])
        >>> a1, a2, a3 = A.get_diag_blocks()
        >>> a1
        [1,    3]
        [y, z**2]
        >>> a2
        [x]
        >>> a3
        [0]
        >>>

        """
        sub_blocks = []
        def recurse_sub_blocks(M):
            i = 1
            while i <= M.shape[0]:
                if i == 1:
                    to_the_right = M[0, i:]
                    to_the_bottom = M[i:, 0]
                else:
                    to_the_right = M[:i, i:]
                    to_the_bottom = M[i:, :i]
                if any(to_the_right) or any(to_the_bottom):
                    i += 1
                    continue
                else:
                    sub_blocks.append(M[:i, :i])
                    if M.shape == M[:i, :i].shape:
                        return
                    else:
                        recurse_sub_blocks(M[i:, i:])
                        return
        recurse_sub_blocks(self)
        return sub_blocks

    def diagonalize(self, reals_only=False, sort=False, normalize=False):
        """
        Return diagonalized matrix D and transformation P such as

            D = P^-1 * M * P

        where M is current matrix.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(3, 3, [1, 2, 0, 0, 3, 0, 2, -4, 2])
        >>> m
        [1,  2, 0]
        [0,  3, 0]
        [2, -4, 2]
        >>> (P, D) = m.diagonalize()
        >>> D
        [1, 0, 0]
        [0, 2, 0]
        [0, 0, 3]
        >>> P
        [-1, 0, -1]
        [ 0, 0, -1]
        [ 2, 1,  2]
        >>> P.inv() * m * P
        [1, 0, 0]
        [0, 2, 0]
        [0, 0, 3]

        See Also
        ========

        is_diagonal
        is_diagonalizable
        """
        from sympy.matrices import diag

        if not self.is_square:
            raise NonSquareMatrixError()
        if not self.is_diagonalizable(reals_only, False):
            self._diagonalize_clear_subproducts()
            raise MatrixError("Matrix is not diagonalizable")
        else:
            if self._eigenvects is None:
                self._eigenvects = self.eigenvects(simplify=True)
            if sort:
                self._eigenvects.sort(key=default_sort_key)
                self._eigenvects.reverse()
            diagvals = []
            P = self._new(self.rows, 0, [])
            for eigenval, multiplicity, vects in self._eigenvects:
                for k in range(multiplicity):
                    diagvals.append(eigenval)
                    vec = vects[k]
                    if normalize:
                        vec = vec/vec.norm()
                    P = P.col_insert(P.cols, vec)
            D = diag(*diagvals)
            self._diagonalize_clear_subproducts()
            return (P, D)

    def is_diagonalizable(self, reals_only=False, clear_subproducts=True):
        """
        Check if matrix is diagonalizable.

        If reals_only==True then check that diagonalized matrix consists of the only not complex values.

        Some subproducts could be used further in other methods to avoid double calculations,
        By default (if clear_subproducts==True) they will be deleted.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(3, 3, [1, 2, 0, 0, 3, 0, 2, -4, 2])
        >>> m
        [1,  2, 0]
        [0,  3, 0]
        [2, -4, 2]
        >>> m.is_diagonalizable()
        True
        >>> m = Matrix(2, 2, [0, 1, 0, 0])
        >>> m
        [0, 1]
        [0, 0]
        >>> m.is_diagonalizable()
        False
        >>> m = Matrix(2, 2, [0, 1, -1, 0])
        >>> m
        [ 0, 1]
        [-1, 0]
        >>> m.is_diagonalizable()
        True
        >>> m.is_diagonalizable(True)
        False

        See Also
        ========

        is_diagonal
        diagonalize
        """
        if not self.is_square:
            return False
        res = False
        self._is_symbolic = self.is_symbolic()
        self._is_symmetric = self.is_symmetric()
        self._eigenvects = None
        #if self._is_symbolic:
        #    self._diagonalize_clear_subproducts()
        #    raise NotImplementedError("Symbolic matrices are not implemented for diagonalization yet")
        self._eigenvects = self.eigenvects(simplify=True)
        all_iscorrect = True
        for eigenval, multiplicity, vects in self._eigenvects:
            if len(vects) != multiplicity:
                all_iscorrect = False
                break
            elif reals_only and not eigenval.is_real:
                all_iscorrect = False
                break
        res = all_iscorrect
        if clear_subproducts:
            self._diagonalize_clear_subproducts()
        return res

    def _diagonalize_clear_subproducts(self):
        del self._is_symbolic
        del self._is_symmetric
        del self._eigenvects

    def jordan_form(self, calc_transformation = True):
        """
        Return Jordan form J of current matrix.

        If calc_transformation is specified as False, then transformation P such that

              J = P^-1 * M * P

        will not be calculated.

        Notes
        =====

        Calculation of transformation P is not implemented yet.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(4, 4, [6, 5, -2, -3, -3, -1, 3, 3, 2, 1, -2, -3, -1, 1, 5, 5])
        >>> m
        [ 6,  5, -2, -3]
        [-3, -1,  3,  3]
        [ 2,  1, -2, -3]
        [-1,  1,  5,  5]

        >>> (P, J) = m.jordan_form()
        >>> J
        [2, 1, 0, 0]
        [0, 2, 0, 0]
        [0, 0, 2, 1]
        [0, 0, 0, 2]

        See Also
        ========

        jordan_cells
        """
        from sympy.matrices import diag

        (P, Jcells) = self.jordan_cells(calc_transformation)
        J = diag(*Jcells)
        return (P, J)

    def jordan_cells(self, calc_transformation = True):
        """
        Return a list of Jordan cells of current matrix.
        This list shape Jordan matrix J.

        If calc_transformation is specified as False, then transformation P such that

              J = P^-1 * M * P

        will not be calculated.

        Notes
        =====

        Calculation of transformation P is not implemented yet.

        Examples
        ========

        >>> from sympy import Matrix
        >>> m = Matrix(4, 4, [
        ...  6,  5, -2, -3,
        ... -3, -1,  3,  3,
        ...  2,  1, -2, -3,
        ... -1,  1,  5,  5])

        >>> (P, Jcells) = m.jordan_cells()
        >>> Jcells[0]
        [2, 1]
        [0, 2]
        >>> Jcells[1]
        [2, 1]
        [0, 2]

        See Also
        ========

        jordan_form
        """
        from sympy.matrices import jordan_cell, diag

        if not self.is_square:
            raise NonSquareMatrixError()
        _eigenvects = self.eigenvects()
        Jcells = []
        for eigenval, multiplicity, vects in _eigenvects:
            geometrical = len(vects)
            if geometrical == multiplicity:
                Jcell = diag( *([eigenval] * multiplicity))
                Jcells.append(Jcell)
            else:
                sizes = self._jordan_split(multiplicity, geometrical)
                cells = []
                for size in sizes:
                    cell = jordan_cell(eigenval, size)
                    cells.append(cell)
                Jcells += cells
        return (None, Jcells)

    def _jordan_split(self, algebraical, geometrical):
        """return a list of integers with sum equal to 'algebraical'
        and length equal to 'geometrical'"""
        n1 = algebraical // geometrical
        res = [n1] * geometrical
        res[len(res) - 1] += algebraical % geometrical
        assert sum(res) == algebraical
        return res

    def has(self, *patterns):
        """
        Test whether any subexpression matches any of the patterns.

        Examples
        ========

        >>> from sympy import Matrix, Float
        >>> from sympy.abc import x, y
        >>> A = Matrix(((1, x), (0.2, 3)))
        >>> A.has(x)
        True
        >>> A.has(y)
        False
        >>> A.has(Float)
        True
        """
        return any(a.has(*patterns) for a in self._mat)

    def dual(self):
        """
        Returns the dual of a matrix, which is:

        `(1/2)*levicivita(i, j, k, l)*M(k, l)` summed over indices `k` and `l`

        Since the levicivita method is anti_symmetric for any pairwise
        exchange of indices, the dual of a symmetric matrix is the zero
        matrix. Strictly speaking the dual defined here assumes that the
        'matrix' `M` is a contravariant anti_symmetric second rank tensor,
        so that the dual is a covariant second rank tensor.

        """
        from sympy import LeviCivita
        from sympy.matrices import zeros

        M, n = self[:, :], self.rows
        work = zeros(n)
        if self.is_symmetric():
            return work

        for i in range(1, n):
            for j in range(1, n):
                acum = 0
                for k in range(1, n):
                    acum += LeviCivita(i, j, 0, k)*M[0, k]
                work[i, j] = acum
                work[j, i] = -acum

        for l in range(1, n):
            acum = 0
            for a in range(1, n):
                for b in range(1, n):
                    acum += LeviCivita(0, l, a, b)*M[a, b]
            acum /= 2
            work[0, l] = -acum
            work[l, 0] = acum

        return work

    @classmethod
    def hstack(cls, *args):
        """Return a matrix formed by joining args horizontally (i.e.
        by repeated application of row_join).

        Examples
        ========

        >>> from sympy.matrices import Matrix, eye
        >>> Matrix.hstack(eye(2), 2*eye(2))
        [1, 0, 2, 0]
        [0, 1, 0, 2]
        """
        return reduce(cls.row_join, args)

    @classmethod
    def vstack(cls, *args):
        """Return a matrix formed by joining args vertically (i.e.
        by repeated application of col_join).

        Examples
        ========

        >>> from sympy.matrices import Matrix, eye
        >>> Matrix.vstack(eye(2), 2*eye(2))
        [1, 0]
        [0, 1]
        [2, 0]
        [0, 2]
        """
        return reduce(cls.col_join, args)

    def row_join(self, rhs):
        """
        Concatenates two matrices along self's last and rhs's first column

        >>> from sympy import Matrix, zeros, ones
        >>> M = zeros(3)
        >>> V = ones(3, 1)
        >>> M.row_join(V)
        [0, 0, 0, 1]
        [0, 0, 0, 1]
        [0, 0, 0, 1]

        See Also
        ========

        row
        col_join
        """
        if self.rows != rhs.rows:
            raise ShapeError("`self` and `rhs` must have the same number of rows.")

        newmat = self.zeros(self.rows, self.cols + rhs.cols)
        newmat[:, :self.cols] = self
        newmat[:, self.cols:] = rhs
        return newmat

    def col_join(self, bott):
        """
        Concatenates two matrices along self's last and bott's first row

        >>> from sympy import Matrix, zeros, ones
        >>> M = zeros(3)
        >>> V = ones(1, 3)
        >>> M.col_join(V)
        [0, 0, 0]
        [0, 0, 0]
        [0, 0, 0]
        [1, 1, 1]

        See Also
        ========

        col
        row_join
        """
        if self.cols != bott.cols:
            raise ShapeError("`self` and `bott` must have the same number of columns.")

        newmat = self.zeros(self.rows+bott.rows, self.cols)
        newmat[:self.rows, :] = self
        newmat[self.rows:, :] = bott
        return newmat

    def row_insert(self, pos, mti):
        """
        Insert one or more rows at the given row position.

        >>> from sympy import Matrix, zeros, ones
        >>> M = zeros(3)
        >>> V = ones(1, 3)
        >>> M.row_insert(1, V)
        [0, 0, 0]
        [1, 1, 1]
        [0, 0, 0]
        [0, 0, 0]

        See Also
        ========

        row
        col_insert
        """
        if pos == 0:
            return mti.col_join(self)
        elif pos < 0:
            pos = self.rows + pos
        if pos < 0:
            pos = 0
        elif pos > self.rows:
            pos = self.rows

        if self.cols != mti.cols:
            raise ShapeError("`self` and `mti` must have the same number of columns.")

        newmat = self.zeros(self.rows + mti.rows, self.cols)
        i, j = pos, pos + mti.rows
        newmat[:i  , :] = self[:i, :]
        newmat[i: j, :] = mti
        newmat[j:  , :] = self[i:, :]
        return newmat

    def col_insert(self, pos, mti):
        """
        Insert one or more columns at the given column position.

        >>> from sympy import Matrix, zeros, ones
        >>> M = zeros(3)
        >>> V = ones(3, 1)
        >>> M.col_insert(1, V)
        [0, 1, 0, 0]
        [0, 1, 0, 0]
        [0, 1, 0, 0]

        See Also
        ========

        col
        row_insert
        """
        if pos == 0:
            return mti.row_join(self)
        elif pos < 0:
            pos = self.cols + pos
        if pos < 0:
            pos = 0
        elif pos > self.cols:
            pos = self.cols

        if self.rows != mti.rows:
            raise ShapeError("self and mti must have the same number of rows.")

        newmat = self.zeros(self.rows, self.cols + mti.cols)
        i, j = pos, pos + mti.cols
        newmat[:,  :i] = self[:, :i]
        newmat[:, i:j] = mti
        newmat[:, j: ] = self[:, i:]
        return newmat


def classof(A, B):
    """
    Determines strategy for combining Immutable and Mutable matrices

    Currently the strategy is that Mutability is contagious

    Examples
    ========

    >>> from sympy import Matrix, ImmutableMatrix
    >>> from sympy.matrices.matrices import classof
    >>> M = Matrix([[1, 2], [3, 4]]) # a Mutable Matrix
    >>> IM = ImmutableMatrix([[1, 2], [3, 4]])
    >>> classof(M, IM)
    <class 'sympy.matrices.dense.MutableDenseMatrix'>
    """
    try:
        if A._class_priority > B._class_priority:
            return A.__class__
        else:
            return B.__class__
    except: pass
    try:
        import numpy
        if isinstance(A, numpy.ndarray):
            return B.__class__
        if isinstance(B, numpy.ndarray):
            return A.__class__
    except: pass
    raise TypeError("Incompatible classes %s, %s"%(A.__class__, B.__class__))

def a2idx(j, n=None):
    """Return integer after making positive and validating against n."""
    if isinstance(j, slice):
        return j
    if type(j) is not int:
        try:
            j = j.__index__()
        except AttributeError:
            raise IndexError("Invalid index a[%r]" % (j, ))
    if n is not None:
        if j < 0:
            j += n
        if not (j >= 0 and j < n):
            raise IndexError("Index out of range: a[%s]" % (j, ))
    return int(j)
