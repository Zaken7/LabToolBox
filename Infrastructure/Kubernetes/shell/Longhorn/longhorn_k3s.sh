#!/bin/bash

echo -e " \033[33;2m    __  _          _        ___                            \033[0m"
echo -e " \033[33;2m    \ \(_)_ __ ___( )__    / _ \__ _ _ __ __ _  __ _  ___  \033[0m"
echo -e " \033[33;2m     \ \ | '_ \` _ \/ __|  / /_\/ _\` | '__/ _\` |/ _\` |/ _ \ \033[0m"
echo -e " \033[33;2m  /\_/ / | | | | | \__ \ / /_\\  (_| | | | (_| | (_| |  __/ \033[0m"
echo -e " \033[33;2m  \___/|_|_| |_| |_|___/ \____/\__,_|_|  \__,_|\__, |\___| \033[0m"
echo -e " \033[33;2m                                               |___/       \033[0m"
echo -e " \033[35;2m          __                   _                          \033[0m"
echo -e " \033[35;2m         / /  ___  _ __   __ _| |__   ___  _ __ _ __      \033[0m"
echo -e " \033[35;2m        / /  / _ \| '_ \ / _\` | '_ \ / _ \| '__| '_ \     \033[0m"
echo -e " \033[35;2m       / /__| (_) | | | | (_| | | | | (_) | |  | | | |    \033[0m"
echo -e " \033[35;2m       \____/\___/|_| |_|\__, |_| |_|\___/|_|  |_| |_|    \033[0m"
echo -e " \033[35;2m                         |___/                            \033[0m"
echo -e " \033[36;2m                                                          \033[0m"
echo -e " \033[32;2m             https://youtube.com/@jims-garage              \033[0m"
echo -e " \033[32;2m                                                           \033[0m"

#############################################
# YOU SHOULD ONLY NEED TO EDIT THIS SECTION #
#############################################
# Set the IP addresses of master1
master1=192.168.145.202

# Set the IP addresses of your Longhorn nodes
longhorn1=192.168.145.113
longhorn2=192.168.145.111
longhorn3=192.168.145.112
longhorn4=192.168.145.114

# User of remote machines
user=ubuntu

# Interface used on remotes
interface=eth0

# Set the virtual IP address (VIP)
vip=192.168.145.215

# Array of longhorn nodes
storage=($longhorn1 $longhorn2 $longhorn3 $longhorn4)

#ssh certificate name variable
certName=kube
key=kube.pub
#############################################
#            DO NOT EDIT BELOW              #
#############################################
# For testing purposes - in case time is wrong due to VM snapshots
sudo timedatectl set-ntp off
sudo timedatectl set-ntp on

# add ssh keys for all nodes
cd /home/$user/.ssh
for node in "${storage[@]}"; do
    ssh-copy-id -i $key $user@$node
    if [ $? -ne 0 ]; then
        exit 1
    fi
done

# add open-iscsi - needed for Debian and non-cloud Ubuntu
if ! command -v sudo service open-iscsi status &>/dev/null; then
    echo -e " \033[31;5mOpen-ISCSI not found, installing\033[0m"
    sudo apt install open-iscsi
else
    echo -e " \033[32;5mOpen-ISCSI already installed\033[0m"
fi

# Step 1: Add new longhorn nodes to cluster (note: label added)
for newnode in "${storage[@]}"; do
    k3sup join \
        --ip $newnode \
        --user $user \
        --sudo \
        --k3s-channel stable \
        --server-ip $master1 \
        --k3s-extra-args "--node-label \"longhorn=true\"" \
        --ssh-key $HOME/.ssh/$certName
    echo -e " \033[32;5mAgent node joined successfully!\033[0m"
done

# Step 2: Install Longhorn (using modified Official to pin to Longhorn Nodes)
kubectl apply -f $HOME/longhorn/longhorn.yaml
kubectl get pods \
    --namespace longhorn-system \
    --watch

# Step 3: Print out confirmation

kubectl get nodes
kubectl get svc -n longhorn-system

echo -e " \033[32;5mHappy Kubing! Access Longhorn through Rancher UI\033[0m"
