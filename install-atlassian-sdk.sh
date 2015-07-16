#!/bin/bash
# Author: Sorin Sbarnea
# Version: 1.0
# Description: KISS installer for Atlassian SDK

if [ -f /etc/debian_version ]; then
  sudo sh -c 'echo "deb https://sdkrepo.atlassian.com/debian/ stable contrib" >/etc/apt/sources.list.d/atlassian.list'
  sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys B07804338C015B73
  sudo apt-get update -qq
  sudo apt-get install apt-transport-https
  sudo apt-get install -y atlassian-plugin-sdk
  sudo apt-get upgrade -y atlassian-plugin-sdk
elif [ -f /etc/redhat-release ]; then
  sudo wget http://sdkrepo.atlassian.com/atlassian-sdk-stable.repo -O /etc/yum.repos.d/atlassian-sdk-stable.repo
  sudo yum clean all
  sudo yum updateinfo metadata
  sudo yum install atlassian-plugin-sdk
elif [[ "$OSTYPE" == "darwin"* ]]; then
  which brew || ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
  brew tap atlassian/tap
  brew install atlassian/tap/atlassian-plugin-sdk 
fi
