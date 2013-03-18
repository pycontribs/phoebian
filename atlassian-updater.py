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

def run(cmd):
  print cmd
  ret = os.system(cmd)
  if ret:
    sys.exit("Execution of '%s' failed with %s return code." % (cmd,ret))

products = {
  'confluence': { 
    'path':'/opt/Confluence', 
    'keep': ['conf/server.xml','conf/web.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','confluence/WEB-INF/classes/confluence-init.properties'], 
    'filter_description':'Standalone',
    'size':1300+300}, # mininum amount of space needed for downloadin and insalling the updgrade
  'jira': { 
    'path':'/opt/jira', 
    'keep': ['conf/server.xml','conf/web.xml','conf/context.xml','conf/catalina.properties','conf/logging.properties','bin/setenv.sh','atlassian-jira/WEB-INF/classes/jira-application.properties'],
    'filter_description':'TAR.GZ',
    'size':1300+300 # mininum amount of space needed for downloadin and insalling the updgrade
    },

}

#for product in products:
#  if os.file.exists('/etc/init.d/%s' % product)
product = 'jira'

old = "%s.old" % products[product]['path']
if os.path.exists(old):
    logging.error("'%s' folder found, cannot upgrade if the backup directory already exists." % old)
    sys.exit(1)

if not os.path.exists(products[product]['path']):
  sys.exit('Unable to find %s installation' % product)
url = "https://my.atlassian.com/download/feeds/current/%s.json" % product
fp = codecs.getreader("latin-1")(urllib2.urlopen(url))
s = fp.read()[10:-1]  # "downloads(...)" is not valid json !!! who was the programmer that coded this?
data = json.loads(s)

freespace = get_free_space_mb('/')
if freespace < products[product]['size']:
    logging.error("Freespace on / %s MB but we need at least %s MB free. Fix the problem and try again." % (freespace,products[product]['size']))

for d in data:
  #print d
  if 'Unix' in d['platform'] and 'Cluster' not in d['description'] and products[product]['filter_description'] in d['description']:
    url = d['zipUrl']
    version = d['version']
    break
print version, url
archive = url.split('/')[-1]
dirname = re.sub('\.tar\.gz','',archive)
if product == 'jira': dirname += '-standalone'
run('cd /tmp && wget --progress=bar:force --timestamp %s' % url)
run('cd /tmp && tar -xzf %s' % archive)
#sys.exit(1)
run('service %s stop' % product)
run('mv %s %s.old' % (products[product]['path'],products[product]['path']))
run('mv /tmp/%s %s' % (dirname,products[product]['path']))

#WEB-INF/classes/log4j.properties
#WEB-INF/classes/logging.properties
for f in products[product]['keep']:
   run('cp -af %s.old/%s %s/%s' % (products[product]['path'],f,products[product]['path'],f))

run('service %s start' % product)

print "Done"
