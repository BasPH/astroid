# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.

# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""tests for specific behaviour of astng nodes

Copyright (c) 2003-2005 LOGILAB S.A. (Paris, FRANCE).
http://www.logilab.fr/ -- mailto:contact@logilab.fr
"""

__revision__ = "$Id: unittest_nodes.py,v 1.6 2005-12-28 14:56:21 syt Exp $"

import unittest

from logilab.astng import builder, nodes, NotFoundError

from data import module as test_module

abuilder = builder.ASTNGBuilder() 
MODULE = abuilder.module_build(test_module)
MODULE2 = abuilder.file_build('data/module2.py', 'data.module2')


class ImportNodeTC(unittest.TestCase):
    
    def test_import_self_resolve(self):
        import_ = MODULE2['myos']
        myos = import_.infer('myos').next()
        self.failUnless(isinstance(myos, nodes.Module), myos)
        self.failUnlessEqual(myos.name, 'os')

    def test_from_self_resolve(self):
        from_ = MODULE['modutils']
        spawn = from_.infer('spawn').next()
        self.failUnless(isinstance(spawn, nodes.Class), spawn)
        self.failUnlessEqual(spawn.root().name, 'logilab.common')
        from_ = MODULE2['abspath']
        abspath = from_.infer('abspath').next()
        self.failUnless(isinstance(abspath, nodes.Function), abspath)
        self.failUnlessEqual(abspath.root().name, 'os.path')

    def test_real_name(self):
        from_ = MODULE['modutils']
        self.assertEquals(from_.real_name('spawn'), 'Execute')
        imp_ = MODULE['os']
        self.assertEquals(imp_.real_name('os'), 'os')
        self.assertRaises(NotFoundError, imp_.real_name, 'os.path')
        imp_ = MODULE['spawn']
        self.assertEquals(imp_.real_name('spawn'), 'Execute')
        self.assertRaises(NotFoundError, imp_.real_name, 'Execute')
        imp_ = MODULE2['YO']
        self.assertEquals(imp_.real_name('YO'), 'YO')
        self.assertRaises(NotFoundError, imp_.real_name, 'data')

    def test_as_string(self):
        ast = MODULE['modutils']
        self.assertEquals(ast.as_string(), "from logilab.common import modutils, Execute as spawn")
        ast = MODULE['os']
        self.assertEquals(ast.as_string(), "import os.path")

class CmpNodeTC(unittest.TestCase):
    def test_as_string(self):
        ast = abuilder.string_build("a == 2")
        self.assertEquals(ast.as_string(), "a == 2")
        
__all__ = ('ImportNodeTC',)
        
if __name__ == '__main__':
    unittest.main()
