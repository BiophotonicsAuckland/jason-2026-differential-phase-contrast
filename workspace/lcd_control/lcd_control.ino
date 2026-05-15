#include "HyperDisplay_KWH018ST01_4WSPI.h"

#define SERIAL_PORT Serial
#define PWM_PIN 32             // Pin definitions
#define CS_PIN 25
#define DC_PIN 26
#define SPI_PORT SPI
#define SPI_SPEED 32000000    // Requests host uC to use the fastest possible SPI speed up to 32 MHz

#define LCD_WIDTH 128

// Define how many pixels can the hardware store in the memory to speed up painting
// Setting too higher could cause OOM which crashes the device
#define MAX_PIXELS_IN_MEM 500

KWH018ST01_4WSPI lcd_screen;
ILI9163C_color_18_t white;
ILI9163C_color_18_t black;
ILI9163C_color_18_t white_color_array[1];

unsigned long duration;
unsigned int prevBox[4];

void setup() {
  SERIAL_PORT.begin(115200);

  lcd_screen.begin(DC_PIN, CS_PIN, PWM_PIN, SPI_PORT, SPI_SPEED);  // This is a non-hyperdisplay function, but it is required to make the display work
  lcd_screen.clearDisplay();                                       // clearDisplay is also not part of hyperdisplay, but we will use it here for simplicity

  white = lcd_screen.rgbTo18b( 255, 255, 255);
  white_color_array[0] = white;
  black = lcd_screen.rgbTo18b( 0, 0, 0 );
}

bool isInArea(int x, int targetX) {
  return targetX>=0 ? x>=targetX : x<-targetX;
}

bool isInCircle(int x, int y, int centerX, int centerY, int radius) {
  return (x-centerX)*(x-centerX) + (y-centerY)*(y-centerY) < radius*radius;
}

void loop() {
  if (SERIAL_PORT.available() > 0) {
    duration = millis();
    // Read the incoming integer using Serial.parseInt()
    int mode = SERIAL_PORT.parseInt();
    int targetX = SERIAL_PORT.parseInt();
    int targetY = SERIAL_PORT.parseInt();
    int InnerRadius = SERIAL_PORT.parseInt();
    int OuterRadius = SERIAL_PORT.parseInt();

    while (SERIAL_PORT.read()!=10) {
    }

    int startY = max(0, abs(targetY) - OuterRadius);
    int endY = min(lcd_screen.yExt - 1, abs(targetY) + OuterRadius);
    int startX = max(0, abs(targetX) - OuterRadius);
    int endX = min(LCD_WIDTH - 1, abs(targetX) + OuterRadius);

    if (prevBox[0]<startX || prevBox[1]<startY || prevBox[2]>endX || prevBox[3]>endY) {
      lcd_screen.clearDisplay();
    }
    // myTFT.yline(incomingInt, 0, 127, (color_t)white_color_array, 1, 0);
    // myTFT.rectangle(0, 0, incomingInt, 159, true, (color_t)white_color_array, 1, 0);

    if ((endX-startX)*(endY-startY) <= MAX_PIXELS_IN_MEM) {
      speedy_paint(startX, endX, startY, endY, mode, targetX, targetY, InnerRadius, OuterRadius);
    } else {
      incremental_paint(startX, endX, startY, endY, mode, targetX, targetY, InnerRadius, OuterRadius);
    }

    SERIAL_PORT.print("0| ");
    SERIAL_PORT.print("r: ");
    SERIAL_PORT.print(InnerRadius);
    SERIAL_PORT.print("-");
    SERIAL_PORT.print(OuterRadius);
    SERIAL_PORT.print("|");
    SERIAL_PORT.println(millis() - duration);
    
    prevBox[0] = startX;
    prevBox[1] = startY;
    prevBox[2] = endX;
    prevBox[3] = endY;
  }
}

void incremental_paint(int startX, int endX, int startY, int endY, int mode, int targetX, int targetY, int InnerRadius, int OuterRadius) {
  bool splitInX = mode==0;
  bool splitInY = mode>0;
  ILI9163C_color_18_t lcd_array[endX-startX+1];
  
  for (int y=startY; y<=endY; y++) {
      for (int x=startX; x<=endX; x++) {
        if (!isInCircle(x, y, abs(targetX), abs(targetY), InnerRadius) 
          && isInCircle(x, y, abs(targetX), abs(targetY), OuterRadius)
          && !(splitInX && !isInArea(x, targetX)) && !(splitInY && !isInArea(y, targetY))) {
          lcd_array[x-startX].r = 255;
        } else {
          lcd_array[x-startX].r = 0;
        }
      }
      lcd_screen.fillFromArray(startX, y, endX, y, lcd_array, endX-startX+1);
    }
}

void speedy_paint(int startX, int endX, int startY, int endY, int mode, int targetX, int targetY, int InnerRadius, int OuterRadius) {
  bool splitInX = mode==0;
  bool splitInY = mode>0;
  ILI9163C_color_18_t lcd_array2[endX-startX+1][endY-startY+1];

  for (int y=startY; y<=endY; y++) {
    for (int x=startX; x<=endX; x++) {
      if (!isInCircle(x, y, abs(targetX), abs(targetY), InnerRadius) 
        && isInCircle(x, y, abs(targetX), abs(targetY), OuterRadius)
        && !(splitInX && !isInArea(x, targetX)) && !(splitInY && !isInArea(y, targetY))) {
        lcd_array2[x-startX][y-startY].r = 255;
      } else {
        lcd_array2[x-startX][y-startY].r = 0;
      }
    }
  }
  lcd_screen.fillFromArray(startX, startY, endX, endY, lcd_array2, (endY-startY+1)*(endX-startX+1));
}
