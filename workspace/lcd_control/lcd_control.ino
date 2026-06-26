#include "HyperDisplay_KWH018ST01_4WSPI.h"

#define SERIAL_PORT Serial
#define PWM_PIN 32             // Pin definitions
#define CS_PIN 25
#define DC_PIN 26
#define SPI_PORT SPI
#define SPI_SPEED 32000000    // Requests host uC to use the fastest possible SPI speed up to 32 MHz

#define TRIGGER_INPUT_PIN 22
#define TRIGGER_OUTPUT_PIN 12        // The pin configured to set the PIN

#define LCD_WIDTH 128

// Define how many pixels can the hardware store in the memory to speed up painting
// Setting too higher could cause OOM which crashes the device
#define MAX_PIXELS_IN_MEM 500

KWH018ST01_4WSPI lcd_screen;
ILI9163C_color_18_t white;
ILI9163C_color_18_t black;
ILI9163C_color_18_t white_color_array[1];

// LCD pattern parameters
int mode = 0;
int targetX;
int targetY;
int InnerRadius;
int OuterRadius;
int startY;
int endY;
int startX;
int endX;

int painting_delay_ms = 25;
bool triggered = false;
int frame_count = 0;

unsigned long duration;
unsigned int prevBox[4];

void trigger() {
  triggered = true;
}

void setup() {
  SERIAL_PORT.begin(115200);

  lcd_screen.begin(DC_PIN, CS_PIN, PWM_PIN, SPI_PORT, SPI_SPEED);  // This is a non-hyperdisplay function, but it is required to make the display work
  // lcd_screen.setNormalFramerate(0x04, 0x00);
  // lcd_screen.setIdleFramerate(0x10, 0x10);
  lcd_screen.clearDisplay();                                       // clearDisplay is also not part of hyperdisplay, but we will use it here for simplicity

  white = lcd_screen.rgbTo18b( 255, 255, 255);
  white_color_array[0] = white;
  black = lcd_screen.rgbTo18b( 0, 0, 0 );

  pinMode(TRIGGER_OUTPUT_PIN, OUTPUT);
  pinMode(TRIGGER_INPUT_PIN, INPUT_PULLUP);
  attachInterrupt(TRIGGER_INPUT_PIN, trigger, RISING);
}

bool isInArea(int x, int targetX) {
  return targetX>=0 ? x>=targetX : x<-targetX;
}

bool isInCircle(int x, int y, int centerX, int centerY, int radius) {
  return (x-centerX)*(x-centerX) + (y-centerY)*(y-centerY) < radius*radius;
}

void hardware_trigger() {
  if (frame_count == 0) {
    return;
  }

  delay(painting_delay_ms);
  digitalWrite(TRIGGER_OUTPUT_PIN, HIGH);
  delayMicroseconds(1000);
  digitalWrite(TRIGGER_OUTPUT_PIN, LOW);
  unsigned long start_wait = millis();
  while (triggered == false) {
    if (millis() - start_wait > 1000) {
      mode = 0;
      break; 
    }
    delay(1);
  }
  triggered = false;
  
  if (frame_count > 0) {
    frame_count -= 1;
  }
}

void loop() {
  if (SERIAL_PORT.available() > 0) {
    duration = millis();
    // Read the incoming integer using Serial.parseInt()
    mode = SERIAL_PORT.parseInt();
    targetX = SERIAL_PORT.parseInt();
    targetY = SERIAL_PORT.parseInt();
    InnerRadius = SERIAL_PORT.parseInt();
    OuterRadius = SERIAL_PORT.parseInt();
    frame_count = SERIAL_PORT.parseInt();

    while (SERIAL_PORT.read()!=10) {
    }

    startY = max(0, abs(targetY) - OuterRadius);
    endY = min(lcd_screen.yExt - 1, abs(targetY) + OuterRadius);
    startX = max(0, abs(targetX) - OuterRadius);
    endX = min(LCD_WIDTH - 1, abs(targetX) + OuterRadius);

    if (prevBox[0]<startX || prevBox[1]<startY || prevBox[2]>endX || prevBox[3]>endY) {
      lcd_screen.clearDisplay();
    }
    // myTFT.yline(incomingInt, 0, 127, (color_t)white_color_array, 1, 0);
    // myTFT.rectangle(0, 0, incomingInt, 159, true, (color_t)white_color_array, 1, 0);

    if (mode == 4) {
      pattern_paint(startX, endX, startY, endY, targetX, targetY, InnerRadius, OuterRadius);
    } else {
      bool canSpeedPaint = (endX-startX)*(endY-startY) <= MAX_PIXELS_IN_MEM;

      if (canSpeedPaint) {
        speedy_paint(startX, endX, startY, endY, mode, targetX, targetY, InnerRadius, OuterRadius);
      } else {
        incremental_paint(startX, endX, startY, endY, mode, targetX, targetY, InnerRadius, OuterRadius);
      }
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
  if (mode == 4) {
    pattern_paint(startX, endX, startY, endY, targetX, targetY, InnerRadius, OuterRadius);
  } else if (mode !=0) {
    hardware_trigger();
  }
}

void pattern_paint(int startX, int endX, int startY, int endY, int targetX, int targetY, int InnerRadius, int OuterRadius) {
  bool canSpeedPaint = (endX-startX)*(endY-startY) <= MAX_PIXELS_IN_MEM;

    if (canSpeedPaint) {
      speedy_paint(startX, endX, startY, endY, 1, abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    } else {
      incremental_paint(startX, endX, startY, endY, 1, abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    }

    hardware_trigger();

    if (canSpeedPaint) {
      speedy_paint(startX, endX, startY, endY, 1, -abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    } else {
      incremental_paint(startX, endX, startY, endY, 1, -abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    }

    hardware_trigger();

    if (canSpeedPaint) {
      speedy_paint(startX, endX, startY, endY, 2, abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    } else {
      incremental_paint(startX, endX, startY, endY, 2, abs(targetX), abs(targetY), InnerRadius, OuterRadius);
    }

    hardware_trigger();

    if (canSpeedPaint) {
      speedy_paint(startX, endX, startY, endY, 2, abs(targetX), -abs(targetY), InnerRadius, OuterRadius);
    } else {
      incremental_paint(startX, endX, startY, endY, 2, abs(targetX), -abs(targetY), InnerRadius, OuterRadius);
    }

    hardware_trigger();
}

void incremental_paint(int startX, int endX, int startY, int endY, int mode, int targetX, int targetY, int InnerRadius, int OuterRadius) {
  bool splitInX = mode==1;
  bool splitInY = mode==2;
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
  bool splitInX = mode==1;
  bool splitInY = mode==2;
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
