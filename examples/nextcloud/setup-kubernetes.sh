#!/bin/bash

if [ $(id -u) -ne 0 ] ; then
	echo "❌ Run me as root"
	exit 1
fi

helm repo add nextcloud https://nextcloud.github.io/helm/
helm install -f nextcloud-chart-values.yml nextcloud nextcloud/nextcloud