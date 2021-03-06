#!/usr/bin/env python
"""
    This script is supposed to easy the upgrade of Atlassian products, including Jira, Confluence and Crowd

    Send my thanks to this company that failed to provide an easy method for upgrading their products.

    For the moment this script supports only the 64 bit Linux variants.

    How it works:

    * first it detects what products you have installed by looking at their default locations
    * downloads the latest version
    * stops the service
    * rename old version directory by addin '.old'
    * puts the new version in place
    * copies essential files from the old version
    * restarts the service
"""

import codecs
import ctypes
import datetime
import fnmatch
import inspect
import urllib2
import json
import os
import platform
import re
import sys
import tempfile
import time
import logging
from collections import OrderedDict
from distutils.version import LooseVersion
from optparse import OptionParser
from tendo import colorer

# trick for py2/3 compatibility
if 'basestring' not in globals():
   basestring = str

ARCHIVE_DIR='/var/backups/archive/'
DOWNLOADS_DIR='/var/backups/downloads/'

os.system('mkdir -p %s' % ARCHIVE_DIR)

MYDIR = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile( inspect.currentframe() ))[0]))


FINAL_MARKER = ('f',)
VERSION_RE = re.compile(r'''
    ^
    (?P<version>\d+\.\d+)          # minimum 'N.N'
    (?P<extraversion>(?:\.\d+)*)   # any number of extra '.N' segments
    (?:
        (?P<prerel>[abc]|rc)       # 'a'=alpha, 'b'=beta, 'c'=release candidate
                                   # 'rc'= alias for release candidate
        (?P<prerelversion>\d+(?:\.\d+)*)
    )?
    (?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?
    $''', re.VERBOSE)

def get_free_space_mb(folder):
    """ Return folder/drive free space (in bytes)
    """
    if platform.system() == 'Windows':
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free_bytes))
        return free_bytes.value/1024/1024
    else:
        st = os.statvfs(folder)
        return st.f_bavail * st.f_frsize/1024/1024

class NormalizedVersion(object):
    """A rational version.

    Good:
        1.2         # equivalent to "1.2.0"
        1.2.0
        1.2a1
        1.2.3a2
        1.2.3b1
        1.2.3c1
        1.2.3.4
        TODO: fill this out

    Bad:
        1           # mininum two numbers
        1.2a        # release level must have a release serial
        1.2.3b
    """
    def __init__(self, s, error_on_huge_major_num=True):
        """Create a NormalizedVersion instance from a version string.

        @param s {str} The version string.
        @param error_on_huge_major_num {bool} Whether to consider an
            apparent use of a year or full date as the major version number
            an error. Default True. One of the observed patterns on PyPI before
            the introduction of `NormalizedVersion` was version numbers like this:
                2009.01.03
                20040603
                2005.01
            This guard is here to strongly encourage the package author to
            use an alternate version, because a release deployed into PyPI
            and, e.g. downstream Linux package managers, will forever remove
            the possibility of using a version number like "1.0" (i.e.
            where the major number is less than that huge major number).
        """
        self._parse(s, error_on_huge_major_num)

    @classmethod
    def from_parts(cls, version, prerelease=FINAL_MARKER,
                   devpost=FINAL_MARKER):
        return cls(cls.parts_to_str((version, prerelease, devpost)))

    def _parse(self, s, error_on_huge_major_num=True):
        """Parses a string version into parts."""
        match = VERSION_RE.search(s)
        if not match:
            raise IrrationalVersionError(s)

        groups = match.groupdict()
        parts = []

        # main version
        block = self._parse_numdots(groups['version'], s, False, 2)
        extraversion = groups.get('extraversion')
        if extraversion not in ('', None):
            block += self._parse_numdots(extraversion[1:], s)
        parts.append(tuple(block))

        # prerelease
        prerel = groups.get('prerel')
        if prerel is not None:
            block = [prerel]
            block += self._parse_numdots(groups.get('prerelversion'), s,
                                         pad_zeros_length=1)
            parts.append(tuple(block))
        else:
            parts.append(FINAL_MARKER)

        # postdev
        if groups.get('postdev'):
            post = groups.get('post')
            dev = groups.get('dev')
            postdev = []
            if post is not None:
                postdev.extend([FINAL_MARKER[0], 'post', int(post)])
                if dev is None:
                    postdev.append(FINAL_MARKER[0])
            if dev is not None:
                postdev.extend(['dev', int(dev)])
            parts.append(tuple(postdev))
        else:
            parts.append(FINAL_MARKER)
        self.parts = tuple(parts)
        if error_on_huge_major_num and self.parts[0][0] > 1980:
            raise HugeMajorVersionNumError("huge major version number, %r, "
                "which might cause future problems: %r" % (self.parts[0][0], s))

    def _parse_numdots(self, s, full_ver_str, drop_trailing_zeros=True,
                       pad_zeros_length=0):
        """Parse 'N.N.N' sequences, return a list of ints.

        @param s {str} 'N.N.N..." sequence to be parsed
        @param full_ver_str {str} The full version string from which this
            comes. Used for error strings.
        @param drop_trailing_zeros {bool} Whether to drop trailing zeros
            from the returned list. Default True.
        @param pad_zeros_length {int} The length to which to pad the
            returned list with zeros, if necessary. Default 0.
        """
        nums = []
        for n in s.split("."):
            if len(n) > 1 and n[0] == '0':
                raise IrrationalVersionError("cannot have leading zero in "
                    "version number segment: '%s' in %r" % (n, full_ver_str))
            nums.append(int(n))
        if drop_trailing_zeros:
            while nums and nums[-1] == 0:
                nums.pop()
        while len(nums) < pad_zeros_length:
            nums.append(0)
        return nums

    def __str__(self):
        return self.parts_to_str(self.parts)

    @classmethod
    def parts_to_str(cls, parts):
        """Transforms a version expressed in tuple into its string
        representation."""
        # XXX This doesn't check for invalid tuples
        main, prerel, postdev = parts
        s = '.'.join(str(v) for v in main)
        if prerel is not FINAL_MARKER:
            s += prerel[0]
            s += '.'.join(str(v) for v in prerel[1:])
        if postdev and postdev is not FINAL_MARKER:
            if postdev[0] == 'f':
                postdev = postdev[1:]
            i = 0
            while i < len(postdev):
                if i % 2 == 0:
                    s += '.'
                s += str(postdev[i])
                i += 1
        return s

    def __repr__(self):
        return "%s('%s')" % (self.__class__.__name__, self)

    def _cannot_compare(self, other):
        raise TypeError("cannot compare %s and %s"
                % (type(self).__name__, type(other).__name__))

    def __eq__(self, other):
        if not isinstance(other, NormalizedVersion):
            self._cannot_compare(other)
        return self.parts == other.parts

    def __lt__(self, other):
        if not isinstance(other, NormalizedVersion):
            self._cannot_compare(other)
        return self.parts < other.parts

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return not (self.__lt__(other) or self.__eq__(other))

    def __le__(self, other):
        return self.__eq__(other) or self.__lt__(other)

    def __ge__(self, other):
        return self.__eq__(other) or self.__gt__(other)

#--- end of import 

# --- start of import
# http://www.python.org/dev/peps/pep-0386/
FINAL_MARKER = ('f',)
VERSION_RE = re.compile(r'''
    ^
    (?P<version>\d+\.\d+)          # minimum 'N.N'
    (?P<extraversion>(?:\.\d+)*)   # any number of extra '.N' segments
    (?:
        (?P<prerel>[-]{0,1}[abc]|rc|beta)       # 'a'=alpha, 'b'=beta, 'c'=release candidate
                                   # 'rc'= alias for release candidate
        (?P<prerelversion>\d+(?:\.\d+)*)
    )?
    (?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?
    $''', re.VERBOSE)

class IrrationalVersionError(Exception):
    """This is an irrational version."""
    pass

class NormalizedVersion(object):
    """A rational version.

    Good:
        1.2         # equivalent to "1.2.0"
        1.2.0
        1.2a1
        1.2.3a2
        1.2.3b1
        1.2.3c1
        1.2.3.4
        TODO: fill this out

    Bad:
        1           # mininum two numbers
        1.2a        # release level must have a release serial
        1.2.3b
    """
    def __init__(self, s, error_on_huge_major_num=True):
        """Create a NormalizedVersion instance from a version string.

        @param s {str} The version string.
        @param error_on_huge_major_num {bool} Whether to consider an
            apparent use of a year or full date as the major version number
            an error. Default True. One of the observed patterns on PyPI before
            the introduction of `NormalizedVersion` was version numbers like this:
                2009.01.03
                20040603
                2005.01
            This guard is here to strongly encourage the package author to
            use an alternate version, because a release deployed into PyPI
            and, e.g. downstream Linux package managers, will forever remove
            the possibility of using a version number like "1.0" (i.e.
            where the major number is less than that huge major number).
        """
        self._parse(s, error_on_huge_major_num)

    @classmethod
    def from_parts(cls, version, prerelease=FINAL_MARKER,
                   devpost=FINAL_MARKER):
        return cls(cls.parts_to_str((version, prerelease, devpost)))

    def _parse(self, s, error_on_huge_major_num=True):
        """Parses a string version into parts."""
        #print s, type(s)
        match = VERSION_RE.search(str(s))
        if not match:
            raise IrrationalVersionError(s)

        groups = match.groupdict()
        parts = []

        # main version
        block = self._parse_numdots(groups['version'], s, False, 2)
        extraversion = groups.get('extraversion')
        if extraversion not in ('', None):
            block += self._parse_numdots(extraversion[1:], s)
        parts.append(tuple(block))

        # prerelease
        prerel = groups.get('prerel')
        if prerel is not None:
            block = [prerel]
            block += self._parse_numdots(groups.get('prerelversion'), s,
                                         pad_zeros_length=1)
            parts.append(tuple(block))
        else:
            parts.append(FINAL_MARKER)

        # postdev
        if groups.get('postdev'):
            post = groups.get('post')
            dev = groups.get('dev')
            postdev = []
            if post is not None:
                postdev.extend([FINAL_MARKER[0], 'post', int(post)])
                if dev is None:
                    postdev.append(FINAL_MARKER[0])
            if dev is not None:
                postdev.extend(['dev', int(dev)])
            parts.append(tuple(postdev))
        else:
            parts.append(FINAL_MARKER)
        self.parts = tuple(parts)
        if error_on_huge_major_num and self.parts[0][0] > 1980:
            raise HugeMajorVersionNumError("huge major version number, %r, "
                "which might cause future problems: %r" % (self.parts[0][0], s))

    def _parse_numdots(self, s, full_ver_str, drop_trailing_zeros=True,
                       pad_zeros_length=0):
        """Parse 'N.N.N' sequences, return a list of ints.

        @param s {str} 'N.N.N..." sequence to be parsed
        @param full_ver_str {str} The full version string from which this
            comes. Used for error strings.
        @param drop_trailing_zeros {bool} Whether to drop trailing zeros
            from the returned list. Default True.
        @param pad_zeros_length {int} The length to which to pad the
            returned list with zeros, if necessary. Default 0.
        """
        nums = []
        for n in s.split("."):
            if len(n) > 1 and n[0] == '0':
                raise IrrationalVersionError("cannot have leading zero in "
                    "version number segment: '%s' in %r" % (n, full_ver_str))
            nums.append(int(n))
        if drop_trailing_zeros:
            while nums and nums[-1] == 0:
                nums.pop()
        while len(nums) < pad_zeros_length:
            nums.append(0)
        return nums

    def __str__(self):
        return self.parts_to_str(self.parts)

    @classmethod
    def parts_to_str(cls, parts):
        """Transforms a version expressed in tuple into its string
        representation."""
        # XXX This doesn't check for invalid tuples
        main, prerel, postdev = parts
        s = '.'.join(str(v) for v in main)
        if prerel is not FINAL_MARKER:
            s += prerel[0]
            s += '.'.join(str(v) for v in prerel[1:])
        if postdev and postdev is not FINAL_MARKER:
            if postdev[0] == 'f':
                postdev = postdev[1:]
            i = 0
            while i < len(postdev):
                if i % 2 == 0:
                    s += '.'
                s += str(postdev[i])
                i += 1
        return s

    def __repr__(self):
        return "%s('%s')" % (self.__class__.__name__, self)

    def _cannot_compare(self, other):
        raise TypeError("cannot compare %s and %s"
                % (type(self).__name__, type(other).__name__))

    def __eq__(self, other):
        if not isinstance(other, NormalizedVersion):
            self._cannot_compare(other)
        return self.parts == other.parts

    def __lt__(self, other):
        if not isinstance(other, NormalizedVersion):
            self._cannot_compare(other)
        return self.parts < other.parts

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return not (self.__lt__(other) or self.__eq__(other))

    def __le__(self, other):
        return self.__eq__(other) or self.__lt__(other)

    def __ge__(self, other):
        return self.__eq__(other) or self.__gt__(other)

def suggest_normalized_version(s):
    """Suggest a normalized version close to the given version string.
 
    If you have a version string that isn't rational (i.e. NormalizedVersion
    doesn't like it) then you might be able to get an equivalent (or close)
    rational version from this function.
 
    This does a number of simple normalizations to the given string, based
    on observation of versions currently in use on PyPI. Given a dump of
    those version during PyCon 2009, 4287 of them:
    - 2312 (53.93%) match NormalizedVersion without change
      with the automatic suggestion
    - 3474 (81.04%) match when using this suggestion method
 
    @param s {str} An irrational version string.
    @returns A rational version string, or None, if couldn't determine one.
    """
    try:
        x = NormalizedVersion(s)
        if x:
            return x   # already rational
    #except IrrationalVersionError:
    except Exception:
        pass
    #print(type(s))
    rs = s.lower()
 
    # part of this could use maketrans
    for orig, repl in (('-alpha', 'a'), ('-beta', 'b'), ('alpha', 'a'),
                       ('beta', 'b'), ('-rc', '.0c'), ('-final', ''),
                       ('-pre', 'c'),
                       ('-release', ''), ('.release', ''), ('-stable', ''),
                       ('+', '.'), ('_', '.'), (' ', ''), ('.final', ''),
                       ('final', ''),
                       ('-m','a'),
        ):
        rs = rs.replace(orig, repl)
 
    
    # remove leading 0 from version number
    rs = re.sub(r"a0", r"a", rs)

    # if something ends with dev or pre, we add a 0
    rs = re.sub(r"pre$", r"pre0", rs)
    rs = re.sub(r"dev$", r"dev0", rs)
 
    # if we have something like "b-2" or "a.2" at the end of the
    # version, that is pobably beta, alpha, etc
    # let's remove the dash or dot
    rs = re.sub(r"([abc]|rc)[\-\.](\d+)$", r"\1\2", rs)
 
    # 1.0-dev-r371 -> 1.0.dev371
    # 0.1-dev-r79 -> 0.1.dev79
    rs = re.sub(r"[\-\.](dev)[\-\.]?r?(\d+)$", r".\1\2", rs)
 
    # Clean: 2.0.a.3, 2.0.b1, 0.9.0~c1
    rs = re.sub(r"[.~]?([abc])\.?", r"\1", rs)
 
    # Clean: v0.3, v1.0
    if rs.startswith('v'):
        rs = rs[1:]
 
    # Clean leading '0's on numbers.
    #TODO: unintended side-effect on, e.g., "2003.05.09"
    # PyPI stats: 77 (~2%) better
    rs = re.sub(r"\b0+(\d+)(?!\d)", r"\1", rs)
 
    # Clean a/b/c with no version. E.g. "1.0a" -> "1.0a0". Setuptools infers
    # zero.
    # PyPI stats: 245 (7.56%) better
    rs = re.sub(r"(\d+[abc])$", r"\g<1>0", rs)
 
    # the 'dev-rNNN' tag is a dev tag
    rs = re.sub(r"\.?(dev-r|dev\.r)\.?(\d+)$", r".dev\2", rs)
 
    # clean the - when used as a pre delimiter
    rs = re.sub(r"-(a|b|c)(\d+)$", r"\1\2", rs)
 
    # a terminal "dev" or "devel" can be changed into ".dev0"
    rs = re.sub(r"[\.\-](dev|devel)$", r".dev0", rs)
 
    # a terminal "dev" can be changed into ".dev0"
    rs = re.sub(r"(?![\.\-])dev$", r".dev0", rs)
 
    # a terminal "final" or "stable" can be removed
    rs = re.sub(r"(final|stable)$", "", rs)
 
    # The 'r' and the '-' tags are post release tags
    #   0.4a1.r10       ->  0.4a1.post10
    #   0.9.33-17222    ->  0.9.3.post17222
    #   0.9.33-r17222   ->  0.9.3.post17222
    rs = re.sub(r"\.?(r|-|-r)\.?(\d+)$", r".post\2", rs)
 
    # Clean 'r' instead of 'dev' usage:
    #   0.9.33+r17222   ->  0.9.3.dev17222
    #   1.0dev123       ->  1.0.dev123
    #   1.0.git123      ->  1.0.dev123
    #   1.0.bzr123      ->  1.0.dev123
    #   0.1a0dev.123    ->  0.1a0.dev123
    # PyPI stats:  ~150 (~4%) better
    rs = re.sub(r"\.?(dev|git|bzr)\.?(\d+)$", r".dev\2", rs)
 
    # Clean '.pre' (normalized from '-pre' above) instead of 'c' usage:
    #   0.2.pre1        ->  0.2c1
    #   0.2-c1         ->  0.2c1
    #   1.0preview123   ->  1.0c123
    # PyPI stats: ~21 (0.62%) better
    rs = re.sub(r"\.?(pre|preview|-c)(\d+)$", r"c\g<2>", rs)
 
    # Tcl/Tk uses "px" for their post release markers
    rs = re.sub(r"p(\d+)$", r".post\1", rs)
 
    #logging.debug("suggest_normalized => %s" % rs)
    try:
        NormalizedVersion(rs)
        return rs   # already rational
    except IrrationalVersionError as e:
        logging.warning("Got IrrationalVersionError: %s" % e)
    return None

#--- end of import 

#print NormalizedVersion('1.0')
#print NormalizedVersion('1.2.1-b1')


def run(cmd, fatal=True, silent=False):
  if not silent:
      logging.debug(cmd)
  ret = os.system(cmd)
  if ret:
    msg = "Execution of '%s' failed with %s return code." % (cmd,ret)
    if fatal:
        sys.exit(msg)
    else:
        logging.error(msg)
  return 0

instances = {}
# we keep here all detected instances, we detect them by looking at services that do match: crowd* jira* confluence* bamboo*

products = {
  'jira': { 
    'paths':['/opt/atlassian/%(instance)s'], 
    'keep': [
    'atlassian-jira/images/icons/priorities/unknown.png',
    'atlassian-jira/includes/decorators/aui-layout/footer.jsp', 
    'atlassian-jira/includes/decorators/aui-layout/head-common.jsp', # patched for new relic
    'atlassian-jira/secure/admin/custom/findattachments.jsp',
    'atlassian-jira/WEB-INF/cgi/*',
    'atlassian-jira/WEB-INF/classes/crowd.properties',
    'atlassian-jira/WEB-INF/classes/jira-application.properties',
    'atlassian-jira/WEB-INF/classes/jpm.xml',
    'atlassian-jira/WEB-INF/classes/log4j.properties',
    'atlassian-jira/WEB-INF/classes/seraph-config.xml',
    'atlassian-jira/WEB-INF/lib/klogger*',
    'bin/setenv.sh',
    'bin/user.sh',
    'conf/catalina.properties',
    'conf/context.xml',
    'conf/logging.properties',
    'conf/server.xml',
    'conf/web.xml',
    'lib/activation*',
    'lib/apache-log4j-extras*',
    'lib/jira-javamelody*',
    'lib/klogger*',
    'lib/mail*',
    'lib/newrelic-api.jar', 
    '.eap',
    '.auto'],
    'filter_description':'TAR.GZ',
    'version': "cat README.txt | grep -m 1 'JIRA ' | sed -e 's,.*JIRA ,,' -e 's,#.*,,'",
    'version_regex': '^JIRA ([\d\.-]+)#.*',
    'log': ['%(path)s/logs/catalina.out', '/var/atlassian/application-data/%(instance)s/log/atlassian-jira.log'],
    'size': 1300+300,
    'min_version':'4.0',
    'user': 'jira',
    },
 'confluence': {
    'paths':['/opt/atlassian/%(instance)s','/opt/%(instance)s'],
    'keep': ['bin/user.sh','confluence/robots.txt','conf/server.xml','conf/web.xml','conf/catalina.properties','conf/logging.properties',
'bin/setenv.sh',
'confluence/WEB-INF/classes/confluence-init.properties',
'confluence/WEB-INF/classes/log4j.properties',
'confluence/WEB-INF/classes/mime.types',
'lib/*melody*.jar','confluence/lib/*melody*.jar','confluence/WEB-INF/lib/sqljdbc4.jar','confluence/WEB-INF/lib/mysql-*.jar','.eap','.auto'],
    'filter_description':'Standalone',
    'version': "cat README.txt | grep -m 1 'Atlassian Confluence' | sed -e 's,.*Atlassian Confluence ,,' -e 's,- .*,,'",
    'log': ['%(path)s/logs/catalina.out', '/var/atlassian/application-data/%(instance)s/logs/atlassian-confluence.log'],
    'size':1000,
    'min_version': '4.0',
    'user': 'confluence',
    }, 
  'crowd': {
    'paths':['/opt/atlassian/%(instance)s','/opt/%(instance)s'],
    'keep': ['build.properties','apache-tomcat/bin/setenv.sh','crowd-webapp/WEB-INF/classes/crowd-init.properties','lib/*melody*.jar','crowd-webapp/WEB-INF/classes/log4j.properties','.eap','bin/user.sh','.auto'],
    'filter_description':'TAR.GZ',
    'version':"ls crowd-webapp/WEB-INF/lib/crowd-core-[0-9]* | sed -e 's,.*crowd-core-,,' -e 's,\.jar,,'",
    'size':500+300, # mininum amount of space needed for downloadin and installing the updgrade
    'min_version':'2.0',
    'log': ['%(path)s/apache-tomcat/logs/catalina.out','/opt/atlassian/%(instance)s/logs/*.log'],
    'user': 'crowd',
    },
  'bamboo': {
    'paths':['/opt/atlassian/%(instance)s'],
    'keep': ['conf/wrapper.conf','atlassian-bamboo/WEB-INF/classes/bamboo-init.properties','bin/setenv.sh','lib/*melody*.jar','.eap','.auto','bin/user.sh'],
    'filter_description':'TAR.GZ',
    'version': "cat atlassian-bamboo/META-INF/maven/com.atlassian.bamboo/atlassian-bamboo-web-app/pom.properties | grep -m 1 'version=' | sed -e 's,.*version=,,' -e 's,-.*,,'",
    'size':200+300, # mininum amount of space needed for downloadin and installing the updgrade
    'min_version':'4.4.5',
    'log': ['%(path)s/logs/bamboo.log'],
    'user': 'bamboo',
    },

}

def is_major(v1s, v2s):
    """
    Returns True if the difference between the two version strings is a major one. A Minor one means that only the 3rd number is different.
    """
    global options

    # if the major switch is enabled, this will return False in order to allow upgrades
    if options.major:
        return False

    v1 = str(v1s).split('.')
    v2 = str(v2s).split('.')
    if v1[0] != v2[0] or v1[1] != v2[1]:
        return True
    return False

def get_cmd_output(cmd):
    stdout_handle = os.popen(cmd)
    text = stdout_handle.read()
    ret = stdout_handle.close()
    if ret is None or ret == 0:
        return text.rstrip()
    return None

parser = OptionParser()
parser.add_option("-y", dest="force", default=False, action="store_true",
                  help="Force updater to do the peform the upgrade.")
parser.add_option("-q", dest="quiet", default=False, action="store_true",help="no output if nothing is wrong, good for cron usage.")
parser.add_option("-m", dest="major", default=False, action="store_true",help="upgrade major versions, should be used with a lot of care")
parser.add_option("-p", dest="product", default='*', help="which product to update, by default is * (all)")

(options, args) = parser.parse_args()

if sys.stdout.isatty():
    loglevel = logging.INFO
else:
    loglevel = logging.WARN

if not options.quiet:
   loglevel = logging.DEBUG
logging.basicConfig(level=loglevel,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%Y-%m-%d %H:%M',
                    )

logging.debug("Detecting installed Atlassian instances...")

TMPDIR=tempfile.gettempdir()
logging.info("Changing current directory to: %s" % TMPDIR)
os.chdir(TMPDIR)


def enable_logging():
    #logging.getLogger().setLevel(logging.DEBUG)
    return


# --- smart auto-update code which is supposed to get latest version from the repo and recall the script if needed
def modification_date(filename):
    t = os.path.getmtime(filename)
    return datetime.datetime.fromtimestamp(t)

n = modification_date(os.path.join(MYDIR, __file__))

cmd = "git -C %s --work-tree=%s pull -q -u" % (MYDIR, MYDIR)
if os.system(cmd):
    logging.error("Critical error, `%s` returned an error code." % cmd)
    #sys.exit(1)

if n != modification_date(os.path.join(MYDIR, __file__)):
     logging.warning("We've being updated, we will run the new version")
     os.execv(".",sys.argv)

# --- end of auto-update


product = None
instances = OrderedDict()


for p in products:
    if options.product == '*' or p == options.product:
        for file in os.listdir('/etc/init.d' ):
            if fnmatch.fnmatch(file, '%s*' % p) and '@' not in file:
                instances[file]={"product":p}
        for file in os.listdir('/lib/systemd/system' ):
            if fnmatch.fnmatch(file, '%s*.service' % p) and '@' not in file:
                instances[file.split('.')[0]]={"product":p}

logging.debug("Detected instances: %s" % instances)

for instance,instance_dic in instances.iteritems():
    product = instance_dic['product']
    logging.debug("Checking %s ..." % instance)
    if os.path.isfile("/etc/init.d/%s" % instance):
        instance_dic['start']='sudo service %s start &' % instance
        instance_dic['stop']='sudo service %s stop' % instance
        instance_dic['started'] = os.system('sudo service %s status >>/dev/null' % instance) == 0
    elif os.path.isfile("/lib/systemd/system/%s.service" % instance):
        instance_dic['start']='sudo systemctl start %s &' % instance
        instance_dic['stop']='sudo systemctl stop %s' % instance
        instance_dic['started'] = os.system('sudo systemctl status %s >>/dev/null' % instance) == 0
    else:
        raise NotImplemented()

    for path in products[product]['paths']:
        path = path % {'instance':instance}
        logging.debug(path)
        if os.path.exists(path):
            instances[instance]['path'] = path
            break
    if 'path' not in instances[instance]:
        print("Unable to find 'path' of %s : %s" % (instance, instances[instance]))
        sys.exit(1)

    for path in products[product]['log']:
        path = path % {'instance':instance, 'path': instance_dic['path']}
        instances[instance]['log'] = []
        if os.path.exists(path):
            instances[instance]['log'].append(path)

    logging.debug("Analysing %s instance from %s" % (instance,instances[instance]['path']))

    if platform.system() == 'Darwin':
        if not os.path.exists(products[product]['path']):
            logging.info("`%s` not found..." % product)
            continue
        instances[instance]['start']=products[product]['path']+'bin/start-%s.sh' % product
        instances[instance]['stop']=products[product]['path']+'bin/stop-%s.sh' % product

    elif not os.path.exists(instance_dic['path']):
        logging.info("`%s` not found..." % product)
        continue
 
    cwd = os.getcwd()
    os.chdir(instances[instance]['path'])
    current_version = get_cmd_output(products[product]['version']).rstrip('-')
    try:
        current_version = NormalizedVersion(current_version)
    except:
        s = suggest_normalized_version(current_version)
        if not s:
            logging.error("unable to suggest_normalized_version(%s)" % current_version)
            raise NotImplemented()
        current_version = NormalizedVersion(s)

    os.chdir(cwd)
    if not current_version:
        logging.error('Unable to detect the current version of %s' % product)
        continue

    eap = os.path.isfile(os.path.join(instances[instance]['path'],'.eap'))
    auto = os.path.isfile(os.path.join(instances[instance]['path'],'.auto'))
    logging.info('%s has eap=%s auto_upgrade=%s' % (instance, eap, auto))

    feeds = ['current']
    #feeds = ['archived', 'current']
    if eap:
        feeds = ['current','eap', 'archived']

    version = None
    url = None
    for feed in feeds:
        if product == 'jira':
            brand = 'jira-software'
        else:
            brand = product

        # https://my.atlassian.com/download/feeds/archived/confluence.json

        json_url = "https://my.atlassian.com/download/feeds/%s/%s.json" % (feed, brand)
        fp = codecs.getreader("latin-1")(urllib2.urlopen(json_url))
        s = fp.read()[10:-1]  # "downloads(...)" is not valid json !!! who was the programmer that coded this?
        data = json.loads(s)

        with open('%s/%s.%s.json' % (tempfile.gettempdir(),feed,product),'w') as outfile:
            json.dump(data, outfile, sort_keys = True, indent = 4, ensure_ascii=False)

        release_notes = ''
        try:
            for d in data:
            
                url = d['zipUrl']
                #print(url)
                release_notes = d['releaseNotes']

                xx = ''
#                    products[product]['filter_description'] in d['description'] and \

                if 'Unix' in d['platform'] and \
                    'Cluster' not in d['description'] and \
                    '-OD' not in d['version'] and \
                     d['zipUrl'] and \
                     d['zipUrl'].endswith('tar.gz'):
                    #logging.debug(d)

                    try:
                        xx = suggest_normalized_version(d['version'])
                        if not xx:
                            raise NotImplementedError("Unable to normalize %s" % d['version'])
                    except Exception as e:
                        logging.error(e)
                        continue
                else:
                    continue

                #logging.debug(xx)

                if not xx: continue

                if not version:
                    version = NormalizedVersion(xx)
                else:
                    new_version = NormalizedVersion(xx)
                    #logging.debug("Found %s" % new_version)
                    #logging.debug("%s %s %s", d['version'], xx, new_version)
                    if version < new_version and not is_major(version, new_version):
                        logging.debug("Found a newer version %s in '%s' feed, picking it instead of %s." % (new_version,feed,version))
                        version = new_version
                        url = d['zipUrl']
                        release_notes = d['releaseNotes']
                #break

                logging.debug("%s: Compare version %s with %s" % (instance, version, current_version))
                if version <= current_version:
                    logging.info("Update found %s version %s and latest release is %s, we'll do nothing." % (product, current_version, version))
                    continue
                else:
                    break

        except Exception as e:
            if type(e) == IrrationalVersionError:
               logging.error(e)
               continue
            else:
               raise e


    if not url or not release_notes:
        logging.error("WTH... %s %s" %  (url, release_notes))
        continue

    if not url.endswith('.tar.gz'):
        #logging.error('Unknown format for %s' % url)
        continue

    if version <= current_version:
        logging.debug("Compared %s with %s ..." % (version, current_version))
        continue

    #if current_version < LooseVersion(products[product]['min_version']):
    #  logging.error('The version of %s found (%s) is too old for automatic upgrade.' % (product,current_version))
    #  continue
    logging.info("%s: Local version of %s is %s and we found version %s (eap=%s). Release notes: %s" % (instance, product, current_version, version, eap, release_notes))
    archive = url.split('/')[-1]
    dirname = re.sub('\.tar\.gz','',archive)
    if product == 'jira': dirname += '-standalone'
    
    wrkdir = os.path.normpath(os.path.join(instance_dic['path'],'..'))
    freespace = get_free_space_mb(wrkdir)
    if freespace < products[product]['size']:
        logging.error("Freespace on %s is %s MB but we need at least %s MB free. Fix the problem and try again." % (wrkdir,freespace,products[product]['size']))
        sys.exit(2)
    
    # sed -u  - not avilable under OS X
    x = run('cd %s && wget -q --timestamp --continue %s 2>&1' % (wrkdir,url), silent=True)
    #print(x)
    run('cd %s && tar -xzf %s' % (wrkdir,archive))
    
    old_dir = "%s-%s-old" % (instance,current_version)
    if os.path.isdir(old_dir) or os.path.isfile(old_dir + '.tar.gz'):
        logging.error("Execution halted because we already found existing old file/dir (%s or %s.tar.gz). This would usually indicate an incomplete upgrade." % (old_dir,old_dir)) 
        sys.exit(1)

    if not auto:
      # for eap we upgrade without needing -y parameter
      if not options.force:
        logging.info("Skipping next steps because you did not call script with -y parameter, nor we were able to detect the '.auto' file in installation home directory.")
        continue

    reason = "Upgrade of %s instance initiated. Check %s" % (instance, release_notes)
    run('service %s stop "%s" || echo ignoring stop failure because it could also be already stopped' % (instance, reason))
    run('mv %s %s' % (instance_dic['path'],old_dir))
    run('mv %s/%s %s' % (wrkdir,dirname,instance_dic['path']))
    run('useradd -m %s || echo ""' % (products[product]['user']))
    run('chown -R %s:%s %s || echo "failed chown"' % (products[product]['user'],products[product]['user'],instance_dic['path']))
    
    for f in products[product]['keep']:
        if os.path.exists(os.path.join(old_dir,f)):
            run('mkdir -p "%s"' % os.path.dirname(os.path.join(instance_dic['path'],f)))
            run('cp -af --preserve=links %s/%s %s/%s' % (old_dir,f,instance_dic['path'],f))

    if instance_dic['started']:
        time.sleep(5)
        run(instance_dic['start'])
    else:
        logging.info("Upgrade made bug instance was not started because it was not started before the upgrade.")

    #run('pwd && rm %s' % os.path.join(wrkdir,archive))

    # archive old version and keep only the archive
    run("pwd && tar cfz %s%s.tar.gz %s && rm -R %s" % (ARCHIVE_DIR,old_dir,old_dir,old_dir))

    if os.isatty(sys.stdout.fileno()) and 'log' in instance_dic:
       logging.info("Starting tail of the logs in order to allow you to see if something went wrong. Press Ctrl-C once to stop it.")
       cmd = "tail "
       for elem in instance_dic['log']:
           cmd += " -F %s" % elem
       logging.debug(cmd)
       run(cmd)

    break # if we did one upgrade we'll stop here, we don't want to upgrade several products in a single execution :D

if not product:
   logging.error('No product to be upgraded was found!')
else:
   logging.debug("Done")
