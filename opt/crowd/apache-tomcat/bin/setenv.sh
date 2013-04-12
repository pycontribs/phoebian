JAVA_OPTS="-Xms128m -Xmx512m -XX:MaxPermSize=256m -Dfile.encoding=UTF-8 $JAVA_OPTS"
CATALINA_OPTS="-Dcom.sun.management.jmxremote -Dcom.sun.management.jmxremote.port=8096 -Dcom.sun.management.jmxremote.local.only=false -Dcom.sun.management.jmxremote.authenticate=false -Dcom.sun.management.jmxremote.ssl=false"

export JAVA_OPTS
export CATALINA_OPTS
