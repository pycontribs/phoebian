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
from distutils.version import StrictVersion
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
  'confluence': { 
    'path':'/opt/Confluence', 
    'keep': ['conf/server.xml','conf/web.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','confluence/WEB-INF/classes/confluence-init.properties'], 
    'filter_description':'Standalone',
    'version': "cat README.txt | grep -m 1 'Atlassian Confluence' | sed -e 's,.*Atlassian Confluence ,,' -e 's,-.*,,'",
    'log':'',
    'size':1000,
    },
  'jira': { 
    'path':'/opt/jira', 
    'keep': ['conf/server.xml','conf/web.xml','conf/context.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','atlassian-jira/WEB-INF/classes/jira-application.properties'],
    'filter_description':'TAR.GZ',
    'version': "cat README.txt | grep -m 1 'JIRA ' | sed -e 's,.*JIRA ,,' -e 's,-.*,,'",
    'version_regex': '^JIRA ([\d\.]+)-.*',
    'log': '/opt/jira/logs/catalina.out',
    'size': 1300+300,
    },
  'crowd': {
    'path':'/opt/crowd',
    'keep': ['build.properties'],
    'filter_description':'TAR.GZ',
    'version':"ls crowd-webapp/WEB-INF/lib/crowd-core-* | sed -e 's,.*crowd-core-,,' -e 's,\.jar,,'",
    'size':500+300 # mininum amount of space needed for downloadin and insalling the updgrade
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
parser.add_option("-q", dest="quiet", default=False, action="store_true",help="no output if nothing is wrong, good for cron usage.")
(options, args) = parser.parse_args()

loglevel = logging.WARNING
if not options.quiet:
   loglevel = logging.DEBUG
logging.basicConfig(level=loglevel,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%Y-%m-%d %H:%M',
                    )

product = None
for product in products:
    if not os.path.isfile('/etc/init.d/%s' % product) or not os.path.exists(products[product]['path']):
        logging.info("`%s` not found..." % product)
        break

    if not os.path.exists(products[product]['path']):
      logging.debug('Unable to find %s installation' % product)
      break

    cwd = os.getcwd()
    os.chdir(products[product]['path'])
    current_version = get_cmd_output(products[product]['version'])
    os.chdir(cwd)
    if not current_version:
        logging.error('Unable to detect the current version of %s' % product)
        sys.exit(1)
    
    url = "https://my.atlassian.com/download/feeds/current/%s.json" % product
    fp = codecs.getreader("latin-1")(urllib2.urlopen(url))
    s = fp.read()[10:-1]  # "downloads(...)" is not valid json !!! who was the programmer that coded this?
    data = json.loads(s)
    
    for d in data:
      #print d
      if 'Unix' in d['platform'] and 'Cluster' not in d['description'] and products[product]['filter_description'] in d['description']:
        url = d['zipUrl']
        version = d['version']
        break
    
    if StrictVersion(version) <= StrictVersion(current_version):
      logging.info("Update found %s version %s and latest release is %s, we'll do nothing." % (product, current_version, version))
      continue
    
    logging.debug("Local version of %s is %s and we found version %s at %s" % (current_version, product, version, url))
    archive = url.split('/')[-1]
    dirname = re.sub('\.tar\.gz','',archive)
    if product == 'jira': dirname += '-standalone'
    
    freespace = get_free_space_mb('/')
    if freespace < products[product]['size']:
        logging.error("Freespace on / %s MB but we need at least %s MB free. Fix the problem and try again." % (freespace,products[product]['size']))
        sys.exit(2)
        
    run('cd /tmp && wget --timestmap --continue --progress=dot %s 2>&1 | grep --line-buffered "%%" | sed -u -e "s,\\.,,g" | awk \'{printf("\\b\\b\\b\\b%%4s", $2)}\' && printf "\\r"' % url)
    run('cd /tmp && tar -xzf %s' % archive)
    
    old_dir = "%s-%s-old" % (products[product]['path'],current_version)
    if os.path.isdir(old_dir) or os.path.isfile(old_dir + '.tar.gz'):
        logging.error("Execution halted because we already found existing old file/dir (%s or %s.tar.gz). This would usually indicate an incomplete upgrade." % (old_dir,old_dir)) 
        sys.exit(1)

    if not options.force:
      logging.info("Stopping here because you did not call script with -y parameter.")
      sys.exit()

    
    run('service %s stop' % product)
    run('mv %s %s' % (products[product]['path'],old_dir))
    run('mv /tmp/%s %s' % (dirname,products[product]['path']))
    
    for f in products[product]['keep']:
       run('cp -af %s/%s %s/%s' % (old_dir,f,products[product]['path'],f))
    
    run('service %s start' % product)

    if os.isatty(sys.stdout.fileno()):
      logging.info("Starting tail of the logs in order to allow you to see if something went wrong. Press Ctrl-C once to stop it.")
      run("sh -c 'tail -n +0 --pid=$$ -f %s | { sed \"/org.apache.catalina.startup.Catalina start/ q\" && kill $$ ;}'" % products[product]['log'])

    run('rm %s' % archive)
    break # if we did one upgrade we'll stop here, we don't want to upgrade several products in a single execution :D

    # TODO: use versioned .old directory to allow multiple updates
    run("tar cfz %s.tar.gz %s && rm -R %s" % (old_dir,old_dir,old_dir))
    # TODO: archive old version in order to preserve disk space

if not product:
   logging.error('No product to be upgraded was found!')
else:
   logging.info("Done")
