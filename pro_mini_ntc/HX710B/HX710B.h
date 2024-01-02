/**
 *
 * HX710B library for Arduino with MPS20N0040D pressure sensor support
 * https://github.com/kurimawxx00/hx710B_pressure_sensor
 * 
 * Based on HX711 library by https://github.com/bogde/
 *
 * MIT License
 * (c) 2021 Roland Pelayo
 * MIT License
 * (c) 2023 Vladimir L
 *
**/
#ifndef HX710B_h
#define HX710B_h

#if ARDUINO >= 100
#include "Arduino.h"
#else
#include "WProgram.h"
#endif

class HX710B
{
	private:
		byte PD_SCK;	// Power Down and Serial Clock Input Pin
		byte DOUT;		// Serial Data Output Pin
		long OFFSET = 0;	// used for tare weight
		float SCALE = 1;	// used to return weight in grams, kg, ounces, whatever
        float RES = 1/2839.49; //  коэфф. преобразования давления в Pascal
	public:

		HX710B();

		virtual ~HX710B();

		// Initialize library with data output pin, clock input pin and gain factor.
		// Channel selection is made by passing the appropriate gain:
		// - With a gain factor of 64 or 128, channel A is selected
		// - With a gain factor of 32, channel B is selected
		// The library default is "128" (Channel A).
		void begin(byte dout, byte pd_sck);

		// Check if HX710B is ready
		// from the datasheet: When output data is not ready for retrieval, digital output pin DOUT is high. Serial clock
		// input PD_SCK should be low. When DOUT goes to low, it indicates data is ready for retrieval.
		bool is_ready();

		// Wait for the HX710B to become ready
		void wait_ready(unsigned long delay_ms = 0);
		bool wait_ready_retry(int retries = 3, unsigned long delay_ms = 0);
		bool wait_ready_timeout(unsigned long timeout = 1000, unsigned long delay_ms = 0);

		// waits for the chip to be ready and returns a reading
		long read();

		// returns an average reading; times = how many times to read
		long read_average(byte times = 10);

        // returns pressure in kilopascals
        float pascal();
        //returns pressure in atm
        float atm();
        //returns pressure in mmHg
        float mmHg();
        //returns pressure in psi
        float psi();

        float raw2pascal(long raw);
        float raw2mmHg(long raw);
        float raw2psi(long raw);
        float raw2atm(long raw);
		float raw2mmWtr(long raw);

		// returns (read_average() - OFFSET), that is the current value without the tare weight; times = how many readings to do
		double get_value(byte times = 1);

		// returns get_value() divided by SCALE, that is the raw value divided by a value obtained via calibration
		// times = how many readings to do
		float get_units(byte times = 1);

		// set the OFFSET value for tare weight; times = how many times to read the tare value
		void tare(byte times = 10);

		// set the SCALE value; this value is used to convert the raw data to "human readable" data (measure units)
		void set_scale(float scale = 1.f);

		// get the current SCALE
		float get_scale();

		// set OFFSET, the value that's subtracted from the actual reading (tare weight)
		void set_offset(long offset = 0);

		// get the current OFFSET
		long get_offset();

		// puts the chip into power down mode
		void power_down();

		// wakes up the chip after power down mode
		void power_up();
};

#endif /* HX710B_h */
