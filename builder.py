# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""The ASTNGBuilder makes astng from living object and / or from compiler.ast

The builder is not thread safe and can't be used to parse different sources
at the same time.

TODO:
 - more complet representation on inspect build
   (imported modules ? use dis.dis ?)


:version:   $Revision: 1.54 $  
:author:    Sylvain Thenault
:copyright: 2003-2005 LOGILAB S.A. (Paris, FRANCE)
:contact:   http://www.logilab.fr/ -- mailto:python-projects@logilab.org
:copyright: 2003-2005 Sylvain Thenault
:contact:   mailto:thenault@gmail.com
"""

__revision__ = "$Id: builder.py,v 1.54 2006-03-14 15:21:33 syt Exp $"
__doctype__ = "restructuredtext en"

import sys
from os.path import splitext, basename, dirname, exists, abspath
from parser import ParserError
from compiler import parse
from inspect import isfunction, ismethod, ismethoddescriptor, isclass, \
     isbuiltin
try: # python 2.2 inspect module doesn't have the isdatadescriptor function
    from inspect import isdatadescriptor
except ImportError:
    def isdatadescriptor(_):
        """fake isdatadescriptor function, always returning False"""
        return False

from logilab.common.fileutils import norm_read
from logilab.common.modutils import modpath_from_file

from logilab.astng import nodes
from logilab.astng.utils import ASTWalker
from logilab.astng._exceptions import ASTNGBuildingException
from logilab.astng.raw_building import *

# ast NG builder ##############################################################

class ASTNGBuilder:
    """provide astng building methods
    """
    
    def __init__(self): # XXX _ was the manager, keep for bw compat
        self._module = None
        self._file = None
        self._done = None
        self._stack, self._par_stack = None, None
        self._metaclass = None        
        self._walker = ASTWalker(self)
        self._dyn_modname_map = {'gtk': 'gtk._gtk'}
        
    def module_build(self, module, modname=None):
        """build an astng from a living module instance
        """
        node = None
        self._module = module
        path = getattr(module, '__file__', None)
        if path is not None:
            path_, ext = splitext(module.__file__)
            if ext in ('.py', '.pyc', '.pyo') and exists(path_ + '.py'):
                node = self.file_build(path_ + '.py', modname)
        if node is None:
            # this is a built-in module
            # get a partial representation by introspection
            node = self.inspect_build(module, modname=modname, path=path)
        return node

    def inspect_build(self, module, modname=None, path=None):
        """build astng from a living module (i.e. using inspect)
        this is used when there is no python source code available (either
        because it's a built-in module or because the .py is not available)
        """
        self._module = module
        node = build_module(modname or module.__name__, module.__doc__)
        node.file = node.path = path and abspath(path) or path
        node.package = hasattr(module, '__path__')
        attach___dict__(node)
        self._done = {}
        self.object_build(node, module)
        return node
    
    def file_build(self, path, modname=None):
        """build astng from a source code file (i.e. from an ast)

        path is expected to be a python source file
        """
        try:
            data = norm_read(path)
        except IOError, ex:
            msg = 'Unable to load file %r (%s)' % (path, ex)
            raise ASTNGBuildingException(msg)
        self._file = path
        # get module name if necessary, *before modifying sys.path*
        if modname is None:
            try:
                modname = '.'.join(modpath_from_file(path))
            except ImportError:
                modname = splitext(basename(path))[0]
        # build astng representation
        try:
            sys.path.insert(0, dirname(path))
            node = self.string_build(data, modname, path)
            node.file = abspath(path)
        finally:
            self._file = None
            sys.path.pop(0)
        return node
    
    def string_build(self, data, modname='', path=None):
        """build astng from a source code stream (i.e. from an ast)"""
        try:
            return self.ast_build(parse(data + '\n'), modname, path)
        except ParserError, ex:
            # compiler.parse with python <= 2.2 raise ParserError instead of
            # SyntaxError
            ex = SyntaxError('invalid syntax')
            ex.lineno = 1 # dummy line number
            raise ex
        
    def ast_build(self, node, modname=None, path=None):
        """recurse on the ast (soon ng) to add some arguments et method
        """
        if path is not None:
            node.file = node.path = abspath(path)
        else:
            node.file = node.path = '<?>'
        if modname.endswith('.__init__'):
            modname = modname[:-9]
            node.package = True
        else:
            node.package = path and path.find('__init__.py') > -1 or False
        node.name = modname 
        node.pure_python = True
        self._walker.walk(node)
        return node

    # callbacks to build from an existing compiler.ast tree ###################

    def visit_module(self, node):
        """visit a stmt.Module node -> init node and push the corresponding
        object or None on the top of the stack
        """
        self._stack = [self._module]
        self._par_stack = [node]
        self._metaclass = ['']
        self._global_names = []
        node.parent = None
        node.globals = node.locals = {}
        for name, value in ( ('__name__', node.name),
                             ('__file__', node.path),
                             ('__doc__', node.doc) ):
            const = nodes.Const(value)
            const.parent = node
            node.locals[name] = [const]
        attach___dict__(node)
        if node.package:
            # FIXME: List(Const())
            const = nodes.Const(dirname(node.path))
            const.parent = node
            node.locals['__path__'] = [const]
            

    def leave_module(self, _):
        """leave a stmt.Module node -> pop the last item on the stack and check
        the stack is empty
        """
        self._stack.pop()
        assert not self._stack, 'Stack is not empty : %s' % self._stack
        self._par_stack.pop()
        assert not self._par_stack, \
               'Parent stack is not empty : %s' % self._par_stack
        
    def visit_class(self, node):
        """visit a stmt.Class node -> init node and push the corresponding
        object or None on the top of the stack
        """
        self.visit_default(node)
        node.instance_attrs = {}
        node.basenames = [b_node.as_string() for b_node in node.bases]
        self._push(node)
        for name, value in ( ('__name__', node.name),
                             ('__module__', node.root().name),
                             ('__doc__', node.doc) ):
            const = nodes.Const(value)
            const.parent = node
            node.locals[name] = [const]
        attach___dict__(node)
        self._metaclass.append(self._metaclass[-1])
        
    def leave_class(self, node):
        """leave a stmt.Class node -> pop the last item on the stack
        """
        self.leave_default(node)
        self._stack.pop()
        metaclass = self._metaclass.pop()
        if not node.bases:
            # no base classes, detect new / style old style according to
            # current scope
            node._newstyle = metaclass == 'type'
        
    def visit_function(self, node):
        """visit a stmt.Function node -> init node and push the corresponding
        object or None on the top of the stack
        """
        self.visit_default(node)
        self._global_names.append({})
        node.argnames = list(node.argnames)
        if isinstance(node.parent.frame(), nodes.Class):
            node.type = 'method'
            if node.name == '__new__':
                node.type = 'classmethod'
        self._push(node)
        register_arguments(node, node.argnames)
        
    def leave_function(self, node):
        """leave a stmt.Function node -> pop the last item on the stack
        """
        self.leave_default(node)
        self._stack.pop()
        self._global_names.pop()
        
    def visit_lambda(self, node):
        """visit a stmt.Lambda node -> init node locals
        """
        self.visit_default(node)
        node.argnames = list(node.argnames)
        node.locals = {}
        register_arguments(node, node.argnames)
        
    def visit_global(self, node):
        """visit a stmt.Global node -> add declared names to locals
        """
        self.visit_default(node)
        if not self._global_names: # global at the module level, no effect
            return
        for name in node.names:
            self._global_names[-1].setdefault(name, []).append(node)
#             node.parent.set_local(name, node)
#         module = node.root()
#         if module is not node.frame():
#             for name in node.names:
#                 module.set_local(name, node)
            
    def visit_import(self, node):
        """visit a stmt.Import node -> add imported names to locals
        """
        self.visit_default(node)
        for (name, asname) in node.names:
            name = asname or name
            node.parent.set_local(name.split('.')[0], node)
            
    def visit_from(self, node):
        """visit a stmt.From node -> add imported names to locals
        """
        self.visit_default(node)
        # add names imported by the import to locals
        for (name, asname) in node.names:
            if name == '*':
                try:
                    imported = node.root().import_module(node.modname)
                except ASTNGBuildingException:
                    #import traceback
                    #traceback.print_exc()
                    continue
                    # FIXME: log error
                    #print >> sys.stderr, \
                    #      'Unable to get imported names for %r line %s"' % (
                    #    node.modname, node.lineno)
                for name in imported.wildcard_import_names():
                    node.parent.set_local(name, node)
            else:
                node.parent.set_local(asname or name, node)

    def leave_decorators(self, node):
        """python >= 2.4
        visit a stmt.Decorator node -> check for classmethod and staticmethod
        """
        func = node.parent
        for decorator_expr in node.nodes:
            if isinstance(decorator_expr, nodes.Name) and \
                   decorator_expr.name in ('classmethod', 'staticmethod'):
                func.type = decorator_expr.name
        self.leave_default(node)
        
    def visit_assign(self, node):
        """visit a stmt.Assign node -> check for classmethod and staticmethod
        + __metaclass__
        """
        self.visit_default(node)
        klass = node.parent.frame()
        #print node
        if isinstance(klass, nodes.Class) and \
            isinstance(node.expr, nodes.CallFunc) and \
            isinstance(node.expr.node, nodes.Name):
            func_name = node.expr.node.name
            if func_name in ('classmethod', 'staticmethod'):
                for ass_node in node.nodes:
                    if isinstance(ass_node, nodes.AssName):
                        try:
                            meth = klass[ass_node.name]
                            if isinstance(meth, nodes.Function):
                                meth.type = func_name
                            #else:
                            #    print >> sys.stderr, 'FIXME 1', meth
                        except KeyError:
                            #print >> sys.stderr, 'FIXME 2', ass_node.name
                            continue
        elif (isinstance(node.nodes[0], nodes.AssName)
              and node.nodes[0].name == '__metaclass__'): # XXX check more...
            self._metaclass[-1] = 'type'

    def visit_assname(self, node):
        """visit a stmt.AssName node -> add name to locals
        """
        self.visit_default(node)
        self._add_local(node, node.name)

    def visit_augassign(self, node):
        """visit a stmt.AssName node -> add name to locals
        """
        self.visit_default(node)
        if not isinstance(node.node, nodes.Name):
            return  # XXX
        self._add_local(node, node.node.name)

    def _add_local(self, node, name):
        if self._global_names and name in self._global_names[-1]:
            node.root().set_local(name, node)
        else:
            node.parent.set_local(name, node)
        
    def visit_assattr(self, node):
        """visit a stmt.AssAttr node -> add name to locals, handle members
        definition
        """
        self.visit_default(node)
        frame = node.frame()
        if isinstance(frame, nodes.Function) and frame.type != 'function':
            klass = frame.parent.frame()
            # are we assigning to a (new ?) instance attribute ?
            try:
                _self = frame.argnames[0]
            except IndexError:
                # first argument is missing !
                return
            if isinstance(node.expr, nodes.Name) and node.expr.name == _self:
                # unittest_scoped_nodes.ClassNodeTC.test_classmethod_attributes
                #
                # if frame.type == 'classmethod': XXX at this point we may have
                # not encountered the classmethod decorator, so we havn't yet
                # the correct type
                # hack according to the argument name
                if _self == 'self': 
                    iattrs = klass.instance_attrs
                else:
                    iattrs = klass.locals
                # assign if not yet existant in others
                if not iattrs.has_key(node.attrname):
                    iattrs[node.attrname] = [node]
                # but always assign in __init__, except if previous assigment
                # already come from __init__
                elif frame.name == '__init__' and not \
                         iattrs[node.attrname][0].frame().name == '__init__':
                    iattrs[node.attrname].insert(0, node)
                else:
                    iattrs[node.attrname].append(node)
                    
    def visit_default(self, node):
        """default visit method, handle the parent attribute
        """
        node.parent = self._par_stack[-1]
        assert node.parent is not node
        self._par_stack.append(node)

    def leave_default(self, _):       
        """default leave method, handle the parent attribute
        """
        self._par_stack.pop()             

    def _push(self, node):
        """update the stack and init some parts of the Function or Class node
        """
        obj = getattr(self._stack[-1], node.name, None)
        self._stack.append(obj)
        node.locals = {}
        node.parent.frame().set_local(node.name, node)

    # astng from living objects ###############################################
    #
    # this is actually a really minimal representation, including only Module,
    # Function and Class nodes and some others as guessed
    
    def object_build(self, node, obj):
        """recursive method which create a partial ast from real objects
         (only function, class, and method are handled)
        """
        if self._done.has_key(obj):
            return self._done[obj]
        self._done[obj] = node
        modname = self._module.__name__
        modfile = getattr(self._module, '__file__', None)
        for name in dir(obj):
            try:
                member = getattr(obj, name)
            except AttributeError:
                # damned ExtensionClass.Base, I know you're there !
                attach_dummy_node(node, name)
                continue
            if ismethod(member):
                member = member.im_func
            if isfunction(member):
                # verify this is not an imported function
                if member.func_code.co_filename != modfile:
                    attach_dummy_node(node, name)
                    continue
                object_build_function(node, member)
            elif isbuiltin(member):
                # verify this is not an imported member
                if self._member_module(member) != modname:
                    imported_member(node, member, name)
                    continue
                object_build_methoddescriptor(node, member)                
            elif isclass(member):
                # verify this is not an imported class
                if self._member_module(member) != modname:
                    imported_member(node, member, name)
                    continue
                if member in self._done:
                    class_node = self._done[member]
                    node.add_local_node(class_node)
                else:
                    class_node = object_build_class(node, member)
                # recursion
                self.object_build(class_node, member)
            elif ismethoddescriptor(member):
                assert isinstance(member, object)
                object_build_methoddescriptor(node, member)
            elif isdatadescriptor(member):
                assert isinstance(member, object)
                object_build_datadescriptor(node, member, name)
            elif isinstance(member, (int, long, float, str, unicode)) or member is None:
                attach_const_node(node, name, member)
            else:
                # create an empty node so that the name is actually defined
                attach_dummy_node(node, name)

    def _member_module(self, member):
        modname = getattr(member, '__module__', None)
        return self._dyn_modname_map.get(modname, modname)
        
def imported_member(node, member, name):
    """consider a class/builtin member where __module__ != current module name

    check if it's sound valid and then add an import node, else use a dummy node
    """
    # /!\ some classes like ExtensionClass doesn't have a 
    # __module__ attribute !
    member_module = getattr(member, '__module__', '__builtin__')
    try:
        getattr(sys.modules[member_module], name)
    except (KeyError, AttributeError):
        attach_dummy_node(node, name)
    else:
        attach_import_node(node, member_module, name)
    
# optimize the tokenize module
#from logilab.common.bind import optimize_module
#import tokenize
#optimize_module(sys.modules['tokenize'], tokenize.__dict__)
#optimize_module(sys.modules[__name__], sys.modules[__name__].__dict__)
