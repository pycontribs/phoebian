Phoebian could be also called the missing link when it comes to managing JIRA and Confluence instances. 

It includes:

Linux service scripts
---------------------
Service scripts that do try to restart the services nicely and forcing them if they fail, that are also cleaning up temporary directories and rotating the logs.

If you want to keep on the bleeding edge (EAP releases), just create a file named .eap in the installation directory. The upgrade script will know that this instance is supposed to be a bleeding edge one and it will upgrade to pre-releases when they are available.

Updater
-------
atlassian-updater.py is a script that detects what products you have installed, which version they are, downloads new releases or EAP versions if desired and performs upgrades.

This script can also be used even if you have multiple instances of the same product as long you are using a meaningful way to identify them.


The scripts tries to detect the installation location, and we recommend you to use the default installation directories:

Installation directories
/opt/atlassian/jira
/opt/atlassian/jira-other-instance
/opt/atlassian/crowd
/opt/atlassian/confluence
/opt/atlassian/bamboo

Home directories
/var/atlassian/application-data/jira
/var/atlassian/application-data/confluence
/var/atlassian/application-data/crowd
/var/atlassian/application-data/bamboo

For each instance it does require a service script in /etc/init.d/{instance}

The script is able to run with MULTIPLE instances, just use a pattern as "jira-xxx" and it will work. Obviously the same instance name must exist in all 3 location: /init.d, /opt and /var.

PORTS : trying to use the default ones, as long they do not overlap.

8080 - jira 
8081 - jira JMX/RMI
9005 - jira tomcat shutdown

8090 - confluence
8091 - confluence JMX/RMI
8000 - confluence tomcat shutdown

8095 - crowd
8096 - crowd JMX/RMI
8020 - crowd tomcat shutdown



Maturity
========

This scrip is used in production, with at least 8 hosting servers since 2013. It is not perfect but makes administration tasks much easier and faster, minimising the downtimes.

