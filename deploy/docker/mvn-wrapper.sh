#!/bin/sh
set -eu

POM="${PWD}/pom.xml"
REQUESTED_JDK="${APAAS_BACKEND_JDK_VERSION:-17}"
case "$REQUESTED_JDK" in
  8|1.8|jdk8|java8)
    export JAVA_HOME=/opt/jdk8
    ;;
  17|jdk17|java17)
    export JAVA_HOME=/opt/jdk17
    ;;
  auto)
    if [ -f "$POM" ]; then
      if grep -Eq '<(java.version|maven.compiler.source|maven.compiler.target|source|target)>[[:space:]]*(1\.8|8)[[:space:]]*</' "$POM"; then
        export JAVA_HOME=/opt/jdk8
      elif grep -Eq '<(java.version|maven.compiler.source|maven.compiler.target|source|target)>[[:space:]]*17[[:space:]]*</' "$POM"; then
        export JAVA_HOME=/opt/jdk17
      fi
    fi
    ;;
  *)
    export JAVA_HOME=/opt/jdk17
    ;;
esac

export PATH="$JAVA_HOME/bin:$PATH"
exec /opt/maven/bin/mvn "$@"
