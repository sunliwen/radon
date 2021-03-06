import ast
import operator
import collections


# Helper functions to use in combination with map()
GET_COMPLEXITY = operator.attrgetter('complexity')
GET_REAL_COMPLEXITY = operator.attrgetter('real_complexity')
NAMES_GETTER = operator.attrgetter('name', 'asname')

BaseFunc = collections.namedtuple('Function', ['name', 'lineno', 'col_offset',
                                               'is_method', 'classname',
                                               'clojures', 'complexity'])
BaseClass = collections.namedtuple('Class', ['name', 'lineno', 'col_offset',
                                             'methods', 'real_complexity'])


class Function(BaseFunc):
    '''Base object represeting a function.
    '''

    @property
    def letter(self):
        '''The letter representing the function. It is `M` if the function is
        actually a method, `F` otherwise.
        '''
        return 'M' if self.is_method else 'F'

    @property
    def fullname(self):
        '''The full name of the function. If it is a method, then the full name
        is:
                {class name}.{method name}
        Otherwise it is just the function name.
        '''
        if self.classname is None:
            return self.name
        return '{0}.{1}'.format(self.classname, self.name)

    def __str__(self):
        return '{0} {1}:{2} {3} - {4}'.format(self.letter, self.lineno,
                                              self.col_offset, self.fullname,
                                              self.complexity)


class Class(BaseClass):

    letter = 'C'

    @property
    def fullname(self):
        '''The full name of the class. It is just its name. This attribute
        exists for consistency (see :data:`Function.fullname`).
        '''
        return self.name

    @property
    def complexity(self):
        '''The average complexity of the class. It corresponds to the average
        complexity of its methods plus one.
        '''
        if not self.methods:
            return self.real_complexity
        return int(self.real_complexity / float(len(self.methods))) + 1

    def __str__(self):
        return '{0} {1}:{2} {3} - {4}'.format(self.letter, self.lineno,
                                              self.col_offset, self.name,
                                              self.complexity)


class CodeVisitor(ast.NodeVisitor):
    '''Base class for every NodeVisitors in `radon.visitors`. It implements a
    couple utility class methods and a static method.
    '''

    @staticmethod
    def get_name(obj):
        '''Shorthand for ``obj.__class__.__name__``.'''
        return obj.__class__.__name__

    @classmethod
    def from_code(cls, code, **kwargs):
        '''Instanciate the class from source code (string object). The
        `**kwargs` are directly passed to the `ast.NodeVisitor` constructor.
        '''
        return cls.from_ast(ast.parse(code), **kwargs)

    @classmethod
    def from_ast(cls, ast_node, **kwargs):
        '''Instanciate the class from an AST node. The `**kwargs` are
        directly passed to the `ast.NodeVisitor` constructor.
        '''
        visitor = cls(**kwargs)
        visitor.visit(ast_node)
        return visitor


class ComplexityVisitor(CodeVisitor):
    '''A visitor that keeps track of the cyclomatic complexity of
    the elements.

    :param to_method: If True, every function is treated as a method. In this
        case the *classname* parameter is used as class name.
    :param classname: Name of parent class.
    :param off: If True, the starting value for the complexity is set to 1,
        otherwise to 0.
    '''

    def __init__(self, to_method=False, classname=None, off=True):
        self.off = off
        self.complexity = 1 if off else 0
        self.functions = []
        self.classes = []
        self.to_method = to_method
        self.classname = classname

    @property
    def functions_complexity(self):
        '''The total complexity from all functions (i.e. the total number of
        decision points + 1).
        '''
        return sum(map(GET_COMPLEXITY, self.functions)) - len(self.functions)

    @property
    def classes_complexity(self):
        '''The total complexity from all classes (i.e. the total number of
        decision points + 1).
        '''
        return sum(map(GET_REAL_COMPLEXITY, self.classes)) - len(self.classes)

    @property
    def total_complexity(self):
        '''The total complexity. Computed adding up the class complexity, the
        functions complexity, and the classes complexity.
        '''
        return (self.complexity + self.functions_complexity +
                self.classes_complexity + (not self.off))

    @property
    def blocks(self):
        '''All the blocks visited. These include: all the functions, the
        classes and their methods. The returned list is not sorted.
        '''
        blocks = self.functions
        for cls in self.classes:
            blocks.append(cls)
            blocks.extend(cls.methods)
        return blocks

    def generic_visit(self, node):
        '''Main entry point for the visitor.'''
        # Get the name of the class
        name = self.get_name(node)
        # The Try/Except block is counted as the number of handlers
        # plus the `else` block.
        # In Python 3.3 the TryExcept and TryFinally nodes have been merged
        # into a single node: Try
        if name in ('Try', 'TryExcept'):
            self.complexity += len(node.handlers) + len(node.orelse)
        elif name == 'BoolOp':
            self.complexity += len(node.values) - 1
        # Lambda functions, ifs, with and assert statements count all as 1.
        elif name in ('Lambda', 'With', 'If', 'IfExp', 'Assert'):
            self.complexity += 1
        # The For and While blocks count as 1 plus the `else` block.
        elif name in ('For', 'While'):
            self.complexity += len(node.orelse) + 1
        # List, set, dict comprehensions and generator exps count as 1 plus
        # the `if` statement.
        elif name == 'comprehension':
            self.complexity += len(node.ifs) + 1

        super(ComplexityVisitor, self).generic_visit(node)

    def visit_FunctionDef(self, node):
        # The complexity of a function is computed taking into account
        # the following factors: number of decorators, the complexity
        # the function's body and the number of clojures (which count
        # double).
        clojures = []
        body_complexity = 1
        for child in node.body:
            visitor = ComplexityVisitor(off=False)
            visitor.visit(child)
            clojures.extend(visitor.functions)
            # Add general complexity and clojures' complexity
            body_complexity += (visitor.complexity +
                                visitor.functions_complexity)

        func = Function(node.name, node.lineno, node.col_offset,
                        self.to_method, self.classname, clojures,
                        body_complexity)
        self.functions.append(func)

    def visit_ClassDef(self, node):
        # The complexity of a class is computed taking into account
        # the following factors: number of decorators and the complexity
        # of the class' body (which is the sum of all the complexities).
        methods = []
        # According to Cyclomatic Complexity definition it has to start off
        # from 1.
        body_complexity = 1
        classname = node.name
        for child in node.body:
            visitor = ComplexityVisitor(True, classname, off=False)
            visitor.visit(child)
            methods.extend(visitor.functions)
            body_complexity += (visitor.complexity +
                                visitor.functions_complexity)

        cls = Class(classname, node.lineno, node.col_offset,
                    methods, body_complexity)
        self.classes.append(cls)


class HalsteadVisitor(CodeVisitor):
    '''Visitor that keeps track of operators and operands, in order to compute
    Halstead metrics (see :func:`radon.metrics.hh_visit`).
    '''

    types = {ast.Num: 'n',
             ast.Name: 'id',
             ast.Attribute: 'attr'}

    def __init__(self, context=None):
        self.operators_seen = set()
        self.operands_seen = set()
        self.operators = 0
        self.operands = 0
        self.context = context

    @property
    def distinct_operators(self):
        '''The number of distinct operators.'''
        return len(self.operators_seen)

    @property
    def distinct_operands(self):
        '''The number of distinct operands.'''
        return len(self.operands_seen)

    def dispatch(meth):
        '''Does all the hard work needed for every node.

        The decorated method must return a tuple of 4 elements:

            * the number of operators
            * the number of operands
            * the operators seen (a sequence)
            * the operands seen (a sequence)
        '''
        def aux(self, node):
            results = meth(self, node)
            self.operators += results[0]
            self.operands += results[1]
            self.operators_seen.update(results[2])
            for operand in results[3]:
                new_operand = getattr(operand,
                                      self.types.get(type(operand), ''),
                                      operand)

                self.operands_seen.add((self.context, new_operand))
            # Now dispatch to children
            super(HalsteadVisitor, self).generic_visit(node)
        return aux

    @dispatch
    def visit_BinOp(self, node):
        '''A binary operator.'''
        return (1, 2, (self.get_name(node.op),), (node.left, node.right))

    @dispatch
    def visit_UnaryOp(self, node):
        '''A unary operator.'''
        return (1, 1, (self.get_name(node.op),), (node.operand,))

    @dispatch
    def visit_BoolOp(self, node):
        '''A boolean operator.'''
        return (1, len(node.values), (self.get_name(node.op),), node.values)

    @dispatch
    def visit_AugAssign(self, node):
        '''An augmented assign (contains an operator).'''
        return (1, 2, (self.get_name(node.op),), (node.target, node.value))

    @dispatch
    def visit_Compare(self, node):
        '''A comparison.'''
        return (len(node.ops), len(node.comparators) + 1,
                map(self.get_name, node.ops), node.comparators + [node.left])

    def visit_FunctionDef(self, node):
        for child in node.body:
            visitor = HalsteadVisitor.from_ast(child, context=node.name)
            self.operators += visitor.operators
            self.operands += visitor.operands
            self.operators_seen.update(visitor.operators_seen)
            self.operands_seen.update(visitor.operands_seen)
