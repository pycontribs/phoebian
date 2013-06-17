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
import urllib2
import json
import os
import platform
import re
import sys
import logging
from distutils.version import LooseVersion
from optparse import OptionParser

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

#print NormalizedVersion('1.0')
#print NormalizedVersion('1.2.1-b1')


def run(cmd, fatal=True):
  logging.debug(cmd)
  ret = os.system(cmd)
  if ret:
    msg = "Execution of '%s' failed with %s return code." % (cmd,ret)
    if fatal:
        sys.exit(msg)
    else:
        logging.error(msg)
  return 0

products = {
  'jira': { 
    'path':'/opt/jira', 
    'keep': ['conf/server.xml','conf/web.xml','conf/context.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','atlassian-jira/WEB-INF/classes/jira-application.properties'],
    'filter_description':'TAR.GZ',
    'version': "cat README.txt | grep -m 1 'JIRA ' | sed -e 's,.*JIRA ,,' -e 's,#.*,,'",
    'version_regex': '^JIRA ([\d\.-]+)#.*',
    'log': '/opt/jira/logs/catalina.out',
    'size': 1300+300,
    'min_version':'4.0',
    },
 'confluence': {
    'path':'/opt/Confluence',
    'keep': ['conf/server.xml','conf/web.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','confluence/WEB-INF/classes/confluence-init.properties','confluence/WEB-INF/classes/mime.types'],
    'filter_description':'Standalone',
    'version': "cat README.txt | grep -m 1 'Atlassian Confluence' | sed -e 's,.*Atlassian Confluence ,,' -e 's,-.*,,'",
    'log':'',
    'size':1000,
    'min_version': '4.0'
    }, 
  'crowd': {
    'path':'/opt/crowd',
    'keep': ['build.properties','apache-tomcat/bin/setenv.sh','crowd-webapp/WEB-INF/classes/crowd-init.properties'],
    'filter_description':'TAR.GZ',
    'version':"ls crowd-webapp/WEB-INF/lib/crowd-core-* | sed -e 's,.*crowd-core-,,' -e 's,\.jar,,'",
    'size':500+300, # mininum amount of space needed for downloadin and insalling the updgrade
    'min_version':'2.0',
    'log': '/opt/crowd/apache-tomcat/logs/catalina.out',
    },
}


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
parser.add_option("--eap", dest="feed", default='current', action="store_const", const="eap",
                  help="Use EAP (beta) feeds instead of releases.")
parser.add_option("-q", dest="quiet", default=False, action="store_true",help="no output if nothing is wrong, good for cron usage.")
(options, args) = parser.parse_args()

loglevel = logging.WARNING
if not options.quiet:
   loglevel = logging.DEBUG
logging.basicConfig(level=loglevel,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%Y-%m-%d %H:%M',
                    )

def enable_logging():
    logging.getLogger().setLevel(logging.DEBUG)

product = None
for product in products:
    if not os.path.isfile('/etc/init.d/%s' % product) or not os.path.exists(products[product]['path']):
        logging.info("`%s` not found..." % product)
        continue

    cwd = os.getcwd()
    os.chdir(products[product]['path'])
    current_version = get_cmd_output(products[product]['version']).rstrip('-')
    os.chdir(cwd)
    if not current_version:
        logging.error('Unable to detect the current version of %s' % product)
        sys.exit(1)
    
    url = "https://my.atlassian.com/download/feeds/%s/%s.json" % (options.feed,product)
    fp = codecs.getreader("latin-1")(urllib2.urlopen(url))
    s = fp.read()[10:-1]  # "downloads(...)" is not valid json !!! who was the programmer that coded this?
    data = json.loads(s)
    
    for d in data:
      if 'Unix' in d['platform'] and 'Cluster' not in d['description'] and products[product]['filter_description'] in d['description']:
        url = d['zipUrl']
        version = d['version']
        break

    #print "json:", version
    #print "disk:", current_version

    if NormalizedVersion(version) <= NormalizedVersion(current_version):
      logging.info("Update found %s version %s and latest release is %s, we'll do nothing." % (product, current_version, version))
      continue
    else:
      enable_logging()
    
    if LooseVersion(current_version) < LooseVersion(products[product]['min_version']):
      logging.error('The version of %s found (%s) is too old for automatic upgrade.' % (product,current_version))
      continue
    
    logging.debug("Local version of %s is %s and we found version %s at %s" % (product, current_version, version, url))
    archive = url.split('/')[-1]
    dirname = re.sub('\.tar\.gz','',archive)
    if product == 'jira': dirname += '-standalone'
    
    wrkdir = os.path.normpath(os.path.join(products[product]['path'],".."))
    freespace = get_free_space_mb(wrkdir)
    if freespace < products[product]['size']:
        logging.error("Freespace on % is %s MB but we need at least %s MB free. Fix the problem and try again." % (wrkdir,freespace,products[product]['size']))
        sys.exit(2)
    
    run('cd %s && wget --timestamp --continue --progress=dot %s 2>&1 | grep --line-buffered "%%" | sed -u -e "s,\\.,,g" | awk \'{printf("\\b\\b\\b\\b%%4s", $2)}\' && printf "\\r"' % (wrkdir,url))
    run('cd %s && tar -xzf %s' % (wrkdir,archive))
    
    old_dir = "%s-%s-old" % (products[product]['path'],current_version)
    if os.path.isdir(old_dir) or os.path.isfile(old_dir + '.tar.gz'):
        logging.error("Execution halted because we already found existing old file/dir (%s or %s.tar.gz). This would usually indicate an incomplete upgrade." % (old_dir,old_dir)) 
        sys.exit(1)

    if not options.force:
      logging.info("Stopping here because you did not call script with -y parameter.")
      sys.exit()

    
    run('service %s stop' % product)
    run('mv %s %s' % (products[product]['path'],old_dir))
    run('mv %s/%s %s' % (wrkdir,dirname,products[product]['path']))
    
    for f in products[product]['keep']:
       run('cp -af %s/%s %s/%s' % (old_dir,f,products[product]['path'],f))
    
    run('service %s start' % product)

    if os.isatty(sys.stdout.fileno()):
       logging.info("Starting tail of the logs in order to allow you to see if something went wrong. Press Ctrl-C once to stop it.")
       # run("sh -c 'tail -n +0 --pid=$$ -f %s | { sed \"/org\.apache\.catalina\.startup\.Catalina start/ q\" && kill $$ ;}'" % products[product]['log'])
       cmd = "tail -f %s | tee /proc/$$/fd/0 | grep 'org.apache.catalina.startup.Catalina start' | read -t 1200 dummy_var" % products[product]['log']
       run(cmd)

    run('rm %s' % archive)
    break # if we did one upgrade we'll stop here, we don't want to upgrade several products in a single execution :D

    # TODO: use versioned .old directory to allow multiple updates
    run("tar cfz %s.tar.gz %s && rm -R %s" % (old_dir,old_dir,old_dir))
    # TODO: archive old version in order to preserve disk space

if not product:
   logging.error('No product to be upgraded was found!')
else:
   logging.info("Done")
