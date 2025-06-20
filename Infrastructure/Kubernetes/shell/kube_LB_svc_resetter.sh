#!/bin/bash

kubectl get svc --all-namespaces -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type" | grep LoadBalancer | while read ns name type; do
  echo "Patching service $ns/$name"
  kubectl patch svc $name -n $ns -p '{"metadata":{"annotations":{"metallb.universe.tf/ip-allocated-from-pool": null}}}'
done
