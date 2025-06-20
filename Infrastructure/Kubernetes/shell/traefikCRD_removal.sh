#!/bin/bash

# Get a list of CRDs containing "traefik"
crds=$(kubectl get crds | grep traefik | awk '{print $1}')

# Check if any CRDs were found
if [ -z "$crds" ]; then
    echo "No Traefik CRDs found."
    exit 0
fi

# Prompt for confirmation before deleting
read -p "Are you sure you want to delete the following CRDs? (y/n): $crds\n" confirm

if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
    # Delete the CRDs
    for crd in $crds; do
        echo "Deleting CRD: $crd"
        kubectl delete crd "$crd"
    done
    echo "Deletion complete."
else
    echo "Deletion cancelled."
fi
