################################################################################
# Makefile for Electroluminescent Door Sign
# Author: Rich Rademacher, UWaterloo/IQC
#
# Purpose: This file is a set of Make macros to build the AVR program for
# 		this board
#
# Requires:  WinAVR compiler for ATTiny13A, Gnu Make for Windows/Linux
################################################################################

# 
# Tools
#
SHELL=${COMSPEC}	# sometimes needed to use DOS backslashes
#AVR_PATH="c:/WinAVR-20100110/"
AVR_PATH="c:/Program Files (x86)/Arduino/hardware/tools/avr"
CC=${AVR_PATH}"/bin/avr-gcc.exe"
AVRDUDE=${AVR_PATH}"/bin/avrdude.exe"
REMOVE="rm"
OBJCOPY=${AVR_PATH}"/bin/avr-objcopy.exe"

# 
# Target name
#
TARGET_BASE=el_doorsign
TARGET_ELF=${TARGET_BASE}.elf
TARGET_HEX=${TARGET_BASE}.hex
TARGET_EEP=${TARGET_BASE}.eep
FORMAT=ihex

#
# processor defaults
#
MCU=attiny13a
DUDE_PROC=t13
F_CPU=1152000

#
# Flag options
#
INCLUDE_DIR=${AVR_PATH}/avr/include
CFLAGS= -Wall -Wstrict-prototypes -mmcu=${MCU} -I. -DF_CPU="${F_CPU}" -O1
DUDECONF=${AVR_PATH}/etc/avrdude.conf
DUDEFLAGS= -C ${DUDECONF} -c usbtiny -p ${DUDE_PROC}

#
# default target
#
all: ${TARGET}

# 
# programmer
#
program: ${TARGET_HEX} 
	${AVRDUDE} ${DUDEFLAGS} -U flash:w:${TARGET_HEX} 

#
# Generic Target for *.c to *.s (assembly)
#
%.s:%.c
	${CC} ${CFLAGS} -S $< -o $@

#
# Generic Target for *.s to *.o (objects_
#
%.o:%.s
	${CC} ${CFLAGS} -c $< -o $@

#
# Generic Target for *.o to *.elf (link)
#
%.elf:%.o
	${CC} ${CFLAGS} $< -o $@

#
# generate hex from ELF file
#
%.hex: %.elf
	${OBJCOPY} -O ${FORMAT} -R .eeprom -R .fuse -R .lock $< $@

#
# generate EEPOM file from ELF 
#
%.eep: %.elf
	${OBJCOPY} -j .eeprom --set-section-flags=.eeprom"alloc,load" \
		--change-section-lma .eeprom=0 --no-change-warnings -O ${FORMAT} $< $@
#
# disable built-in rules
#
.SUFFIXES:
MAKEFLAGS += --no-builtin-rules

.SECONDARY: 

#
# remove all intermediate files
#
clean:
	-${REMOVE} *.s
	-${REMOVE} *.o
	-${REMOVE} ${TARGET_ELF}
	-${REMOVE} ${TARGET_HEX}


