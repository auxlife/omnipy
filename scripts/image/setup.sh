#!/usr/bin/env bash
sudo touch /boot/ssh

echo "pi:x:11669:11669::/home/pi:/bin/bash" >>/etc/passwd
echo "pi:x:11669" >>/etc/group
echo "pi ALL=(ALL) NOPASSWD: ALL" >>/etc/sudoers
echo "pi:omnipy" | chpasswd
mkdir /home/pi/

echo "omnipy" > /etc/hostname


sudo apt update
sudo apt install -y screen git python3 python3-pip vim jq bluez-tools libglib2.0-dev


dpkg-reconfigure tzdata

cd /home/pi/
git clone https://github.com/auxlife/omnipy.git

git clone https://github.com/winemug/bluepy.git

sudo cp /home/pi/omnipy/scripts/image/rc.local /etc/

sudo pip3 install simplejson Flask cryptography requests

cd /home/pi/bluepy
python3 ./setup.py build
sudo python3 ./setup.py install

sudo chown -R pi.pi /home/pi

sudo setcap 'cap_net_raw,cap_net_admin+eip' `which hciconfig`
sudo setcap 'cap_net_raw,cap_net_admin+eip' `which hcitool`
sudo setcap 'cap_net_raw,cap_net_admin+eip' `which btmgmt`
sudo setcap 'cap_net_raw,cap_net_admin+eip' `which bt-agent`
sudo setcap 'cap_net_raw,cap_net_admin+eip' `which bt-network`
sudo setcap 'cap_net_raw,cap_net_admin+eip' `which bt-device`
sudo find /usr/local -name bluepy-helper -exec setcap 'cap_net_raw,cap_net_admin+eip' {} \;
sudo find /home/pi -name bluepy-helper -exec setcap 'cap_net_raw,cap_net_admin+eip' {} \;

sudo apt autoremove



mkdir -p /home/pi/omnipy/data
rm /home/pi/omnipy/data/key
cp /home/pi/omnipy/scripts/recovery.key /home/pi/omnipy/data/key

sudo cp /home/pi/omnipy/scripts/omnipy.service /etc/systemd/system/
sudo cp /home/pi/omnipy/scripts/omnipy-beacon.service /etc/systemd/system/
sudo cp /home/pi/omnipy/scripts/omnipy-pan.service /etc/systemd/system/
sudo chown -R pi:pi /home/pi/*
sudo systemctl enable omnipy.service
sudo systemctl enable omnipy-beacon.service
sudo systemctl enable omnipy-pan.service
sudo systemctl start omnipy.service
sudo systemctl start omnipy-beacon.service
sudo systemctl start omnipy-pan.service


sudo touch /boot/omnipy-btreset
