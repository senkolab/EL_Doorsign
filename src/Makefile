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
AVR_PATH="c:/WinAVR-20100110/"
CC=${AVR_PATH}"/bin/avr-gcc.exe"
REMOVE="rm"


# 
# Target name
#
TARGET=el_doorsign.elf

#
# processor defaults
#
MCU=attiny13a
F_CPU=8000000

#
# Flag options
#
INCLUDE_DIR=${AVR_PATH}/avr/include
CFLAGS= -Wall -Wstrict-prototypes -mmcu=${MCU} -I. -DF_CPU="${F_CPU}" -O1


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
# disable built-in rules
#
.SUFFIXES:
MAKEFLAGS += --no-builtin-rules

#
# remove all intermediate files
#
clean:
	${REMOVE} *.s
	${REMOVE} ${TARGET}

#
# generic target
#
all: ${TARGET}
