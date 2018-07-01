////////////////////////////////////////////////////////////////////////////////
// 
// el_doorsign_main.c - main routine for the electroluminescent doorsign
//
// Author: Rich Rademacher
//          University of Waterloo/IQC
//
//
////////////////////////////////////////////////////////////////////////////////

//
// include files from WinAVR source tree
//
#include <avr/io.h>
#include <util/delay.h>


//
// external prototypes
//
extern void portInit(void);
extern void timerInit(void);


//
// main routine
//
int main(void) {


  portInit();


  // stall forever
  while(1)
  {
    _delay_ms(100);
  }
  
}


//
// initialize ports
//
void portInit(void)
{
  // PB0 = OC0A - EL display
  // PB1 = OC0B - Speaker
  // PB2 = none
  // PB3 = none
  // PB4 = not bonded to pin
  // PB5 = On/Off input (active low)
  DDRB = 0x3;
}

//
// initialize Timer
//
void initTimer(void) {

}
