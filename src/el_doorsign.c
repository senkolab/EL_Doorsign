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
//#include <util/delay.h>
#include <avr/interrupt.h>

//
// external prototypes
//
void portInit(void);
void timerAudio(int); 
void timerEL(voidd); 
void wdogInit(void); 
void note(int, int);
void rest(int);
void _delay_ms(int);
void play(void);


//
// Note frequencies
//
#define C0      ( 16 )
#define Db0     ( 17 )
#define D0      ( 18 )
#define Eb0     ( 19 )
#define E0      ( 20 )
#define F0      ( 21 )
#define Gb0     ( 23 )
#define G0      ( 24 )
#define Ab0     ( 25 )
#define A0      ( 27 )
#define Bb0     ( 29 )
#define B0      ( 30 )
#define C1      ( 32 )
#define Db1     ( 34 )
#define D1      ( 36 )
#define Eb1     ( 38 )
#define E1      ( 41 )
#define F1      ( 43 )
#define Gb1     ( 46 )
#define G1      ( 49 )
#define Ab1     ( 51 )
#define A1      ( 55 )
#define Bb1     ( 58 )
#define B1      ( 61 )
#define C2      ( 65 )
#define Db2     ( 69 )
#define D2      ( 73 )
#define Eb2     ( 77 )
#define E2      ( 82 )
#define F2      ( 87 )
#define Gb2     ( 92 )
#define G2      ( 98 )
#define Ab2     ( 103 )
#define A2      ( 110 )
#define Bb2     ( 116 )
#define B2      ( 123 )
#define C3      ( 130 )
#define Db3     ( 138 )
#define D3      ( 146 )
#define Eb3     ( 155 )
#define E3      ( 164 )
#define F3      ( 174 )
#define Gb3     ( 185 )
#define G3      ( 196 )
#define Ab3     ( 207 )
#define A3      ( 220 )
#define Bb3     ( 233 )
#define B3      ( 246 )
#define C4      ( 261 )
#define Db4     ( 277 )
#define D4      ( 293 )
#define Eb4     ( 311 )
#define E4      ( 329 )
#define F4      ( 349 )
#define Gb4     ( 369 )
#define G4      ( 392 )
#define Ab4     ( 415 )
#define A4      ( 440 )
#define Bb4     ( 466 )
#define B4      ( 493 )
#define C5      ( 523 )
#define Db5     ( 554 )
#define D5      ( 587 )
#define Eb5     ( 622 )
#define E5      ( 659 )
#define F5      ( 698 )
#define Gb5     ( 739 )
#define G5      ( 783 )
#define Ab5     ( 830 )
#define A5      ( 880 )
#define Bb5     ( 932 )
#define B5      ( 987 )
#define C6      ( 1046 )
#define Db6     ( 1108 )
#define D6      ( 1174 )
#define Eb6     ( 1244 )
#define E6      ( 1318 )
#define F6      ( 1396 )
#define Gb6     ( 1479 )
#define G6      ( 1567 )
#define Ab6     ( 1661 )
#define A6      ( 1760 )
#define Bb6     ( 1864 )
#define B6      ( 1975 )
#define C7      ( 2093 )
#define Db7     ( 2217 )
#define D7      ( 2349 )
#define Eb7     ( 2489 )
#define E7      ( 2637 )
#define F7      ( 2793 )
#define Gb7     ( 2959 )
#define G7      ( 3135 )
#define Ab7     ( 3322 )
#define A7      ( 3520 )
#define Bb7     ( 3729 )
#define B7      ( 3951 )
#define C8      ( 4186 )
#define Db8     ( 4434 )
#define D8      ( 4698 )
#define Eb8     ( 4978 )
#define E8      ( 5274 )
#define F8      ( 5587 )
#define Gb8     ( 5919 )
#define G8      ( 6271 )
#define Ab8     ( 6644 )
#define A8      ( 7040 )
#define Bb8     ( 7458 )
#define B8      ( 7902 )

#define EIGHTH  (200)

//
// main routine
//
int main(void) {
  int state = 0;

  wdogInit();
  portInit();

  play();
  timerEL();

  // stall forever
  while(1)
  {
    if((PORTB & (1<<5)) == 0)
    {
      state = 0;
    }
    else if(state == 0)
    {
      play();
      state = 1;
    }
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
void timerAudio(int freq_a) {
  int value;

  CLKPR = 0;                  // program clock prescaler
  CLKPR = (1<<CLKPCE);        // enable prescaler changes

  TCCR0A = (1<<COM0A0) | (1<<COM0B0) | (1<<WGM01);     // COM-A = COM-B = toggle on ocmpare

  value = (F_CPU / 2 / 32) / freq_a - 1;

  if(value > 32)
  {
    TCCR0B = 0x2;   // CLK io / 32
  }
  else {
    TCCR0B = 0x3;   // CLK io / 64
    value = (F_CPU / 2 / 64) / freq_a - 1;
  }

  OCR0A = value; 
  OCR0B = value;

}

//
// initialize Timer for EL display
//
void timerEL(void) {

  CLKPR = 0;                  // program clock prescaler
  CLKPR = (1<<CLKPCE);        // enable prescaler changes

  TCCR0A = (1<<COM0A0) | (1<<COM0B0) | (1<<WGM01);     // COM-A = COM-B = toggle on ocmpare

  TCCR0B = 0x1;   // CLK io / 8

  OCR0A = 2;

}

//
// configure watchdog
//
void wdogInit(void) 
{
  WDTCR = (1 << WDCE);    // disable watchdog
}

//
// single note
//
void note(int freq, int ms_on)
{
  timerAudio(freq);
  DDRB |= 0x2;    // turn on PB1 (speaker)
  _delay_ms(ms_on);

}

   
//
// single rest
//
void rest(int ms_off)
{
  DDRB &= ~0x2;   // turn off PB1 (speaker)
  _delay_ms(ms_off);
}

//
// fake delay
//
void _delay_ms(int ms) 
{
  volatile int n;
  while(ms--)
  {
    for(n=0; n<40; n++)
      ;
  }
}

//
// play the tune
//
void play(void) 
{
    note(C4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(C4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(Bb4, 1*EIGHTH);    rest(1*EIGHTH); 
    note(C4,  1*EIGHTH);    rest(3*EIGHTH); 
    note(G4,  1*EIGHTH);    rest(3*EIGHTH); 
    note(G4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(C4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(F4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(E4,  1*EIGHTH);    rest(1*EIGHTH); 
    note(C4,  1*EIGHTH);    rest(1*EIGHTH); 
} 
